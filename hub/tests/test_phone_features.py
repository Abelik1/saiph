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
    assert features.snapshot(hub.DB)=={'threads':[],'messages':[],'calls':[],'photos':[],'media':[],'ringers':[]}
def test_remote_control_targets_one_computer_that_offers_it(hub):
    c=client(hub);_,phone=pair(hub,c);_,computer=pair(hub,c)
    with pytest.raises(ValueError):apply(hub,phone,'remote.command',{'app':'media','control':'next'},[computer])
    caps(hub,computer,['remote'])
    apply(hub,phone,'remote.catalog.request',{},[computer])
    apply(hub,phone,'remote.command',{'app':'keyboard','control':'type','text':'hello'},[computer])
    for payload,targets in (({'app':'media','control':'next'},None),({'app':'Media','control':'next'},[computer]),
                            ({'app':'media','control':'next','shell':'calc'},[computer]),({'app':'keyboard','control':'type','text':'x'*501},[computer])):
        with pytest.raises(ValueError):apply(hub,phone,'remote.command',payload,targets)
    with pytest.raises(ValueError):apply(hub,phone,'remote.catalog.request',{'all':True},[computer])
    catalog={'apps':[{'id':'media','name':'Media','available':True,'controls':[{'id':'next','label':'Next','kind':'button'}]}]}
    apply(hub,computer,'remote.catalog',catalog,[phone])
    apply(hub,computer,'remote.result',{'app':'media','control':'next','ok':True,'message':''},[phone])
    with pytest.raises(ValueError):apply(hub,computer,'remote.catalog',{'apps':[{**catalog['apps'][0],'controls':[{'id':'x','label':'X','kind':'script'}]}]},[phone])
def test_ring_targets_one_phone_that_can_ring(hub):
    c=client(hub);_,phone=pair(hub,c);_,computer=pair(hub,c)
    with pytest.raises(ValueError):apply(hub,computer,'phone.ring',{},[phone])
    caps(hub,phone,['ring'])
    apply(hub,computer,'phone.ring',{},[phone])
    with pytest.raises(ValueError):apply(hub,computer,'phone.ring',{'volume':100},[phone])
    with pytest.raises(ValueError):apply(hub,computer,'phone.ring',{})
def session(**extra):
    return {'source':'com.spotify.music','app':'Spotify','title':'Song','artist':'Artist','playing':True,'can_play':True,'can_pause':True,
            'can_next':True,'can_previous':True,'can_seek':False,'position_ms':1000,'length_ms':200000,'volume':50,**extra}
def test_media_state_is_kept_per_phone_and_commands_need_the_capability(hub):
    c=client(hub);_,phone=pair(hub,c);_,computer=pair(hub,c)
    apply(hub,phone,'media.state',{'sessions':[session()]})
    apply(hub,phone,'media.state',{'sessions':[session(playing=False)]})
    assert [m['sessions'][0]['playing'] for m in features.snapshot(hub.DB)['media']]==[False]
    with pytest.raises(ValueError):apply(hub,phone,'media.state',{'sessions':[session(volume=101)]})
    with pytest.raises(ValueError):apply(hub,computer,'media.command',{'source':'com.spotify.music','action':'next'},[phone])
    caps(hub,phone,['media'])
    apply(hub,computer,'media.command',{'source':'com.spotify.music','action':'next'},[phone])
    for payload in ({'source':'x','action':'shell'},{'source':'x','action':'seek','value':-1}):
        with pytest.raises(ValueError):apply(hub,computer,'media.command',payload,[phone])
def test_contacts_and_call_log_answers_are_relayed_but_never_stored(hub):
    c=client(hub);_,phone=pair(hub,c);_,computer=pair(hub,c)
    caps(hub,phone,['contacts','call-log'])
    apply(hub,computer,'contacts.search',{'query':'Ali'},[phone])
    apply(hub,phone,'contacts.results',{'query':'Ali','contacts':[{'name':'PRIVATE_NAME','numbers':['+441234']}]},[computer])
    apply(hub,computer,'calls.log.request',{},[phone])
    apply(hub,phone,'calls.log',{'calls':[{'number':'+441234','name':'PRIVATE_NAME','timestamp':1,'duration':5,'type':'missed'}]},[computer])
    assert 'PRIVATE_NAME' not in json.dumps(features.snapshot(hub.DB))
    with pytest.raises(ValueError):apply(hub,phone,'contacts.results',{'query':'Ali','contacts':[]})
    with pytest.raises(ValueError):apply(hub,phone,'contacts.results',{'query':'Ali','contacts':[{'name':'x','numbers':['1'*41]}]},[computer])
    with pytest.raises(ValueError):apply(hub,computer,'contacts.search',{'query':''},[phone])
def test_compose_dial_and_ringer_commands_are_bounded(hub):
    c=client(hub);_,phone=pair(hub,c);_,computer=pair(hub,c)
    caps(hub,phone,['sms','ringer','call-dial'])
    apply(hub,computer,'sms.compose',{'addresses':['+447700900123'],'text':'Hello'},[phone])
    for payload in ({'addresses':[],'text':'x'},{'addresses':['a','b'],'text':'x'},{'addresses':['bad\nnumber'],'text':'x'},{'addresses':['1'],'text':''}):
        with pytest.raises(ValueError):apply(hub,computer,'sms.compose',payload,[phone])
    apply(hub,computer,'call.dial',{'number':'+44 (0) 7700-900123'},[phone])
    for number in ('tel:123','*21*07700900123#','#31#'):
        with pytest.raises(ValueError):apply(hub,computer,'call.dial',{'number':number},[phone])
    apply(hub,computer,'phone.ringer',{'mode':'silent'},[phone])
    with pytest.raises(ValueError):apply(hub,computer,'phone.ringer',{'mode':'loud'},[phone])
    apply(hub,phone,'ringer.state',{'mode':'vibrate'})
    assert features.snapshot(hub.DB)['ringers'][0]['mode']=='vibrate'
