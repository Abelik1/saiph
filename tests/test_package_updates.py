# SPDX-License-Identifier: AGPL-3.0-or-later
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import threading
import time
from types import SimpleNamespace
import urllib.error
import zipfile

import pytest

from orion_mini import package_updates as updates
from orion_mini.storage import read_json, write_json


CONFIG = {'base_url': 'http://100.64.1.2:9876', 'paired': True, 'device_id': 'dev_' + 'a' * 32}


def metadata(build=2, profile='link', platform='windows-x86_64'):
    return dict(schema=1, build=build, profile=profile, platform=platform, version=f'0.1.0-preview.{build}', sha256='a' * 64, bytes=100)


def native(release):
    package = {'format': 'orion-desktop-package', 'schema': 1,
               **{key: release[key] for key in ('platform', 'profile', 'version')}}
    files = {'package-manifest.json': json.dumps(package).encode(),
             'app/_internal/distribution-profile.json': json.dumps({'schema': 1, 'profile': release['profile']}).encode(),
             'app/_internal/distribution-release.json': json.dumps({key: release[key] for key in ('schema', 'build', 'version', 'platform')}).encode()}
    payload = io.BytesIO()
    if release['platform'] == 'windows-x86_64':
        with zipfile.ZipFile(payload, 'w') as archive:
            for name, body in files.items():
                archive.writestr(name, body)
        zipped = payload.getvalue()
        pe = bytearray(512); pe[:2] = b'MZ'; struct.pack_into('<I', pe, 60, 128); pe[128:134] = b'PE\0\0\x64\x86'
        body = pe + zipped + struct.pack('<Q', len(zipped)) + b'ORIONZIP'
    else:
        elf = bytearray(64); elf[:6] = b'\x7fELF\x02\x01'; elf[18:20] = b'\x3e\0'
        files.update({'app/saiph': bytes(elf), 'app/OrionMini': bytes(elf), 'install.sh': b'#!/bin/sh\nexit 0\n', 'VERSION': release['version'].encode(), 'SHA256SUMS': b'',
                      'LINUX_COMPATIBILITY': b'linux-x86_64 glibc 2.35\n'})
        with tarfile.open(fileobj=payload, mode='w:gz') as archive:
            for name, body in files.items():
                info = tarfile.TarInfo('orion/' + name); info.size = len(body); info.mode = 0o700
                archive.addfile(info, io.BytesIO(body))
        body = payload.getvalue()
    release.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
    return bytes(body)


@pytest.fixture
def packaged(tmp_path, monkeypatch):
    bundle = tmp_path / 'bundle'; bundle.mkdir()
    write_json(bundle / 'distribution-profile.json', {'schema': 1, 'profile': 'link'})
    installed = {key: metadata(build=1)[key] for key in ('schema', 'build', 'version', 'platform')}
    write_json(bundle / 'distribution-release.json', installed)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(bundle), raising=False)
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(updates.platform, 'machine', lambda: 'AMD64')
    root = tmp_path / 'profile'; root.mkdir()
    (root / 'hub-device-key.pem').write_text('SYNTHETIC_KEY_NOT_LOADED')
    # Exercise package logic without modifying Windows ACLs or launching tools.
    def private(root):
        path = Path(root) / 'package-updates'; path.mkdir(exist_ok=True)
        return path
    monkeypatch.setattr(updates, '_private_directory', private)
    monkeypatch.setattr(updates.hub_client, 'signed_headers', lambda *args: {'X-Orion-Device-Id': CONFIG['device_id']})
    return root, bundle


class Reply(io.BytesIO):
    def __init__(self, body, release, **headers):
        super().__init__(body)
        self.status = 200
        self.headers = {'Content-Length': str(release['bytes']), 'X-Orion-SHA256': release['sha256'], **headers}


