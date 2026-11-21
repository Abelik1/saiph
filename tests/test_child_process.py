# SPDX-License-Identifier: AGPL-3.0-or-later
"""Child programs get the user's environment, never the frozen bundle's libraries."""
import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from orion_mini import child_process

PACKAGE = Path(__file__).resolve().parents[1] / 'src/orion_mini'
linux_only = pytest.mark.skipif(sys.platform == 'win32', reason='LD_LIBRARY_PATH is a Linux concern')


def frozen(monkeypatch, bundled='/opt/saiph/_internal', original=None):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setenv('LD_LIBRARY_PATH', bundled)
    monkeypatch.setenv('_PYI_ARCHIVE_FILE', '/opt/saiph/saiph')
    if original is None:
        monkeypatch.delenv('LD_LIBRARY_PATH_ORIG', raising=False)
    else:
        monkeypatch.setenv('LD_LIBRARY_PATH_ORIG', original)


@linux_only
def test_frozen_build_drops_its_library_path_and_bootloader_variables(monkeypatch):
    frozen(monkeypatch)
    environment = child_process.system_environment()
    assert 'LD_LIBRARY_PATH' not in environment and '_PYI_ARCHIVE_FILE' not in environment
    assert environment['PATH'] == os.environ['PATH']


@linux_only
def test_frozen_build_restores_the_users_library_path_once(monkeypatch):
    frozen(monkeypatch, original='/home/user/libs')
    once = child_process.system_environment()
    assert once['LD_LIBRARY_PATH'] == '/home/user/libs' and 'LD_LIBRARY_PATH_ORIG' not in once
    assert child_process.system_environment(once) == once  # wrappers re-apply it to caller-built environments


@linux_only
def test_caller_built_environment_from_the_frozen_process_is_cleaned(monkeypatch):
    frozen(monkeypatch)
    environment = child_process.system_environment({**os.environ, 'ADB': '/sdk/adb'})
    assert environment['ADB'] == '/sdk/adb' and 'LD_LIBRARY_PATH' not in environment


@linux_only
def test_source_checkout_keeps_a_developer_library_path_unless_asked(monkeypatch):
    monkeypatch.delattr(sys, 'frozen', raising=False)
    monkeypatch.delenv('LD_LIBRARY_PATH_ORIG', raising=False)
    monkeypatch.setenv('LD_LIBRARY_PATH', '/home/dev/libs')
    assert child_process.system_environment()['LD_LIBRARY_PATH'] == '/home/dev/libs'
    assert 'LD_LIBRARY_PATH' not in child_process.system_environment(drop_library_path=True)


def test_windows_keeps_library_path_but_drops_bootloader_variables(monkeypatch):
    monkeypatch.setattr(child_process.sys, 'platform', 'win32')
    environment = child_process.system_environment({'LD_LIBRARY_PATH': '/x', '_PYI_APPLICATION_HOME_DIR': 'C:/app', '_MEIPASS2': 'C:/tmp'})
    assert environment == {'LD_LIBRARY_PATH': '/x'}


@linux_only
def test_run_and_popen_always_pass_a_cleaned_environment(monkeypatch):
    frozen(monkeypatch, original='/home/user/libs')
    seen = []
    monkeypatch.setattr(subprocess, 'run', lambda args, **options: seen.append(options['env']))
    monkeypatch.setattr(subprocess, 'Popen', lambda args, **options: seen.append(options['env']))
    child_process.run(['true'])
    child_process.popen(['true'], env={**os.environ, 'EXTRA': '1'})
    assert [env['LD_LIBRARY_PATH'] for env in seen] == ['/home/user/libs', '/home/user/libs']
    assert seen[1]['EXTRA'] == '1'


class FakeProcess:
    def __init__(self, outcome):
        self.outcome = outcome

    def wait(self, timeout=None):
        if self.outcome == 'running' and timeout is not None:
            raise subprocess.TimeoutExpired('opener', timeout)
        return 0 if self.outcome == 'running' else self.outcome


def opener(monkeypatch, outcomes, installed=('xdg-open', 'gio')):
    monkeypatch.setattr(child_process.sys, 'platform', 'linux')
    calls = []

    def start(argv, **options):
        calls.append(argv)
        outcome = outcomes[len(calls) - 1]
        if outcome == 'missing':
            raise FileNotFoundError(argv[0])
        assert options['start_new_session'] and options['stdin'] is subprocess.DEVNULL
        return FakeProcess(outcome)

    which = lambda name: f'/usr/bin/{name}' if name in installed else None
    return calls, lambda url: child_process.open_url(url, start=start, which=which, wait=0.01)


@pytest.mark.parametrize('outcome', [0, 'running'])
def test_open_url_reports_success_when_xdg_open_succeeds_or_keeps_running(monkeypatch, outcome):
    calls, open_url = opener(monkeypatch, [outcome])
    assert open_url('https://account.example.invalid/authorize?state=s') is True
    assert calls == [['/usr/bin/xdg-open', 'https://account.example.invalid/authorize?state=s']]


