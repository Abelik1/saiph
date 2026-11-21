# SPDX-License-Identifier: AGPL-3.0-or-later
"""Actual Qt-free service and profile exclusion, using synthetic profiles."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

import pytest

from orion_mini.electron_service import isolated_session, load_configuration
from orion_mini.profile_lock import ProfileLock


def session(tmp_path, **changes):
    profile = tmp_path / 'profile'
    profile.mkdir(exist_ok=True)
    (profile / 'settings.json').write_text(json.dumps({'start_with_windows': False,
        'close_to_tray': False, 'machine': {'name': 'Test desktop'}}), encoding='utf-8')
    file = tmp_path / 'session.json'
    file.write_text(json.dumps({'schema': 1, 'shell': 'electron', 'mode': 'isolated',
        'nonce': 'a' * 48, 'existing_profile': False, 'profile': str(profile), **changes}), encoding='utf-8')
    return file


def test_refuses_live_existing_and_outside_profiles(tmp_path):
    for changes in ({'mode': 'live'}, {'existing_profile': True}, {'shell': 'qt'},
                    {'nonce': ''}, {'profile': str(tmp_path)}, {'fixture': 'owner'}):
        with pytest.raises(ValueError):
            isolated_session(session(tmp_path, **changes))


def test_live_configuration_cannot_seed_phone_data(tmp_path):
    file = tmp_path / 'service.json'
    file.write_text(json.dumps({'schema': 1, 'mode': 'live', 'profile': str(tmp_path / 'owner'),
        'desktop_pid': os.getpid(), 'desktop_executable': sys.executable,
        'binary_address': 'synthetic', 'binary_token': 'a' * 64, 'fixture': 'phone'}))
    with pytest.raises(ValueError):
        load_configuration(file)
    assert not (tmp_path / 'owner').exists()


class Service:
    def __init__(self, file):
        env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
               'ORION_MINI_TEST': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
        self.child = subprocess.Popen([sys.executable, '-m', 'orion_mini.electron_service', '--ui-session', str(file)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.packets = queue.Queue()
        def receive():
            for line in self.child.stdout:
                self.packets.put(json.loads(line))
        threading.Thread(target=receive, daemon=True).start()
        assert self.packets.get(timeout=30)['type'] == 'ready'
        self.counter = 0
        self.native = lambda method, args: ''

    def call(self, method, args=None, *, control=False):
        self.counter += 1
        ident = str(self.counter)
        packet = {'id': ident, 'method': method, 'args': args or {}}
        if control:
            packet['type'] = 'control'
        self.send(packet)
        while True:
            packet = self.packets.get(timeout=30)
            if packet.get('type') == 'native':
                self.send({'native_id': packet['native_id'], 'ok': True,
                           'result': self.native(packet['method'], packet['args'])})
            elif packet.get('id') == ident:
                return packet

    def send(self, packet):
        self.child.stdin.write(json.dumps(packet).encode() + b'\n')
        self.child.stdin.flush()

    def close(self):
        self.child.stdin.close()
        try:
            self.child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.child.kill()
            self.child.wait()
            raise
        assert self.child.returncode == 0, self.child.stderr.read().decode()


def test_service_real_state_persistence_native_callback_and_no_qt(tmp_path):
    file = session(tmp_path, fixture='phone')
    service = Service(file)
    try:
        assert service.call('hello', control=True)['result'] == {'protocol': 1, 'runtime': 'electron', 'qt_loaded': False}
        first = service.call('state')
        assert first['result']['settings']['machine']['name'] == 'Test desktop'
        assert service.call('settings.save', {'machine': {'name': 'Test Ω desktop'}, 'close_to_tray': True, 'start_with_windows': True})['ok']
        assert json.loads((tmp_path / 'profile/settings.json').read_text(encoding='utf-8'))['machine']['name'] == 'Test Ω desktop'
        second = service.call('state')
        assert second['revision'] != first['revision']
        assert service.call('state', {'revision': second['revision']})['unchanged']
        selected = str(tmp_path / 'profile/Synthetic original.jpg')
        calls = []
        def native(method, args):
            calls.append(method)
            return selected
        service.native = native
        assert service.call('dialog.file')['result'] == {'path': selected}
        assert calls == ['dialog.open']
        denied = service.call('hosted.approve', {'confirmed': True})
        assert not denied['ok'] and 'isolated' in denied['error']
        assert service.call('hello', control=True)['result']['qt_loaded'] is False
    finally:
        service.close()
    with ProfileLock(tmp_path / 'profile/app.lock'):
        pass
    restarted = Service(file)
    try:
        assert restarted.call('state')['result']['settings']['machine']['name'] == 'Test Ω desktop'
    finally:
        restarted.close()


def test_cross_shell_profile_lock_both_directions_and_stale_age(tmp_path, qapp):
    from PySide6.QtCore import QLockFile
    path = tmp_path / 'app.lock'
    qt = QLockFile(str(path))
    assert qt.tryLock(100)
    try:
        assert not ProfileLock(path).acquire()
    finally:
        qt.unlock()
    with ProfileLock(path):
        qt.setStaleLockTime(1)
        import time
        time.sleep(.02)
        assert not qt.tryLock(10), 'Qt must not remove an aged live native lock'
        assert not ProfileLock(path).acquire()
    assert qt.tryLock(100)
    qt.unlock()


def test_eof_during_native_dialog_releases_pending_callback_and_profile(tmp_path):
    file = session(tmp_path)
    service = Service(file)
    service.send({'id': 'waiting', 'method': 'dialog.file', 'args': {}})
    while service.packets.get(timeout=20).get('type') != 'native':
        pass
    service.close()
    with ProfileLock(tmp_path / 'profile/app.lock'):
        pass


def test_dead_process_lock_recovered_and_unknown_host_preserved(tmp_path):
    import psutil
    import socket
    path = tmp_path / 'app.lock'
    pid = max(psutil.pids()) + 100000
    path.write_text(f'{pid}\nSynthetic\n{socket.gethostname()}\n\n\n')
    with ProfileLock(path):
        pass
    path.write_text(f'{pid}\nSynthetic\nother-computer.invalid\n\n\n')
    assert not ProfileLock(path).acquire()
    assert path.exists()


def test_a_native_crash_leaves_its_call_stack_in_the_profile(tmp_path):
    from orion_mini import electron_service
    script = """