def download(monkeypatch, body, release, **headers):
    requests = []; handlers = []
    def build(*supplied):
        handlers.extend(supplied)
        def open(request, **kwargs):
            requests.append(request)
            return Reply(body, release, **headers)
        return SimpleNamespace(open=open)
    monkeypatch.setattr(updates.urllib.request, 'build_opener', build)
    return requests, handlers


def test_source_and_unversioned_bundles_do_not_use_git_or_network(tmp_path, monkeypatch):
    monkeypatch.delattr(sys, 'frozen', raising=False)
    monkeypatch.setattr(updates.hub_client, 'signed', lambda *args: pytest.fail('No packaged metadata means no network update'))
    assert updates.check(tmp_path, CONFIG) == {'supported': False, 'available': False, 'current': None, 'release': None}
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    assert not updates.check(tmp_path, CONFIG)['supported']


@pytest.mark.parametrize('change', [{'schema': True}, {'build': True}, {'build': -1}, {'platform': 'linux-x86_64'},
    {'platform': 'windows-arm64'}, {'version': '1.0.0\n'}, {'download_url': 'https://untrusted.invalid'}])
def test_immutable_current_metadata_is_strict(packaged, change):
    root, bundle = packaged
    release = read_json(bundle / 'distribution-release.json')
    write_json(bundle / 'distribution-release.json', {**release, **change})
    assert updates.current() is None


def test_check_uses_saved_mesh_pairing_and_rejects_replays_or_conflicts(packaged, monkeypatch):
    root, _ = packaged
    offered = metadata(); calls = []
    def signed(root, config, path):
        calls.append((config, path)); return {'release': offered}
    monkeypatch.setattr(updates.hub_client, 'signed', signed)
    assert updates.check(root, CONFIG)['available']
    assert calls[-1] == (CONFIG, '/v1/link/desktop/releases/windows-x86_64/link')
    for changed in (metadata(build=1), {**metadata(), 'sha256': 'b' * 64}, metadata(profile='workspace'), metadata(platform='linux-x86_64')):
        offered = changed
        with pytest.raises(ValueError):
            updates.check(root, CONFIG)
    assert (root / 'hub-device-key.pem').read_text() == 'SYNTHETIC_KEY_NOT_LOADED'


def test_cloud_preview_never_contacts_retained_hub_pairing(packaged, monkeypatch):
    root, _ = packaged
    monkeypatch.setattr(updates.hub_client, 'signed', lambda *args: pytest.fail('Inactive Hub was contacted'))
    result = updates.check(root, CONFIG, cloud=True)
    assert result['reason'] == 'cloud_manual'
    assert result['current'] and not result['supported'] and not result['available'] and result['release'] is None
    assert not (root / 'package-updates').exists()


def test_new_build_cannot_reuse_current_install_directory(packaged, monkeypatch):
    root, _ = packaged
    offered = {**metadata(), 'version': metadata(build=1)['version']}
    monkeypatch.setattr(updates.hub_client, 'signed', lambda *args: {'release': offered})
    with pytest.raises(ValueError, match='new version directory'):
        updates.check(root, CONFIG)


@pytest.mark.parametrize('config', [{**CONFIG, 'paired': False}, {**CONFIG, 'device_id': 'invalid'},
    {**CONFIG, 'base_url': 'https://example.com'}, {**CONFIG, 'base_url': 'http://127.0.0.1:8765'},
    {**CONFIG, 'base_url': 'http://100.64.0.1:9876?code=private'}])
def test_unpaired_public_or_supplied_credential_origin_is_never_contacted(packaged, monkeypatch, config):
    monkeypatch.setattr(updates.hub_client, 'signed', lambda *args: pytest.fail('Unsafe origin reached network'))
    with pytest.raises(ValueError):
        updates.check(packaged[0], config)


