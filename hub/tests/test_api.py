# SPDX-License-Identifier: AGPL-3.0-or-later
import base64, hashlib, importlib, os, time, uuid
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient


def test_pair_then_signed_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv('ORION_HUB_DATA',str(tmp_path/'data'))
    monkeypatch.setenv('ORION_HUB_AUTOMATIONS',str(tmp_path/'automations.json'))
    import orion_hub.app as mod
    mod=importlib.reload(mod); client=TestClient(mod.app)
    from orion_hub.security import create_pairing_code
    code=create_pairing_code(mod.DB)
    key=ec.generate_private_key(ec.SECP256R1()); pub=key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    r=client.post('/v1/pairing/claim',json={'code':code,'name':'test','public_key_der_b64':base64.b64encode(pub).decode()}); assert r.status_code==200
    device=r.json()['device_id']
    ts=str(int(time.time())); nonce=str(uuid.uuid4()); body=b''; path='/v1/dashboard'
    canonical=f"GET\n{path}\n{ts}\n{nonce}\n{hashlib.sha256(body).hexdigest()}".encode(); sig=base64.b64encode(key.sign(canonical,ec.ECDSA(hashes.SHA256()))).decode()
    headers={'X-Orion-Device-Id':device,'X-Orion-Timestamp':ts,'X-Orion-Nonce':nonce,'X-Orion-Signature':sig}
    assert client.get(path,headers=headers).status_code==200
    assert client.get(path,headers=headers).status_code==409
