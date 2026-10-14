# SPDX-License-Identifier: AGPL-3.0-or-later
"""The no-terminal Linux setup wraps the unchanged release archive and its install.sh."""
import hashlib
import importlib.util
import io
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).parents[1]
INSTALLER = ROOT / 'scripts/packaging/install-linux.sh'
SPEC = importlib.util.spec_from_file_location('linux_setup_packaging', ROOT / 'scripts/packaging/build-desktop-distribution.py')
packaging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packaging)

SYNTHETIC_INSTALLER = b'''#!/bin/sh
printf '%s\\n' "$(cd "$(dirname "$0")" && pwd -P)" > "$SAIPH_TEST_MARKER"
printf '%s %s\\n' "${SAIPH_AUTOSTART:-unset}" "${SAIPH_FILE_ACTIONS:-unset}" > "$SAIPH_TEST_MARKER.choices"
echo "synthetic installer output"
if [ "${SAIPH_TEST_FAIL:-0}" != 0 ]; then echo "synthetic failure reason" >&2; exit 3; fi
'''
# Behaves like zenity/kdialog/a terminal: records each call and answers from a list.
FAKE_TOOL = '''#!/bin/sh
count=$(cat "$FAKE_LOG.count" 2>/dev/null || echo 0); count=$((count + 1)); echo "$count" > "$FAKE_LOG.count"
printf '%s %s\\n' "$(basename "$0")" "$(printf '%s ' "$@" | tr '\\n' ' ')" >> "$FAKE_LOG"
answer=$(echo "${FAKE_ANSWERS:-}" | cut -d ' ' -f "$count")
case " $* " in *" --list "*|*" --checklist "*) printf '%s\\n' "${FAKE_CHOICES:-}" ;; esac
case "$(basename "$0"):${1:-}" in
  zenity:--progress) cat > /dev/null ;;
  x-terminal-emulator:-e) shift; printf '\\n\\n' | "$@"; exit $? ;;
esac
exit "${answer:-0}"
'''
TOOLS = ('sh', 'tail', 'wc', 'sha256sum', 'cut', 'tar', 'gzip', 'mktemp', 'tr', 'cat', 'mv', 'rm', 'mkdir',
         'basename', 'dirname', 'head', 'cp', 'chmod')


class PrivateEnvironment(dict):
    def __repr__(self):
        return '<private process environment>'


@pytest.fixture
def shell():
    if sys.platform == 'win32':
        executable = Path('C:/Program Files/Git/bin/bash.exe')
        if not executable.is_file():
            pytest.skip('Git Bash is unavailable for shell wrapper checks')
        return str(executable)
    return '/bin/sh'


def shell_path(path):
    value = str(Path(path).resolve()).replace('\\', '/')
    if sys.platform == 'win32':
        return '/' + value[0].lower() + value[2:]
    return value


def archive(tmp_path, version='1.0.0', files=None):
    """A release-shaped tar.gz; synthetic unless real installer files are given."""
    files = files or {'install.sh': SYNTHETIC_INSTALLER, 'SHA256SUMS': b'synthetic\n',
                      'app/saiph': b'#!/bin/sh\nexit 0\n'}
    path = tmp_path / ('Saiph-Link-' + version + '-linux-x86_64.tar.gz')
    with tarfile.open(path, 'w:gz') as output:
        for name, content in files.items():
            item = tarfile.TarInfo('orion/' + name)
            item.size, item.mode = len(content), 0o755 if name in {'install.sh', 'app/saiph', 'app/OrionMini'} else 0o644
            output.addfile(item, io.BytesIO(content))
    return path


def setup_file(tmp_path, version='1.0.0', files=None):
    source = archive(tmp_path, version, files)
    result = packaging.build_linux_setup(source, source.with_name(source.name.replace('.tar.gz', '.run')))
    return source, Path(result['artifact']), result


