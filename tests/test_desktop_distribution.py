# SPDX-License-Identifier: AGPL-3.0-or-later
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zipfile

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location('desktop_distribution', ROOT / 'scripts/packaging/build-desktop-distribution.py')
packaging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packaging)


def bundle(tmp_path, magic=b'MZ'):
    root = tmp_path / 'bundle'
    root.mkdir()
    (root / 'Saiph.exe').write_bytes(magic + b'synthetic executable fixture')
    (root / '_internal').mkdir()
    (root / '_internal/runtime.txt').write_text('packaged runtime fixture')
    (root / '_internal/distribution-profile.json').write_text(json.dumps({'schema': 1, 'profile': 'link'}))
    (root / '_internal/distribution-release.json').write_text(json.dumps({'schema': 1, 'platform': 'windows-x86_64', 'version': '0.1.0-preview.1', 'build': 0}))
    return root


def test_secret_state_and_path_traversal_are_rejected(tmp_path):
    root = bundle(tmp_path)
    (root / 'google-services.json').write_text('{}')
    with pytest.raises(ValueError, match='private state'): packaging.audit_bundle(root, 'windows-x86_64')
    (root / 'google-services.json').unlink()
    (root / 'innocent.txt').write_text('-----BEGIN ' + 'EC PRIVATE KEY-----\nsynthetic')
    with pytest.raises(ValueError, match='private key'): packaging.audit_bundle(root, 'windows-x86_64')
    for path in ['../escape', '/absolute', 'C:/escape', 'directory\\escape', 'line\nbreak']:
        with pytest.raises(ValueError): packaging.safe_path(path)



def test_link_bundles_exclude_and_workspace_bundles_require_the_add_on(tmp_path):
    root = bundle(tmp_path)
    for module in ['orion_workspace', 'orion_workspace.window', 'faster_whisper.transcribe']:
        with pytest.raises(ValueError, match='personal Workspace modules'):
            packaging.audit_profile_contents(root, 'link', ['orion_mini.app', module])
    packaging.audit_profile_contents(root, 'link', ['orion_mini.app', 'orion_mini.modules'])
    with pytest.raises(ValueError, match='missing the orion_workspace add-on'):
        packaging.audit_profile_contents(root, 'workspace', ['orion_mini.app'])
    with pytest.raises(ValueError, match='skills'):
        packaging.audit_profile_contents(root, 'workspace', ['orion_mini.app', 'orion_workspace.edition'])
    (root / '_internal/skills').mkdir()
    packaging.audit_profile_contents(root, 'workspace', ['orion_mini.app', 'orion_workspace.edition'])


def test_native_build_takes_the_workspace_add_on_only_from_an_explicit_checkout(tmp_path):
    spec = importlib.util.spec_from_file_location('native_build', ROOT / 'scripts/build-native.py')
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    parser = build.argparse.ArgumentParser()
    addon = tmp_path / 'orion'
    with pytest.raises(SystemExit):
        build.workspace_source(parser, 'workspace', None)
    with pytest.raises(SystemExit):
        build.workspace_source(parser, 'link', addon)
    assert build.workspace_source(parser, 'link', None) is None
    with pytest.raises(SystemExit):
        build.workspace_source(parser, 'workspace', addon)
    for name in ['src/orion_workspace/edition.py', 'scripts/dev.py']:
        (addon / name).parent.mkdir(parents=True, exist_ok=True)
        (addon / name).write_text('')
    (addon / 'skills').mkdir()
    assert build.workspace_source(parser, 'workspace', addon) == addon.resolve()
    assert 'orion_workspace' in build.LINK_EXCLUDED_MODULES

def test_linux_requires_actual_linux_executable(tmp_path):
    root = bundle(tmp_path)
    (root / 'saiph').write_bytes(b'MZ-not-linux')
    with pytest.raises(ValueError, match='Linux-built ELF'): packaging.audit_bundle(root, 'linux-x86_64')


def test_tls_label_constants_are_not_mistaken_for_pem_credentials(tmp_path):
    root = bundle(tmp_path)
    (root / '_internal/tls.dll').write_bytes(b'\x00-----BEGIN ' + b'PRIVATE KEY-----\x00')
    packaging.audit_bundle(root, 'windows-x86_64')
    (root / '_internal/tls.dll').write_bytes(b'\x00\n-----BEGIN ' + b'PRIVATE KEY-----\r\nsynthetic\n')
    with pytest.raises(ValueError, match='private key'):
        packaging.audit_bundle(root, 'windows-x86_64')