def test_verified_stage_is_separate_from_execution_and_uses_no_proxy_redirect(packaged, monkeypatch, caplog):
    root, _ = packaged
    release = metadata(); body = native(release)
    monkeypatch.setattr(updates.hub_client, 'signed', lambda *args: {'release': release})
    monkeypatch.setattr(updates.subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('Stage launched code'))
    requests, handlers = download(monkeypatch, body, release)
    result = updates.stage(root, CONFIG, release)
    assert result['staged'] and Path(result['path']).read_bytes() == body
    assert read_json(Path(result['path']).parent / 'staged.json') == release
    assert requests[0].full_url == CONFIG['base_url'] + '/v1/link/desktop/artifacts/windows-x86_64/link/' + release['sha256']
    assert any(isinstance(handler, updates.urllib.request.ProxyHandler) and handler.proxies == {} for handler in handlers)
    assert any(isinstance(handler, updates.hub_client._NoRedirect) for handler in handlers)
    assert CONFIG['device_id'] not in caplog.text


@pytest.mark.parametrize('failure', ['corrupt', 'truncated', 'too-long', 'wrong-size-header', 'wrong-digest-header', 'html-native', 'wrong-edition', 'wrong-build'])
def test_corrupt_and_mislabeled_downloads_cannot_stage_or_change_app_data(packaged, monkeypatch, failure):
    root, _ = packaged
    release = metadata(); body = native(release)
    headers = {}
    if failure == 'corrupt': body = body[:-1] + b'X'
    if failure == 'truncated': body = body[:-1]
    if failure == 'too-long': body += b'X'
    if failure == 'wrong-size-header': headers['Content-Length'] = '1'
    if failure == 'wrong-digest-header': headers['X-Orion-SHA256'] = 'b' * 64
    if failure == 'html-native':
        body = b'<html>private error body</html>'
        release.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
    if failure in {'wrong-edition', 'wrong-build'}:
        other = metadata(profile='workspace') if failure == 'wrong-edition' else metadata(build=99)
        body = native(other)
        release.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
    monkeypatch.setattr(updates.hub_client, 'signed', lambda *args: {'release': release})
    download(monkeypatch, body, release, **headers)
    with pytest.raises(ValueError) as error:
        updates.stage(root, CONFIG, release)
    assert 'private error body' not in str(error.value)
    assert not list((root / 'package-updates').glob('staged-*'))
    assert (root / 'hub-device-key.pem').read_text() == 'SYNTHETIC_KEY_NOT_LOADED'


def test_publication_change_requires_new_explicit_download_action(packaged, monkeypatch):
    root, _ = packaged
    first = metadata(); native(first)
    second = metadata(build=3); native(second)
    monkeypatch.setattr(updates.hub_client, 'signed', lambda *args: {'release': second})
    monkeypatch.setattr(updates.urllib.request, 'build_opener', lambda *args: pytest.fail('Changed release downloaded'))
    with pytest.raises(ValueError, match='changed'):
        updates.stage(root, CONFIG, first)


def test_redirect_refusal_does_not_leak_server_error_body(packaged, monkeypatch):
    release = metadata(); native(release)
    monkeypatch.setattr(updates.hub_client, 'signed', lambda *args: {'release': release})
    def fail(*args, **kwargs):
        raise urllib.error.HTTPError('http://100.64.1.2:9876', 302, 'PRIVATE_REDIRECT_REASON', {}, None)
    monkeypatch.setattr(updates.urllib.request, 'build_opener', lambda *args: SimpleNamespace(open=fail))
    with pytest.raises(ValueError) as error:
        updates.stage(packaged[0], CONFIG, release)
    assert 'PRIVATE_REDIRECT_REASON' not in str(error.value)


@pytest.mark.parametrize('name,kind', [('orion/../escape', 'file'), ('/orion/escape', 'file'),
    ('orion/app/link', 'symlink'), ('orion/app/hard', 'hardlink'), ('orion/app/fifo', 'fifo'),
    ('orion/unexpected/file', 'file'), ('orion/app\\escape', 'file'), ('orion/LINUX_COMPATIBILITY/nested', 'file'),
    ('orion/VERSION', 'directory'), ('orion/LINUX_COMPATIBILITY.bak', 'file')])