@pytest.fixture
def profile(tmp_path):
    paths = {'home': tmp_path / 'home with spaces', 'cache': tmp_path / 'cache', 'fake': tmp_path / 'fake-bin',
             'marker': tmp_path / 'installer-ran', 'log': tmp_path / 'calls.log'}
    paths['home'].mkdir(); paths['fake'].mkdir()
    environment = PrivateEnvironment({**os.environ, 'HOME': shell_path(paths['home']),
                                     'XDG_CACHE_HOME': shell_path(paths['cache']),
                                     'XDG_CONFIG_HOME': shell_path(tmp_path / 'config'),
                                     'XDG_DATA_HOME': shell_path(tmp_path / 'data'),
                                     'SAIPH_TEST_MARKER': shell_path(paths['marker']),
                                     'FAKE_LOG': shell_path(paths['log']), 'FAKE_PATH': shell_path(paths['fake'])})
    for name in ('DISPLAY', 'WAYLAND_DISPLAY', 'RESTRICTED_PATH',
                 'ORION_INSTALL_ROOT', 'ORION_INSTALL_ISOLATED', 'FAKE_ANSWERS', 'FAKE_CHOICES', 'SAIPH_TEST_FAIL',
                 'SAIPH_AUTOSTART', 'SAIPH_FILE_ACTIONS'):
        environment.pop(name, None)
    return environment, paths


def run(shell, setup, environment, *arguments, timeout=60):
    # Fake desktop tools come first. A restricted PATH also hides any real
    # zenity/kdialog/terminal, leaving only wrappers for standard commands.
    command = 'PATH="$FAKE_PATH:${RESTRICTED_PATH:-$PATH}"; export PATH; exec sh "$@"'
    return subprocess.run([shell, '-c', command, 'setup-harness', shell_path(setup), *arguments],
                          env=environment, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)


def restrict(shell, tmp_path, environment):
    """Expose only standard commands, through wrappers, so no real dialog tool is found."""
    tools = tmp_path / 'standard-tools'; tools.mkdir()
    for name in TOOLS:
        found = subprocess.run([shell, '-c', 'command -v "$1"', 'lookup', name], capture_output=True, text=True)
        target = found.stdout.strip()
        if found.returncode or not target.startswith('/'):
            pytest.skip('Standard command unavailable for wrapper checks: ' + name)
        (tools / name).write_text('#!/bin/sh\nexec "' + target + '" "$@"\n', newline='\n')
        (tools / name).chmod(0o755)
    environment['RESTRICTED_PATH'] = shell_path(tools)


def fake(paths, *names):
    for name in names:
        (paths['fake'] / name).write_text(FAKE_TOOL, newline='\n')
        (paths['fake'] / name).chmod(0o755)


def calls(paths):
    return paths['log'].read_text().splitlines() if paths['log'].is_file() else []


def test_setup_appends_unchanged_archive_and_fills_template(tmp_path):
    source, setup, result = setup_file(tmp_path, '0.1.0-beta.1')
    content, payload = setup.read_bytes(), source.read_bytes()
    assert setup.name == 'Saiph-Link-0.1.0-beta.1-linux-x86_64.run'
    assert content.endswith(payload) and content.startswith(b'#!/bin/sh\n')
    header = content[:-len(payload)].decode('utf-8')
    assert "payload_bytes='%d'" % len(payload) in header
    assert "payload_sha256='%s'" % hashlib.sha256(payload).hexdigest() in header
    assert "archive_name='Saiph-Link-0.1.0-beta.1-linux-x86_64.tar.gz'" in header
    assert not re.search(r'@[A-Z_]+@', header) and '\r' not in header
    assert result['payload_sha256'] == hashlib.sha256(payload).hexdigest()
    assert result['sha256'] == hashlib.sha256(content).hexdigest() and result['bytes'] == len(content)
    if os.name != 'nt':
        assert setup.stat().st_mode & 0o111


def test_setup_refuses_existing_output_and_unreleased_archives(tmp_path):
    source, setup, _ = setup_file(tmp_path)
    before = setup.read_bytes()
    with pytest.raises(ValueError, match='already exists'):
        packaging.build_linux_setup(source, setup)
    assert setup.read_bytes() == before
    renamed = tmp_path / 'download.tar.gz'
    shutil.copyfile(source, renamed)
    with pytest.raises(ValueError, match='finished Saiph Linux release archive'):
        packaging.build_linux_setup(renamed, tmp_path / 'download.run')
    windows = tmp_path / 'Saiph-Link-1.0.0-windows-x86_64.tar.gz'
    shutil.copyfile(source, windows)
    with pytest.raises(ValueError, match='finished Saiph Linux release archive'):
        packaging.build_linux_setup(windows, tmp_path / 'other.run')