def test_manifest_has_exact_bytes_hashes_and_preview_state(tmp_path, monkeypatch):
    root = bundle(tmp_path)
    monkeypatch.setattr(packaging, 'license_inventory', lambda target, *args: target.mkdir())
    staging = tmp_path / 'staging'
    manifest = packaging.prepare(root, staging, '0.1.0-preview.1', 'windows-x86_64', tmp_path / 'absent', tmp_path)
    assert manifest['release_state'] == 'internal-preview'
    assert manifest['profile'] == 'link'
    assert manifest['entrypoint'] == 'app/Saiph.exe'
    # Updaters installed before the rename relaunch OrionMini.exe; it is a recorded byte copy.
    assert (staging / 'app/OrionMini.exe').read_bytes() == (staging / 'app/Saiph.exe').read_bytes()
    assert {'app/Saiph.exe', 'app/OrionMini.exe'} <= {item['path'] for item in manifest['files']}
    for item in manifest['files']:
        assert packaging.digest(staging / item['path']) == item['sha256']
        assert (staging / item['path']).stat().st_size == item['bytes']
    with pytest.raises(ValueError, match='semantic version'):
        packaging.prepare(root, tmp_path / 'bad', '../escape', 'windows-x86_64', tmp_path, tmp_path)
    (root / 'OrionMini.exe').write_bytes(b'MZ stale copy')
    with pytest.raises(ValueError, match='compatibility executable'):
        packaging.prepare(root, tmp_path / 'stale', '0.1.0-preview.1', 'windows-x86_64', tmp_path / 'absent', tmp_path)


def windows_payload(version, legacy=False, executable=b'MZ synthetic'):
    """Package files and manifest: the pre-rename layout, or Saiph.exe with its compatibility copy."""
    files = {'app/OrionMini.exe': executable} if legacy else {'app/Saiph.exe': executable, 'app/OrionMini.exe': executable}
    files['licenses/inventory.json'] = b'{}'
    items = [{'path': path, 'bytes': len(content), 'sha256': packaging.hashlib.sha256(content).hexdigest()} for path, content in files.items()]
    manifest = {'format': 'orion-desktop-package', 'schema': 1, 'version': version, 'platform': 'windows-x86_64', 'profile': 'link', 'build': 7,
                'entrypoint': 'app/OrionMini.exe' if legacy else 'app/Saiph.exe', 'files': items, 'release_state': 'internal-preview',
                'license_inventory': 'licenses/inventory.json'}
    return files, manifest


@pytest.fixture
def native_fixture_root():
    # Redirected AppData/AppContainer temp roots cannot provide atomic Windows
    # renames. Exercise the installer on a real local checkout filesystem.
    target = ROOT / 'test-artifacts'
    target.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='installer-proof-', dir=target) as directory:
        yield Path(directory)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows native installer')