def test_linux_extraction_refuses_paths_links_and_special_files(tmp_path, name, kind):
    path = tmp_path / 'bad.tar.gz'
    with tarfile.open(path, 'w:gz') as archive:
        info = tarfile.TarInfo(name)
        info.type = {'file': tarfile.REGTYPE, 'symlink': tarfile.SYMTYPE, 'hardlink': tarfile.LNKTYPE, 'fifo': tarfile.FIFOTYPE,
                     'directory': tarfile.DIRTYPE}[kind]
        info.linkname = '../escape'
        archive.addfile(info, io.BytesIO())
    with pytest.raises(ValueError):
        updates._extract_linux(path, tmp_path)
    assert not (tmp_path.parent / 'escape').exists()


def test_linux_archive_is_bounded_and_extracts_only_into_fresh_directory(tmp_path):
    release = metadata(platform='linux-x86_64'); body = native(release)
    path = tmp_path / 'safe.tar.gz'; path.write_bytes(body)
    updates._verify(path, release)
    installer = updates._extract_linux(path, tmp_path)
    assert installer == tmp_path / 'extracted/orion/install.sh'
    assert installer.read_bytes().startswith(b'#!/bin/sh')
    with pytest.raises(FileExistsError):
        updates._extract_linux(path, tmp_path)


def real_linux_package(tmp_path, monkeypatch, release):
    """Package a synthetic bundle with the actual Linux packaging wrapper."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('linux_update_packaging', Path(__file__).parents[1] / 'scripts/packaging/build-desktop-distribution.py')
    packaging = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packaging)
    staging = tmp_path / 'package'
    elf = bytearray(64); elf[:6] = b'\x7fELF\x02\x01'; elf[18:20] = b'\x3e\0'
    files = {'app/saiph': bytes(elf), 'app/OrionMini': bytes(elf),
             'app/_internal/distribution-profile.json': json.dumps({'schema': 1, 'profile': release['profile']}).encode(),
             'app/_internal/distribution-release.json': json.dumps({key: release[key] for key in ('schema', 'build', 'version', 'platform')}).encode(),
             'licenses/inventory.json': b'{}', 'components.json': b'{}',
             'package-manifest.json': json.dumps({'format': 'orion-desktop-package', 'schema': 1, 'files': [],
                                                  **{key: release[key] for key in ('platform', 'profile', 'version', 'build')}}).encode()}
    for name, body in files.items():
        (staging / name).parent.mkdir(parents=True, exist_ok=True); (staging / name).write_bytes(body)
    with monkeypatch.context() as patch:
        patch.setattr(packaging.shutil, 'which', lambda tool: 'synthetic-readelf')
        patch.setattr(packaging.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(stdout='Name: GLIBC_2.35'))
        path = tmp_path / ('Saiph-Link-' + release['version'] + '-linux-x86_64.tar.gz')
        packaging.build_linux(staging, path)
    body = path.read_bytes()
    release.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
    return path


def test_real_linux_package_layout_verifies_and_extracts_with_compatibility_receipt(tmp_path, monkeypatch):
    release = metadata(platform='linux-x86_64')
    path = real_linux_package(tmp_path, monkeypatch, release)
    with tarfile.open(path, 'r:gz') as archive:
        top = {name.split('/')[1] for name in archive.getnames() if name.count('/')}
    # The fixture must stay identical to what the packaging wrapper writes.
    assert top == updates.LINUX_DIRECTORIES | updates.LINUX_FILES
    updates._verify(path, release)
    installer = updates._extract_linux(path, tmp_path)
    assert (installer.parent / 'LINUX_COMPATIBILITY').read_text() == 'linux-x86_64 glibc 2.35\n'
    assert installer.read_bytes() == (Path(__file__).parents[1] / 'scripts/packaging/install-linux.sh').read_bytes()


def test_linux_package_without_compatibility_receipt_is_refused(tmp_path):
    release = metadata(platform='linux-x86_64')
    source = tmp_path / 'source.tar.gz'; source.write_bytes(native(release))
    path = tmp_path / 'missing.tar.gz'
    with tarfile.open(source, 'r:gz') as original, tarfile.open(path, 'w:gz') as archive:
        for item in original:
            if item.name != 'orion/LINUX_COMPATIBILITY':
                archive.addfile(item, original.extractfile(item))
    with pytest.raises(ValueError, match='missing its installer'):
        updates._extract_linux(path, tmp_path)


def legacy_updater():
    """The updater installed with 0.1.0-beta.4, which newer packages must still satisfy."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('orion_mini._legacy_package_updates_beta4',
                                                  Path(__file__).parent / 'fixtures/legacy_package_updates_beta4.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_renamed_linux_package_still_installs_through_the_beta4_updater(tmp_path, monkeypatch):
    release = metadata(platform='linux-x86_64')
    path = real_linux_package(tmp_path, monkeypatch, release)
    legacy = legacy_updater()
    legacy._verify(path, release)
    installer = legacy._extract_linux(path, tmp_path)
    # beta.4 relaunches app/OrionMini after installing; it is the same program as app/saiph.
    app = installer.parent / 'app'
    assert (app / 'OrionMini').read_bytes() == (app / 'saiph').read_bytes()
    current = tmp_path / 'current'; current.mkdir()
    updates._verify(path, release)
    assert (updates._extract_linux(path, current).parent / 'app/saiph').is_file()


