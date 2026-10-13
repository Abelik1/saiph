# SPDX-License-Identifier: AGPL-3.0-or-later
"""Actual shell preflight checks; native Linux lifecycle remains Linux-only."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / 'scripts/packaging/install-linux.sh'


class PrivateEnvironment(dict):
    def __repr__(self):
        return '<private process environment>'


@pytest.fixture
def shell():
    if sys.platform == 'win32':
        executable = Path('C:/Program Files/Git/bin/bash.exe')
        if not executable.is_file():
            pytest.skip('Git Bash is unavailable for shell-only preflight checks')
        return str(executable)
    return '/bin/sh'


def shell_path(path):
    value = str(path.resolve()).replace('\\', '/')
    if sys.platform == 'win32':
        return '/' + value[0].lower() + value[2:]
    return value


@pytest.fixture
def profile(tmp_path):
    home = tmp_path / 'home with spaces'; home.mkdir()
    config = tmp_path / 'config'; config.mkdir()
    data = tmp_path / 'data'; data.mkdir()
    environment = PrivateEnvironment({**os.environ, 'HOME': shell_path(home), 'XDG_CONFIG_HOME': shell_path(config),
                                     'XDG_DATA_HOME': shell_path(data), 'ORION_INSTALL_ISOLATED': '0'})
    environment.pop('ORION_INSTALL_ROOT', None)
    paths = {'launcher': home / '.local/bin/orion', 'desktop': data / 'applications/orion.desktop',
             'autostart': config / 'autostart/orion.desktop', 'mime': data / 'mime/packages/orion-enrollment.xml'}
    return home, paths, environment


def run_preflight(shell, tmp_path, environment, capture=None):
    # Execute the production ownership/preflight block verbatim. Git Bash has
    # no flock; this proves shell checks, not actual Linux locking or install.
    source = SCRIPT.read_text().split('# One inode and one lock')[0]
    harness = tmp_path / 'preflight.sh'
    exported = ''
    if capture is not None:
        capture.mkdir()
        for name in ('launcher', 'desktop', 'autostart', 'mime'):
            exported += f'cp "$integration_work/{name}" "{shell_path(capture / name)}"\n'
    harness.write_text(source + '\n' + exported + 'echo PREFLIGHT_ACCEPTED\n', newline='\n')
    return subprocess.run([shell, shell_path(harness)], env=environment, capture_output=True, timeout=45)


@pytest.mark.parametrize('name', ['launcher', 'desktop', 'autostart', 'mime'])
def test_unrelated_integration_refuses_before_install_mutation(shell, tmp_path, profile, name):
    home, paths, environment = profile
    target = paths[name]; target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b'user-owned-content\n# ORION_OWNED=1\n')
    before = target.read_bytes()
    result = run_preflight(shell, tmp_path, environment)
    assert result.returncode != 0 and b'unrelated integration retained' in result.stderr
    assert target.read_bytes() == before
    assert not (home / '.local/lib/orion').exists()
    assert not (home / '.local/lib/orion.install.lock').exists()


def test_empty_profile_preflight_honors_xdg_and_creates_no_integration(shell, tmp_path, profile):
    home, paths, environment = profile
    result = run_preflight(shell, tmp_path, environment)
    assert result.returncode == 0 and b'PREFLIGHT_ACCEPTED' in result.stdout
    assert all(not path.exists() for path in paths.values())
    assert not (home / '.local/lib/orion').exists()


def test_exact_owned_integrations_allow_upgrade_and_preserve_disabled_startup(shell, tmp_path, profile):
    _, paths, environment = profile
    capture = tmp_path / 'generated'
    assert run_preflight(shell, tmp_path, environment, capture).returncode == 0
    for name, target in paths.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(capture / name, target)
    startup = paths['autostart']
    startup.write_bytes(startup.read_bytes().replace(b'enabled=true', b'enabled=false'))
    before = {name: target.read_bytes() for name, target in paths.items()}
    assert run_preflight(shell, tmp_path, environment).returncode == 0
    assert {name: target.read_bytes() for name, target in paths.items()} == before


def test_symlink_integration_is_retained_even_when_content_looks_owned(shell, tmp_path, profile):
    home, paths, environment = profile
    target = paths['launcher']; target.parent.mkdir(parents=True)
    foreign = tmp_path / 'foreign'; foreign.write_text('# ORION_OWNED=1\n')
    try:
        target.symlink_to(foreign)
    except OSError:
        pytest.skip('Host cannot create a real symlink for shell fixture')
    result = run_preflight(shell, tmp_path, environment)
    assert result.returncode != 0 and b'symlink retained' in result.stderr
    assert target.is_symlink() and foreign.read_text() == '# ORION_OWNED=1\n'
    assert not (home / '.local/lib/orion').exists()


@pytest.mark.skipif(sys.platform != 'linux', reason='Real Linux shell/flock install lifecycle')
@pytest.mark.parametrize('receipt, message', [
    ('linux-x86_64 glibc 999.0\n', b'needs glibc 999.0'),
    ('linux-x86_64 glibc not-a-version\n', b'Invalid package glibc requirement'),
])
def test_linux_incompatible_package_refuses_before_install_mutation(tmp_path, shell, profile, receipt, message):
    home, paths, environment = profile
    package = tmp_path / 'incompatible-package'; package.mkdir()
    shutil.copyfile(SCRIPT, package / 'install.sh')
    (package / 'LINUX_COMPATIBILITY').write_text(receipt)
    result = subprocess.run([shell, str(package / 'install.sh')], env=environment,
                            capture_output=True, timeout=15)
    assert result.returncode != 0 and message in result.stderr
    assert not (home / '.local/lib/orion').exists()
    assert not (home / '.local/lib/orion.install.lock').exists()
    assert all(not path.exists() for path in paths.values())


@pytest.mark.skipif(sys.platform != 'linux', reason='Real Linux shell/flock install lifecycle')
@pytest.mark.parametrize('startup_mode', ['enabled', 'disabled', 'removed'])
def test_linux_upgrade_preserves_optout_uninstall_preserves_modified_integration(tmp_path, shell, profile, startup_mode):
    home, paths, environment = profile
    package = tmp_path / 'package'; package.mkdir()
    shutil.copyfile(SCRIPT, package / 'install.sh')
    (package / 'app').mkdir(); (package / 'app/OrionMini').write_bytes(b'#!/bin/sh\nexit 0\n')
    (package / 'licenses').mkdir(); (package / 'licenses/notice').write_text('synthetic notice')
    (package / 'package-manifest.json').write_text('{}')
    (package / 'LINUX_COMPATIBILITY').write_text('linux-x86_64 glibc 2.17\n')
    def install(version, *arguments):
        (package / 'VERSION').write_text(version + '\n')
        files = ['VERSION', 'LINUX_COMPATIBILITY', 'package-manifest.json', 'app/OrionMini', 'licenses/notice', 'install.sh']
        (package / 'SHA256SUMS').write_text(''.join(hashlib.sha256((package / name).read_bytes()).hexdigest() + '  ' + name + '\n' for name in files))
        return subprocess.run([shell, str(package / 'install.sh'), *arguments], env=environment, capture_output=True, timeout=15)
    assert install('1.0.0').returncode == 0
    retained_installer = home / '.local/lib/orion/current/install.sh'
    assert retained_installer.is_file() and os.access(retained_installer, os.X_OK)
    for path in paths.values(): assert path.is_file()
    # Simulate the exact launch integration of the earlier Orion release.
    for name in ('desktop', 'autostart', 'mime'):
        paths[name].write_bytes(paths[name].read_bytes().replace(b'Name=Saiph', b'Name=Orion').replace(b'Saiph device enrollment', b'Orion device enrollment'))
    appdata = home / '.local/share/OrionMini'
    appdata.mkdir(parents=True)
    retained = {
        'orion-mini.sqlite3': b'synthetic existing database bytes',
        'settings.json': b'{"start_with_windows": false, "hub": {"device_id": "synthetic-device"}}',
        'hub-device-key.pem': b'synthetic pairing bytes',
    }
    for name, content in retained.items():
        (appdata / name).write_bytes(content)
    if startup_mode == 'removed':
        paths['autostart'].unlink()
    elif startup_mode == 'disabled':
        paths['autostart'].write_bytes(paths['autostart'].read_bytes().replace(b'enabled=true', b'enabled=false'))
    assert install('1.0.1').returncode == 0
    assert b'Name=Saiph\n' in paths['desktop'].read_bytes()
    if startup_mode == 'removed':
        assert not paths['autostart'].exists()
    else:
        startup = paths['autostart'].read_bytes()
        assert b'Name=Saiph\n' in startup
        assert (b'enabled=false' if startup_mode == 'disabled' else b'enabled=true') in startup
    assert {name: (appdata / name).read_bytes() for name in retained} == retained
    paths['desktop'].write_text('user modified desktop\n# ORION_OWNED=1\n')
    # Uninstall still works after the extracted download is gone.
    shutil.rmtree(package)
    result = subprocess.run([shell, str(retained_installer), '--uninstall'], env=environment,
                            capture_output=True, timeout=15)
    assert result.returncode == 0
    assert paths['desktop'].read_text() == 'user modified desktop\n# ORION_OWNED=1\n'
    assert not paths['launcher'].exists() and not paths['mime'].exists()
    assert (home / '.local/lib/orion/releases/1.0.0/app/OrionMini').is_file()


@pytest.mark.parametrize("disabled", [False, True])
def test_orion_brand_integrations_remain_owned_without_mutating_pairing(shell, tmp_path, profile, disabled):
    home, paths, environment = profile
    capture = tmp_path / "generated"
    assert run_preflight(shell, tmp_path, environment, capture).returncode == 0
    assert b"Name=Saiph\n" in (capture / "desktop").read_bytes()
    for name, target in paths.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        old = (capture / name).read_bytes().replace(b"Name=Saiph", b"Name=Orion").replace(b"Saiph device enrollment", b"Orion device enrollment")
        if disabled and name == "autostart":
            old = old.replace(b"enabled=true", b"enabled=false")
        target.write_bytes(old)
    appdata = home / "OrionMini"
    appdata.mkdir()
    (appdata / "settings.json").write_text('{"start_with_windows": false, "hub": {"device_id": "synthetic-device"}}')
    (appdata / "hub-device-key.pem").write_bytes(b"synthetic pairing bytes")
    before = {path: path.read_bytes() for path in [*paths.values(), *appdata.iterdir()]}
    result = run_preflight(shell, tmp_path, environment)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.skipif(sys.platform != 'linux', reason='Real Linux shell/flock install lifecycle')
def test_linux_same_version_reinstall_explains_nothing_changed(tmp_path, shell, profile):
    home, paths, environment = profile
    package = tmp_path / 'package'; package.mkdir()
    shutil.copyfile(SCRIPT, package / 'install.sh')
    (package / 'app').mkdir(); (package / 'app/OrionMini').write_bytes(b'#!/bin/sh\nexit 0\n')
    (package / 'licenses').mkdir(); (package / 'licenses/notice').write_text('synthetic notice')
    (package / 'package-manifest.json').write_text('{}')
    (package / 'LINUX_COMPATIBILITY').write_text('linux-x86_64 glibc 2.17\n')
    (package / 'VERSION').write_text('1.0.0\n')
    files = ['VERSION', 'LINUX_COMPATIBILITY', 'package-manifest.json', 'app/OrionMini', 'licenses/notice', 'install.sh']
    (package / 'SHA256SUMS').write_text(''.join(hashlib.sha256((package / name).read_bytes()).hexdigest() + '  ' + name + '\n' for name in files))

    def install(*arguments):
        return subprocess.run([shell, str(package / 'install.sh'), *arguments], env=environment, capture_output=True, timeout=15)

    assert install().returncode == 0
    root = home / '.local/lib/orion'
    before = {path: path.read_bytes() for path in paths.values()}
    result = install()
    assert result.returncode == 1
    assert b'Saiph 1.0.0 is already installed. Nothing changed.' in result.stderr
    assert {path: path.read_bytes() for path in paths.values()} == before
    assert os.readlink(root / 'current') == 'releases/1.0.0'
    assert sorted(path.name for path in (root / 'releases').iterdir()) == ['1.0.0']
    assert install('--uninstall').returncode == 0
    result = install()
    assert result.returncode == 1 and b'was installed here before' in result.stderr
    assert not (root / 'current').exists() and not paths['launcher'].exists()


@pytest.mark.skipif(sys.platform != 'linux', reason='Real Linux shell/flock install lifecycle')
def test_linux_file_actions_follow_choice_and_never_return_unasked(tmp_path, shell, profile):
    # Physical acceptance: a beta.5 -> beta.6 upgrade without the setup dialog
    # (terminal --text, and the in-app updater) re-added declined Send to phone actions.
    home, paths, environment = profile
    data = Path(environment['XDG_DATA_HOME'])
    actions = [data / 'nautilus/scripts/Send to phone (Saiph)', data / 'kio/servicemenus/saiph-send-to-phone.desktop',
               data / 'kservices5/ServiceMenus/saiph-send-to-phone.desktop']
    foreign = data / 'nautilus/scripts/Synthetic own script'
    package = tmp_path / 'package'; package.mkdir()
    shutil.copyfile(SCRIPT, package / 'install.sh')
    (package / 'app').mkdir(); (package / 'app/OrionMini').write_bytes(b'#!/bin/sh\nexit 0\n')
    (package / 'licenses').mkdir(); (package / 'licenses/notice').write_text('synthetic notice')
    (package / 'package-manifest.json').write_text('{}')
    (package / 'LINUX_COMPATIBILITY').write_text('linux-x86_64 glibc 2.17\n')
    def install(version, choice=None):
        (package / 'VERSION').write_text(version + '\n')
        files = ['VERSION', 'LINUX_COMPATIBILITY', 'package-manifest.json', 'app/OrionMini', 'licenses/notice', 'install.sh']
        (package / 'SHA256SUMS').write_text(''.join(hashlib.sha256((package / name).read_bytes()).hexdigest() + '  ' + name + '\n' for name in files))
        env = PrivateEnvironment({key: value for key, value in environment.items() if key != 'SAIPH_FILE_ACTIONS'})
        if choice:
            env['SAIPH_FILE_ACTIONS'] = choice
        assert subprocess.run([shell, str(package / 'install.sh')], env=env, capture_output=True, timeout=15).returncode == 0
        return [path.exists() for path in actions]

    assert install('1.0.0') == [True, True, True]  # first install: on by default
    # Kubuntu 24.04's KF5 Dolphin needs the old location and service type; KF6 ignores both.
    assert b'ServiceTypes=KonqPopupMenu/Plugin\n' in actions[2].read_bytes()
    assert actions[2].read_bytes().replace(b'ServiceTypes=KonqPopupMenu/Plugin\n', b'') == actions[1].read_bytes()
    owned = [path.read_bytes() for path in actions]
    foreign.write_text('#!/bin/sh\necho synthetic\n')
    assert install('1.0.1', 'off') == [False, False, False]  # declined: only Saiph's own actions go
    assert foreign.read_text() == '#!/bin/sh\necho synthetic\n'
    assert install('1.0.2') == [False, False, False]  # upgrade without a choice keeps them off
    assert install('1.0.3', 'on') == [True, True, True]
    assert [path.read_bytes() for path in actions] == owned
    actions[0].unlink()  # removed by hand in the file manager
    actions[2].unlink()  # as installed by a release that wrote only the KF6 menu
    assert install('1.0.4') == [False, True, True]  # unset keeps a removed action off, completes Dolphin's pair
    assert foreign.exists()
    retained = home / '.local/lib/orion/current/install.sh'
    assert subprocess.run([shell, str(retained), '--uninstall'], env=environment, capture_output=True, timeout=15).returncode == 0
    assert [path.exists() for path in actions] == [False, False, False] and foreign.exists()