def test_open_url_falls_back_to_gio_and_reports_failure(monkeypatch):
    calls, open_url = opener(monkeypatch, [3, 0])
    assert open_url('https://example.invalid/') is True
    assert calls[1] == ['/usr/bin/gio', 'open', 'https://example.invalid/']
    calls, open_url = opener(monkeypatch, [4, 'missing'])
    assert open_url('https://example.invalid/') is False
    calls, open_url = opener(monkeypatch, [], installed=())
    assert open_url('https://example.invalid/') is False and calls == []


def test_open_url_never_passes_an_option_shaped_target(monkeypatch):
    calls, open_url = opener(monkeypatch, [0])
    assert open_url('--manual') is False and calls == []


def test_open_url_uses_the_os_handler_on_windows(monkeypatch):
    monkeypatch.setattr(child_process.sys, 'platform', 'win32')
    opened = []
    monkeypatch.setattr(child_process.webbrowser, 'open', lambda url: opened.append(url) or True)
    assert child_process.open_url('ms-settings:signinoptions') is True and opened == ['ms-settings:signinoptions']


@linux_only
def test_a_real_child_sees_the_users_environment_not_the_bundles(monkeypatch, tmp_path):
    """A synthetic xdg-open records what a browser launcher would inherit."""
    record = tmp_path / 'record'
    launcher = tmp_path / 'xdg-open'
    launcher.write_text('#!/bin/sh\nprintf "%s\\n%s\\n%s\\n" "${LD_LIBRARY_PATH-unset}" "${_PYI_ARCHIVE_FILE-unset}" "$1" > "$RECORD"\n')
    launcher.chmod(0o755)
    frozen(monkeypatch, bundled=str(tmp_path / 'bundle-libs'))
    monkeypatch.setenv('RECORD', str(record))
    monkeypatch.setattr(child_process.sys, 'platform', 'linux')
    assert child_process.open_url('https://example.invalid/sign-in', which=lambda name: str(launcher) if name == 'xdg-open' else None, wait=5)
    assert record.read_text().splitlines() == ['unset', 'unset', 'https://example.invalid/sign-in']


# Everything that starts another program. Only child_process.py may use these directly.
LAUNCHERS = {
    'subprocess': {'run', 'Popen', 'call', 'check_call', 'check_output', 'getoutput', 'getstatusoutput'},
    'os': {'system', 'popen', 'startfile', 'posix_spawn', 'posix_spawnp', 'spawnl', 'spawnle', 'spawnlp', 'spawnlpe',
           'spawnv', 'spawnve', 'spawnvp', 'spawnvpe', 'execl', 'execle', 'execlp', 'execlpe', 'execv', 'execve', 'execvp', 'execvpe'},
    'asyncio': {'create_subprocess_exec', 'create_subprocess_shell'},
    'pty': {'spawn'},
}
LAUNCHER_MODULES = {'webbrowser'}
LAUNCHER_NAMES = {'QProcess', 'QDesktopServices'}


def launches(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.attr in LAUNCHERS.get(node.value.id, ()) or node.value.id in LAUNCHER_MODULES:
                yield node.lineno, f'{node.value.id}.{node.attr}'
        elif isinstance(node, ast.ImportFrom) and node.module:
            module = node.module.split('.')[0]
            for alias in node.names:
                if alias.name in LAUNCHERS.get(module, ()) or module in LAUNCHER_MODULES or alias.name in LAUNCHER_NAMES:
                    yield node.lineno, f'from {node.module} import {alias.name}'
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in LAUNCHER_MODULES:
                    yield node.lineno, f'import {alias.name}'
        elif isinstance(node, ast.Name) and node.id in LAUNCHER_NAMES:
            yield node.lineno, node.id


def test_only_child_process_starts_other_programs():
    found = [f'{path.name}:{line}: {what}' for path in sorted(PACKAGE.glob('*.py')) if path.name != 'child_process.py'
             for line, what in launches(ast.parse(path.read_text(encoding='utf-8')))]
    assert not found, 'Start programs through orion_mini.child_process so a frozen Linux build ' \
                      "does not hand them its bundled libraries:\n" + '\n'.join(found)


def test_guard_recognises_each_launch_form():
    sample = ('import subprocess, os, webbrowser\nfrom subprocess import Popen\nfrom PySide6.QtGui import QDesktopServices\n'
              'subprocess.run(["x"])\nos.execv("x", [])\nwebbrowser.open("u")\nQProcess.startDetached("x")\n')
    kinds = {what for _, what in launches(ast.parse(sample))}
    assert {'subprocess.run', 'os.execv', 'webbrowser.open', 'import webbrowser', 'from subprocess import Popen',
            'from PySide6.QtGui import QDesktopServices', 'QProcess'} <= kinds