def test_linux_package_without_the_renamed_executable_is_refused(tmp_path):
    release = metadata(platform='linux-x86_64')
    source = tmp_path / 'source.tar.gz'; source.write_bytes(native(release))
    path = tmp_path / 'legacy-only.tar.gz'
    with tarfile.open(source, 'r:gz') as original, tarfile.open(path, 'w:gz') as archive:
        for item in original:
            if item.name != 'orion/app/saiph':
                archive.addfile(item, original.extractfile(item))
    with pytest.raises(ValueError, match='Incomplete Linux native package'):
        updates._package_metadata(path, release)


@pytest.mark.parametrize('target', ['windows-x86_64', 'linux-x86_64'])
def test_only_the_installed_executable_names_may_start_an_install(packaged, monkeypatch, tmp_path, target):
    root, _ = packaged
    release = metadata(platform=target); body = native(release)
    monkeypatch.setattr(updates, 'current', lambda: {key: metadata(build=1, platform=target)[key]
                                                  for key in ('schema', 'build', 'version', 'platform', 'profile')})
    monkeypatch.setattr(updates.hub_client, 'signed', lambda *args: {'release': release})
    download(monkeypatch, body, release)
    staged = updates.stage(root, CONFIG, release)
    local = tmp_path / 'Local'; monkeypatch.setenv('LOCALAPPDATA', str(local)); monkeypatch.setattr(Path, 'home', lambda: local)
    app = (local / 'Programs/OrionMini/releases/0.1.0-preview.1/app' if target == 'windows-x86_64'
           else local / '.local/lib/orion/releases/0.1.0-preview.1/app')
    calls = []
    monkeypatch.setattr(updates.subprocess, 'Popen', lambda *args, **kwargs: calls.append(args))
    for name in ('python.exe', 'Saiph-portable.exe', 'saiph-copy'):
        monkeypatch.setattr(sys, 'executable', str(app / name))
        with pytest.raises(ValueError, match='native package'):
            updates.install(root, staged)
    assert calls == []


