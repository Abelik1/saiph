# SPDX-License-Identifier: AGPL-3.0-or-later
import hashlib
import json
import time
import pytest
from fastapi.testclient import TestClient
from orion_hub.hosted_auth import AccessTokens, ServiceAuth0Config
from orion_hub.hosted_service import SharedHosted
from orion_hub.hosted_downloads import Downloads
from test_hosted_service import service


@pytest.fixture
def release(service, tmp_path):
    directory = tmp_path / 'release'
    directory.mkdir()
    (directory / 'installer.exe').write_bytes(b'synthetic installer')
    catalog = {'windows': {'file':'installer.exe','sha256':hashlib.sha256(b'synthetic installer').hexdigest()}}
    (directory / 'catalog.json').write_text(json.dumps(catalog))
    downloads = Downloads(service['registry'], directory)
    web = AccessTokens(ServiceAuth0Config(service['auth'].issuer, service['auth'].audience, ('web',)),
                       key_resolver=lambda kid: service['authority'].public_key())
    client = TestClient(SharedHosted(service['registry'], tokens=service['tokens'], web_tokens=web, downloads=downloads))
    return client, downloads, directory


def test_web_entitlement_issues_checked_file_ticket_native_cannot_issue(service, release):
    client, downloads, _ = release
    alice = service['token']('auth0|alice', azp='web')
    assert client.post('/v1/beta/download', headers=service['accounts'][0]['headers'], json={'artifact':'windows'}).status_code == 401
    assert client.post('/v1/beta/download', headers=service['token']('auth0|unknown', azp='web'), json={'artifact':'windows'}).status_code == 403
    assert client.post('/v1/beta/download', headers=alice, json={'artifact':'../../accounts.sqlite3'}).status_code == 404
    result = client.post('/v1/beta/download', headers=alice, json={'artifact':'windows'})
    assert result.status_code == 200
    ticket = result.json()['ticket']
    response = client.get('/v1/download/' + ticket)
    assert response.content == b'synthetic installer'
    assert 'attachment' in response.headers['content-disposition']
    assert 'no-store' in response.headers['cache-control']
    assert client.get('/v1/download/' + ticket, headers={'Range':'bytes=0-8'}).content == b'synthetic'
    with service['registry'].connect() as db:
        assert db.execute('SELECT digest FROM download_tickets').fetchone()[0] != ticket
    service['registry'].set_active(service['accounts'][0]['id'], False)
    assert client.get('/v1/download/' + ticket).status_code == 404


def test_ticket_expiry_forgery_and_release_change_fail_closed(service, release):
    client, downloads, directory = release
    identity = {'issuer':service['auth'].issuer,'subject':'auth0|alice'}
    ticket = downloads.issue(identity, 'windows')['ticket']
    assert client.get('/v1/download/' + 'a'*43).status_code == 404
    assert client.get('/v1/download/' + ticket + '?artifact=linux').status_code == 404
    with service['registry'].connect() as db:
        db.execute('UPDATE download_tickets SET expires_at=?', (int(time.time()) - 1,))
    assert client.get('/v1/download/' + ticket).status_code == 404
    (directory / 'installer.exe').write_bytes(b'changed')
    with pytest.raises(ValueError): Downloads(service['registry'], directory)


def test_download_ticket_flood_is_bounded(service, release):
    client, _, _ = release
    headers = service['token']('auth0|alice', azp='web')
    for _ in range(30):
        assert client.post('/v1/beta/download', headers=headers, json={'artifact':'windows'}).status_code == 200
    assert client.post('/v1/beta/download', headers=headers, json={'artifact':'windows'}).status_code == 429
