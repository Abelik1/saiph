# SPDX-License-Identifier: AGPL-3.0-or-later
import base64, hashlib, os, time
from pathlib import Path
from types import SimpleNamespace
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature
from orion_hub.db import Database
from orion_hub.security import canonical, consume_pairing_code, create_pairing_code
from orion_hub.net import validate_watch_url


def test_pairing_code_is_one_time_and_not_stored_plaintext(tmp_path):
    db=Database(tmp_path/'db.sqlite3'); code=create_pairing_code(db)
    row=db.row('select * from pairing_codes')
    assert code not in str(row)
    assert consume_pairing_code(db,code) is True
    assert consume_pairing_code(db,code) is False


def test_signature_contract_round_trip():
    key=ec.generate_private_key(ec.SECP256R1()); body=b'{"title":"x"}'
    payload=canonical('POST','/v1/tasks','123','abc',body)
    sig=key.sign(payload,ec.ECDSA(hashes.SHA256()))
    key.public_key().verify(sig,payload,ec.ECDSA(hashes.SHA256()))


def test_watch_url_blocks_local_targets(monkeypatch):
    monkeypatch.setattr('socket.getaddrinfo', lambda *a,**k:[(2,1,6,'',('127.0.0.1',443))])
    try:
        validate_watch_url('https://localhost/status')
        assert False, 'local URL should be blocked'
    except ValueError as e:
        assert 'blocked' in str(e)


def test_watch_url_blocks_cleartext_by_default(monkeypatch):
    monkeypatch.setattr('socket.getaddrinfo', lambda *a,**k:[(2,1,6,'',('1.1.1.1',443))])
    try:
        validate_watch_url('http://example.com/')
        assert False
    except ValueError:
        pass