@pytest.mark.parametrize('running', ['renamed', 'compatibility'])
@pytest.mark.parametrize('target', ['windows-x86_64', 'linux-x86_64'])
def test_explicit_install_revalidates_and_waits_only_owned_app_pid(packaged, monkeypatch, tmp_path, target, running):
    root, _ = packaged
    release = metadata(platform=target); body = native(release)
    monkeypatch.setattr(updates, 'current', lambda: {key: metadata(build=1, platform=target)[key]
                                                  for key in ('schema', 'build', 'version', 'platform', 'profile')})
    monkeypatch.setattr(updates.hub_client, 'signed', lambda *args: {'release': release})
    download(monkeypatch, body, release)
    staged = updates.stage(root, CONFIG, release)
    local = tmp_path / 'Local'; monkeypatch.setenv('LOCALAPPDATA', str(local))
    if target == 'windows-x86_64':
        current_exe = local / 'Programs/OrionMini/releases/0.1.0-preview.1/app' / ('Saiph.exe' if running == 'renamed' else 'OrionMini.exe')
        # This fixture validates command construction on either build host.
        monkeypatch.setattr(updates.subprocess, 'CREATE_NO_WINDOW', 0, raising=False)
        monkeypatch.setattr(updates.subprocess, 'CREATE_NEW_PROCESS_GROUP', 0, raising=False)
    else:
        monkeypatch.setattr(Path, 'home', lambda: local)
        current_exe = local / '.local/lib/orion/releases/0.1.0-preview.1/app' / ('saiph' if running == 'renamed' else 'OrionMini')
    monkeypatch.setattr(sys, 'executable', str(current_exe))
    calls = []
    monkeypatch.setattr(updates.subprocess, 'Popen', lambda *args, **kwargs: calls.append((args, kwargs)))
    assert updates.install(root, staged) == {'started': True}
    command = calls[0][0][0]
    if target == 'windows-x86_64':
        assert command[command.index('-AppPid') + 1] == str(os.getpid())
        assert command[command.index('-Package') + 1] == staged['path']
        # A beta.4 updater relaunches the compatibility copy once; later updates open Saiph.exe.
        assert command[command.index('-NextExe') + 1] == str(local / 'Programs/OrionMini/releases' / release['version'] / 'app/Saiph.exe')
        assert command[command.index('-OldExe') + 1] == str(current_exe)
        helper = Path(staged['path']).parent / 'install.ps1'
        assert 'Wait-Process' in helper.read_text(encoding='utf-8-sig')
        assert '--no-launch' in helper.read_text(encoding='utf-8-sig')
        assert 'Stop-Process' not in helper.read_text(encoding='utf-8-sig')
    else:
        assert command[:3] == ['/bin/sh', str(Path(staged['path']).parent / 'install.sh'), str(os.getpid())]
        assert command[3] == staged['path'] and command[7] == str(current_exe)
        assert command[6] == str(local / '.local/lib/orion/releases' / release['version'] / 'app/saiph')
        assert calls[0][1]['start_new_session'] is True
        assert Path(command[5]).is_file()
    assert calls[0][1]['stdout'] == updates.subprocess.DEVNULL
    Path(staged['path']).write_bytes(body[:-1] + b'X')
    with pytest.raises(ValueError):
        updates.install(root, staged)
    assert len(calls) == 1