def test_native_installer_upgrade_uninstall_and_corruption_preserve_user_data(native_fixture_root):
    tmp_path = native_fixture_root
    compiler = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    if not compiler.is_file(): pytest.skip('Windows Framework compiler absent')
    stub = tmp_path / 'setup-stub.exe'
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/out:' + str(stub),
                    '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll', '/reference:System.IO.Compression.dll',
                    '/reference:System.IO.Compression.FileSystem.dll', '/reference:System.Web.Extensions.dll',
                    str(ROOT / 'scripts/packaging/WindowsSetup.cs')], check=True, capture_output=True)
    install = tmp_path / 'installed'
    owner = tmp_path / 'owner-data'
    owner.mkdir(); (owner / 'pairing-key.txt').write_text('synthetic-key-retained')
    (owner / 'settings.json').write_text('{"start_with_windows": false, "hub": {"device_id": "synthetic-device"}}')
    (owner / 'orion-mini.sqlite3').write_bytes(b'synthetic existing user database')
    owner_before = {path.name: path.read_bytes() for path in owner.iterdir()}
    legacy_source = tmp_path / 'OrionSetup.cs'
    legacy_source.write_bytes((ROOT / 'tests/fixtures/legacy_orion_windows_setup.cs').read_bytes())
    legacy_stub = tmp_path / 'legacy-stub.exe'
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/out:' + str(legacy_stub),
                    '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll', '/reference:System.IO.Compression.dll',
                    '/reference:System.IO.Compression.FileSystem.dll', '/reference:System.Web.Extensions.dll', str(legacy_source)],
                   check=True, capture_output=True)

    def installer(version, corrupt=False, escape=False):
        files, manifest = windows_payload(version, legacy=version == '0.1.0-preview.1')
        if escape:
            files['../owner-data/pairing-key.txt'] = b'changed'
            manifest['files'].append({'path': '../owner-data/pairing-key.txt', 'bytes': 7, 'sha256': packaging.hashlib.sha256(b'changed').hexdigest()})
        archive = tmp_path / (version + '.zip')
        with zipfile.ZipFile(archive, 'w') as output:
            for path, content in files.items(): output.writestr(path, content + (b'broken' if corrupt else b''))
            output.writestr('package-manifest.json', json.dumps(manifest))
        executable = tmp_path / (version + '.exe')
        shutil.copyfile(legacy_stub if version == '0.1.0-preview.1' else stub, executable)
        with executable.open('ab') as output:
            output.write(archive.read_bytes()); output.write(struct.pack('<Q', archive.stat().st_size) + b'ORIONZIP')
        return executable

    def run(executable, *extra):
        result = subprocess.run([str(executable), '--silent', '--isolated', '--no-launch', '--destination', str(install), *extra], capture_output=True, timeout=30)
        if result.returncode:
            print(result.stderr.decode(errors='replace'))
        return result.returncode

    assert run(installer('0.1.0-preview.1')) == 0
    installed_manifest = json.loads((install / 'releases/0.1.0-preview.1/package-manifest.json').read_text())
    assert (installed_manifest['profile'], installed_manifest['build'], installed_manifest['license_inventory']) == ('link', 7, 'licenses/inventory.json')
    # A second install or uninstall must fail before modifying the marker or
    # old release while another process holds this destination's mutex.
    holder_source = tmp_path / 'hold.cs'
    holder_source.write_text('''using System; using System.IO; using System.Reflection; using System.Threading;
class Hold { static void Main(string[] args) {
var type=Assembly.LoadFile(args[0]).GetType("Setup");
var flags=BindingFlags.NonPublic|BindingFlags.Static;
type.GetField("destination",flags).SetValue(null,args[1]);
using(var mutex=new Mutex(false,(string)type.GetMethod("LockName",flags).Invoke(null,null))) {
mutex.WaitOne(); File.WriteAllText(args[2],"ready");
while(!File.Exists(args[3])) Thread.Sleep(20); mutex.ReleaseMutex(); }
}}''')
    holder_exe = tmp_path / 'hold.exe'
    subprocess.run([str(compiler), '/nologo', '/out:' + str(holder_exe), str(holder_source)], check=True, capture_output=True)
    ready = tmp_path / 'lock-ready'; release_lock = tmp_path / 'lock-release'
    holder = subprocess.Popen([str(holder_exe), str(stub), str(install), str(ready), str(release_lock)])
    try:
        deadline = time.monotonic() + 10
        while not ready.exists():
            assert holder.poll() is None and time.monotonic() < deadline
            time.sleep(.02)
        before_locked = (install / 'orion-install.json').read_bytes()
        contender = installer('0.1.0-preview.7')
        assert run(contender) != 0
        assert run(contender, '--uninstall') != 0
        assert (install / 'orion-install.json').read_bytes() == before_locked
        assert (install / 'releases/0.1.0-preview.1/app/OrionMini.exe').is_file()
        assert (owner / 'pairing-key.txt').read_text() == 'synthetic-key-retained'
    finally:
        release_lock.write_text('release')
        holder.wait(timeout=10)
    assert run(installer('0.1.0-preview.2')) == 0
    assert {path.name: path.read_bytes() for path in owner.iterdir()} == owner_before
    before = (install / 'orion-install.json').read_bytes()
    assert run(installer('0.1.0-preview.3', corrupt=True)) != 0
    assert run(installer('0.1.0-preview.4', escape=True)) != 0
    assert (install / 'orion-install.json').read_bytes() == before
    assert (owner / 'pairing-key.txt').read_text() == 'synthetic-key-retained'
    # User modifications within even the install directory must survive uninstall.
    custom = install / 'releases/0.1.0-preview.2/app/user-added.txt'
    custom.write_text('user file retained')
    # A listed release whose folder was already deleted must not block removal.
    shutil.rmtree(install / 'releases/0.1.0-preview.1')
    assert run(installer('0.1.0-preview.5'), '--uninstall') == 0
    assert custom.read_text() == 'user file retained'
    assert json.loads((install / 'orion-install.json').read_text())['versions'] == ['0.1.0-preview.2']
    assert (owner / 'pairing-key.txt').read_text() == 'synthetic-key-retained'
    assert run(installer('0.1.0-preview.6')) == 0


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows native installer')
def test_upgrade_from_pre_rename_release_owns_both_names_and_rolls_back_to_its_entrypoint(native_fixture_root):
    tmp_path = native_fixture_root
    compiler = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    if not compiler.is_file(): pytest.skip('Windows Framework compiler absent')
    references = ['/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll', '/reference:System.IO.Compression.dll',
                  '/reference:System.IO.Compression.FileSystem.dll', '/reference:System.Web.Extensions.dll']
    stubs = {}
    for name, source in (('current', ROOT / 'scripts/packaging/WindowsSetup.cs'), ('legacy', ROOT / 'tests/fixtures/legacy_orion_windows_setup.cs')):
        copy = tmp_path / (name + '.cs'); copy.write_bytes(source.read_bytes())
        stubs[name] = tmp_path / (name + '-stub.exe')
        subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/out:' + str(stubs[name]), *references, str(copy)],
                       check=True, capture_output=True)

    def installer(version, stub, legacy):
        files, manifest = windows_payload(version, legacy=legacy)
        archive = tmp_path / (version + '.zip')
        with zipfile.ZipFile(archive, 'w') as output:
            for path, content in files.items(): output.writestr(path, content)
            output.writestr('package-manifest.json', json.dumps(manifest))
        executable = tmp_path / (version + '.exe')
        shutil.copyfile(stubs[stub], executable)
        with executable.open('ab') as output:
            output.write(archive.read_bytes()); output.write(struct.pack('<Q', archive.stat().st_size) + b'ORIONZIP')
        return executable

    install = tmp_path / 'installed'
    def run(executable, *extra):
        return subprocess.run([str(executable), '--silent', '--isolated', '--no-launch', '--destination', str(install), *extra],
                              capture_output=True, timeout=30).returncode

    # A beta.4-style release (OrionMini.exe only), then the renamed release.
    assert run(installer('0.1.0-beta.4', 'legacy', legacy=True)) == 0
    assert run(installer('0.1.0-beta.5', 'current', legacy=False)) == 0
    renamed = install / 'releases/0.1.0-beta.5/app'
    assert (renamed / 'Saiph.exe').read_bytes() == (renamed / 'OrionMini.exe').read_bytes()
    # The renamed installer only accepts packages built with the new entrypoint.
    assert run(installer('0.1.0-beta.6', 'current', legacy=True)) != 0
    assert not (install / 'releases/0.1.0-beta.6').exists()

    probe = tmp_path / 'Probe.cs'
    probe.write_text(r'''using System; using System.Collections; using System.IO; using System.Reflection;
class Probe { static void Main(string[] args) {
var type = Assembly.LoadFile(args[0]).GetType("Setup");
var flags = BindingFlags.NonPublic | BindingFlags.Static;
type.GetField("destination", flags).SetValue(null, args[1]);
type.GetField("isolated", flags).SetValue(null, true);
Func<string, string> relative = path => path.Substring(args[1].Length + 1).Replace('\\', '/');
var existing = type.GetMethod("Existing", flags).Invoke(null, null);
foreach (string path in (IEnumerable)type.GetMethod("OwnedExecutables", flags).Invoke(null, new[] { existing })) Console.WriteLine("owned " + relative(path));
foreach (string version in new[] { args[2], args[3] })
    Console.WriteLine("entry " + relative((string)type.GetMethod("ReleaseExecutable", flags).Invoke(null, new object[] { Path.Combine(args[1], "releases", version) })));
}}''')
    checker = tmp_path / 'probe.exe'
    subprocess.run([str(compiler), '/nologo', '/platform:x64', '/out:' + str(checker), str(probe)], check=True, capture_output=True)
    lines = subprocess.run([str(checker), str(stubs['current']), str(install), '0.1.0-beta.4', '0.1.0-beta.5'],
                           capture_output=True, text=True, timeout=30, check=True).stdout.splitlines()
    # Startup entries and shortcuts naming any of these are Saiph's own to migrate or remove.
    assert sorted(line for line in lines if line.startswith('owned ')) == [
        'owned releases/0.1.0-beta.4/app/OrionMini.exe', 'owned releases/0.1.0-beta.5/app/OrionMini.exe',
        'owned releases/0.1.0-beta.5/app/Saiph.exe']
    # Rolling integration back to beta.4 points shortcuts at its own executable.
    assert [line for line in lines if line.startswith('entry ')] == [
        'entry releases/0.1.0-beta.4/app/OrionMini.exe', 'entry releases/0.1.0-beta.5/app/Saiph.exe']

    assert run(install / 'Uninstall.exe', '--uninstall') == 0
    assert not (install / 'releases/0.1.0-beta.4').exists() and not (install / 'releases/0.1.0-beta.5').exists()


