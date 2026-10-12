# SPDX-License-Identifier: AGPL-3.0-or-later
import hashlib
import io
import json
import struct
from concurrent.futures import ThreadPoolExecutor
import zipfile

import pytest
from fastapi.testclient import TestClient

from orion_hub import desktop_releases as releases
from test_acceptance import headers, pair
from test_link import client, hub


def installer(tmp_path, build=1, profile='link', version=None):
    version = version or f'0.1.0-preview.{build}'
    path = tmp_path / f'installer-{build}-{profile}.exe'
    pe = bytearray(512); pe[:2] = b'MZ'; struct.pack_into('<I', pe, 60, 128); pe[128:134] = b'PE\0\0\x64\x86'
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as archive:
        archive.writestr('package-manifest.json', json.dumps({'format': 'orion-desktop-package', 'schema': 1,
            'platform': 'windows-x86_64', 'profile': profile, 'version': version}))
        archive.writestr('app/_internal/distribution-profile.json', json.dumps({'schema': 1, 'profile': profile}))
        archive.writestr('app/_internal/distribution-release.json', json.dumps({'schema': 1, 'platform': 'windows-x86_64', 'build': build, 'version': version}))
    zipped = payload.getvalue()
    path.write_bytes(pe + zipped + struct.pack('<Q', len(zipped)) + b'ORIONZIP')
    return path


def publish(data, path, build=1, profile='link', version=None):
    version = version or f'0.1.0-preview.{build}'
    return releases.publish(data, path, 'windows-x86_64', profile, build, version)


def test_publish_is_pinned_immutable_and_monotonic(tmp_path):
    data = tmp_path / 'data'
    first = publish(data, installer(tmp_path))
    original, length = releases.open_artifact(data, first['platform'], first['profile'], first['sha256'])
    second = publish(data, installer(tmp_path, build=2), build=2)
    assert releases.latest(data, 'windows-x86_64', 'link') == second
    with original:
        assert hashlib.sha256(original.read()).hexdigest() == first['sha256']
        assert length == first['bytes']
    for build in (1, 2):
        with pytest.raises(ValueError, match='not newer'):
            publish(data, installer(tmp_path, build=build), build=build)
    assert releases.latest(data, 'windows-x86_64', 'link') == second


def test_wrong_label_or_native_format_cannot_replace_pointer(tmp_path):
    data = tmp_path / 'data'
    first = publish(data, installer(tmp_path))
    for profile, build, version in [('workspace', 2, '0.1.0-preview.1'), ('link', 3, '0.1.0-preview.1'), ('link', 2, '9.0.0')]:
        with pytest.raises(ValueError):
            publish(data, installer(tmp_path, build=2), profile=profile, build=build, version=version)
    bad = tmp_path / 'html.exe'; bad.write_bytes(b'<html>not a package</html>')
    with pytest.raises(ValueError):
        publish(data, bad, build=3)
    assert releases.latest(data, 'windows-x86_64', 'link') == first


def test_interrupted_pointer_activation_can_retry_same_immutable_artifact(tmp_path, monkeypatch):
    data = tmp_path / 'data'; path = installer(tmp_path)
    replace = releases.os.replace
    monkeypatch.setattr(releases.os, 'replace', lambda *args: (_ for _ in ()).throw(OSError('synthetic interruption')))
    with pytest.raises(OSError):
        publish(data, path)
    assert releases.latest(data, 'windows-x86_64', 'link') is None
    monkeypatch.setattr(releases.os, 'replace', replace)
    result = publish(data, path)
    assert releases.latest(data, 'windows-x86_64', 'link') == result


def test_newer_build_cannot_reuse_current_or_historical_install_directory(tmp_path):
    data = tmp_path / 'data'
    publish(data, installer(tmp_path))
    current = publish(data, installer(tmp_path, build=2), build=2)
    for version in ('0.1.0-preview.1', '0.1.0-preview.2'):
        with pytest.raises(ValueError, match='already been published'):
            publish(data, installer(tmp_path, build=3, version=version), build=3, version=version)
        assert releases.latest(data, 'windows-x86_64', 'link') == current


def test_concurrent_publishers_cannot_roll_back_a_newer_pointer(tmp_path):
    data = tmp_path / 'data'; paths = [(installer(tmp_path, build=n), n) for n in range(1, 6)]
    def send(item):
        try:
            publish(data, item[0], build=item[1])
        except ValueError:
            pass  # A larger build won the race.
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(send, reversed(paths)))
    assert releases.latest(data, 'windows-x86_64', 'link')['build'] == 5


@pytest.mark.parametrize('changes', [{'build': True}, {'build': 0}, {'build': 1.0}, {'bytes': True},
    {'bytes': releases.MAX_BYTES + 1}, {'sha256': '../private'}, {'platform': 'linux-arm64'},
    {'profile': 'personal'}, {'schema': True}, {'version': '1.2.3\n'}, {'download_url': 'https://untrusted.invalid'}])
def test_release_metadata_is_finite(changes):
    value = dict(schema=1, platform='windows-x86_64', profile='link', build=1,
                 version='0.1.0', sha256='a' * 64, bytes=100)
    with pytest.raises(ValueError):
        releases.validate({**value, **changes})


def test_routes_require_mesh_signature_and_live_pairing(hub, tmp_path):
    c = client(hub); key, device = pair(hub, c)
    published = publish(hub.DATA, installer(tmp_path))
    metadata = '/v1/link/desktop/releases/windows-x86_64/link'
    artifact = '/v1/link/desktop/artifacts/windows-x86_64/link/' + published['sha256']
    for path in (metadata, artifact):
        assert c.get(path).status_code == 401
        assert c.get(path, headers={'Authorization': 'Bearer synthetic-delegate'}).status_code == 401
        auth = headers(key, device, 'GET', path)
        assert c.get(path, headers={**auth, 'Origin': 'https://untrusted.invalid'}).status_code == 403
        c.cookies.set('orion_session', 'synthetic-browser')
        assert c.get(path, headers=headers(key, device, 'GET', path)).status_code == 403
        c.cookies.clear()
        public = TestClient(hub.app, base_url='http://127.0.0.1:8765', client=('100.64.0.2', 9))
        assert public.get(path, headers=headers(key, device, 'GET', path)).status_code == 403
    assert c.get(metadata, headers=headers(key, device, 'GET', metadata)).json() == {'release': published}
    auth = headers(key, device, 'GET', artifact)
    response = c.get(artifact, headers=auth)
    assert response.status_code == 200 and hashlib.sha256(response.content).hexdigest() == published['sha256']
    assert response.headers['x-orion-sha256'] == published['sha256']
    assert c.get(artifact, headers=auth).status_code == 409
    hub.DB.execute('DELETE FROM devices WHERE id=?', (device,))
    for path in (metadata, artifact):
        assert c.get(path, headers=headers(key, device, 'GET', path)).status_code == 401


def test_old_digest_url_stays_bound_after_publish_and_unknown_is_not_a_path(hub, tmp_path):
    c = client(hub); key, device = pair(hub, c)
    first = publish(hub.DATA, installer(tmp_path))
    publish(hub.DATA, installer(tmp_path, build=2), build=2)
    path = '/v1/link/desktop/artifacts/windows-x86_64/link/' + first['sha256']
    response = c.get(path, headers=headers(key, device, 'GET', path))
    assert response.status_code == 200 and hashlib.sha256(response.content).hexdigest() == first['sha256']
    for digest in ('not-a-hash', 'a' * 64):
        path = '/v1/link/desktop/artifacts/windows-x86_64/link/' + digest
        assert c.get(path, headers=headers(key, device, 'GET', path)).status_code == 404
