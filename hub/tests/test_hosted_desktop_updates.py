# SPDX-License-Identifier: AGPL-3.0-or-later
"""Desktop update feed on the shared Hosted service: native account tokens, checked descriptions."""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from orion_hub.hosted_auth import AccessTokens, ServiceAuth0Config
from orion_hub.hosted_downloads import Downloads
from orion_hub.hosted_service import SharedHosted
from orion_hub.hosted_usage import classify
from test_hosted_service import service  # noqa: F401  (fixture)

WINDOWS = b'MZ synthetic windows installer'
LINUX = b'#!/bin/sh\n# synthetic linux setup\n'


def description(platform, body, **changes):
    value = {'schema': 1, 'platform': platform, 'profile': 'link', 'build': 12, 'version': '0.1.0-beta.12',
             'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body), 'notes': 'Faster photo sync.\nFewer prompts.'}
    value.update(changes)
    return json.dumps(value).encode()


def publish(directory, files):
    directory.mkdir(exist_ok=True)
    catalog = {}
    for key, (name, body) in files.items():
        (directory / name).write_bytes(body)
        catalog[key] = {'file': name, 'sha256': hashlib.sha256(body).hexdigest()}
    (directory / 'catalog.json').write_text(json.dumps(catalog))
    return directory


def complete(directory):
    return publish(directory, {
        'windows': ('Saiph-Setup.exe', WINDOWS), 'linux': ('Saiph-Setup.run', LINUX),
        'windows_release': ('windows-release.json', description('windows-x86_64', WINDOWS)),
        'linux_release': ('linux-release.json', description('linux-x86_64', LINUX, notes='')),
    })


@pytest.fixture
def feed(service, tmp_path):
    downloads = Downloads(service['registry'], complete(tmp_path / 'release'))
    web = AccessTokens(ServiceAuth0Config(service['auth'].issuer, service['auth'].audience, ('web',)),
                       key_resolver=lambda kid: service['authority'].public_key())
    client = TestClient(SharedHosted(service['registry'], tokens=service['tokens'], web_tokens=web, downloads=downloads))
    return client, downloads


def test_native_account_reads_the_exact_description(service, feed, tmp_path):
    client, _ = feed
    headers = service['accounts'][0]['headers']
    response = client.get('/v1/app/desktop/windows-x86_64/release', headers=headers)
    assert response.status_code == 200
    assert response.content == (tmp_path / 'release' / 'windows-release.json').read_bytes()
    assert response.headers['content-type'] == 'application/json'
    assert response.headers['cache-control'] == 'no-store'
    linux = client.get('/v1/app/desktop/linux-x86_64/release', headers=headers)
    assert json.loads(linux.content)['sha256'] == hashlib.sha256(LINUX).hexdigest()


def test_ticket_downloads_only_the_described_installer_with_resume(service, feed):
    client, _ = feed
    headers = service['accounts'][0]['headers']
    for platform, body in (('windows-x86_64', WINDOWS), ('linux-x86_64', LINUX)):
        response = client.post(f'/v1/app/desktop/{platform}/download', headers=headers, content=b'{}')
        assert response.status_code == 200 and set(response.json()) == {'ticket'}
        ticket = response.json()['ticket']
        assert len(ticket) == 43
        # The ticket is the only credential: Authorization on the file request is refused.
        assert client.get('/v1/download/' + ticket, headers=headers).status_code == 404
        assert client.get('/v1/download/' + ticket).content == body
        assert client.get('/v1/download/' + ticket, headers={'Range': 'bytes=2-'}).content == body[2:]


def test_description_files_are_never_downloadable(service, feed):
    _, downloads = feed
    identity = {'issuer': service['auth'].issuer, 'subject': 'auth0|alice'}
    for artifact in ('windows_release', 'linux_release'):
        with pytest.raises(Exception) as refused:
            downloads.issue(identity, artifact)
        assert refused.value.status_code == 404


def test_website_tokens_signed_out_and_unknown_accounts_are_refused(service, feed):
    client, _ = feed
    path = '/v1/app/desktop/windows-x86_64/release'
    assert client.get(path).status_code == 401
    assert client.get(path, headers=service['token']('auth0|alice', azp='web')).status_code == 401
    assert client.get(path, headers=service['token']('auth0|unknown')).status_code == 403
    assert client.post('/v1/app/desktop/windows-x86_64/download', headers=service['token']('auth0|alice', azp='web'),
                       content=b'{}').status_code == 401


def test_revoked_or_expired_accounts_are_refused(service, feed):
    client, _ = feed
    alice, bob = service['accounts']
    service['registry'].set_active(alice['id'], False)
    assert client.get('/v1/app/desktop/windows-x86_64/release', headers=alice['headers']).status_code == 403
    assert client.post('/v1/app/desktop/windows-x86_64/download', headers=alice['headers'], content=b'{}').status_code == 403
    assert client.get('/v1/app/desktop/windows-x86_64/release', headers=bob['headers']).status_code == 200


@pytest.mark.parametrize('headers, suffix', [({'Origin': 'https://saiph.example.test'}, ''), ({'Cookie': 'session=1'}, ''),
                                             ({}, '?platform=linux-x86_64')])
def test_browser_style_requests_are_refused(service, feed, headers, suffix):
    client, _ = feed
    response = client.get('/v1/app/desktop/windows-x86_64/release' + suffix,
                          headers={**service['accounts'][0]['headers'], **headers})
    assert response.status_code == 403


def test_unknown_platforms_actions_methods_and_bodies(service, feed):
    client, _ = feed
    headers = service['accounts'][0]['headers']
    assert client.get('/v1/app/desktop/macos-arm64/release', headers=headers).status_code == 404
    assert client.get('/v1/app/desktop/windows-x86_64/notes', headers=headers).status_code == 404
    assert client.get('/v1/app/desktop/../download/x', headers=headers).status_code == 404
    assert client.post('/v1/app/desktop/macos-arm64/download', headers=headers, content=b'{}').status_code == 404
    assert client.post('/v1/app/desktop/windows-x86_64/release', headers=headers, content=b'{}').status_code == 405
    assert client.get('/v1/app/desktop/windows-x86_64/download', headers=headers).status_code == 405
    assert client.post('/v1/app/desktop/windows-x86_64/download', headers=headers,
                       content=json.dumps({'artifact': 'linux'})).status_code == 400


def test_no_description_answers_204_and_offers_no_ticket(service, tmp_path):
    directory = publish(tmp_path / 'website-only', {'windows': ('Saiph-Setup.exe', WINDOWS)})
    client = TestClient(SharedHosted(service['registry'], tokens=service['tokens'],
                                     downloads=Downloads(service['registry'], directory)))
    headers = service['accounts'][0]['headers']
    response = client.get('/v1/app/desktop/windows-x86_64/release', headers=headers)
    assert response.status_code == 204 and response.content == b''
    assert client.post('/v1/app/desktop/windows-x86_64/download', headers=headers, content=b'{}').status_code == 404


def test_service_without_downloads_has_no_feed(service):
    # The desktop explains a 404 as "your Saiph account doesn't offer desktop updates yet".
    headers = service['accounts'][0]['headers']
    assert service['client'].get('/v1/app/desktop/windows-x86_64/release', headers=headers).status_code == 404
    assert service['client'].post('/v1/app/desktop/windows-x86_64/download', headers=headers, content=b'{}').status_code == 404


@pytest.mark.parametrize('platform, body, changes', [
    ('windows-x86_64', WINDOWS, {'sha256': 'a' * 64}),
    ('windows-x86_64', WINDOWS, {'bytes': len(WINDOWS) + 1}),
    ('linux-x86_64', WINDOWS, {}),  # Another platform's description.
    ('windows-x86_64', WINDOWS, {'profile': 'enterprise'}),
    ('windows-x86_64', WINDOWS, {'schema': 2}),
    ('windows-x86_64', WINDOWS, {'build': 0}),
    ('windows-x86_64', WINDOWS, {'build': True}),
    ('windows-x86_64', WINDOWS, {'version': 'latest'}),
    ('windows-x86_64', WINDOWS, {'notes': 'x' * 4001}),
    ('windows-x86_64', WINDOWS, {'notes': 'Update ‮exe.txt'}),
    ('windows-x86_64', WINDOWS, {'notes': 'bell\u0007'}),
    ('windows-x86_64', WINDOWS, {'url': 'https://elsewhere.invalid/Saiph.exe'}),
])
def test_descriptions_that_disagree_with_their_installer_refuse_to_load(service, tmp_path, platform, body, changes):
    directory = publish(tmp_path / 'bad', {
        'windows': ('Saiph-Setup.exe', WINDOWS),
        'windows_release': ('windows-release.json', description(platform, body, **changes))})
    with pytest.raises(ValueError, match='does not match its installer'):
        Downloads(service['registry'], directory)


@pytest.mark.parametrize('raw', [b'{"schema":1,"schema":1}', b'{"bytes": NaN}', b'\xff\xfe', b'[]', b' ' * 16385])
def test_malformed_descriptions_refuse_to_load(service, tmp_path, raw):
    directory = publish(tmp_path / 'bad', {'windows': ('Saiph-Setup.exe', WINDOWS),
                                           'windows_release': ('windows-release.json', raw)})
    with pytest.raises(ValueError):
        Downloads(service['registry'], directory)


def test_a_description_needs_its_installer(service, tmp_path):
    directory = publish(tmp_path / 'bad', {'linux': ('Saiph-Setup.run', LINUX),
                                           'windows_release': ('windows-release.json', description('windows-x86_64', WINDOWS))})
    with pytest.raises(ValueError, match='has no installer'):
        Downloads(service['registry'], directory)


def test_a_changed_description_file_refuses_to_load(service, tmp_path):
    directory = complete(tmp_path / 'release')
    (directory / 'windows-release.json').write_bytes(description('windows-x86_64', WINDOWS, notes='Edited later.'))
    with pytest.raises(ValueError, match='checksum'):
        Downloads(service['registry'], directory)


def test_desktop_tickets_share_the_download_limits(service, feed):
    client, _ = feed
    headers = service['accounts'][0]['headers']
    for _ in range(30):
        assert client.post('/v1/app/desktop/windows-x86_64/download', headers=headers, content=b'{}').status_code == 200
    assert client.post('/v1/app/desktop/linux-x86_64/download', headers=headers, content=b'{}').status_code == 429


def test_usage_totals_use_fixed_route_names():
    assert classify('GET', '/v1/app/desktop/windows-x86_64/release') == 'desktop.release'
    assert classify('POST', '/v1/app/desktop/linux-x86_64/download') == 'desktop.download'
