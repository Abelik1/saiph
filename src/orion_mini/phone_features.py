# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone pages and bounded direct transfers, independent of the desktop UI."""
from __future__ import annotations
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from uuid import UUID, uuid4
from .hub_client import signed_headers
from .peer import PeerServer, Blobs, mesh_address, NoRedirect
from .cloud import ensure_layout
from .models import utc_now

MAX_FILE=2*1024**3
MAX_CAPTURE=32*1024**2  # A phone photo placed on the clipboard, not an arbitrary file.
CAPTURE_SECONDS=900
CAPTURE_TYPES={'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.webp':'image/webp'}
MEDIA_ACTIONS={'play','pause','next','previous','seek','volume'}
RINGER_MODES={'ring','vibrate','silent'}
DIAL=re.compile(r'[0-9+() .-]{1,40}')  # No * or #: MMI codes can change call forwarding.
ANSWER_SECONDS=300  # Contact results and call history are kept in memory this long.
NEW_PHOTO_SECONDS=120  # A photo this recent, first seen now, is offered on the computer.
MAX_ATTACHMENT=20*1024**2
PREVIEW_BYTES=400*1024  # MMS pictures up to this size are shown inline in the conversation.
SAVE_ANSWER_SECONDS=60  # A save the phone never answered becomes retryable.
def safe_name(value):
    # Filenames are labels, never paths; Windows device names are rejected too.
    name=str(value).replace('\\','/').rsplit('/',1)[-1]
    name=''.join('_' if c in '<>:"/\\|?*' or ord(c)<32 else c for c in name).strip(' .')[:180]
    if not name or name.split('.')[0].rstrip().upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:name='Shared file'
    return name
def file_sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        while chunk:=source.read(1024*1024):digest.update(chunk)
    return digest.hexdigest()
_previews={}  # Inline MMS pictures by (path, size, digest, on-disk size, modified time).
def same_file(path,size,sha256):
    """True while path still holds exactly the recorded bytes; legacy rows without a digest compare size."""
    try:
        path=Path(path)
        return path.is_file() and path.stat().st_size==size and (not sha256 or file_sha256(path)==sha256)
    except OSError:return False
def display_folder(path):
    """'Downloads → Orion' for the UI; the full path stays available separately."""
    parent=Path(path).parent
    try:return ' → '.join(parent.relative_to(Path.home()).parts) or str(parent)
    except ValueError:return str(parent)
class FileBlobs(Blobs):
    def add_path(self, source):
        source=Path(source)
        if not source.is_file() or source.stat().st_size>MAX_FILE:raise ValueError('Choose a file up to 2 GB.')
        with self.lock:
            self.prune()
            if len(self.items)>=8:raise ValueError('Existing transfers are still available. Try again shortly.')
            ident=str(uuid4());path=self.root/ident;size=0;digest=hashlib.sha256()
            try:
                with source.open('rb') as incoming,path.open('xb') as outgoing:
                    while chunk:=incoming.read(65536):
                        size+=len(chunk)
                        if size>MAX_FILE:raise ValueError('File exceeds 2 GB.')
                        digest.update(chunk);outgoing.write(chunk)
                self.items[ident]=(path,time.time()+900,size)
                return ident,size,digest.hexdigest()
            except BaseException:path.unlink(missing_ok=True);raise
class FileServer(PeerServer):
    def __init__(self,root,config,address=None,port=8767):
        super().__init__(root,config,address,port,cache_dir='file-cache')
        self.blobs=FileBlobs(Path(root)/'file-cache')
    def offer_file(self,path):
        ident,size,digest=self.blobs.add_path(path)
        import mimetypes
        return {'name':safe_name(Path(path).name),'mime':mimetypes.guess_type(path)[0] or 'application/octet-stream',
                'size':size,'sha256':digest,'blob':{'id':ident,'address':self.address,'port':self.port}}
def download(root,config,source,payload,directory,max_size=MAX_FILE,timeout=30):
    blob=payload['blob'];address=mesh_address(blob['address']);ident=blob['id'];size=payload['size']
    if str(UUID(ident))!=ident or type(blob['port']) is not int or not 1024<=blob['port']<=65535:raise ValueError('Invalid peer resource.')
    if type(size) is not int or not 0<=size<=max_size:raise ValueError('File exceeds its size limit.')
    path=f'/v1/peer/{source}/blobs/{ident}';host=f'[{address}]' if ':' in address else address
    request=urllib.request.Request(f'http://{host}:{blob["port"]}{path}',headers=signed_headers(root,config['device_id'],path))
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    temporary=directory/('.orion-'+str(uuid4())+'.part');digest=hashlib.sha256();total=0
    destination=directory/safe_name(payload['name'])
    try:
        with opener.open(request,timeout=timeout) as response,temporary.open('xb') as output:
            if int(response.headers.get('Content-Length','-1'))!=size:raise ValueError('Peer size mismatch.')
            while chunk:=response.read(65536):
                total+=len(chunk)
                if total>size:raise ValueError('Peer size mismatch.')
                output.write(chunk);digest.update(chunk)
            output.flush();os.fsync(output.fileno())
        if total!=size or digest.hexdigest()!=payload['sha256']:raise ValueError('Peer content mismatch.')
        # Never overwrite an existing personal download.
        if destination.exists():destination=directory/(destination.stem+' '+str(uuid4())[:8]+destination.suffix)
        temporary.replace(destination);return destination
    except (OSError,urllib.error.URLError):raise ValueError('Direct transfer is unavailable. Saiph will retry automatically.') from None
    finally:temporary.unlink(missing_ok=True)