def test_main_writes_setup_beside_archive_only_for_linux(tmp_path, monkeypatch, capsys):
    source = archive(tmp_path)
    monkeypatch.setattr(packaging, 'build_linux', lambda staging, output: shutil.copyfile(source, output))
    monkeypatch.setattr(packaging, 'audit_bundle', lambda *args: 'link')
    monkeypatch.setattr(packaging, 'audit_installed_modules', lambda *args: None)
    monkeypatch.setattr(packaging, 'prepare', lambda *args: {'profile': 'link', 'files': []})
    output = tmp_path / 'distribution'
    monkeypatch.setattr(sys, 'argv', ['build', '--platform', 'linux-x86_64', '--version', '0.1.0-beta.1',
                                      '--output', str(output), '--linux-setup'])
    packaging.main()
    result = json.loads(capsys.readouterr().out)
    assert Path(result['artifact']).name == 'Saiph-Link-0.1.0-beta.1-linux-x86_64.tar.gz'
    assert Path(result['setup']['artifact']).name == 'Saiph-Link-0.1.0-beta.1-linux-x86_64.run'
    assert Path(result['setup']['artifact']).read_bytes().endswith(Path(result['artifact']).read_bytes())
    monkeypatch.setattr(sys, 'argv', ['build', '--platform', 'windows-x86_64', '--version', '0.1.0-beta.1',
                                      '--output', str(tmp_path / 'windows'), '--linux-setup'])
    with pytest.raises(SystemExit):
        packaging.main()
    assert not (tmp_path / 'windows').exists()


def test_text_install_runs_the_archive_installer_from_a_private_folder_and_cleans_up(shell, tmp_path, profile):
    environment, paths = profile
    _, setup, _ = setup_file(tmp_path)
    result = run(shell, setup, environment, '--text')
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert b'synthetic installer output' in result.stdout
    ran_from = paths['marker'].read_text().strip()
    assert '/saiph-setup.' in ran_from and ran_from.endswith('/files/orion')
    # The private extraction folder is removed; only the cache root remains.
    assert list(paths['cache'].iterdir()) == []


def test_text_install_reports_installer_failure(shell, tmp_path, profile):
    environment, paths = profile
    _, setup, _ = setup_file(tmp_path)
    environment['SAIPH_TEST_FAIL'] = '1'
    result = run(shell, setup, environment, '--text')
    assert result.returncode == 3
    assert b'synthetic failure reason' in result.stderr and b'could not be installed' in result.stderr
    assert list(paths['cache'].iterdir()) == []


@pytest.mark.parametrize('damage', ['truncated', 'changed', 'appended'])
def test_damaged_download_never_runs_the_installer(shell, tmp_path, profile, damage):
    environment, paths = profile
    _, setup, _ = setup_file(tmp_path)
    content = bytearray(setup.read_bytes())
    if damage == 'truncated':
        del content[-40:]
    elif damage == 'changed':
        content[-40] ^= 1
    else:
        content += b'\n'
    setup.write_bytes(bytes(content))
    result = run(shell, setup, environment, '--text')
    assert result.returncode != 0 and b'damaged or incomplete' in result.stderr
    assert not paths['marker'].exists()
    assert list(paths['cache'].iterdir()) == []


def test_extract_recovers_the_identical_archive_and_retains_existing_folders(shell, tmp_path, profile):
    environment, paths = profile
    source, setup, _ = setup_file(tmp_path)
    destination = tmp_path / 'unpacked here'
    result = run(shell, setup, environment, '--extract', shell_path(tmp_path) + '/unpacked here')
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert (destination / source.name).read_bytes() == source.read_bytes()
    assert (destination / 'orion/install.sh').read_bytes() == SYNTHETIC_INSTALLER
    assert not paths['marker'].exists()
    existing = tmp_path / 'existing'; existing.mkdir(); (existing / 'user.txt').write_text('kept')
    result = run(shell, setup, environment, '--extract', shell_path(existing))
    assert result.returncode != 0 and b'retained' in result.stderr
    assert [path.name for path in existing.iterdir()] == ['user.txt']


