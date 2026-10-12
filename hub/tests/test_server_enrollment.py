# SPDX-License-Identifier: AGPL-3.0-or-later
import importlib.util
import json
import tarfile
import os
import sys
import stat
from types import SimpleNamespace
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from orion_hub import enrollment, server, server_install
from orion_hub.db import Database
from orion_hub.security import consume_pairing_code
from test_link import hub, client
from test_acceptance import pair, headers


def test_stopped_existing_mesh_is_not_retargeted_to_new_controller(monkeypatch):
    monkeypatch.setattr(server_install.shutil, 'which', lambda _: 'synthetic-tailscale')
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if command[1:] == ['status', '--json']:
            return json.dumps({'BackendState': 'Stopped'})
        if command[1:] == ['debug', 'prefs']:
            return json.dumps({'ControlURL': 'https://existing.example.test', 'Persist': {'PrivateNodeKey': 'synthetic'}})
        return ''
    monkeypatch.setattr(server_install, 'run', run)
    with pytest.raises(server_install.SetupError, match='another controller'):
        server_install.ensure_mesh('ubuntu', 'noble', 'https://new.example.test')
    assert not any('up' in command for command in calls)


def test_stopped_existing_custom_mesh_is_resumed_without_choosing_owner_defaults(monkeypatch):
    monkeypatch.setattr(server_install.shutil, 'which', lambda _: 'synthetic-tailscale')
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if command[1:] == ['status', '--json']:
            return json.dumps({'BackendState': 'Stopped'})
        if command[1:] == ['debug', 'prefs']:
            return json.dumps({'ControlURL': 'https://existing.example.test', 'Persist': {'PrivateNodeKey': 'synthetic'}})
        if command[1:] == ['ip', '-4']:
            return '100.64.1.2'
        return ''
    monkeypatch.setattr(server_install, 'run', run)
    assert server_install.ensure_mesh('ubuntu', 'noble', None) == ('100.64.1.2', 'https://existing.example.test')
    assert ['tailscale', 'up'] in calls
    assert not any('--login-server=' in part or '--auth-key=' in part for call in calls for part in call)


def test_install_lock_rejects_contender_and_closes_descriptors_without_unlinking(monkeypatch, tmp_path):
    held = [False]
    descriptors = []
    closed = []
    def acquire(fd, flags):
        if held[0]: raise BlockingIOError()
        held[0] = True
    def close(fd):
        closed.append(fd)
        if fd == 11: held[0] = False
    monkeypatch.setitem(sys.modules, 'fcntl', SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=acquire))
    def open_lock(*args):
        descriptors.append(args)
        return 10 + len(descriptors)
    monkeypatch.setattr(server_install.os, 'open', open_lock)
    monkeypatch.setattr(server_install.os, 'close', close)
    monkeypatch.setattr(server_install.os, 'fstat', lambda fd: SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=42))
    monkeypatch.setattr(server_install.os, 'geteuid', lambda: 42, raising=False)
    monkeypatch.setattr(server_install.os, 'O_NOFOLLOW', 0x20000, raising=False)
    monkeypatch.setattr(server_install.os, 'O_CLOEXEC', 0x80000, raising=False)
    lock = tmp_path / 'lock'
    with server_install.installation_lock(lock):
        with pytest.raises(ValueError, match='Another Saiph server installation'):
            with server_install.installation_lock(lock): pytest.fail('Concurrent activation entered')
    assert closed == [12,11]
    assert all(args[1] & server_install.os.O_NOFOLLOW for args in descriptors)
    assert all(args[2] == 0o600 for args in descriptors)


@pytest.mark.skipif(sys.platform == 'win32', reason='Actual Unix flock and permissions')
def test_actual_install_lock_contends_releases_and_refuses_symlink(tmp_path):
    lock = tmp_path / 'install.lock'
    with server_install.installation_lock(lock):
        with pytest.raises(ValueError, match='Another Saiph server installation'):
            with server_install.installation_lock(lock): pytest.fail('Concurrent activation entered')
    with server_install.installation_lock(lock): pass
    inode = lock.stat().st_ino
    with server_install.installation_lock(lock): pass
    assert lock.stat().st_ino == inode
    link = tmp_path / 'link'; link.symlink_to(lock)
    with pytest.raises(OSError):
        with server_install.installation_lock(link): pytest.fail('Symlink accepted')


