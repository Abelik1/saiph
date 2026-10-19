# SPDX-License-Identifier: AGPL-3.0-or-later
"""The desktop's own Saiph account updater against the real Hosted service routes.

No network: the desktop CloudFeed talks to SharedHosted through an in-process test
client, with synthetic accounts, tokens and installers.
"""
import hashlib
import io
import json
from pathlib import Path
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from orion_hub.hosted_auth import AccessTokens, ServiceAuth0Config
from orion_hub.hosted_downloads import Downloads
from orion_hub.hosted_service import AccountRegistry, SharedHosted
from orion_mini import package_updates as updates
from orion_mini.storage import read_json
from orion_mini.update_schedule import DesktopUpdates
from test_package_updates import CONFIG, metadata, native, packaged  # noqa: F401  (fixture)
from test_package_updates_cloud import linux, linux_setup  # noqa: F401  (fixture)

ORIGIN = 'https://api.saiph.example.test'


class Wire:
    """requests.Session's surface, as CloudFeed uses it, over the in-process service."""

    class Response:
        def __init__(self, response):
            self.status_code, self.headers = response.status_code, response.headers
            self.raw = io.BytesIO(response.content)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_content(self, size):
            while chunk := self.raw.read(size):
                yield chunk

    def __init__(self, client):
        self.client, self.calls = client, []

    def _path(self, url, kwargs):
        assert url.startswith(ORIGIN + '/') and kwargs['allow_redirects'] is False
        self.calls.append(url[len(ORIGIN):])
        return url[len(ORIGIN):]

    def get(self, url, **kwargs):
        return self.Response(self.client.get(self._path(url, kwargs), headers=kwargs['headers']))

    def post(self, url, **kwargs):
        return self.Response(self.client.post(self._path(url, kwargs), headers=kwargs['headers'], content=kwargs['data']))


@pytest.fixture
def hosted(tmp_path):
    auth = ServiceAuth0Config('https://synthetic.eu.auth0.com/', 'https://saiph.example.test/api', ('desktop',))
    authority = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    registry = AccountRegistry(tmp_path / 'shared', auth)
    registry.admit('auth0|alice', expires_at=int(time.time()) + 3600)
    claims = dict(iss=auth.issuer, aud=auth.audience, azp='desktop', sub='auth0|alice',
                  iat=int(time.time()), exp=int(time.time()) + 300)
    token = jwt.encode(claims, authority, algorithm='RS256', headers={'kid': 'synthetic'})

    def serve(files):
        directory = tmp_path / 'release'
        directory.mkdir(exist_ok=True)
        catalog = {}
        for key, (name, body) in files.items():
            (directory / name).write_bytes(body)
            catalog[key] = {'file': name, 'sha256': hashlib.sha256(body).hexdigest()}
        (directory / 'catalog.json').write_text(json.dumps(catalog))
        app = SharedHosted(registry, tokens=AccessTokens(auth, key_resolver=lambda kid: authority.public_key()),
                           downloads=Downloads(registry, directory))
        wire = Wire(TestClient(app))
        return updates.CloudFeed(ORIGIN, token, http=wire), wire
    return serve


def described(release, notes='Faster photo sync.'):
    return json.dumps({**release, 'notes': notes}).encode()


def test_windows_check_and_stage_through_the_hosted_routes(packaged, hosted, monkeypatch):
    root, _ = packaged
    release = metadata(build=2); body = native(release)
    feed, wire = hosted({'windows': ('Saiph-Setup.exe', body), 'windows_release': ('windows-release.json', described(release))})
    result = updates.check(root, CONFIG, cloud=feed)
    assert result['available'] and result['release'] == release and result['notes'] == 'Faster photo sync.'
    monkeypatch.setattr(updates.subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('Stage launched code'))
    staged = updates.stage(root, CONFIG, release, cloud=feed)
    assert Path(staged['path']).read_bytes() == body
    assert read_json(Path(staged['path']).parent / 'staged.json') == release
    assert wire.calls[:4] == ['/v1/app/desktop/windows-x86_64/release'] * 2 + ['/v1/app/desktop/windows-x86_64/download',
                                                                                wire.calls[3]]
    assert wire.calls[3].startswith('/v1/download/')


def test_linux_run_check_and_stage_through_the_hosted_routes(linux, hosted, tmp_path, monkeypatch):
    body, offered, payload = linux_setup(tmp_path, monkeypatch, metadata(platform='linux-x86_64'))
    feed, _ = hosted({'linux': ('Saiph-Setup.run', body), 'linux_release': ('linux-release.json', described(offered, ''))})
    assert updates.check(linux, CONFIG, cloud=feed)['available']
    staged = updates.stage(linux, CONFIG, offered, cloud=feed)
    assert Path(staged['path']).name == payload['sha256'] + '.tar.gz'


def test_no_description_means_up_to_date(packaged, hosted):
    root, _ = packaged
    feed, _ = hosted({'windows': ('Saiph-Setup.exe', b'MZ website installer only')})
    result = updates.check(root, CONFIG, cloud=feed)
    assert result['supported'] and not result['available'] and result['release'] is None


def test_footer_state_follows_the_hosted_feed(packaged, hosted, monkeypatch):
    root, _ = packaged
    release = metadata(build=2); body = native(release)
    feed, _ = hosted({'windows': ('Saiph-Setup.exe', body), 'windows_release': ('windows-release.json', described(release))})
    monkeypatch.setattr(updates, 'source_for', lambda workspace: feed)
    installs = []
    monkeypatch.setattr(updates, 'install', lambda root, staged: installs.append(staged) or {'started': True})
    workspace = type('Workspace', (), {'root': root, 'settings': {'hub': dict(CONFIG)}})()
    restarted = []
    state = DesktopUpdates(workspace, restart=lambda: restarted.append(True))
    assert state.background_check() is True
    assert state.status()['state'] == 'available' and state.status()['version'] == release['version']
    assert state.update_now() == {'started': True, 'version': release['version']}
    assert installs[0]['release'] == release and Path(installs[0]['path']).read_bytes() == body
    assert restarted == [True]