def windows_sdk_signtool():
    kits = Path('C:/Program Files (x86)/Windows Kits/10/bin')
    found = sorted(kits.glob('10.*/x64/signtool.exe')) if kits.is_dir() else []
    return found[-1] if found else None


def throwaway_openssl():
    candidates = [shutil.which('openssl'), 'C:/Program Files/Git/usr/bin/openssl.exe', 'C:/Program Files/Git/mingw64/bin/openssl.exe']
    return next((Path(path) for path in candidates if path and Path(path).is_file()), None)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows native installer and SDK SignTool')
def test_authenticode_signed_installer_still_finds_its_payload(native_fixture_root):
    tmp_path = native_fixture_root
    compiler, signtool, openssl = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe'), windows_sdk_signtool(), throwaway_openssl()
    if not compiler.is_file() or not signtool or not openssl: pytest.skip('Framework compiler, SDK SignTool or OpenSSL absent')
    stub = tmp_path / 'setup-stub.exe'
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/out:' + str(stub),
                    '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll', '/reference:System.IO.Compression.dll',
                    '/reference:System.IO.Compression.FileSystem.dll', '/reference:System.Web.Extensions.dll',
                    str(ROOT / 'scripts/packaging/WindowsSetup.cs')], check=True, capture_output=True)
    # A throwaway self-signed certificate in a file; nothing enters a certificate store.
    key, certificate, pfx = tmp_path / 'throwaway.key', tmp_path / 'throwaway.crt', tmp_path / 'throwaway.pfx'
    subprocess.run([str(openssl), 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=Saiph synthetic test signer',
                    '-addext', 'extendedKeyUsage=codeSigning', '-keyout', str(key), '-out', str(certificate)], check=True, capture_output=True)
    subprocess.run([str(openssl), 'pkcs12', '-export', '-inkey', str(key), '-in', str(certificate), '-out', str(pfx),
                    '-passout', 'pass:synthetic', '-keypbe', 'PBE-SHA1-3DES', '-certpbe', 'PBE-SHA1-3DES', '-macalg', 'sha1'], check=True, capture_output=True)

    def installer(version, aligned=True):
        files, manifest = windows_payload(version)
        archive = tmp_path / (version + '.zip')
        with zipfile.ZipFile(archive, 'w') as output:
            for path, content in files.items(): output.writestr(path, content)
            output.writestr('package-manifest.json', json.dumps(manifest))
        executable = tmp_path / (version + '.exe')
        shutil.copyfile(stub, executable)
        padding = packaging.aligned_padding(stub.stat().st_size + archive.stat().st_size + 16)
        if not aligned: padding = padding + 1 if padding < 7 else 0
        with executable.open('ab') as output:
            output.write(b'\0' * padding); output.write(archive.read_bytes()); output.write(struct.pack('<Q', archive.stat().st_size) + b'ORIONZIP')
        assert (executable.stat().st_size % 8 == 0) == aligned
        unsigned = executable.stat().st_size
        subprocess.run([str(signtool), 'sign', '/fd', 'sha256', '/f', str(pfx), '/p', 'synthetic', str(executable)], check=True, capture_output=True)
        assert executable.stat().st_size > unsigned
        return executable

    install = tmp_path / 'installed'
    def run(executable):
        return subprocess.run([str(executable), '--silent', '--isolated', '--no-launch', '--destination', str(install)], capture_output=True, timeout=30).returncode

    assert run(installer('0.2.0-preview.1')) == 0
    assert json.loads((install / 'releases/0.2.0-preview.1/package-manifest.json').read_text())['version'] == '0.2.0-preview.1'
    # Signing an unaligned file inserts padding after the trailer: fail closed.
    assert run(installer('0.2.0-preview.2', aligned=False)) != 0
    # Bytes appended after the certificate table no longer match the PE header.
    appended = installer('0.2.0-preview.3')
    with appended.open('ab') as output: output.write(b'unexpected')
    assert run(appended) != 0
    assert not (install / 'releases/0.2.0-preview.2').exists() and not (install / 'releases/0.2.0-preview.3').exists()