def builder():
    path = Path(__file__).resolve().parents[2] / 'scripts/build-orion-server.py'
    spec = importlib.util.spec_from_file_location('orion_server_package_builder', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_private_invitation_is_independent_one_use_and_android_compatible(tmp_path, monkeypatch, capsys):
    db = Database(tmp_path / 'hub.sqlite3')
    monkeypatch.setenv('ORION_HUB_MESH_IP', '100.64.1.2')
    monkeypatch.setenv('ORION_HUB_PORT', '9876')
    captured = []
    original = enrollment.qrcode.make
    def make(uri, **kwargs):
        captured.append(uri); return original(uri, **kwargs)
    monkeypatch.setattr(enrollment.qrcode, 'make', make)
    target = tmp_path / 'phone.orion-enrollment'
    enrollment.write_enrollment(db, target, login_server='https://mesh.example.test')
    item = json.loads(target.read_text())
    assert item['hub'] == 'http://100.64.1.2:9876'
    assert item['expires_at'].endswith('Z') and item['mesh_login_server'] == 'https://mesh.example.test'
    assert parse_qs(urlsplit(captured[0]).query)['code'] == [item['code']]
    assert item['code'] not in capsys.readouterr().out
    assert consume_pairing_code(db, item['code']) and not consume_pairing_code(db, item['code'])
    with pytest.raises(FileExistsError):
        enrollment.write_enrollment(db, target)
    assert json.loads(target.read_text()) == item


def test_failed_qr_reservation_retains_existing_files_and_creates_no_code(tmp_path):
    db = Database(tmp_path / 'hub.sqlite3')
    target = tmp_path / 'phone.orion-enrollment'
    target.with_suffix('.svg').write_text('existing')
    with pytest.raises(FileExistsError):
        enrollment.write_enrollment(db, target, origin='http://100.64.1.2:8765')
    assert not target.exists() and not db.rows('SELECT * FROM pairing_codes')
    assert target.with_suffix('.svg').read_text() == 'existing'


@pytest.mark.parametrize('value', ['80', '65536', '-1', '1.5', 'bad'])
def test_server_custom_port_refuses_privileged_or_invalid_values(monkeypatch, value):
    monkeypatch.setenv('ORION_HUB_PORT', value)
    with pytest.raises(ValueError):
        server.listener_port()


def test_server_custom_port_and_ipv6_enrollment(monkeypatch):
    monkeypatch.setenv('ORION_HUB_PORT', '9876')
    monkeypatch.setenv('ORION_HUB_MESH_IP', 'fd7a:115c:a1e0::14')
    assert server.listener_port() == 9876
    assert enrollment.configured_origin() == 'http://[fd7a:115c:a1e0::14]:9876'


def test_packaged_server_has_finite_source_only_contents_and_detects_tampering(tmp_path):
    root = Path(__file__).resolve().parents[2]
    output = tmp_path / 'server.tar.gz'
    digest = builder().build(root, output, '0.1.0-unified.1')
    assert len(digest) == 64
    with tarfile.open(output) as archive:
        assert all(not member.issym() and '..' not in Path(member.name).parts for member in archive.getmembers())
        archive.extractall(tmp_path / 'extracted')
    folder = tmp_path / 'extracted/orion-server'
    manifest = server_install.verify_package(folder)
    assert 'install.py' in manifest['files'] and 'hub/orion_hub/security.py' in manifest['files']
    assert not any('google-services' in path or '.sqlite' in path or '.pem' in path for path in manifest['files'])
    (folder / 'hub/requirements.txt').write_text('tampered')
    with pytest.raises(ValueError):
        server_install.verify_package(folder)


def test_server_install_rejects_unknown_distribution_and_contains_no_owner_edge(tmp_path):
    with pytest.raises(ValueError):
        server_install.supported_system({'ID':'unknown','VERSION_ID':'1'}, 'x86_64')
    assert server_install.supported_system({'ID':'ubuntu','VERSION_ID':'24.04'}, 'x86_64') == ('ubuntu','noble')
    config = server_install.config_text('100.64.1.2', 9876, None)
    assert '100.64.0.1' not in config and '.ts.net' not in config and 'FIREBASE' not in config
    assert 'ORION_HUB_PORT=9876' in config and 'ORION_MESH_LOGIN_SERVER' not in config
    assert 'ProtectSystem=strict' in server_install.unit_text()


def test_paired_device_can_invite_without_supplied_address_or_browser_access(hub):
    with client(hub) as http:
        key, device = pair(hub, http)
        path = '/v1/link/enrollment'
        raw = b'{}'
        response = http.post(path, content=raw, headers=headers(key, device, 'POST', path, raw))
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        artifact = response.json()
        assert artifact['hub'] == 'http://100.64.0.1:8765' and artifact['expires_at'].endswith('Z')
        assert consume_pairing_code(hub.DB, artifact['code'])
        hostile = b'{"hub":"http://127.0.0.1:8765"}'
        assert http.post(path, content=hostile, headers=headers(key, device, 'POST', path, hostile)).status_code == 400
        assert http.post(path, content=raw).status_code == 401
        browser = {**headers(key, device, 'POST', path, raw), 'Origin':'http://localhost'}
        assert http.post(path, content=raw, headers=browser).status_code == 403


def test_revoked_devices_cannot_create_new_enrollment(hub):
    with client(hub) as http:
        key, device = pair(hub, http)
        hub.DB.execute('DELETE FROM devices WHERE id=?', (device,))
        path = '/v1/link/enrollment'; raw = b'{}'
        assert http.post(path, content=raw, headers=headers(key, device, 'POST', path, raw)).status_code == 401


def test_upgrades_preserve_optional_private_configuration():
    old = 'ORION_HUB_PORT=8765\nORION_FIREBASE_PROJECT_ID=private-project\nORION_FIREBASE_CREDENTIALS=/private/firebase.json\n'
    merged = server_install.merged_config(old, '100.64.1.2', 9876, None)
    assert merged.count('ORION_HUB_PORT=') == 1 and 'ORION_HUB_PORT=9876' in merged
    assert 'ORION_FIREBASE_CREDENTIALS=/private/firebase.json' in merged
    assert 'ORION_FIREBASE_PROJECT_ID=private-project' in merged


def test_failed_upgrade_restores_previous_release_and_config_without_replacing_data(tmp_path, monkeypatch):
    install = tmp_path / 'install'; config = tmp_path / 'config'; data = tmp_path / 'private-data'
    old = install / 'releases/old'; new = install / 'releases/new'
    old.mkdir(parents=True); new.mkdir(); config.mkdir(); data.mkdir()
    current = install / 'current'
    unit = tmp_path / 'orion.service'; wrapper = tmp_path / 'orion-server'
    monkeypatch.setattr(server_install, 'INSTALL', install); monkeypatch.setattr(server_install, 'CONFIG', config)
    monkeypatch.setattr(server_install, 'DATA', data); monkeypatch.setattr(server_install, 'UNIT', unit)
    monkeypatch.setattr(server_install, 'WRAPPER', wrapper)
    original_is_symlink = Path.is_symlink; original_resolve = Path.resolve
    monkeypatch.setattr(Path, 'is_symlink', lambda path: True if path == current else original_is_symlink(path))
    monkeypatch.setattr(Path, 'resolve', lambda path, **kw: old if path == current else original_resolve(path, **kw))
    (config / 'server.env').write_text('ORION_HUB_PORT=9876\nORION_FIREBASE_PROJECT_ID=synthetic-private\n')
    (config / 'server.json').write_text('{"port":9876}')
    (install / 'managed.json').write_text('{"release":"old"}')
    unit.write_text('previous unit'); wrapper.write_text('previous wrapper')
    (data / 'state.bin').write_bytes(b'synthetic retained private state')
    retained = {path:path.read_bytes() for path in (config / 'server.env',config / 'server.json',install / 'managed.json',unit,wrapper)}
    commands = []; switches = []; health = []
    monkeypatch.setattr(server_install, 'run', lambda command, **kw: commands.append(command))
    monkeypatch.setattr(server_install, 'private_write', lambda path,value,**kw: path.write_text(value))
    # Files above simulate root-owned Unix paths on the Windows test host.
    monkeypatch.setattr(server_install, 'check_owned', lambda *args, **kwargs: None)
    monkeypatch.setattr(server_install, 'switch_release', lambda pointer, release: switches.append(release))
    def check(port):
        health.append(port)
        if port == 9877:
            raise server_install.SetupError('synthetic failure')
    monkeypatch.setattr(server_install, 'wait_health', check)
    with pytest.raises(ValueError, match='previous release and configuration were restored'):
        server_install.activate_release(new, '100.64.1.2', 9877, None, {'release':'old'}, False)
    assert switches == [new, old] and health == [9877,9876]
    assert all(path.read_bytes() == value for path,value in retained.items())
    assert (data / 'state.bin').read_bytes() == b'synthetic retained private state'
    assert ['systemctl','start','orion-server'] in commands
