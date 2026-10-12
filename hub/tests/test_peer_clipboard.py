# SPDX-License-Identifier: AGPL-3.0-or-later
import hashlib
from uuid import uuid4
import pytest
from test_link import hub, client, event
from test_acceptance import pair, headers, post

def test_direct_peer_proof_is_bound_to_destination_and_cannot_replay(hub):
    c=client(hub); sender_key,sender=pair(hub,c); receiver_key,receiver=pair(hub,c); other_key,other=pair(hub,c)
    path=f'/v1/peer/{receiver}/blobs/{uuid4()}'
    proof={'path':path,'headers':headers(sender_key,sender,'GET',path)}
    assert post(c,other_key,other,'/v1/link/peer/verify',proof).status_code==403
    r=post(c,receiver_key,receiver,'/v1/link/peer/verify',proof)
    assert r.status_code==200 and r.json()['device_id']==sender
    assert post(c,receiver_key,receiver,'/v1/link/peer/verify',proof).status_code==409
    # Revocation takes effect immediately, including on direct endpoints.
    proof['headers']=headers(sender_key,sender,'GET',path)
    hub.DB.execute('DELETE FROM devices WHERE id=?',(sender,))
    assert post(c,receiver_key,receiver,'/v1/link/peer/verify',proof).status_code==401

def payload():
    return {'mime':'text/plain','text':'PRIVATE_CLIP','size':12,'sha256':hashlib.sha256(b'PRIVATE_CLIP').hexdigest()}

@pytest.mark.parametrize('changes',[
    {'size':True},{'text':'WRONG'},{'sha256':'0'*64},{'size':25*1024*1024+1},
    {'mime':'application/executable'}, {'blob':{'id':str(uuid4()),'address':'127.0.0.1','port':8766}},
])
def test_clipboard_bounds_hash_and_mesh_descriptor_are_atomic(hub,changes):
    c=client(hub);_,device=pair(hub,c)
    with pytest.raises(ValueError):hub.LINK.store.publish(device,event(type='clipboard',payload={**payload(),**changes}))
    assert not hub.DB.rows('SELECT * FROM link_events')

def test_clipboard_keeps_content_out_of_logs(hub,caplog):
    c=client(hub);_,device=pair(hub,c)
    value=payload();value['size']=len(value['text'].encode())
    hub.LINK.store.publish(device,event(type='clipboard',payload=value))
    assert 'PRIVATE_CLIP' not in caplog.text