class PhoneFeatures:
    def __init__(self,workspace):
        self.workspace=workspace;self.store=workspace.store;self.lock=threading.RLock();self.pending={};self.file_server=None
        self.changed=lambda:None;self.stop_requested=threading.Event();self.worker=None;self.thumbnail_worker=None
        self.capture_ready=lambda row,mime,data:None  # Set by the runtime: clipboard and notice.
        self.answers={}  # (device, kind) -> private answer kept in memory only (contacts, call history).
        self.answers_lock=threading.Lock()  # Separate: GUI snapshots never wait on the restore writer.
        self.photo_new=lambda row:None  # Set by the runtime: offer a new screenshot or photo.
    def restore(self,snapshot):
        # One atomic transaction, rather than one fsync and retention scan per
        # row. GUI readers use WAL and never wait on the feature writer lock.
        with self.lock,self.store.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            for kind,key in [('thread','threads'),('message','messages'),('call','calls'),('photo','photos'),('media','media'),('ringer','ringers'),('attachment','attachments')]:
                present=set();devices=set()
                for row in snapshot.get(key,[]):
                    item=self._save(kind,row,connection=connection,prune=False);present.add(item['id']);devices.add(row['device_id'])
                old=connection.execute('SELECT id FROM records WHERE kind=?',('phone_'+kind,)).fetchall()
                connection.executemany('DELETE FROM records WHERE kind=? AND id=?',(('phone_'+kind,ident) for (ident,) in old if ident not in present))
                for device in devices:self._prune(connection,kind,device)
            connection.execute("DELETE FROM records WHERE kind='phone_thumbnail' AND id NOT IN (SELECT id FROM records WHERE kind='phone_photo')")
    def _save(self,kind,row,*,connection=None,prune=True):
        if connection is None:
            with self.store.connect() as connection:return self._save(kind,row,connection=connection,prune=prune)
        key=(str(row['thread'])+':'+str(row['id']) if kind=='message' else str(row['thread'])+':'+str(row['message']) if kind=='attachment'
             else str(row.get('thread',row.get('id','current'))))
        ident=hashlib.sha256((row['device_id']+'\0'+kind+'\0'+key).encode()).hexdigest()
        previous={}
        if kind=='photo':
            previous_row=connection.execute("SELECT data FROM records WHERE kind='phone_photo' AND id=?",(ident,)).fetchone()
            if previous_row:
                old=json.loads(previous_row[0])
                if old.get('thumbnail',{}).get('sha256')==row['thumbnail']['sha256']:previous={'preview':old.get('preview')}
        saved={**previous,**row,'message_id':row.get('id') if kind=='message' else None,'photo_id':row.get('id') if kind=='photo' else None,'id':ident,'updated_at':utc_now()}
        connection.execute('INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data',('phone_'+kind,ident,json.dumps(saved)))
        if prune:self._prune(connection,kind,row['device_id'])
        if kind=='photo':
            if not saved.get('preview'):
                # Persist before ACK; network transfer belongs to a separate worker.
                pending={'id':ident,'device_id':row['device_id'],'thumbnail':row['thumbnail'],'received':time.time(),'retry_at':0,'updated_at':utc_now()}
                connection.execute('INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data',('phone_thumbnail',ident,json.dumps(pending)))
            else:connection.execute("DELETE FROM records WHERE kind='phone_thumbnail' AND id=?",(ident,))
            if prune:connection.execute("DELETE FROM records WHERE kind='phone_thumbnail' AND id NOT IN (SELECT id FROM records WHERE kind='phone_photo')")
        return saved
    @staticmethod
    def _prune(connection,kind,device):
        limit={'thread':500,'message':2000,'photo':100,'call':1,'media':1,'ringer':1,'attachment':2000}[kind]
        connection.execute("DELETE FROM records WHERE kind=? AND json_extract(data,'$.device_id')=? AND id NOT IN (SELECT id FROM records WHERE kind=? AND json_extract(data,'$.device_id')=? ORDER BY json_extract(data,'$.updated_at') DESC,rowid DESC LIMIT ?)",('phone_'+kind,device,'phone_'+kind,device,limit))
    def snapshot(self):
        with self.store.connect() as connection:
            connection.execute('BEGIN')
            result={name:[json.loads(row[0]) for row in connection.execute('SELECT data FROM records WHERE kind=? ORDER BY rowid DESC',('phone_'+kind,))]
                    for kind,name in [('thread','threads'),('message','messages'),('call','calls'),('photo','photos'),('file','files'),('photo_save','photo_saves'),('media','media'),('ringer','ringers'),('attachment','attachments'),('attachment_file','attachment_files')]}
        now=time.time();transfers=None;saves=[]
        for row in result['photo_saves']:
            if row['status']=='saved' and not Path(row['path']).is_file():continue
            if row['status']=='saving' and now-row.get('started',0)>SAVE_ANSWER_SECONDS:
                if transfers is None:transfers=self.store.all('phone_transfer')
                row=self._unanswered(row,transfers)
            saves.append(row)
        result['photo_saves']=saves
        result['attachment_files']=[self._attachment_view(row) for row in result['attachment_files']]
        with self.answers_lock:
            self.answers={key:value for key,value in self.answers.items() if now-value['at']<ANSWER_SECONDS}
            result['contacts']=[{**v['payload'],'device_id':k[0]} for k,v in self.answers.items() if k[1]=='contacts.results']
            result['call_logs']=[{**v['payload'],'device_id':k[0]} for k,v in self.answers.items() if k[1]=='calls.log']
        return result
    def event(self,event,config):
        kind=event['type'];row={**event['payload'],'device_id':event['source']}
        with self.lock:
            if kind=='sms.thread':
                with self.store.connect() as connection:
                    connection.execute('BEGIN IMMEDIATE')
                    self._save('thread',row,connection=connection)
                    self._save('message',{'thread':row['thread'],**row['message'],'device_id':row['device_id']},connection=connection)
            elif kind=='sms.messages':
                with self.store.connect() as connection:
                    connection.execute('BEGIN IMMEDIATE')
                    for message in row['messages']:self._save('message',{'thread':row['thread'],**message,'device_id':row['device_id']},connection=connection,prune=False)
                    self._prune(connection,'message',row['device_id'])
            elif kind=='sms.remove':
                for name in ['thread','message','attachment']:
                    for old in self.store.all('phone_'+name):
                        if old['device_id']==row['device_id'] and old['thread']==row['thread']:self.store.delete('phone_'+name,old['id'])
            elif kind=='sms.index':
                for old in self.store.all('phone_message'):
                    if old['device_id']==row['device_id'] and old['thread']==row['thread'] and old['message_id'] not in row['ids']:self.store.delete('phone_message',old['id'])
            elif kind=='call.state':self._save('call',row)
            elif kind=='media.state':self._save('media',row)
            elif kind=='ringer.state':self._save('ringer',row)
            elif kind=='sms.attachments':self._save('attachment',row)
            elif kind in {'contacts.results','calls.log'}:
                # Private answers to this computer's request: memory only, never stored.
                with self.answers_lock:self.answers[(row['device_id'],kind)]={'payload':event['payload'],'at':time.time()}
            elif kind=='photos.index':
                for photo in row['photos']:
                    ident=hashlib.sha256((row['device_id']+'\0photo\0'+str(photo.get('id'))).encode()).hexdigest()
                    try:self.store.get('phone_photo',ident);seen=True
                    except ValueError:seen=False
                    saved=self._save('photo',{**photo,'device_id':row['device_id']})
                    # Only a photo taken just now, never seen before, is offered; history is not.
                    if not seen and time.time()*1000-saved.get('timestamp',0)<NEW_PHOTO_SECONDS*1000:self.photo_new(saved)
                self.start(config)
            elif kind=='photos.sync':
                for old in self.store.all('phone_photo'):
                    if old['device_id']==row['device_id'] and old['photo_id'] not in row['ids']:
                        self.store.delete('phone_photo',old['id']);self.store.delete('phone_thumbnail',old['id'])
            elif kind=='capture.insert':
                # The phone asked for its own just-taken photo to be ready to paste here.
                digest=event['payload'].get('sha256') if isinstance(event['payload'],dict) else None
                if set(event['payload'])!={'sha256'} or not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
                    raise ValueError('Invalid capture request.')
                now=time.time()
                for old in self.store.all('phone_capture'):
                    if now-old['received']>CAPTURE_SECONDS:self.store.delete('phone_capture',old['id'])
                intent=self.store.save('phone_capture',{'id':self._photo_key(row['device_id'],digest),'device_id':row['device_id'],'sha256':digest,'received':now})
                done=next((f for f in self.store.all('phone_file') if f['device_id']==row['device_id'] and f.get('sha256')==digest and f.get('path')),None)
                if done:self._insert_capture(done,intent)
            elif kind in {'file.offer','photo.original','sms.attachment.file'}:
                # Completed event IDs suppress retries after the final atomic rename.
                try:return self.store.get('phone_file',event['id'])
                except ValueError:pass
                self.store.save('phone_transfer',{'id':event['id'],'event':event,'received':time.time()})
                self.start(config)
            else:return False
            return True
    def start(self,config):
        with self.lock:
            self.transfer_config=config
            if self.worker is None:
                self.worker=threading.Thread(target=self._transfers,name='orion-files',daemon=True);self.worker.start()
            if self.thumbnail_worker is None:
                self.thumbnail_worker=threading.Thread(target=self._thumbnails,name='orion-thumbnails',daemon=True);self.thumbnail_worker.start()
    def _thumbnails(self):
        while not self.stop_requested.is_set():
            self._thumbnail_once(self.transfer_config)
            self.stop_requested.wait(5)
    def _thumbnail_once(self,config,now=None):
        now=time.time() if now is None else now
        for pending in self.store.all('phone_thumbnail')[:100]:
            if self.stop_requested.is_set():return
            if pending.get('retry_at',0)>now:continue
            try:
                if now-pending['received']>900:raise ValueError('Thumbnail offer expired')
                path=download(self.workspace.root,config,pending['device_id'],pending['thumbnail'],self.workspace.root/'phone-thumbnails',512*1024,timeout=8)
                try:preview='data:image/jpeg;base64,'+base64.b64encode(path.read_bytes()).decode()
                finally:path.unlink(missing_ok=True)
                with self.lock:
                    try:current=self.store.get('phone_photo',pending['id'])
                    except ValueError:
                        self.store.delete('phone_thumbnail',pending['id']);continue
                    # A newer index/offer may have arrived while downloading.
                    if current['thumbnail']['sha256']!=pending['thumbnail']['sha256']:continue
                    self.store.save('phone_photo',{**current,'preview':preview})
                    self.store.delete('phone_thumbnail',pending['id'])
                self.changed()
            except (OSError,ValueError):
                with self.lock:
                    try:current=self.store.get('phone_thumbnail',pending['id'])
                    except ValueError:continue
                    if current['thumbnail']==pending['thumbnail']:
                        self.store.save('phone_thumbnail',{**current,'retry_at':now+30})
    def _transfers(self):
        while not self.stop_requested.is_set():
            self._transfer_once()
            self.stop_requested.wait(10)
    def _transfer_once(self):
        for pending in self.store.all('phone_transfer'):
            event=pending['event'];row=event['payload']
            photo_key=self._photo_key(event['source'],row['photo_id']) if row.get('photo_id') else None
            intent=None
            try:
                if photo_key:
                    try:intent=self.store.get('phone_photo_intent',photo_key)
                    except ValueError:pass
                    cached=self.photo_cached(event['source'],row['photo_id'])
                    if cached and row.get('sha256') and cached.get('sha256')==row['sha256'] and same_file(cached['path'],cached['size'],cached['sha256']):
                        # A repeated offer of an original Orion already holds is not downloaded again.
                        self.store.delete('phone_transfer',event['id'])
                        if not intent or intent['mode']=='save':self.photo_request(event['source'],row['photo_id'],'save')
                        self.changed();continue
                if 'part' in row:
                    # An MMS picture the owner opened: kept in Saiph's own folder, shown in the conversation.
                    path=download(self.workspace.root,self.transfer_config,event['source'],row,self.workspace.root/'sms-attachments',MAX_ATTACHMENT)
                    self.store.save('phone_attachment_file',{'id':self._attachment_key(event['source'],row['thread'],row['message'],row['part']),
                        'device_id':event['source'],'thread':row['thread'],'message':row['message'],'part':row['part'],
                        'name':safe_name(row['name']),'mime':row['mime'],'path':str(path),'size':row['size'],'sha256':row['sha256']})
                    self.store.delete('phone_transfer',event['id']);self.changed();continue
                directory=self._destination(row,intent)
                existing=directory/safe_name(row['name'])
                if photo_key and row.get('sha256') and same_file(existing,row['size'],row['sha256']):path=existing
                else:path=download(self.workspace.root,self.transfer_config,event['source'],row,directory)
                if photo_key:
                    self.store.save('phone_photo_original',{'id':photo_key,'device_id':event['source'],'photo_id':row['photo_id'],'name':row['name'],'path':str(path),'size':row['size'],'sha256':row.get('sha256')})
                    self.pending.pop(photo_key,None)
                    try:latest=self.store.get('phone_photo_intent',photo_key)
                    except ValueError:latest=intent
                    if intent and intent['mode']=='prefetch' and latest and latest['mode']=='save':
                        self.photo_request(event['source'],row['photo_id'],'save')
                    if latest and latest['mode']=='copy':
                        self.store.delete('phone_photo_intent',photo_key)
                        self._copy_original(event['source'],row['photo_id'])
                if not intent or intent['mode'] not in {'prefetch','copy'}:
                    self._complete_file(event,path)
                else:self.store.delete('phone_transfer',event['id'])
                self.changed()
            except (OSError,ValueError):
                if time.time()-pending['received']>900:
                    state=self.photo_save_state(event['source'],row['photo_id']) if photo_key else None
                    self.store.delete('phone_transfer',event['id'])
                    self.store.save('phone_file',{'id':event['id'],'device_id':event['source'],'name':safe_name(row['name']),'path':'','size':row['size'],'status':'unavailable'})
                    if state and state['status']=='saving':
                        self._record_save(event['source'],row['photo_id'],'failed',name=safe_name(row['name']),error='The photo could not be transferred. Try again.')
                    self.changed()
    def _complete_file(self,event,path):
        """Record receipt, local file Handoff and photo save state together; replays cannot resurrect it."""
        row=event['payload'];now=utc_now()
        saved={'id':event['id'],'device_id':event['source'],'name':Path(path).name,'path':str(path),'size':row['size'],
               'photo_id':row.get('photo_id'),'destination':row.get('destination','downloads'),'sha256':row.get('sha256'),'updated_at':now}
        with self.store.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            created=connection.execute('INSERT OR IGNORE INTO records VALUES(?,?,?)',('phone_file',event['id'],json.dumps(saved))).rowcount
            if created and event['type']=='file.offer':
                item={'id':event['id'],'kind':'file','value':saved['name'],'file_id':event['id'],'source':event['source'],'status':'ready','updated_at':now}
                connection.execute('INSERT OR IGNORE INTO records VALUES(?,?,?)',('handoff',event['id'],json.dumps(item)))
                connection.execute("DELETE FROM records WHERE kind='handoff' AND id NOT IN (SELECT id FROM records WHERE kind='handoff' ORDER BY rowid DESC LIMIT 100)")
            if row.get('photo_id'):
                # In the same transaction: once the transfer is gone, Save already sees this copy.
                self._record_save(event['source'],row['photo_id'],'saved',connection=connection,name=saved['name'],path=saved['path'],
                                  size=row['size'],sha256=row.get('sha256'),file_id=event['id'])
            connection.execute("DELETE FROM records WHERE kind='phone_transfer' AND id=?",(event['id'],))
        if event['type']=='file.offer' and row.get('sha256'):
            try:intent=self.store.get('phone_capture',self._photo_key(event['source'],row['sha256']))
            except ValueError:intent=None
            if intent and time.time()-intent['received']<=CAPTURE_SECONDS:self._insert_capture(saved,intent)
    def _insert_capture(self,row,intent):
        """One-shot: the verified received photo goes to this computer's clipboard."""
        self.store.delete('phone_capture',intent['id'])
        path=Path(row['path']);mime=CAPTURE_TYPES.get(path.suffix.lower())
        try:
            if not mime or not same_file(path,row['size'],intent['sha256']) or row['size']>MAX_CAPTURE:return
            data=path.read_bytes()
        except OSError:return
        self.capture_ready(row,mime,data)
    def _destination(self,row,intent=None):
        destination=row.get('destination','downloads')
        if destination=='cloud':
            if (self.workspace.settings.get('cloud') or {}).get('enabled',True) is False:raise ValueError('Cloud is disabled.')
            return ensure_layout(self.workspace.settings)/'Shared'
        if destination!='downloads':raise ValueError('Unknown file destination.')
        return self.workspace.root/'phone-originals' if intent and intent['mode'] in {'prefetch','copy'} else Path.home()/'Downloads'/'Orion'
    @staticmethod
    def _photo_key(device,photo):return hashlib.sha256((device+'\0'+str(photo)).encode()).hexdigest()
    def photo_cached(self,device,photo):
        try:
            row=self.store.get('phone_photo_original',self._photo_key(device,photo))
            if Path(row['path']).is_file():return row
        except ValueError:pass
        return None
    def _record_save(self,device,photo,status,*,connection=None,**fields):
        """Per-photo save state for the tile: metadata only, never photo bytes."""
        if connection is None:
            with self.store.connect() as connection:return self._record_save(device,photo,status,connection=connection,**fields)
        if fields.get('path'):fields['folder']=display_folder(fields['path'])
        saved={'id':self._photo_key(device,photo),'device_id':device,'photo_id':str(photo),'status':status,**fields,'updated_at':utc_now()}
        connection.execute('INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data',('phone_photo_save',saved['id'],json.dumps(saved)))
        connection.execute("DELETE FROM records WHERE kind='phone_photo_save' AND id NOT IN (SELECT id FROM records WHERE kind='phone_photo_save' ORDER BY rowid DESC LIMIT 500)")
        return saved
    @staticmethod
    def _unanswered(row,transfers):
        if any(p['event']['source']==row['device_id'] and str(p['event']['payload'].get('photo_id'))==row['photo_id'] for p in transfers):return row
        return {**row,'status':'failed','error':'Your phone did not send the photo. Try again.'}
    def photo_save_state(self,device,photo):
        try:row=self.store.get('phone_photo_save',self._photo_key(device,photo))
        except ValueError:return None
        if row['status']=='saving' and time.time()-row.get('started',0)>SAVE_ANSWER_SECONDS:row=self._unanswered(row,self.store.all('phone_transfer'))
        return row
    @staticmethod
    def _save_result(row,existing=False):
        result={key:row.get(key) for key in ['status','name','path','folder','file_id','error','updated_at']}
        return {**result,'saved':row['status']=='saved','existing':existing}
    def _file_id(self,path):
        return next((r['id'] for r in self.store.all('phone_file') if r.get('path')==str(path)),None)
    def _save_cached(self,device,photo,cached):
        """Place a held original in Downloads → Orion, reusing an identical copy already there."""
        sha256=cached.get('sha256') or file_sha256(cached['path'])
        directory=Path.home()/'Downloads'/'Orion';directory.mkdir(parents=True,exist_ok=True)
        source=Path(cached['path']);destination=directory/safe_name(cached['name']);file_id=None
        if source.parent==directory:destination=source;file_id=self._file_id(source)  # An earlier save downloaded it here.
        elif same_file(destination,cached['size'],sha256):file_id=self._file_id(destination)
        else:
            if destination.exists():destination=directory/(destination.stem+' '+str(uuid4())[:8]+destination.suffix)
            temporary=directory/('.orion-'+str(uuid4())+'.part')
            try:shutil.copy2(source,temporary);temporary.replace(destination)
            finally:temporary.unlink(missing_ok=True)
        if file_id is None:
            file_id=str(uuid4())
            self.store.save('phone_file',{'id':file_id,'device_id':device,'name':destination.name,'path':str(destination),'size':cached['size'],'photo_id':str(photo)})
        return self._record_save(device,photo,'saved',name=destination.name,path=str(destination),size=cached['size'],sha256=sha256,file_id=file_id)
    @staticmethod
    def _attachment_key(device,thread,message,part):return hashlib.sha256(f'{device}\0{thread}\0{message}\0{part}'.encode()).hexdigest()
    @staticmethod
    def _attachment_view(row):
        """Small pictures inline; anything else is opened or saved on request."""
        view={key:row.get(key) for key in ('id','device_id','thread','message','part','name','mime','size')}
        try:
            path=Path(row['path'])
            if row['mime'].startswith('image/') and row['size']<=PREVIEW_BYTES:
                # State is read every second: hash and encode each file version once, not every time.
                info=path.stat();key=(str(path),row['size'],row.get('sha256'),info.st_size,info.st_mtime_ns)
                preview=_previews.get(key)
                if preview is None and same_file(path,row['size'],row.get('sha256')):
                    preview='data:'+row['mime']+';base64,'+base64.b64encode(path.read_bytes()).decode()
                    if len(_previews)>=256:_previews.clear()
                    _previews[key]=preview
                if preview:view['preview']=preview
            view['ready']=path.is_file()
        except (OSError,KeyError):view['ready']=False
        return view
    def _attachment(self,args):
        row=self.store.get('phone_attachment_file',str(args['id']))
        if not same_file(row['path'],row['size'],row.get('sha256')):raise ValueError('This picture is no longer on this computer. Open it again from the conversation.')
        return row
    def attachment_save(self,args):
        """Copies a received MMS picture into Downloads → Orion; never overwrites."""
        row=self._attachment(args)
        directory=Path.home()/'Downloads'/'Orion';directory.mkdir(parents=True,exist_ok=True)
        destination=directory/safe_name(row['name'])
        if destination.exists():destination=directory/(destination.stem+' '+str(uuid4())[:8]+destination.suffix)
        shutil.copy2(row['path'],destination)
        return {'saved':True,'path':str(destination),'folder':display_folder(destination)}
    def _copy_original(self,device,photo):
        """Places a held original on this computer's clipboard (Copy on a new-photo notice)."""
        cached=self.photo_cached(device,photo)
        mime=CAPTURE_TYPES.get(Path(cached['path']).suffix.lower()) if cached else None
        if not cached or not mime or cached['size']>MAX_CAPTURE or not same_file(cached['path'],cached['size'],cached.get('sha256')):return False
        self.capture_ready({'device_id':device},mime,Path(cached['path']).read_bytes());return True
    def photo_request(self,device,photo,mode='save'):
        if mode=='save':
            with self.lock:result=self._photo_save(device,photo)
            self.changed();return result
        if mode=='copy' and self._copy_original(device,photo):return {'copied':True}
        cached=self.photo_cached(device,photo)
        if cached and mode=='prefetch':return {'ready':True,'path':cached['path']}
        state=self.photo_save_state(device,photo)
        if state and state['status']=='saving':return {'queued':True}  # Hovering must not redirect a save to the cache.
        key=self._photo_key(device,photo)
        self.store.save('phone_photo_intent',{'id':key,'mode':mode})
        # One outstanding request per photo. Repeated Save clicks before the
        # original arrived each produced another original and saved copy.
        if time.time()-self.pending.get(key,0)<60:return {'queued':True}
        result=self.command(device,'photo.request',{'id':str(photo)})
        self.pending[key]=time.time();return result
    def _photo_save(self,device,photo):
        """One saved copy per photo: repeats return it, and a save in flight is not requested twice."""
        state=self.photo_save_state(device,photo)
        if state and state['status']=='saved' and same_file(state['path'],state['size'],state.get('sha256')):return self._save_result(state,existing=True)
        cached=self.photo_cached(device,photo)
        if cached and same_file(cached['path'],cached['size'],cached.get('sha256')):return self._save_result(self._save_cached(device,photo,cached))
        if state and state['status']=='saving':return self._save_result(state)
        key=self._photo_key(device,photo)
        self.store.save('phone_photo_intent',{'id':key,'mode':'save'})
        result=self.command(device,'photo.request',{'id':str(photo)})
        self.pending[key]=time.time()
        return {**self._save_result(self._record_save(device,photo,'saving',started=time.time())),'queued':True,'id':result.get('id')}
    def _has(self,device,capability):
        phone=getattr(self.workspace,'phone',None)
        hosted=getattr(self.workspace,'hosted_phones',None)
        devices=(phone.snapshot()['devices'] if phone else [])+(hosted() if hosted else [])
        return any(d['id']==device and capability in d.get('capabilities',[]) for d in devices)
    def command(self,device,kind,payload):
        # Saiph Hosted phones take the same actions through sealed envelopes.
        hosted=getattr(self.workspace,'hosted_phone_command',None)
        result=hosted(device,kind,payload) if hosted else None
        if result is not None:return result
        runtime=self.workspace.phone_runtime
        if not runtime or not runtime.client or not runtime.loop or not self.workspace.phone.connected:raise ValueError('Saiph is offline. This action has not been sent.')
        capability={'sms.open':'sms','sms.send':'sms','photo.request':'photos','call.command':'call-control','file.offer':'files','phone.ring':'ring',
                    'media.command':'media','contacts.search':'contacts','sms.compose':'sms','phone.ringer':'ringer','call.dial':'call-dial','calls.log.request':'call-log',
                    'sms.attachment.request':'sms'}[kind]
        phone=next((d for d in self.workspace.phone.snapshot()['devices'] if d['id']==device),None)
        # Nothing is queued for an offline device; say so rather than blaming the feature.
        if phone is not None and not phone.get('online'):raise ValueError(f"{phone.get('name') or 'That device'} is offline. Nothing was sent; try again when it reconnects.")
        if phone is None or capability not in phone.get('capabilities',[]):raise ValueError('This feature is unavailable on that device.')
        event={'id':str(uuid4()),'type':kind,'ttl_seconds':30 if kind!='file.offer' else 300,'targets':[device],'payload':payload}
        runtime.loop.call_soon_threadsafe(runtime.client.publish,event);return {'queued':True,'id':event['id']}
    def send_file(self,device,path):
        hosted=getattr(self.workspace,'hosted_phone_file',None)
        result=hosted(device,path) if hosted else None
        if result is not None:return result
        if self.file_server is None:
            config=dict(self.workspace.settings['hub'])
            self.file_server=FileServer(self.workspace.root,config)
        return self.command(device,'file.offer',self.file_server.offer_file(path))
    def offer_bytes(self,mime,data,name):
        """Oversized clipboard automatically follows the same direct file path."""
        if len(data)>MAX_FILE:raise ValueError('File exceeds 2 GB.')
        if self.file_server is None:self.file_server=FileServer(self.workspace.root,dict(self.workspace.settings['hub']))
        path=self.workspace.root/('clipboard-file-'+str(uuid4()))
        try:
            path.write_bytes(data);payload=self.file_server.offer_file(path);payload.update(name=safe_name(name),mime=mime)
            return payload
        finally:path.unlink(missing_ok=True)
    def dispatch(self,method,args):
        if method=='phone.file.send':return self.send_file(args['device_id'],args['path'])
        if method=='phone.sms.open':return self.command(args['device_id'],'sms.open',{'thread':int(args['thread'])})
        if method=='phone.sms.send':
            thread=next((r for r in self.snapshot()['threads'] if r['device_id']==args['device_id'] and r['thread']==int(args['thread'])),None)
            if not thread or not 1<=len(thread['recipients'])<=10:raise ValueError('This conversation is unavailable.')
            if len(thread['recipients'])>1 and not self._has(args['device_id'],'sms-group'):raise ValueError('Group replies stay in your phone’s messaging app. Update Saiph on your phone to reply here.')
            text=str(args['text'])
            if not text.strip() or len(text)>4096:raise ValueError('Enter a message up to 4096 characters.')
            return self.command(args['device_id'],'sms.send',{'thread':int(args['thread']),'text':text})
        if method=='phone.call':return self.command(args['device_id'],'call.command',{'operation':args['operation']})
        if method=='phone.ring':return self.command(args['device_id'],'phone.ring',{})
        if method=='phone.media':
            payload={'source':str(args['source'])[:240],'action':args.get('action')}
            if payload['action'] not in MEDIA_ACTIONS:raise ValueError('Unknown media control.')
            if payload['action'] in {'seek','volume'}:
                value=args.get('value')
                if type(value) is not int or value<0 or (payload['action']=='volume' and value>100):raise ValueError('Choose a valid position or volume.')
                payload['value']=value
            return self.command(args['device_id'],'media.command',payload)
        if method=='phone.contacts.search':
            query=str(args.get('query','')).strip()
            if not 0<len(query)<=64:raise ValueError('Type part of a name or number.')
            return self.command(args['device_id'],'contacts.search',{'query':query})
        if method=='phone.sms.compose':
            address,text=str(args.get('address','')).strip(),str(args.get('text',''))
            if not address or len(address)>120 or any(ord(c)<32 for c in address):raise ValueError('Enter a phone number or choose a contact.')
            if not text.strip() or len(text)>4096:raise ValueError('Enter a message up to 4096 characters.')
            return self.command(args['device_id'],'sms.compose',{'addresses':[address],'text':text})
        if method=='phone.ringer':
            if args.get('mode') not in RINGER_MODES:raise ValueError('Choose ring, vibrate or silent.')
            return self.command(args['device_id'],'phone.ringer',{'mode':args['mode']})
        if method=='phone.dial':
            number=str(args.get('number','')).strip()
            if not DIAL.fullmatch(number) or not any(c.isdigit() for c in number):raise ValueError('Enter a phone number. Codes with * or # stay on your phone.')
            return self.command(args['device_id'],'call.dial',{'number':number})
        if method=='phone.calls.log':return self.command(args['device_id'],'calls.log.request',{})
        if method=='phone.sms.attachment':
            thread,message,part=(int(args[key]) for key in ('thread','message','part'))
            try:
                held=self.store.get('phone_attachment_file',self._attachment_key(args['device_id'],thread,message,part))
                if same_file(held['path'],held['size'],held.get('sha256')):return {'ready':True,'id':held['id']}
            except ValueError:pass
            return self.command(args['device_id'],'sms.attachment.request',{'thread':thread,'message':message,'part':part})
        if method=='phone.sms.attachment.save':return self.attachment_save(args)
        if method=='phone.photo.save':return self.photo_request(args['device_id'],args['photo_id'])
        if method=='phone.photo.prefetch':return self.photo_request(args['device_id'],args['photo_id'],'prefetch')
        raise ValueError('Unknown phone action.')
    def stop(self):
        self.stop_requested.set()
        if self.file_server:self.file_server.stop();self.file_server=None

def mirror_phone(adb,serial,runner=subprocess.Popen):
    """Only a deliberate preview click calls this function. No arbitrary commands."""
    if not serial or any(c.isspace() or c in ';|&' for c in serial):raise ValueError('Choose an authorized phone in Settings → Advanced.')
    from .companion_tools import tool_path
    executable=tool_path('scrcpy')
    if not executable:raise ValueError('Install scrcpy once in Settings → Advanced to enable the phone preview.')
    env=os.environ.copy();env['ADB']=str(adb)
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    runner([executable,'--serial',serial,'--no-audio','--window-title','Saiph · Phone'],env=env,creationflags=flags,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return {'opened':True}
