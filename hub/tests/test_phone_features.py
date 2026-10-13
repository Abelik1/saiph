# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import pytest
from uuid import uuid4
from test_link import hub,client,event
from test_acceptance import pair
from orion_hub import features
from orion_hub.link import Event

def apply(hub,source,kind,payload,targets=None):
    with hub.DB.connect() as c:features.apply(c,source,Event.model_validate(event(type=kind,payload=payload,**({'targets':targets} if targets else {}))),10)
def message(**extra):return {'id':31,'addresses':['test'],'body':'PRIVATE_SMS','timestamp':123,'direction':'incoming','subscription':0,**extra}
def thread():return {'thread':7,'recipients':['test'],'message':message()}
def caps(hub,device,values):hub.DB.execute('INSERT INTO link_devices VALUES(?,?)',(device,json.dumps(values)))
def test_sms_ownership_commands_and_bounded_retention(hub,caplog):
    c=client(hub);_,phone=pair(hub,c);_,computer=pair(hub,c);_,other=pair(hub,c)
    caps(hub,phone,['sms'])
    apply(hub,phone,'sms.thread',thread())
    apply(hub,other,'sms.remove',{'thread':7})
    apply(hub,computer,'sms.send',{'thread':7,'text':'PRIVATE_REPLY'},[phone])
    with pytest.raises(ValueError):apply(hub,computer,'sms.send',{'thread':7,'text':'x'},[other])
    with pytest.raises(ValueError):apply(hub,computer,'sms.send',{'thread':8,'text':'x'},[phone])
    with pytest.raises(ValueError):apply(hub,computer,'sms.send',{'thread':7,'text':'x'})
    with pytest.raises(ValueError):apply(hub,computer,'sms.send',{'thread':7,'text':'x','addresses':['attacker']},[phone])
    apply(hub,phone,'sms.thread',{**thread(),'thread':8,'recipients':['first','second']})
    with pytest.raises(ValueError):apply(hub,computer,'sms.send',{'thread':8,'text':'x'},[phone])
    apply(hub,phone,'sms.messages',{'thread':7,'messages':[message(id=32,body='PRIVATE_LATER',timestamp=124)]})
    assert features.snapshot(hub.DB)['threads'][0]['message']['body']=='PRIVATE_LATER'
    assert len([m for m in features.snapshot(hub.DB)['messages'] if m['thread']==7])==2
    assert 'PRIVATE_SMS' not in caplog.text and 'PRIVATE_REPLY' not in caplog.text
    apply(hub,phone,'sms.remove',{'thread':7})
    assert all(m['thread']!=7 for m in features.snapshot(hub.DB)['messages'])
def test_call_commands_require_current_ring_and_permission(hub):
    c=client(hub);_,phone=pair(hub,c);_,computer=pair(hub,c)
    caps(hub,phone,['calls'])
    apply(hub,phone,'call.state',{'state':'ringing','number':'test','name':''})
    with pytest.raises(ValueError):apply(hub,computer,'call.command',{'operation':'answer'},[phone])
    hub.DB.execute('UPDATE link_devices SET capabilities_json=? WHERE device_id=?',(json.dumps(['calls','call-control']),phone))
    apply(hub,computer,'call.command',{'operation':'answer'},[phone])
    apply(hub,phone,'call.state',{'state':'ended','number':'test'})
    with pytest.raises(ValueError):apply(hub,computer,'call.command',{'operation':'reject'},[phone])
def offer(**extra):return {'name':'Photo.jpg','mime':'image/jpeg','size':1,'sha256':'a'*64,'blob':{'id':str(uuid4()),'address':'100.64.0.3','port':8767},**extra}
@pytest.mark.parametrize('payload',[offer(size=features.MAX_FILE+1),offer(blob={'id':str(uuid4()),'address':'127.0.0.1','port':8767}),offer(sha256='bad')])
def test_invalid_files_never_accept_outside_mesh_or_limits(hub,payload):
    c=client(hub);_,phone=pair(hub,c)
    with pytest.raises(ValueError):apply(hub,phone,'file.offer',payload)
def test_photos_are_metadata_only_and_removed_with_identity(hub):
    c=client(hub);_,phone=pair(hub,c);_,computer=pair(hub,c);caps(hub,phone,['photos'])
    apply(hub,phone,'photos.index',{'photos':[{'id':'17','name':'Photo.jpg','timestamp':1,'thumbnail':offer()}]})
    apply(hub,computer,'photo.request',{'id':'17'},[phone])
    assert features.snapshot(hub.DB)['photos'][0]['device_id']==phone
    with pytest.raises(ValueError):apply(hub,computer,'photo.request',{'id':'18'},[phone])
    hub.DB.execute('DELETE FROM devices WHERE id=?',(phone,))
    assert features.snapshot(hub.DB)['photos']==[]

def test_cloud_destination_is_bounded_to_explicit_capable_computers(hub):
    c=client(hub);_,phone=pair(hub,c);_,computer=pair(hub,c)
    caps(hub,computer,['files'])
    apply(hub,phone,'file.offer',offer(),[computer])
    with pytest.raises(ValueError):apply(hub,phone,'file.offer',offer(destination='cloud'),[computer])
    hub.DB.execute('UPDATE link_devices SET capabilities_json=? WHERE device_id=?',(json.dumps(['files','cloud.files']),computer))
    apply(hub,phone,'file.offer',offer(destination='cloud'),[computer])
    with pytest.raises(ValueError):apply(hub,phone,'file.offer',offer(destination='cloud'))
    with pytest.raises(ValueError):apply(hub,phone,'file.offer',offer(destination='../../other'),[computer])
    with pytest.raises(ValueError):apply(hub,phone,'photos.index',{'photos':[{'id':'17','name':'Photo.jpg','timestamp':1,'thumbnail':offer(destination='cloud')}]},[computer])
def test_capture_insert_names_one_computer_and_a_digest_only(hub):
    c=client(hub);_,phone=pair(hub,c);_,computer=pair(hub,c)
    apply(hub,phone,'capture.insert',{'sha256':'a'*64},[computer])
    for payload,targets in (({'sha256':'a'*64},None),({'sha256':'A'*64},[computer]),({'sha256':'a'*63},[computer]),
                            ({'sha256':'a'*64,'path':'C:/private'},[computer])):
        with pytest.raises(ValueError):apply(hub,phone,'capture.insert',payload,targets)
    assert features.snapshot(hub.DB)=={'threads':[],'messages':[],'calls':[],'photos':[]}
