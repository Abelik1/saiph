# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone-authoritative SMS/calls/photo metadata; contents never enter logs."""
from __future__ import annotations
import json
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

MAX_FILE = 2 * 1024**3
SCHEMA = """
CREATE TABLE IF NOT EXISTS phone_features(device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,kind TEXT NOT NULL,item_key TEXT NOT NULL,data_json TEXT NOT NULL,updated_at REAL NOT NULL,PRIMARY KEY(device_id,kind,item_key));
"""
class Payload(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
class Message(Payload):
    id: int = Field(ge=0)
    addresses: list[str] = Field(max_length=10)
    body: str = Field(max_length=4096)
    timestamp: int = Field(ge=0)
    direction: str = Field(pattern='^(incoming|outgoing)$')
    subscription: int = 0
class Conversation(Payload):
    thread: int = Field(ge=0)
    recipients: list[str] = Field(max_length=10)
    message: Message
class Messages(Payload):
    thread: int = Field(ge=0)
    messages: list[Message] = Field(max_length=10)
class Thread(Payload):
    thread: int = Field(ge=0)
class MessageIndex(Thread):
    ids: list[int] = Field(max_length=2000)
class SmsSend(Thread):
    text: str = Field(min_length=1,max_length=4096)
class Call(Payload):
    state: str = Field(pattern='^(ringing|active|missed|ended)$')
    number: str = Field(max_length=120)
    name: str = Field(default='',max_length=240)
class CallCommand(Payload):
    operation: str = Field(pattern='^(answer|reject)$')
class Blob(Payload):
    id: str
    address: str
    port: int = Field(ge=1024,le=65535)
class File(Payload):
    destination: Literal['downloads','cloud'] = 'downloads'
    name: str = Field(min_length=1,max_length=240)
    mime: str = Field(min_length=1,max_length=120)
    size: int = Field(ge=0,le=MAX_FILE)
    sha256: str = Field(pattern='^[a-f0-9]{64}$')
    blob: Blob
class Photo(Payload):
    id: str = Field(pattern='^[0-9]{1,20}$')
    name: str = Field(max_length=240)
    timestamp: int = Field(ge=0)
    thumbnail: File
class Photos(Payload):
    photos: list[Photo] = Field(max_length=10)
class PhotoKeys(Payload):
    ids: list[str] = Field(max_length=100)
class PhotoRequest(Payload):
    id: str = Field(pattern='^[0-9]{1,20}$')
class CaptureInsert(Payload):
    sha256: str = Field(pattern='^[a-f0-9]{64}$')
class RemoteRequest(Payload):
    pass
class RemoteCommand(Payload):
    app: str = Field(pattern='^[a-z_]{1,32}$')
    control: str = Field(pattern='^[a-z_]{1,32}$')
    text: str | None = Field(default=None,min_length=1,max_length=500)
class RemoteControl(Payload):
    id: str = Field(pattern='^[a-z_]{1,32}$')
    label: str = Field(min_length=1,max_length=60)
    kind: Literal['button','text']
    max: int | None = Field(default=None,ge=1,le=500)
class RemoteApp(Payload):
    id: str = Field(pattern='^[a-z_]{1,32}$')
    name: str = Field(min_length=1,max_length=60)
    available: bool
    controls: list[RemoteControl] = Field(max_length=16)
class RemoteCatalog(Payload):
    apps: list[RemoteApp] = Field(max_length=16)
class RemoteResult(Payload):
    app: str = Field(max_length=32)
    control: str = Field(max_length=32)
    ok: bool
    message: str = Field(max_length=200)
class MediaSession(Payload):
    source: str = Field(min_length=1,max_length=240)
    app: str = Field(max_length=120)
    title: str = Field(max_length=240)
    artist: str = Field(max_length=240)
    playing: bool
    can_play: bool
    can_pause: bool
    can_next: bool
    can_previous: bool
    can_seek: bool
    position_ms: int = Field(ge=0,le=2**40)
    length_ms: int = Field(ge=0,le=2**40)
    volume: int = Field(ge=0,le=100)
class MediaState(Payload):
    sessions: list[MediaSession] = Field(max_length=5)
class MediaCommand(Payload):
    source: str = Field(min_length=1,max_length=240)
    action: Literal['play','pause','next','previous','seek','volume']
    value: int | None = Field(default=None,ge=0,le=2**40)
class ContactsSearch(Payload):
    query: str = Field(min_length=1,max_length=64)
class Contact(Payload):
    name: str = Field(max_length=120)
    numbers: list[str] = Field(max_length=5)
class ContactsResults(Payload):
    query: str = Field(max_length=64)
    contacts: list[Contact] = Field(max_length=20)
class SmsCompose(Payload):
    addresses: list[str] = Field(min_length=1,max_length=1)
    text: str = Field(min_length=1,max_length=4096)
class Ringer(Payload):
    mode: Literal['ring','vibrate','silent']
class Dial(Payload):
    number: str = Field(pattern=r'^[0-9+() .-]{1,40}$')  # No * or #: MMI codes can change call forwarding.
class CallLogEntry(Payload):
    number: str = Field(max_length=120)
    name: str = Field(max_length=240)
    timestamp: int = Field(ge=0)
    duration: int = Field(ge=0)
    type: Literal['incoming','outgoing','missed','rejected','other']
class CallLog(Payload):
    calls: list[CallLogEntry] = Field(max_length=50)
class AttachmentPart(Payload):
    part: int = Field(ge=0)
    mime: str = Field(min_length=1,max_length=120)
    name: str = Field(max_length=180)
class SmsAttachments(Payload):
    thread: int = Field(ge=0)
    message: int = Field(ge=0)
    parts: list[AttachmentPart] = Field(min_length=1,max_length=10)
class SmsAttachmentRequest(Payload):
    thread: int = Field(ge=0)
    message: int = Field(ge=0)
    part: int = Field(ge=0)
class SmsAttachmentFile(File):
    thread: int = Field(ge=0)
    message: int = Field(ge=0)
    part: int = Field(ge=0)
class PhotoOriginal(File):
    photo_id: str = Field(pattern='^[0-9]{1,20}$')

MODELS={'sms.thread':Conversation,'sms.messages':Messages,'sms.remove':Thread,'sms.index':MessageIndex,
        'sms.open':Thread,'sms.send':SmsSend,'call.state':Call,'call.command':CallCommand,
        'photos.index':Photos,'photos.sync':PhotoKeys,'photo.request':PhotoRequest,'photo.original':PhotoOriginal,'file.offer':File,
        'capture.insert':CaptureInsert,'remote.catalog.request':RemoteRequest,'phone.ring':RemoteRequest,'remote.command':RemoteCommand,
        'remote.catalog':RemoteCatalog,'remote.result':RemoteResult,'media.state':MediaState,'media.command':MediaCommand,
        'contacts.search':ContactsSearch,'contacts.results':ContactsResults,'sms.compose':SmsCompose,'ringer.state':Ringer,
        'phone.ringer':Ringer,'call.dial':Dial,'calls.log.request':RemoteRequest,'calls.log':CallLog,
        'sms.attachments':SmsAttachments,'sms.attachment.request':SmsAttachmentRequest,'sms.attachment.file':SmsAttachmentFile}
def ensure(connection):
    connection.execute(SCHEMA)
def _put(c,device,kind,key,data,now,limit):
    c.execute('INSERT INTO phone_features VALUES(?,?,?,?,?) ON CONFLICT(device_id,kind,item_key) DO UPDATE SET data_json=excluded.data_json,updated_at=excluded.updated_at',(device,kind,str(key),json.dumps(data,separators=(',',':')),now))
    c.execute('DELETE FROM phone_features WHERE device_id=? AND kind=? AND item_key NOT IN (SELECT item_key FROM phone_features WHERE device_id=? AND kind=? ORDER BY updated_at DESC,rowid DESC LIMIT ?)',(device,kind,device,kind,limit))
def _get(c,device,kind,key):
    row=c.execute('SELECT data_json FROM phone_features WHERE device_id=? AND kind=? AND item_key=?',(device,kind,str(key))).fetchone()
    return json.loads(row[0]) if row else None
def apply(c,source,event,now):
    model=MODELS.get(event.type)
    if model is None:return
    ensure(c)
    try:
        value=model.model_validate(event.payload)
        data=value.model_dump()
        messages=[value.message] if isinstance(value,Conversation) else value.messages if isinstance(value,Messages) else []
        if any(not a or len(a)>120 for m in messages for a in m.addresses):raise ValueError()
        if isinstance(value,Conversation) and any(not a or len(a)>120 for a in value.recipients):raise ValueError()
        files=([value] if isinstance(value,File) else [p.thumbnail for p in value.photos] if isinstance(value,Photos) else [])
        import ipaddress
        for file in files:
            if str(UUID(file.blob.id))!=file.blob.id:raise ValueError()
            address=ipaddress.ip_address(file.blob.address)
            if address not in ipaddress.ip_network('100.64.0.0/10' if address.version==4 else 'fd7a:115c:a1e0::/48'):raise ValueError()
        if isinstance(value,Photos) and any(p.thumbnail.size>512*1024 for p in value.photos):raise ValueError()
        if isinstance(value,ContactsResults) and any(not n or len(n)>40 for c in value.contacts for n in c.numbers):raise ValueError()
        if isinstance(value,SmsCompose) and any(not a or len(a)>120 or any(ord(ch)<32 for ch in a) for a in value.addresses):raise ValueError()
    except (ValueError,TypeError):raise ValueError('Invalid phone feature envelope') from None
    if any(file.destination=='cloud' for file in files):
        if event.type!='file.offer' or not event.targets:raise ValueError('Cloud files require a destination computer')
        for target in event.targets:
            row=c.execute('SELECT capabilities_json FROM link_devices WHERE device_id=?',(target,)).fetchone()
            if not row or 'cloud.files' not in json.loads(row[0]):raise ValueError('Cloud destination unavailable')
    if event.type.startswith('remote.'):
        # Phone remote: one named computer, which must currently offer remote control.
        if event.targets is None or len(event.targets)!=1:raise ValueError('Remote control names one device')
        if event.type in {'remote.catalog.request','remote.command'}:
            row=c.execute('SELECT capabilities_json FROM link_devices WHERE device_id=?',(event.targets[0],)).fetchone()
            if not row or 'remote' not in json.loads(row[0]):raise ValueError('Remote control unavailable')
        return
    if event.type in {'contacts.results','calls.log','sms.attachment.file'}:
        # Private answers to one computer's request: relayed, never stored.
        if event.targets is None or len(event.targets)!=1:raise ValueError('Phone answer names one device')
        return
    if event.type=='capture.insert':
        # Names one computer that receives the matching photo offer; never stored.
        if event.targets is None or len(event.targets)!=1:raise ValueError('Capture requires one destination computer')
        return
    if event.type in {'sms.open','sms.send','call.command','photo.request','phone.ring','media.command','contacts.search','sms.compose','phone.ringer','call.dial','calls.log.request','sms.attachment.request'}:
        if event.targets is None or len(event.targets)!=1:raise ValueError('Phone command requires one owning phone')
        owner=event.targets[0]
        row=c.execute('SELECT capabilities_json FROM link_devices WHERE device_id=?',(owner,)).fetchone()
        caps=json.loads(row[0]) if row else []
        required={'sms.open':'sms','sms.send':'sms','call.command':'call-control','photo.request':'photos','phone.ring':'ring','media.command':'media',
                  'contacts.search':'contacts','sms.compose':'sms','phone.ringer':'ringer','call.dial':'call-dial','calls.log.request':'call-log','sms.attachment.request':'sms'}[event.type]
        if required not in caps:raise ValueError('Phone capability unavailable')
        if isinstance(value,Thread) and _get(c,owner,'thread',value.thread) is None:raise ValueError('Conversation unavailable')
        if isinstance(value,SmsSend):
            recipients=len((_get(c,owner,'thread',value.thread) or {}).get('recipients',[]))
            # Group replies need a phone that sends them as MMS (sms-group); older phones keep them.
            if not 1<=recipients<=10 or (recipients>1 and 'sms-group' not in caps):raise ValueError('Group messaging remains on the phone')
        if isinstance(value,CallCommand) and (_get(c,owner,'call','current') or {}).get('state')!='ringing':raise ValueError('Call no longer ringing')
        if isinstance(value,PhotoRequest) and _get(c,owner,'photo',value.id) is None:raise ValueError('Photo unavailable')
        if isinstance(value,SmsAttachmentRequest) and value.part not in [p['part'] for p in (_get(c,owner,'attachment',f'{value.thread}:{value.message}') or {}).get('parts',[])]:
            raise ValueError('Attachment unavailable')
        return
    if isinstance(value,Conversation):
        _put(c,source,'thread',value.thread,data,now,500)
        _put(c,source,'message',f'{value.thread}:{value.message.id}',{'thread':value.thread,**value.message.model_dump()},now,2000)
    elif isinstance(value,Messages):
        for message in value.messages:_put(c,source,'message',f'{value.thread}:{message.id}',{'thread':value.thread,**message.model_dump()},now,2000)
        thread=_get(c,source,'thread',value.thread)
        if thread and value.messages:
            thread['message']=max([thread['message'],*(m.model_dump() for m in value.messages)],key=lambda m:m['timestamp'])
            _put(c,source,'thread',value.thread,thread,now,500)
    elif isinstance(value,MessageIndex):
        rows=c.execute('SELECT item_key,data_json FROM phone_features WHERE device_id=? AND kind="message" AND item_key LIKE ?',(source,f'{value.thread}:%')).fetchall()
        current=set(value.ids)
        for row in rows:
            if json.loads(row['data_json'])['id'] not in current:c.execute('DELETE FROM phone_features WHERE device_id=? AND kind="message" AND item_key=?',(source,row['item_key']))
    elif isinstance(value,Thread):
        c.execute('DELETE FROM phone_features WHERE device_id=? AND (kind="thread" AND item_key=? OR kind IN ("message","attachment") AND item_key LIKE ?)',(source,str(value.thread),f'{value.thread}:%'))
    elif isinstance(value,Call):_put(c,source,'call','current',data,now,1)
    elif isinstance(value,MediaState):_put(c,source,'media','current',data,now,1)
    elif isinstance(value,Ringer):_put(c,source,'ringer','current',data,now,1)
    elif isinstance(value,SmsAttachments):_put(c,source,'attachment',f'{value.thread}:{value.message}',data,now,2000)
    elif isinstance(value,Photos):
        for photo in value.photos:_put(c,source,'photo',photo.id,photo.model_dump(),now,100)
    elif isinstance(value,PhotoKeys):
        current=set(value.ids)
        for row in c.execute('SELECT item_key FROM phone_features WHERE device_id=? AND kind="photo"',(source,)).fetchall():
            if row['item_key'] not in current:c.execute('DELETE FROM phone_features WHERE device_id=? AND kind="photo" AND item_key=?',(source,row['item_key']))
    # Files are short-lived delivery offers; photo originals never enter the index.
def snapshot(db):
    with db.connect() as c:
        ensure(c)
        rows=c.execute('SELECT * FROM phone_features ORDER BY updated_at DESC').fetchall()
    result={'threads':[],'messages':[],'calls':[],'photos':[],'media':[],'ringers':[],'attachments':[]}
    names={'thread':'threads','message':'messages','call':'calls','photo':'photos','media':'media','ringer':'ringers','attachment':'attachments'}
    for row in rows:result[names[row['kind']]].append({**json.loads(row['data_json']),'device_id':row['device_id']})
    return result