def test_installer_explains_blocked_setup_and_only_replaces_startup_when_asked(tmp_path):
    compiler = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    if not compiler.is_file(): pytest.skip('Windows Framework compiler absent')
    references = ['/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll', '/reference:System.IO.Compression.dll',
                  '/reference:System.IO.Compression.FileSystem.dll', '/reference:System.Web.Extensions.dll']
    setup = tmp_path / 'setup.exe'
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/out:' + str(setup), *references,
                    str(ROOT / 'scripts/packaging/WindowsSetup.cs')], check=True, capture_output=True)
    probe = tmp_path / 'Probe.cs'
    probe.write_text(r'''
using System; using System.IO;
public static class Probe {
    public static void Main() {
        var owned = new[] { @"C:\Saiph\releases\1\app\OrionMini.exe" };
        string source = "\"E:\\src\\.venv\\Scripts\\pythonw.exe\" -m orion_mini";
        Console.WriteLine(IntegrationPolicy.StartupConflict(source, owned, true, false) != null);   // blocks
        Console.WriteLine(IntegrationPolicy.StartupConflict(source, owned, true, true) == null);    // replace approved
        Console.WriteLine(IntegrationPolicy.StartupConflict(source, owned, false, false) == null);  // startup unticked
        Console.WriteLine(IntegrationPolicy.StartupConflict("\"" + owned[0] + "\"", owned, true, false) == null);
        Console.WriteLine(SetupMessages.Describe(new SetupBlocked("Move the shortcut."), "integration-preflight"));
        Console.WriteLine(SetupMessages.Describe(new IOException("Another Saiph installation is running."), "installation-lock"));
        Console.WriteLine(SetupMessages.Describe(new InvalidDataException(), "payload"));
        Console.WriteLine(SetupMessages.DescribeRemoval(new InvalidDataException(), "uninstall"));
    }
}''')
    checker = tmp_path / 'probe.exe'
    subprocess.run([str(compiler), '/nologo', '/platform:x64', '/out:' + str(checker), '/reference:' + str(setup), str(probe)],
                   check=True, capture_output=True)
    lines = subprocess.run([str(checker)], capture_output=True, text=True, timeout=30, cwd=tmp_path, check=True).stdout.splitlines()
    assert lines[:4] == ['True'] * 4
    assert lines[4] == 'Move the shortcut.'
    assert lines[5] == 'Another Saiph setup is already running. Finish or close it, then try again.'
    assert lines[6] == 'The installation could not finish (step: payload). Your existing release and data were retained.'
    assert lines[7] == 'Saiph could not be removed (step: uninstall). Your settings and data were retained.'