@pytest.mark.parametrize('answers, installs, failure', [('0 0 0 1', True, False), ('1', False, False), ('0 0 0 0', True, True)])
def test_file_manager_launch_uses_zenity_dialogs(shell, tmp_path, profile, answers, installs, failure):
    environment, paths = profile
    _, setup, _ = setup_file(tmp_path)
    fake(paths, 'zenity')
    environment.update({'DISPLAY': ':0', 'FAKE_ANSWERS': answers, 'FAKE_CHOICES': 'autostart fileactions'})
    if failure:
        environment['SAIPH_TEST_FAIL'] = '1'
    result = run(shell, setup, environment)
    log = calls(paths)
    assert log[0].startswith('zenity --question') and 'no administrator password' in log[0]
    assert paths['marker'].exists() == installs
    if not installs:
        assert result.returncode == 0 and len(log) == 1
        return
    assert log[1].startswith('zenity --list --checklist') and 'Start Saiph when I sign in' in log[1]
    assert (paths['marker'].parent / (paths['marker'].name + '.choices')).read_text().split() == ['on', 'on']
    log = log[:1] + log[2:]
    assert log[1].startswith('zenity --progress')
    saved = (paths['cache'] / 'saiph-setup.log').read_text()
    assert 'synthetic installer output' in saved
    if failure:
        assert result.returncode == 3
        assert log[2].startswith('zenity --error') and 'synthetic failure reason' in log[2]
    else:
        assert result.returncode == 0 and log[2].startswith('zenity --question') and 'Open Saiph' in log[2]
    assert [path.name for path in paths['cache'].iterdir()] == ['saiph-setup.log']


def test_kdialog_is_used_without_zenity(shell, tmp_path, profile):
    environment, paths = profile
    _, setup, _ = setup_file(tmp_path)
    restrict(shell, tmp_path, environment)
    fake(paths, 'kdialog')
    environment.update({'WAYLAND_DISPLAY': 'wayland-0', 'FAKE_ANSWERS': '0 0 0 1', 'FAKE_CHOICES': '"fileactions"'})
    result = run(shell, setup, environment)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    log = calls(paths)
    assert [line.split(' ')[0] for line in log] == ['kdialog'] * 4
    assert '--yesno' in log[0] and '--checklist' in log[1] and '--passivepopup' in log[2] and 'Open Saiph' in log[3]
    assert paths['marker'].exists()
    # Unticked start-up is passed as an explicit choice, not left to the default.
    assert (paths['marker'].parent / (paths['marker'].name + '.choices')).read_text().split() == ['off', 'on']


def test_cancelling_the_options_installs_nothing(shell, tmp_path, profile):
    environment, paths = profile
    _, setup, _ = setup_file(tmp_path)
    fake(paths, 'zenity')
    environment.update({'DISPLAY': ':0', 'FAKE_ANSWERS': '0 1'})
    result = run(shell, setup, environment)
    assert result.returncode == 0 and not paths['marker'].exists()
    assert [line.split(' ')[1] for line in calls(paths)] == ['--question', '--list']


def test_terminal_window_opens_when_no_dialog_tool_exists(shell, tmp_path, profile):
    environment, paths = profile
    _, setup, _ = setup_file(tmp_path)
    restrict(shell, tmp_path, environment)
    fake(paths, 'x-terminal-emulator')
    environment['DISPLAY'] = ':0'
    result = run(shell, setup, environment)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    log = calls(paths)
    assert len(log) == 1 and log[0].startswith('x-terminal-emulator -e sh ') and log[0].rstrip().endswith(' --in-terminal')
    assert b'Press Enter to install' in result.stdout and b'Press Enter to close' in result.stdout
    assert paths['marker'].exists()