@pytest.mark.skipif(sys.platform != 'win32', reason='Actual Windows PowerShell/native fixture')
@pytest.mark.parametrize('failure', ['installer', 'hash', 'missing-release'])
def test_windows_handoff_reopens_previous_build_after_failure(tmp_path, failure):
    compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.is_file():
        pytest.skip('Native fixture compiler unavailable')
    old_source = tmp_path / 'old.cs'
    old_source.write_text('''using System; using System.IO;
class Old { static void Main() { File.WriteAllText(Environment.GetEnvironmentVariable("ORION_UPDATE_TEST_MARKER"),"old-reopened"); } }''')
    failing_source = tmp_path / 'failing.cs'
    failing_source.write_text('class Failing { static int Main() { return ' + ('0' if failure == 'missing-release' else '7') + '; } }')
    old = tmp_path / 'old.exe'; failing = tmp_path / 'failing.exe'
    for source, target in ((old_source, old), (failing_source, failing)):
        subprocess.run([str(compiler), '/nologo', '/target:exe', '/out:' + str(target), str(source)],
                       check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    helper = tmp_path / 'handoff.ps1'; helper.write_text(updates.WINDOWS_HANDOFF, encoding='utf-8-sig')
    marker = tmp_path / 'reopened'; status = tmp_path / 'status.json'
    environment = {**os.environ, 'ORION_UPDATE_TEST_MARKER': str(marker)}
    digest = hashlib.sha256(failing.read_bytes()).hexdigest() if failure != 'hash' else '0' * 64
    # Wait for this owned fixture process, never the actual desktop application.
    previous = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(1)'],
                                creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(helper),
            '-AppPid', str(previous.pid), '-Package', str(failing), '-Digest', digest,
            '-NextExe', str(tmp_path / 'never-start.exe'), '-OldExe', str(old), '-StatusFile', str(status)],
            env=environment, capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode != 0
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert marker.read_text() == 'old-reopened'
        assert read_json(status) == {'state': 'failed', 'code': {'installer': 'installer_failed', 'hash': 'damaged_package', 'missing-release': 'missing_release'}[failure]}, (result.stdout, result.stderr)
        assert previous.wait(timeout=5) == 0
    finally:
        if previous.poll() is None:
            previous.terminate(); previous.wait(timeout=5)


@pytest.mark.skipif(sys.platform != 'win32', reason='Actual Windows PowerShell process waiting')
def test_windows_handoff_close_timeout_does_not_install_or_reopen(tmp_path):
    helper = tmp_path / 'handoff.ps1'; helper.write_text(updates.WINDOWS_HANDOFF, encoding='utf-8-sig')
    status = tmp_path / 'status.json'
    # Neither path is executable. Reaching either proves an incorrect handoff.
    forbidden = tmp_path / 'never-execute.exe'; forbidden.write_text('not executable')
    previous = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(helper),
            '-AppPid', str(previous.pid), '-Package', str(forbidden), '-Digest', '0' * 64,
            '-NextExe', str(forbidden), '-OldExe', str(forbidden), '-StatusFile', str(status), '-WaitSeconds', '1'],
            capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 2
        assert read_json(status) == {'state': 'failed', 'code': 'close_timeout'}
        assert previous.poll() is None
    finally:
        if previous.poll() is None:
            previous.terminate(); previous.wait(timeout=5)