def test_installer_alignment_padding():
    assert [packaging.aligned_padding(length) for length in (0, 1, 7, 8, 13, 16)] == [0, 7, 1, 0, 3, 0]


@pytest.mark.skipif(sys.platform != 'linux', reason='Actual Linux shell/flock installer')
def test_linux_lock_covers_install_and_uninstall_without_changing_owned_release(tmp_path):
    fixture = tmp_path / 'package'; fixture.mkdir()
    shutil.copyfile(ROOT / 'scripts/packaging/install-linux.sh', fixture / 'install.sh')
    (fixture / 'VERSION').write_text('0.1.0-preview.1\n')
    (fixture / 'LINUX_COMPATIBILITY').write_text('linux-x86_64 glibc 2.17\n')
    target = tmp_path / 'installed'; target.mkdir()
    (target / 'orion-owned').touch()
    data = target / 'retained'; data.write_bytes(b'synthetic owner state')
    import fcntl
    with (tmp_path / 'installed.install.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for extra in ([], ['--uninstall']):
            import os
            env = {**os.environ, 'ORION_INSTALL_ROOT':str(target), 'ORION_INSTALL_ISOLATED':'1'}
            result = subprocess.run(['sh', str(fixture / 'install.sh'), *extra], env=env, capture_output=True)
            assert result.returncode != 0 and b'Another Saiph installation' in result.stderr
            assert data.read_bytes() == b'synthetic owner state'
    result = subprocess.run(['sh', str(fixture / 'install.sh'), '--uninstall'], env=env, capture_output=True)
    assert result.returncode == 0 and data.read_bytes() == b'synthetic owner state'