import faulthandler, sys
from orion_mini.electron_service import record_crashes
trace = record_crashes(sys.argv[1])
def synthetic_crash_site():
    faulthandler._sigsegv()
synthetic_crash_site()
"""
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, timeout=60)
    assert result.returncode != 0
    trace = (tmp_path / electron_service.CRASH_TRACE).read_text(encoding="utf-8")
    assert "Service started" in trace and "synthetic_crash_site" in trace


def test_the_service_keeps_com_open_for_notifications(monkeypatch):
    """Losing this hold made the second Windows notification crash the service."""
    import ctypes
    from types import SimpleNamespace
    from orion_mini import electron_service
    calls = []
    ole32 = SimpleNamespace(CoIncrementMTAUsage=lambda cookie: calls.append(cookie) or 0)
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(ole32=ole32), raising=False)
    monkeypatch.setattr(sys, 'platform', 'win32')
    electron_service.hold_com()
    assert len(calls) == 1
    monkeypatch.setattr(sys, 'platform', 'linux')
    electron_service.hold_com()
    assert len(calls) == 1
    assert 'hold_com()' in Path(electron_service.__file__).read_text(encoding='utf-8').split('def main(')[1]


def test_an_oversized_crash_trace_starts_again(tmp_path):
    from orion_mini import electron_service
    path = tmp_path / electron_service.CRASH_TRACE
    path.write_bytes(b"x" * (electron_service.MAX_CRASH_TRACE + 1))
    trace = electron_service.record_crashes(tmp_path)
    try:
        assert path.stat().st_size < 200
    finally:
        import faulthandler
        faulthandler.disable()
        trace.close()
