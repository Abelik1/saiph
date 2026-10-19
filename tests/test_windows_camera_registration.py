# SPDX-License-Identifier: AGPL-3.0-or-later
"""The installer's Saiph Camera cleanup, run as a real process against a disposable registry.

`--isolated` with ORION_SETUP_CAMERA_TEST_ROOT redirects both camera registry views into
a newly created HKCU\\Software\\OrionMini\\SetupCameraTests subtree. Real camera
registrations are never read or changed, and nothing is installed outside the
temporary destination."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid
import zipfile

import pytest

if sys.platform != 'win32':
    pytest.skip('Windows native installer', allow_module_level=True)
import winreg

ROOT = Path(__file__).parents[1]
COMPILER = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
CLASSES = r'Software\Classes\CLSID' + '\\'
CATEGORY = CLASSES + r'{860BB310-5D01-11D0-BD3B-00A0C911CE86}\Instance' + '\\'
CAMERA = {'64': ('{D9B25791-5540-48BE-842C-C73BF8540340}', '{D9B25791-5540-48BE-842C-C73BF8540341}'),
          '32': ('{D9B25791-5540-48BE-842C-C73BF8540342}', '{D9B25791-5540-48BE-842C-C73BF8540343}')}


@pytest.fixture(scope='module')
def stub(tmp_path_factory):
    if not COMPILER.is_file(): pytest.skip('Windows Framework compiler absent')
    output = tmp_path_factory.mktemp('camera-setup') / 'setup-stub.exe'
    subprocess.run([str(COMPILER), '/nologo', '/target:winexe', '/platform:x64', '/out:' + str(output),
                    '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll', '/reference:System.IO.Compression.dll',
                    '/reference:System.IO.Compression.FileSystem.dll', '/reference:System.Web.Extensions.dll',
                    str(ROOT / 'scripts/packaging/WindowsSetup.cs')], check=True, capture_output=True)
    return output


@pytest.fixture
def work():
    # Atomic renames need a real local filesystem, as in test_desktop_distribution.
    target = ROOT / 'test-artifacts'
    target.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='camera-setup-', dir=target) as directory:
        yield Path(directory)


@pytest.fixture
def registry():
    """A new HKCU subtree that stands in for both camera registry views."""
    path = r'Software\OrionMini\SetupCameraTests' + '\\' + uuid.uuid4().hex
    winreg.CreateKey(winreg.HKEY_CURRENT_USER, path).Close()
    try:
        yield path
    finally:
        acl(path, None)
        delete_tree(path)


def delete_tree(path):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            children = [winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
    except FileNotFoundError:
        return
    for child in children: delete_tree(path + '\\' + child)
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)


def acl(path, deny):
    """Deny the current user the named rights on every key below path, or (None) remove those denials."""
    script = "$Root = '" + path + "'; $Deny = '" + (deny or '') + "'" + r'''
$me = [Security.Principal.WindowsIdentity]::GetCurrent().User
function Visit([string]$Path) {
  $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($Path, 'ReadWriteSubTree', 'ChangePermissions,ReadPermissions,EnumerateSubKeys,QueryValues')
  if ($key -eq $null) { return }
  $rules = $key.GetAccessControl()
  foreach ($rule in @($rules.GetAccessRules($true, $false, [Security.Principal.SecurityIdentifier]))) {
    if ($rule.AccessControlType -eq 'Deny') { [void]$rules.RemoveAccessRuleSpecific($rule) } }
  if ($Deny -and $Path -match '\{D9B25791-5540-48BE-842C-C73BF8540340\}$') {
    $rules.AddAccessRule((New-Object Security.AccessControl.RegistryAccessRule($me, [Security.AccessControl.RegistryRights]$Deny, 'None', 'None', 'Deny'))) }
  $key.SetAccessControl($rules)
  foreach ($child in $key.GetSubKeyNames()) { Visit "$Path\$child" }
  $key.Close()
}
Visit $Root
'''
    encoded = base64.b64encode(script.encode('utf-16-le')).decode()
    subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], check=True, capture_output=True, timeout=60)


def payload(version, camera=b'synthetic camera component'):
    files = {'app/Saiph.exe': b'MZ synthetic', 'app/OrionMini.exe': b'MZ synthetic', 'licenses/inventory.json': b'{}',
             'app/_internal/camera/SaiphCamera64.dll': b'MZ64 ' + camera + version.encode(),
             'app/_internal/camera/SaiphCamera32.dll': b'MZ32 ' + camera + version.encode()}
    items = [{'path': path, 'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()} for path, content in files.items()]
    manifest = {'format': 'orion-desktop-package', 'schema': 1, 'version': version, 'platform': 'windows-x86_64', 'profile': 'link',
                'build': 7, 'entrypoint': 'app/Saiph.exe', 'files': items, 'release_state': 'internal-preview',
                'license_inventory': 'licenses/inventory.json'}
    return files, manifest


def installer(work, stub, version):
    files, manifest = payload(version)
    archive = work / (version + '.zip')
    with zipfile.ZipFile(archive, 'w') as output:
        for path, content in files.items(): output.writestr(path, content)
        output.writestr('package-manifest.json', json.dumps(manifest))
    executable = work / (version + '.exe')
    shutil.copyfile(stub, executable)
    with executable.open('ab') as output:
        output.write(archive.read_bytes()); output.write(struct.pack('<Q', archive.stat().st_size) + b'ORIONZIP')
    return executable


def run(executable, install, registry, *extra):
    environment = dict(os.environ, ORION_SETUP_CAMERA_TEST_ROOT=registry)
    return subprocess.run([str(executable), '--silent', '--isolated', '--no-launch', '--destination', str(install), *extra],
                          capture_output=True, text=True, timeout=60, env=environment)


def register(registry, release, views=('64', '32')):
    """What each release's DllRegisterServer writes, relative to the test root."""
    for view in views:
        camera, properties = CAMERA[view]
        server = str(release / 'app/_internal/camera' / ('SaiphCamera' + view + '.dll'))
        for clsid in (camera, properties):
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, registry + '\\' + CLASSES + clsid) as key:
                winreg.SetValueEx(key, '', 0, winreg.REG_SZ, 'Saiph Camera')
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, registry + '\\' + CLASSES + clsid + r'\InprocServer32') as key:
                winreg.SetValueEx(key, '', 0, winreg.REG_SZ, server)
                winreg.SetValueEx(key, 'ThreadingModel', 0, winreg.REG_SZ, 'Both')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, registry + '\\' + CATEGORY + camera) as key:
            for name, value in (('CLSID', camera), ('FriendlyName', 'Saiph Camera'), ('DevicePath', 'saiph:camera:' + camera)):
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def registrations(registry):
    found = {}
    for view, ids in CAMERA.items():
        for clsid in ids:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry + '\\' + CLASSES + clsid + r'\InprocServer32') as key:
                    found[clsid] = winreg.QueryValueEx(key, '')[0]
            except FileNotFoundError:
                pass
        try:
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry + '\\' + CATEGORY + ids[0]).Close()
            found['instance ' + ids[0]] = True
        except FileNotFoundError:
            pass
    return found


