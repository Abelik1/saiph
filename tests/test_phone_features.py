# SPDX-License-Identifier: AGPL-3.0-or-later
import hashlib
import io
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import pytest
import time
import threading
from orion_mini import phone_features as f
from orion_mini.storage import Store

@pytest.mark.parametrize('name',['../../secret.txt','..\\secret.txt','CON','NUL.txt','<>:\\?*.txt',''])
def test_untrusted_file_names_stay_in_download_directory(name):
    result=f.safe_name(name)
    assert result and '/' not in result and '\\' not in result and '..' not in result
    assert result.split('.')[0].upper() not in {'CON','NUL'}
def test_stream_download_checks_size_digest_and_never_overwrites(tmp_path,monkeypatch):
    data=b'x'*200000;body={'blob':{'id':str(uuid4()),'address':'100.64.0.3','port':8767},'name':'../file.bin','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    class Response(io.BytesIO):
        headers={'Content-Length':str(len(data))}
    class Opener:
        def open(self,request,timeout):
            assert request.full_url.startswith('http://100.64.0.3:8767/v1/peer/phone/blobs/')
            return Response(data)
    monkeypatch.setattr(f.urllib.request,'build_opener',lambda *_:Opener())
    monkeypatch.setattr(f,'signed_headers',lambda *_:{'X-Orion-Device-Id':'computer'})
    target=tmp_path/'downloads';target.mkdir();(target/'file.bin').write_bytes(b'old')
    path=f.download(tmp_path,{'device_id':'computer'},'phone',body,target)
    assert path.read_bytes()==data and (target/'file.bin').read_bytes()==b'old'
    with pytest.raises(ValueError):f.download(tmp_path,{'device_id':'computer'},'phone',{**body,'sha256':'0'*64},target)
    assert not list(target.glob('*.part'))
    with pytest.raises(ValueError):f.download(tmp_path,{'device_id':'computer'},'phone',{**body,'size':f.MAX_FILE+1},target)
def test_phone_message_reducer_keeps_devices_isolated(tmp_path):
    workspace=SimpleNamespace(root=tmp_path,store=Store(tmp_path));features=f.PhoneFeatures(workspace)
    msg={'id':31,'body':'private','timestamp':1,'direction':'incoming'}
    for device in ['phone','other']:
        features.event({'type':'sms.thread','source':device,'payload':{'thread':1,'recipients':['test'],'message':msg}},None)
    assert len(features.snapshot()['messages'])==2
    features.event({'type':'sms.remove','source':'other','payload':{'thread':1}},None)
    assert features.snapshot()['messages'][0]['device_id']=='phone'
    restored=f.PhoneFeatures(workspace);assert restored.snapshot()['threads'][0]['message']['body']=='private'
def test_file_offer_is_a_snapshot_not_source_path_and_prunes(tmp_path):
    source=tmp_path/'original';source.write_bytes(b'file');cache=f.FileBlobs(tmp_path/'cache')
    ident,size,digest=cache.add_path(source);source.write_bytes(b'changed')
    assert cache.get(ident).read_bytes()==b'file' and size==4 and digest==hashlib.sha256(b'file').hexdigest()
    cache.clear();assert not list((tmp_path/'cache').glob('*'))
def test_mirroring_launches_only_explicit_fixed_scrcpy_arguments(monkeypatch):
    calls=[];monkeypatch.setattr(f.shutil,'which',lambda name:'scrcpy.exe')
    f.mirror_phone('adb.exe','authorized',lambda args,**kwargs:calls.append((args,kwargs)))
    assert calls[0][0]==['scrcpy.exe','--serial','authorized','--no-audio','--window-title','Saiph · Phone']
    with pytest.raises(ValueError):f.mirror_phone('adb','malicious;cmd')
def test_file_queue_survives_restart_and_runs_without_blocking_event_bus(tmp_path,monkeypatch):
    store=Store(tmp_path);workspace=SimpleNamespace(root=tmp_path,store=store)
    event={'id':str(uuid4()),'type':'file.offer','source':'phone','payload':{'name':'file.bin','size':4}}
    store.save('phone_transfer',{'id':event['id'],'event':event,'received':time.time()})
    def fake_download(root,config,source,payload,directory,*_):
        assert source=='phone';path=tmp_path/'complete.bin';path.write_bytes(b'file');return path
    monkeypatch.setattr(f,'download',fake_download)
    features=f.PhoneFeatures(workspace);features.start({'device_id':'computer'})
    try:
        deadline=time.monotonic()+3
        while store.all('phone_transfer') and time.monotonic()<deadline:time.sleep(.02)
        assert not store.all('phone_transfer')
        saved=store.get('phone_file',event['id']);assert Path(saved['path']).read_bytes()==b'file'
        # Replay does not create another download or another history record.
        features.event(event,{'device_id':'computer'})
        assert len(store.all('phone_file'))==1
    finally:features.stop()
def test_desktop_rejects_group_reply_before_transport(tmp_path):
    features=f.PhoneFeatures(SimpleNamespace(root=tmp_path,store=Store(tmp_path)))
    features.event({'type':'sms.thread','source':'phone','payload':{'thread':1,'recipients':['first','second'],'message':{'id':3,'body':'private','timestamp':1,'direction':'incoming'}}},None)
    with pytest.raises(ValueError,match='Group replies'):features.dispatch('phone.sms.send',{'device_id':'phone','thread':1,'text':'reply'})

def test_thumbnail_ack_path_persists_and_restores_offline_retry(tmp_path,monkeypatch):
    workspace=SimpleNamespace(root=tmp_path,store=Store(tmp_path))
    features=f.PhoneFeatures(workspace)
    monkeypatch.setattr(features,'start',lambda config:None)
    thumbnail={'name':'Photo.jpg','size':3,'sha256':hashlib.sha256(b'jpg').hexdigest()}
    photo={'id':'17','name':'Photo.jpg','timestamp':1,'thumbnail':thumbnail}
    attempts=[]
    def download(root,config,source,payload,directory,*args,**kwargs):
        attempts.append(source)
        if len(attempts)==1:raise OSError('offline')
        path=tmp_path/'thumbnail';path.write_bytes(b'jpg');return path
    monkeypatch.setattr(f,'download',download)
    assert features.event({'type':'photos.index','source':'phone','payload':{'photos':[photo]}},{})
    assert not attempts  # Receiving/ACKing metadata does no synchronous HTTP work.
    pending=workspace.store.all('phone_thumbnail')[0]
    restored=f.PhoneFeatures(workspace)
    restored._thumbnail_once({},now=pending['received'])
    restored._thumbnail_once({},now=pending['received']+1)
    assert attempts==['phone'] and workspace.store.all('phone_thumbnail')
    restored._thumbnail_once({},now=pending['received']+31)
    assert attempts==['phone','phone'] and not workspace.store.all('phone_thumbnail')
    assert restored.snapshot()['photos'][0]['preview'].startswith('data:image/jpeg;base64,')
    # Renewing an identical offer preserves the downloaded preview.
    restored.restore({'photos':[{**photo,'device_id':'phone'}]})
    assert not workspace.store.all('phone_thumbnail')
    restored.restore({'photos':[{**photo,'device_id':'phone','thumbnail':{**thumbnail,'sha256':'b'*64}}]})
    assert not restored.snapshot()['photos'][0].get('preview') and workspace.store.all('phone_thumbnail')
    restored.restore({'photos':[]})
    assert not workspace.store.all('phone_thumbnail')

def test_repeated_photo_save_requests_one_original_and_saves_one_copy(tmp_path,monkeypatch):
    # Physical acceptance: several Save clicks produced eight identical copies.
    monkeypatch.setattr(f.Path,'home',lambda:tmp_path/'home')
    workspace=SimpleNamespace(root=tmp_path/'app',store=Store(tmp_path/'app'),settings={})
    features=f.PhoneFeatures(workspace)
    commands=[]
    monkeypatch.setattr(features,'command',lambda device,kind,payload:commands.append((kind,payload)) or {'sent':True})
    for _ in range(4):features.photo_request('phone','17','save')
    assert commands==[('photo.request',{'id':'17'})]
    # The original arrives once and is published to Downloads/Orion.
    original={'id':str(uuid4()),'type':'photo.original','source':'phone',
              'payload':{'name':'Photo.jpg','size':3,'photo_id':'17'}}
    workspace.store.save('phone_transfer',{'id':original['id'],'event':original,'received':time.time()})
    def fake_download(root,config,source,payload,directory,*_):
        directory.mkdir(parents=True,exist_ok=True);path=directory/'Photo.jpg';path.write_bytes(b'jpg');return path
    monkeypatch.setattr(f,'download',fake_download)
    features.start({'device_id':'computer'})
    try:
        deadline=time.monotonic()+3
        while workspace.store.all('phone_transfer') and time.monotonic()<deadline:time.sleep(.02)
    finally:features.stop()
    saved=list((tmp_path/'home'/'Downloads'/'Orion').iterdir())
    assert [p.read_bytes() for p in saved]==[b'jpg']
    # Later clicks return the existing original without a new request or copy.
    again=features.photo_request('phone','17','save')
    assert again['saved'] and again['existing'] and again['path']==str(saved[0])
    assert len(commands)==1 and len(list(saved[0].parent.iterdir()))==1

def test_repeated_save_of_prefetched_photo_keeps_one_saved_copy(tmp_path,monkeypatch):
    monkeypatch.setattr(f.Path,'home',lambda:tmp_path/'home')
    workspace=SimpleNamespace(root=tmp_path/'app',store=Store(tmp_path/'app'),settings={})
    features=f.PhoneFeatures(workspace)
    cache=workspace.root/'phone-originals';cache.mkdir(parents=True)
    (cache/'Photo.jpg').write_bytes(b'jpg')
    workspace.store.save('phone_photo_original',{'id':features._photo_key('phone','17'),'device_id':'phone','photo_id':'17',
                                                 'name':'Photo.jpg','path':str(cache/'Photo.jpg'),'size':3})
    first=features.photo_request('phone','17','save')
    for _ in range(7):
        again=features.photo_request('phone','17','save')
        assert again['existing'] and again['path']==first['path']
    downloads=tmp_path/'home'/'Downloads'/'Orion'
    assert len(list(downloads.iterdir()))==1
    # If the owner deletes the saved copy, Save creates it again.
    Path(first['path']).unlink()
    assert Path(features.photo_request('phone','17','save')['path']).read_bytes()==b'jpg'

def test_cloud_files_use_only_the_configured_shared_folder(tmp_path,monkeypatch):
    workspace=SimpleNamespace(root=tmp_path/'app',store=Store(tmp_path/'app'),settings={'cloud':{'path':str(tmp_path/'Cloud')}})
    features=f.PhoneFeatures(workspace)
    assert features._destination({})==Path.home()/'Downloads'/'Orion'
    assert features._destination({'destination':'cloud','name':'../../outside'})==tmp_path/'Cloud'/'Shared'
    for destination in ['../../outside','screenshots','C:/']:
        with pytest.raises(ValueError):features._destination({'destination':destination})
    workspace.settings['cloud']['enabled']=False
    with pytest.raises(ValueError):features._destination({'destination':'cloud'})

def test_large_phone_restore_uses_one_connection_and_one_retention_scan_per_kind(tmp_path,monkeypatch):
    workspace=SimpleNamespace(root=tmp_path,store=Store(tmp_path));features=f.PhoneFeatures(workspace)
    counts=[];prunes=[];connect=workspace.store.connect;prune=features._prune
    def connected():counts.append(1);return connect()
    def pruned(connection,kind,device):prunes.append((kind,device));return prune(connection,kind,device)
    monkeypatch.setattr(workspace.store,'connect',connected);monkeypatch.setattr(features,'_prune',pruned)
    messages=[{'device_id':'phone','thread':1,'id':i,'body':'synthetic','timestamp':i} for i in range(2100)]
    features.restore({'messages':messages})
    assert len(counts)==1 and prunes==[('message','phone')]
    assert len(features.snapshot()['messages'])==2000

def test_gui_snapshot_reads_previous_complete_state_while_restore_is_writing(tmp_path,monkeypatch):
    workspace=SimpleNamespace(root=tmp_path,store=Store(tmp_path));features=f.PhoneFeatures(workspace)
    features.restore({'messages':[{'device_id':'phone','thread':1,'id':1,'body':'old'}]})
    entered=threading.Event();release=threading.Event();read=threading.Event();failures=[];observed=[];save=features._save
    def stalled(kind,row,**kwargs):
        saved=save(kind,row,**kwargs);entered.set();assert release.wait(3);return saved
    monkeypatch.setattr(features,'_save',stalled)
    def restore():
        try:features.restore({'messages':[{'device_id':'phone','thread':1,'id':2,'body':'new'}]})
        except BaseException as error:failures.append(error)
    def snapshot():
        try:observed.append(features.snapshot()['messages'])
        except BaseException as error:failures.append(error)
        finally:read.set()
    writer=threading.Thread(target=restore);reader=threading.Thread(target=snapshot);writer.start()
    try:
        assert entered.wait(3);reader.start()
        assert read.wait(1), 'GUI snapshot waited on the restore writer lock'
        assert observed[0][0]['message_id']==1 and len(observed[0])==1
    finally:
        release.set();writer.join(3)
        if reader.ident:reader.join(3)
    assert not failures and features.snapshot()['messages'][0]['message_id']==2

def test_restore_failure_rolls_back_and_sms_history_batch_uses_one_connection(tmp_path,monkeypatch):
    workspace=SimpleNamespace(root=tmp_path,store=Store(tmp_path));features=f.PhoneFeatures(workspace)
    features.restore({'messages':[{'device_id':'phone','thread':1,'id':1,'body':'old'}]})
    with pytest.raises(KeyError):features.restore({'messages':[{'device_id':'phone','thread':1,'id':2},{'thread':1,'id':3}]})
    assert [row['message_id'] for row in features.snapshot()['messages']]==[1]
    counts=[];connect=workspace.store.connect
    def connected():counts.append(1);return connect()
    monkeypatch.setattr(workspace.store,'connect',connected)
    features.event({'type':'sms.messages','source':'phone','payload':{'thread':1,'messages':[{'id':i,'body':'synthetic'} for i in range(2,52)]}},None)
    assert len(counts)==1

def _photo_features(tmp_path,monkeypatch):
    # Path.home() uses USERPROFILE on Windows, so HOME alone does not isolate saves.
    monkeypatch.setattr(f.Path,'home',lambda:tmp_path/'home')
    workspace=SimpleNamespace(root=tmp_path/'app',store=Store(tmp_path/'app'),settings={})
    features=f.PhoneFeatures(workspace);commands=[]
    def command(device,kind,payload):commands.append((device,kind,payload));return {'queued':True,'id':str(uuid4())}
    monkeypatch.setattr(features,'command',command)
    return workspace,features,commands

def test_repeated_photo_save_of_a_prefetched_original_keeps_one_file(tmp_path,monkeypatch):
    workspace,features,commands=_photo_features(tmp_path,monkeypatch)
    data=b'synthetic photo bytes';cache=workspace.root/'phone-originals';cache.mkdir(parents=True)
    (cache/'Photo.png').write_bytes(data)
    workspace.store.save('phone_photo_original',{'id':features._photo_key('phone','17'),'device_id':'phone','photo_id':'17','name':'Photo.png','path':str(cache/'Photo.png'),'size':len(data)})
    results=[features.dispatch('phone.photo.save',{'device_id':'phone','photo_id':'17'}) for _ in range(8)]
    downloads=Path.home()/'Downloads'/'Orion'
    assert [p.name for p in downloads.iterdir()]==['Photo.png'] and (downloads/'Photo.png').read_bytes()==data
    assert {r['path'] for r in results}=={str(downloads/'Photo.png')} and not commands
    assert results[0]['status']=='saved' and not results[0]['existing'] and all(r['existing'] for r in results[1:])
    assert results[0]['folder']=='Downloads → Orion' and len(workspace.store.all('phone_file'))==1
    assert results[0]['file_id']==workspace.store.all('phone_file')[0]['id']
    saves=features.snapshot()['photo_saves'];assert [(s['photo_id'],s['status']) for s in saves]==[('17','saved')]
    # A changed copy is not reported as saved; a deliberate new save keeps the edited file.
    (downloads/'Photo.png').write_bytes(b'edited')
    again=features.dispatch('phone.photo.save',{'device_id':'phone','photo_id':'17'})
    assert not again['existing'] and Path(again['path'])!=downloads/'Photo.png' and Path(again['path']).read_bytes()==data
    assert (downloads/'Photo.png').read_bytes()==b'edited'

def test_photo_save_in_flight_is_requested_once_and_completes_with_one_download(tmp_path,monkeypatch):
    workspace,features,commands=_photo_features(tmp_path,monkeypatch)
    data=b'synthetic original';downloads=[]
    def fake_download(root,config,source,payload,directory,*args,**kwargs):
        downloads.append(directory);directory.mkdir(parents=True,exist_ok=True)
        path=directory/f.safe_name(payload['name'])
        if path.exists():path=directory/(path.stem+' '+str(uuid4())[:8]+path.suffix)
        path.write_bytes(data);return path
    monkeypatch.setattr(f,'download',fake_download)
    first=features.dispatch('phone.photo.save',{'device_id':'phone','photo_id':'17'})
    assert first['status']=='saving' and first['queued']
    # Repeated clicks and a hover prefetch while saving send nothing more.
    assert features.dispatch('phone.photo.save',{'device_id':'phone','photo_id':'17'})['status']=='saving'
    assert features.dispatch('phone.photo.prefetch',{'device_id':'phone','photo_id':'17'})=={'queued':True}
    assert len(commands)==1 and workspace.store.get('phone_photo_intent',features._photo_key('phone','17'))['mode']=='save'
    assert features.snapshot()['photo_saves'][0]['status']=='saving'
    offer={'photo_id':'17','name':'Photo.png','size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'blob':{}}
    monkeypatch.setattr(features,'start',lambda config:setattr(features,'transfer_config',config))
    features.event({'id':str(uuid4()),'type':'photo.original','source':'phone','payload':offer},{'device_id':'computer'})
    features._transfer_once()
    saved=features.snapshot()['photo_saves'][0]
    assert saved['status']=='saved' and saved['folder']=='Downloads → Orion' and Path(saved['path']).read_bytes()==data
    assert not workspace.store.all('phone_transfer')
    # A duplicate offer from the phone is not downloaded again.
    features.event({'id':str(uuid4()),'type':'photo.original','source':'phone','payload':offer},{'device_id':'computer'})
    features._transfer_once()
    assert not workspace.store.all('phone_transfer')
    assert len(downloads)==1 and [p.name for p in (Path.home()/'Downloads'/'Orion').iterdir()]==['Photo.png']
    repeat=features.dispatch('phone.photo.save',{'device_id':'phone','photo_id':'17'})
    assert repeat['existing'] and repeat['path']==saved['path'] and len(commands)==1
    # State is metadata only.
    assert 'synthetic' not in str(workspace.store.all('phone_photo_save'))

def test_unanswered_photo_save_becomes_retryable(tmp_path,monkeypatch):
    workspace,features,commands=_photo_features(tmp_path,monkeypatch)
    features.dispatch('phone.photo.save',{'device_id':'phone','photo_id':'17'})
    row=workspace.store.get('phone_photo_save',features._photo_key('phone','17'))
    workspace.store.save('phone_photo_save',{**row,'started':time.time()-f.SAVE_ANSWER_SECONDS-1})
    stale=features.snapshot()['photo_saves'][0]
    assert stale['status']=='failed' and 'did not send' in stale['error']
    assert features.dispatch('phone.photo.save',{'device_id':'phone','photo_id':'17'})['status']=='saving' and len(commands)==2

def test_offline_photo_save_reports_an_error_without_recording_saving(tmp_path,monkeypatch):
    workspace,features,_=_photo_features(tmp_path,monkeypatch)
    def offline(*_):raise ValueError('Orion is offline. This action has not been sent.')
    monkeypatch.setattr(features,'command',offline)
    with pytest.raises(ValueError,match='offline'):features.dispatch('phone.photo.save',{'device_id':'phone','photo_id':'17'})
    assert not features.snapshot()['photo_saves']