@pytest.mark.skipif(sys.platform != 'linux', reason='Real Linux shell/flock install lifecycle')
def test_linux_setup_install_upgrade_and_uninstall_keep_installer_guarantees(shell, tmp_path, profile):
    environment, paths = profile
    home = paths['home']
    integration = {'launcher': home / '.local/bin/orion', 'desktop': tmp_path / 'data/applications/orion.desktop',
                   'autostart': tmp_path / 'config/autostart/orion.desktop',
                   'mime': tmp_path / 'data/mime/packages/orion-enrollment.xml'}

    def release(version):
        files = {'install.sh': INSTALLER.read_bytes(), 'VERSION': (version + '\n').encode(),
                 'LINUX_COMPATIBILITY': b'linux-x86_64 glibc 2.17\n', 'package-manifest.json': b'{}',
                 'app/saiph': b'#!/bin/sh\nexit 0\n', 'app/OrionMini': b'#!/bin/sh\nexit 0\n', 'licenses/notice': b'synthetic notice'}
        files['SHA256SUMS'] = ''.join(hashlib.sha256(content).hexdigest() + '  ' + name + '\n'
                                      for name, content in files.items()).encode()
        folder = tmp_path / version; folder.mkdir()
        return setup_file(folder, version, files)[1]

    result = run(shell, release('1.0.0'), environment, '--text')
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    installed = home / '.local/lib/orion'
    assert (installed / 'current/install.sh').read_bytes() == INSTALLER.read_bytes()
    assert all(path.is_file() for path in integration.values())
    appdata = home / '.local/share/OrionMini'; appdata.mkdir(parents=True)
    retained = {'settings.json': b'{"hub": {"device_id": "synthetic-device"}}', 'hub-device-key.pem': b'synthetic pairing'}
    for name, content in retained.items():
        (appdata / name).write_bytes(content)
    startup = integration['autostart']
    startup.write_bytes(startup.read_bytes().replace(b'enabled=true', b'enabled=false'))
    # The upgrade arrives from a file manager through dialogs.
    fake(paths, 'zenity')
    environment.update({'DISPLAY': ':0', 'FAKE_ANSWERS': '0 0 1'})
    upgrade = release('1.0.1')
    assert run(shell, upgrade, environment).returncode == 0
    assert os.readlink(installed / 'current') == 'releases/1.0.1'
    assert (installed / 'releases/1.0.0/app/saiph').is_file()
    assert b'enabled=false' in startup.read_bytes()
    assert {name: (appdata / name).read_bytes() for name in retained} == retained
    # Opening the same release again is reported as already installed and
    # changes nothing; declining "Open Saiph" launches nothing.
    paths['log'].unlink(); (tmp_path / 'calls.log.count').unlink()
    environment['FAKE_ANSWERS'] = '1'
    before = {path: path.read_bytes() for path in integration.values()}
    result = run(shell, upgrade, environment)
    assert result.returncode == 0
    log = calls(paths)
    assert len(log) == 1 and 'already installed. Nothing changed.' in log[0] and 'Open Saiph' in log[0]
    assert {path: path.read_bytes() for path in integration.values()} == before
    assert os.readlink(installed / 'current') == 'releases/1.0.1'
    result = run(shell, upgrade, environment, '--text')
    assert result.returncode == 0 and b'already installed. Nothing changed.' in result.stdout
    integration['desktop'].write_text('user modified desktop\n# ORION_OWNED=1\n')
    result = subprocess.run([shell, str(installed / 'current/install.sh'), '--uninstall'], env=environment,
                            capture_output=True, timeout=30)
    assert result.returncode == 0
    assert integration['desktop'].read_text() == 'user modified desktop\n# ORION_OWNED=1\n'
    assert not integration['launcher'].exists() and not integration['mime'].exists()
    assert {name: (appdata / name).read_bytes() for name in retained} == retained


@pytest.mark.parametrize('dialog', [None, 'zenity'])
def test_active_same_version_is_reported_as_installed_without_running_installer(shell, tmp_path, profile, dialog):
    environment, paths = profile
    _, setup, _ = setup_file(tmp_path)
    root = tmp_path / 'isolated-root'; (root / 'releases/1.0.0').mkdir(parents=True)
    try:
        (root / 'current').symlink_to('releases/1.0.0', target_is_directory=True)
    except OSError:
        pytest.skip('Host cannot create a real symlink for the install-root fixture')
    environment.update({'ORION_INSTALL_ISOLATED': '1', 'ORION_INSTALL_ROOT': shell_path(root)})
    if dialog:
        fake(paths, dialog)
        environment.update({'DISPLAY': ':0', 'FAKE_ANSWERS': '1'})
        result = run(shell, setup, environment)
        assert len(calls(paths)) == 1 and 'already installed. Nothing changed.' in calls(paths)[0]
    else:
        result = run(shell, setup, environment, '--text')
        assert b'already installed. Nothing changed.' in result.stdout
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert not paths['marker'].exists()
