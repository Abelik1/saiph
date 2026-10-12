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
class PhotoOriginal(File):
    photo_id: str = Field(pattern='^[0-9]{1,20}$')

MODELS={'sms.thread':Conversation,'sms.messages':Messages,'sms.remove':Thread,'sms.index':MessageIndex,
        'sms.open':Thread,'sms.send':SmsSend,'call.state':Call,'call.command':CallCommand,
        'photos.index':Photos,'photos.sync':PhotoKeys,'photo.request':PhotoRequest,'photo.original':PhotoOriginal,'file.offer':File}
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
    except (ValueError,TypeError):raise ValueError('Invalid phone feature envelope') from None
    if any(file.destination=='cloud' for file in files):
        if event.type!='file.offer' or not event.targets:raise ValueError('Cloud files require a destination computer')
        for target in event.targets:
            row=c.execute('SELECT capabilities_json FROM link_devices WHERE device_id=?',(target,)).fetchone()
            if not row or 'cloud.files' not in json.loads(row[0]):raise ValueError('Cloud destination unavailable')
    if event.type in {'sms.open','sms.send','call.command','photo.request'}:
        if event.targets is None or len(event.targets)!=1:raise ValueError('Phone command requires one owning phone')
        owner=event.targets[0]
        row=c.execute('SELECT capabilities_json FROM link_devices WHERE device_id=?',(owner,)).fetchone()
        caps=json.loads(row[0]) if row else []
        required={'sms.open':'sms','sms.send':'sms','call.command':'call-control','photo.request':'photos'}[event.type]
        if required not in caps:raise ValueError('Phone capability unavailable')
        if isinstance(value,Thread) and _get(c,owner,'thread',value.thread) is None:raise ValueError('Conversation unavailable')
        if isinstance(value,SmsSend) and len((_get(c,owner,'thread',value.thread) or {}).get('recipients',[]))!=1:raise ValueError('Group messaging remains on the phone')
        if isinstance(value,CallCommand) and (_get(c,owner,'call','current') or {}).get('state')!='ringing':raise ValueError('Call no longer ringing')
        if isinstance(value,PhotoRequest) and _get(c,owner,'photo',value.id) is None:raise ValueError('Photo unavailable')
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
        c.execute('DELETE FROM phone_features WHERE device_id=? AND (kind="thread" AND item_key=? OR kind="message" AND item_key LIKE ?)',(source,str(value.thread),f'{value.thread}:%'))
    elif isinstance(value,Call):_put(c,source,'call','current',data,now,1)
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
    result={'threads':[],'messages':[],'calls':[],'photos':[]}
    names={'thread':'threads','message':'messages','call':'calls','photo':'photos'}
    for row in rows:result[names[row['kind']]].append({**json.loads(row['data_json']),'device_id':row['device_id']})
    return result
