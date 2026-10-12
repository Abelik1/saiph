# SPDX-License-Identifier: AGPL-3.0-or-later
import hashlib
import sqlite3
import time
from contextlib import closing
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from orion_hub.hosted_service import AccountRegistry, SharedHosted
from orion_hub.hosted_service_migration import import_owner
from test_hosted_service import service, send


def snapshot(service, tmp_path):
    alice = service['accounts'][0]
    source = service['registry'].config({'id':alice['id'], 'subject':'auth0|alice'}).database
    target = tmp_path / 'protected-snapshot.sqlite3'
    with closing(sqlite3.connect(source)) as original, closing(sqlite3.connect(target)) as copied:
        original.backup(copied)
    return target


def test_owner_migration_preserves_deployment_rosters_signed_requests_and_original(service, tmp_path):
    backup = snapshot(service, tmp_path)
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    registry = AccountRegistry(tmp_path / 'new-service', service['auth'])
    assert import_owner(registry, backup, 'auth0|alice', expires_at=int(time.time()) + 86400) == {'imported':True, 'devices':2}
    alice = service['accounts'][0]
    client = TestClient(SharedHosted(registry, tokens=service['tokens']))
    assert client.get('/v1/account', headers=alice['headers']).json()['deployment_id'] == alice['id']
    assert client.get('/v1/devices/rosters', headers=alice['headers']).json()['chain'] == alice['entries']
    assert send(client, alice['devices'][1], 'GET', '/v1/sealed/events').status_code == 200
    assert client.get('/v1/account', headers=service['accounts'][1]['headers']).status_code == 403
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == digest
    with pytest.raises(ValueError):
        import_owner(registry, backup, 'auth0|alice', expires_at=int(time.time()) + 86400)


@pytest.mark.parametrize('cause', ['owner', 'policy', 'expired', 'occupied', 'reserved', 'corrupt'])
def test_bad_import_never_creates_entitled_owner(service, tmp_path, cause):
    backup = snapshot(service, tmp_path)
    registry = AccountRegistry(tmp_path / 'new-service', service['auth'])
    subject, until = 'auth0|alice', int(time.time()) + 86400
    if cause == 'owner': subject = 'auth0|wrong'
    elif cause == 'expired': until = 1
    elif cause == 'occupied': registry.admit('auth0|bob', expires_at=until)
    elif cause == 'reserved': registry.issue_code(until)
    elif cause == 'corrupt': backup.write_bytes(b'not SQLite')
    else:
        with closing(sqlite3.connect(backup)) as db:
            with db: db.execute("UPDATE deployment SET audience='wrong'")
    with pytest.raises((ValueError, sqlite3.Error)):
        import_owner(registry, backup, subject, expires_at=until)
    assert registry.status({'issuer':service['auth'].issuer,'subject':'auth0|alice'}) == {'entitled':False,'until':None}