@pytest.mark.skipif(sys.platform != 'linux', reason='Actual Linux shell/process lifecycle')
@pytest.mark.parametrize('outcome', ['success', 'installer', 'hash', 'missing-release', 'exec'])
def test_linux_handoff_waits_and_reopens_exact_release(tmp_path, outcome):
    # Real shell children and actual EXIT recovery, with no owner profile or GUI.
    # Paths contain spaces to exercise the helper's argument quoting.
    folder = tmp_path / 'native update'; folder.mkdir()
    marker = folder / 'launched'; installed = folder / 'installed'
    old = folder / 'previous app'; next_exe = folder / 'next app'
    for path, label in ((old, 'old'), (next_exe, 'next')):
        path.write_text('#!/bin/sh\nprintf "%s" ' + label + ' > "$ORION_UPDATE_TEST_MARKER"\n')
        path.chmod(0o700)
    if outcome == 'missing-release':
        next_exe.unlink()
    elif outcome == 'exec':
        next_exe.chmod(0o600)
    installer = folder / 'installer'; installer.write_text(
        '#!/bin/sh\nprintf installed > "$ORION_UPDATE_TEST_INSTALLED"\nexit ' +
        ('7' if outcome == 'installer' else '0') + '\n')
    package = folder / 'download'; package.write_bytes(b'bounded synthetic native package')
    digest = '0' * 64 if outcome == 'hash' else hashlib.sha256(package.read_bytes()).hexdigest()
    helper = folder / 'handoff.sh'; helper.write_text(updates.LINUX_HANDOFF)
    status = folder / 'status.json'
    environment = {**os.environ, 'ORION_UPDATE_TEST_MARKER': str(marker),
                   'ORION_UPDATE_TEST_INSTALLED': str(installed)}
    # Reap this owned process in its parent so the shell does not wait on a zombie.
    previous = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(.4)'])
    reaper = threading.Thread(target=previous.wait); reaper.start()
    try:
        child = subprocess.Popen(['/bin/sh', str(helper), str(previous.pid), str(package), digest,
                                 str(installer), str(next_exe), str(old), str(status)],
                                env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(.1)
        assert child.poll() is None and not marker.exists() and not installed.exists()
        stdout, stderr = child.communicate(timeout=10)
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert marker.read_text() == ('next' if outcome == 'success' else 'old'), (stdout, stderr)
        assert installed.exists() == (outcome != 'hash')
        expected = {'success': {'state': 'completed', 'code': ''},
                    'installer': {'state': 'failed', 'code': 'installer_failed'},
                    'hash': {'state': 'failed', 'code': 'damaged_package'},
                    'missing-release': {'state': 'failed', 'code': 'missing_release'},
                    'exec': {'state': 'failed', 'code': 'install_failed'}}[outcome]
        assert read_json(status) == expected
        assert (child.returncode == 0) == (outcome == 'success')
    finally:
        if previous.poll() is None:
            previous.terminate()
        reaper.join(timeout=5)
        if 'child' in locals() and child.poll() is None:
            child.terminate(); child.wait(timeout=5)


@pytest.mark.skipif(sys.platform != 'linux', reason='Actual Linux shell/process timeout')
def test_linux_handoff_close_timeout_never_installs_or_reopens(tmp_path):
    helper = tmp_path / 'handoff.sh'; helper.write_text(updates.LINUX_HANDOFF)
    status = tmp_path / 'status.json'; marker = tmp_path / 'forbidden-execution'
    forbidden = tmp_path / 'never-execute'
    forbidden.write_text('#!/bin/sh\nprintf forbidden > "$ORION_UPDATE_TEST_MARKER"\n')
    forbidden.chmod(0o700)
    # Speed up only the delay command. The production 120-attempt bound and real
    # kill -0 probe still run; the owned application remains alive throughout.
    commands = tmp_path / 'commands'; commands.mkdir()
    sleep = commands / 'sleep'; sleep.write_text('#!/bin/sh\nexit 0\n'); sleep.chmod(0o700)
    environment = {**os.environ, 'PATH': str(commands) + os.pathsep + os.environ['PATH'],
                   'ORION_UPDATE_TEST_MARKER': str(marker)}
    previous = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        result = subprocess.run(['/bin/sh', str(helper), str(previous.pid), str(forbidden), '0' * 64,
                                 str(forbidden), str(forbidden), str(forbidden), str(status)],
                                env=environment, capture_output=True, timeout=10)
        assert result.returncode == 2
        assert read_json(status) == {'state': 'failed', 'code': 'close_timeout'}
        assert not marker.exists() and previous.poll() is None
    finally:
        if previous.poll() is None:
            previous.terminate(); previous.wait(timeout=5)


@pytest.mark.parametrize('stored', [{'state': 'failed', 'code': 'PRIVATE_SERVER_ERROR'},
    {'state': [], 'code': ''}, {'state': 'completed', 'code': '', 'path': 'PRIVATE_PATH'}])
def test_update_status_only_returns_fixed_safe_codes(tmp_path, stored):
    write_json(tmp_path / 'package-updates/update-status.json', stored)
    assert updates.status(tmp_path) == {'state': 'failed', 'code': 'install_failed'}