def log(install):
    path = install / 'setup.log'
    return path.read_text(encoding='utf-8') if path.exists() else ''


def test_update_removes_the_previous_releases_camera_before_the_new_release_runs(work, stub, registry):
    install = work / 'installed'
    assert run(installer(work, stub, '0.1.0-beta.32'), install, registry).returncode == 0
    register(registry, install / 'releases/0.1.0-beta.32')
    assert len(registrations(registry)) == 6
    result = run(installer(work, stub, '0.1.0-beta.33'), install, registry)
    assert result.returncode == 0 and 'warning' not in result.stderr
    assert registrations(registry) == {}
    assert log(install).count(' removed: ') == 4 and 'survived' not in log(install)
    assert json.loads((install / 'orion-install.json').read_text())['current'] == '0.1.0-beta.33'
    # A registration made by a release two updates back is still this installation's.
    register(registry, install / 'releases/0.1.0-beta.32')
    assert run(installer(work, stub, '0.1.0-beta.34'), install, registry).returncode == 0
    assert registrations(registry) == {}


@pytest.mark.parametrize('deny', ['CreateSubKey', 'SetValue'])
def test_update_removes_a_registration_that_dotnet_delete_subkey_tree_silently_skips(work, stub, registry, deny):
    # RegistryKey.DeleteSubKeyTree(name, false) opens the key for writing and returns
    # without deleting anything when that open is refused; regsvr32 /u still works.
    install = work / 'installed'
    assert run(installer(work, stub, '0.1.0-beta.32'), install, registry).returncode == 0
    register(registry, install / 'releases/0.1.0-beta.32')
    acl(registry, deny)
    result = run(installer(work, stub, '0.1.0-beta.33'), install, registry)
    assert result.returncode == 0 and 'warning' not in result.stderr, result.stderr
    assert registrations(registry) == {}


def test_a_registration_that_cannot_be_removed_is_reported_loudly(work, stub, registry):
    install = work / 'installed'
    assert run(installer(work, stub, '0.1.0-beta.32'), install, registry).returncode == 0
    register(registry, install / 'releases/0.1.0-beta.32')
    acl(registry, 'Delete')
    result = run(installer(work, stub, '0.1.0-beta.33'), install, registry)
    # The update still activates; the new release's camera replaces a registration
    # from its own installation's releases folder (native/camera/registration.cpp).
    assert result.returncode == 0
    camera = CAMERA['64'][0]
    assert 'Saiph installer warning: camera registration survived removal: Registry64 ' + camera in result.stderr
    assert ' removal failed: ' in log(install) and 'survived removal: Registry64 ' + camera in log(install)
    assert camera in registrations(registry) and CAMERA['32'][0] not in registrations(registry)


def test_foreign_and_changed_registrations_are_kept(work, stub, registry):
    install, other = work / 'installed', work / 'other-installation'
    assert run(installer(work, stub, '0.1.0-beta.32'), install, registry).returncode == 0
    # Another installation's camera (a different root) and this release after its DLL changed on disk.
    register(registry, other / 'releases/0.1.0-beta.32', views=('64',))
    register(registry, install / 'releases/0.1.0-beta.32', views=('32',))
    (install / 'releases/0.1.0-beta.32/app/_internal/camera/SaiphCamera32.dll').write_bytes(b'MZ32 changed locally')
    before = registrations(registry)
    result = run(installer(work, stub, '0.1.0-beta.33'), install, registry)
    assert result.returncode == 0 and 'warning' not in result.stderr
    assert registrations(registry) == before
    assert log(install).count(' kept: ') == 4


def test_uninstall_removes_owned_registrations(work, stub, registry):
    install = work / 'installed'
    assert run(installer(work, stub, '0.1.0-beta.32'), install, registry).returncode == 0
    register(registry, install / 'releases/0.1.0-beta.32')
    result = run(install / 'Uninstall.exe', install, registry, '--uninstall')
    assert result.returncode == 0, result.stderr
    assert registrations(registry) == {}


@pytest.mark.parametrize('root', [r'Software\Classes', r'Software\OrionMini\SetupCameraTests', r'Software\OrionMini\SetupCameraTests\..\x'])
def test_the_test_registry_is_confined_to_its_disposable_subtree(work, stub, root):
    result = run(installer(work, stub, '0.1.0-beta.32'), work / 'installed', root)
    assert result.returncode != 0 and 'installer failed: arguments' in result.stderr
    assert not (work / 'installed').exists()
