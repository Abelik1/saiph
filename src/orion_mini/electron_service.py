# SPDX-License-Identifier: AGPL-3.0-or-later
"""Private service entrypoint for the Electron desktop, with no Qt runtime."""
from __future__ import annotations
import argparse
from concurrent.futures import Future, ThreadPoolExecutor
import faulthandler
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from uuid import uuid4

PROTOCOL = 1
MAX_REQUEST = 64 * 1024
MAX_RESPONSE = 32 * 1024 * 1024
CRASH_TRACE = 'crash-trace.log'
MAX_CRASH_TRACE = 1024 * 1024


def isolated_session(file: Path):
    file = file.resolve(strict=True)
    session = json.loads(file.read_text(encoding='utf-8'))
    profile = Path(session['profile']).resolve(strict=True)
    if (session.get('schema') != 1 or session.get('shell') != 'electron'
            or session.get('mode') != 'isolated' or session.get('existing_profile') is not False
            or not isinstance(session.get('nonce'), str) or not re.fullmatch(r'[a-f0-9]{48}', session['nonce'])
            or profile != file.parent / 'profile' or not profile.is_dir()
            or session.get('fixture', 'empty') not in ('empty', 'phone')):
        raise ValueError('Choose a fresh isolated Electron session.')
    return session, profile


def load_configuration(file):
    file = file.resolve(strict=True)
    value = json.loads(file.read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or value.get('schema') != 1 or value.get('mode') not in ('isolated', 'live')
            or not isinstance(value.get('profile'), str) or not Path(value['profile']).is_absolute()
            or not isinstance(value.get('desktop_pid'), int) or value['desktop_pid'] <= 0
            or not isinstance(value.get('desktop_executable'), str) or not Path(value['desktop_executable']).is_file()
            or not isinstance(value.get('binary_address'), str)
            or not isinstance(value.get('binary_token'), str) or not re.fullmatch(r'[a-f0-9]{64}', value['binary_token'])
            or value.get('fixture', 'empty') not in ('empty', 'phone')
            or value.get('mode') == 'live' and value.get('fixture', 'empty') != 'empty'):
        raise ValueError('Invalid desktop service configuration.')
    profile = Path(value['profile']).resolve()
    profile.mkdir(mode=0o700, parents=True, exist_ok=True)
    return value, profile


def record_crashes(profile):
    """Keep a native crash's Python call stack; it holds file and function names, never content."""
    path = Path(profile) / CRASH_TRACE
    if path.exists() and path.stat().st_size > MAX_CRASH_TRACE:
        path.unlink()
    trace = open(path, 'a', encoding='utf-8', buffering=1)
    trace.write(f'--- Service started {time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}\n')
    faulthandler.enable(file=trace, all_threads=True)
    return trace  # The handler writes to this file until the process ends: keep it open.


def hold_com():
    """Keep Windows COM's shared apartment open for the life of the service.

    Without this, a thread that finishes with COM can shut the apartment and unload
    the notification library under the live notifier, so the next notification crashes
    the service. Qt used to keep it open before the desktop moved to Electron.
    """
    if sys.platform == 'win32':
        import ctypes
        cookie = ctypes.c_void_p()
        ctypes.windll.ole32.CoIncrementMTAUsage(ctypes.byref(cookie))


def write_packet(output, packet):
    data = json.dumps(packet, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(data) > MAX_RESPONSE:
        raise ValueError('Desktop service response is too large.')
    output.write(data + b'\n')
    output.flush()


class ControlConnection:
    def __init__(self, source, output):
        self.source, self.output = source, output
        self.write_lock = threading.RLock()
        self.pending_lock = threading.RLock()
        self.pending = {}
        self.closed = False
        self.runtime = None
        self.dispatcher = ThreadPoolExecutor(max_workers=1, thread_name_prefix='saiph-dispatch')
        self.controls = ThreadPoolExecutor(max_workers=2, thread_name_prefix='saiph-native-control')
        self.slots = threading.BoundedSemaphore(32)

    def emit(self, packet):
        with self.write_lock:
            if not self.closed:
                try:
                    write_packet(self.output, packet)
                except (OSError, ValueError):
                    self.closed = True

    def native(self, method, args):
        if self.closed:
            raise ValueError('The desktop window has closed.')
        ident, future = uuid4().hex, Future()
        with self.pending_lock:
            self.pending[ident] = future
        try:
            self.emit({'type': 'native', 'native_id': ident, 'method': method, 'args': args})
            return future.result(timeout=300)
        finally:
            with self.pending_lock:
                self.pending.pop(ident, None)

    def dispatch(self, packet):
        ident = packet.get('id', 'invalid')
        try:
            if (not isinstance(ident, str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,64}', ident)
                    or not isinstance(packet.get('args'), dict) or not isinstance(packet.get('method'), str)):
                raise ValueError('Invalid desktop request.')
            method, args = packet['method'], packet['args']
            if packet.get('type') == 'control':
                result = self.control(method, args)
                self.emit({'id': ident, 'ok': True, 'result': result})
            else:
                if set(packet) != {'id', 'method', 'args'}:
                    raise ValueError('Invalid desktop request.')
                if self.runtime.isolated and method not in {'state', 'settings.save', 'usage.screen', 'usage.consent',
                        'insights.week', 'insights.enable', 'insights.clear', 'app.update.progress', 'camera.status',
                        'camera.frame', 'screen.frame', 'screen.invite', 'screen.stop', 'help.open', 'setup.open',
                        'dialog.file', 'dialog.directory', 'phone.photo.view', 'phone.photo.copy', 'phone.photo.drag'} and not (
                            method == 'screen.input' and self.runtime.workspace.screen.session.session == 'test-session'):
                    raise ValueError('Live device/account actions are disabled in isolated sessions.')
                self.runtime.request(ident, method, json.dumps(args))
        except Exception as error:
            self.emit({'id': ident if isinstance(ident, str) else 'invalid', 'ok': False, 'error': str(error)})
        finally:
            self.slots.release()

    def control(self, method, args):
        runtime = self.runtime
        if method == 'visibility':
            runtime.visible = args.get('visible') is True
            if runtime.visible:
                runtime.announce()
            return {'ok': True}
        if method == 'clipboard.authorize':
            return {'allowed': runtime.authorize_clipboard(args.get('token'))}
        if method == 'tray.entries':
            from .tray_menu import phone_entries
            return phone_entries(runtime.workspace.state())
        if method == 'screen.geometry':
            from .storage import write_json
            value = args.get('bounds')
            if (not isinstance(value, dict) or set(value) != {'x', 'y', 'width', 'height'}
                    or any(type(v) is not int for v in value.values())
                    or not 200 <= value['width'] <= 20000 or not 200 <= value['height'] <= 20000
                    or any(abs(value[k]) > 100000 for k in ('x', 'y'))):
                raise ValueError('Invalid phone window geometry.')
            write_json(runtime.workspace.root / 'phone-screen-window.json', value)
            return {'ok': True}
        if method == 'screen.geometry.read':
            from .storage import read_json
            return read_json(runtime.workspace.root / 'phone-screen-window.json')
        if method == 'screen.status':
            return runtime.workspace.screen.session.status()
        if method == 'test.frame' and runtime.isolated:
            from io import BytesIO
            from PIL import Image
            from .screen_session import input_message
            session = runtime.workspace.screen.session
            frame = BytesIO()
            Image.new('RGB', (360, 640), '#204d67').save(frame, 'JPEG')
            session.state, session.frame, session.serial, session.session = 'live', frame.getvalue(), session.serial + 1, 'test-session'
            session.input_enabled = True
            session.dimensions = {'width': 360, 'height': 640}
            session.input = lambda event: input_message(event)
            runtime.screen_state(session.status())
            runtime.preview('screen')
            return {'ok': True}
        if method == 'open.phone':
            runtime.open_phone_page()
            return {'ok': True}
        if method == 'launch.args':
            from .send_files import arguments as split_files
            arguments = args.get('args')
            if not isinstance(arguments, list) or len(arguments) > 110 or any(not isinstance(v, str) or len(v) > 32768 for v in arguments):
                raise ValueError('Invalid desktop launch arguments.')
            rest, files = split_files(['saiph', *arguments])
            if files:
                runtime.confirm_send_files(files)
            elif '--enrollment' in rest:
                index = rest.index('--enrollment')
                if index + 1 >= len(rest):
                    raise ValueError('Choose an invitation.')
                runtime.workspace.dispatch('enrollment.import', {'path': rest[index + 1]})
            elif '--open-phone-app' in rest:
                index = rest.index('--open-phone-app')
                if index + 1 >= len(rest):
                    raise ValueError('Choose a phone app.')
                runtime.open_phone_app(rest[index + 1])
            else:
                runtime.native('window.show', {})
            return {'ok': True}
        if method == 'open.phone.app':
            runtime.open_phone_app(args.get('package'))
            return {'ok': True}
        if method == 'send.files':
            runtime.confirm_send_files(args.get('paths'))
            return {'ok': True}
        if method == 'enrollment.import':
            return runtime.workspace.dispatch('enrollment.import', args)
        if method == 'hello':
            return {'protocol': PROTOCOL, 'runtime': 'electron', 'qt_loaded': any(k.startswith('PySide6') for k in sys.modules)}
        raise ValueError('Unknown native desktop control.')

    def run(self):
        self.emit({'type': 'ready', 'protocol': PROTOCOL, 'mode': 'isolated' if self.runtime.isolated else 'live',
                   'methods': ['state', 'settings.save', 'desktop.actions'], 'capabilities': 2})
        self.runtime.start()
        try:
            while line := self.source.readline(MAX_REQUEST + 1):
                if len(line) > MAX_REQUEST:
                    raise ValueError('Desktop request is too large.')
                packet = json.loads(line)
                if not isinstance(packet, dict):
                    raise ValueError('Invalid desktop packet.')
                if 'native_id' in packet:
                    with self.pending_lock:
                        future = self.pending.get(packet['native_id'])
                    if future and not future.done():
                        if packet.get('ok') is True:
                            future.set_result(packet.get('result'))
                        else:
                            future.set_exception(ValueError('The desktop action could not finish.'))
                elif self.slots.acquire(blocking=False):
                    # Native consent replies remain readable while this dispatcher waits.
                    (self.controls if packet.get('type') == 'control' else self.dispatcher).submit(self.dispatch, packet)
                else:
                    self.emit({'id': packet.get('id', 'invalid'), 'ok': False, 'error': 'The desktop is busy. Try again shortly.'})
        finally:
            self.closed = True
            with self.pending_lock:
                for future in self.pending.values():
                    if not future.done():
                        future.set_exception(ValueError('The desktop has closed.'))
            self.runtime.close()
            self.dispatcher.shutdown(wait=False, cancel_futures=True)
            self.controls.shutdown(wait=False, cancel_futures=True)


def seed_fixture(workspace):
    fixture_path = Path(sys._MEIPASS) / 'test-fixtures/electron-phone.json' if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2] / 'tests/fixtures/electron-phone.json'
    fixture = json.loads(fixture_path.read_text(encoding='utf-8'))
    workspace.phone.connected = True
    workspace.phone.restore({'devices': fixture['devices'], 'notifications': []})
    for kind, rows in fixture['records'].items():
        for row in rows:
            workspace.store.save(kind, row)
    from PIL import Image
    original = workspace.root / 'Synthetic original.jpg'
    Image.new('RGB', (640, 360), '#204d67').save(original, 'JPEG')
    workspace.store.save('phone_photo_original', {'id': workspace.phone_features._photo_key('electron-test-phone', '1'),
        'device_id': 'electron-test-phone', 'photo_id': '1', 'path': str(original), 'name': original.name, 'size': original.stat().st_size})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--config', type=Path)
    choice.add_argument('--ui-session', type=Path)
    options = parser.parse_args(argv)
    config, profile = load_configuration(options.config) if options.config else isolated_session(options.ui_session)
    trace = record_crashes(profile)  # noqa: F841
    hold_com()
    isolated = config['mode'] == 'isolated'
    if isolated:
        os.environ['ORION_MINI_TEST'] = '1'
    else:
        os.environ.pop('ORION_MINI_TEST', None)
    os.environ['ORION_MINI_DATA_DIR'] = str(profile)
    if options.config:
        os.environ['SAIPH_ELECTRON_SERVICE'] = '1'
        os.environ['SAIPH_DESKTOP_EXECUTABLE'] = config['desktop_executable']
        os.environ['SAIPH_DESKTOP_PID'] = str(config['desktop_pid'])
    from .profile_lock import ProfileLock
    from .db_health import check
    from .electron_runtime import ElectronRuntime
    from .native_binary import BinaryLink
    connection = ControlConnection(sys.stdin.buffer, sys.stdout.buffer)
    with ProfileLock(profile / 'app.lock'):
        if any(value == 'failed' for value in check(profile)['results'].values()):
            raise ValueError('The profile failed its database integrity check. Existing data was preserved.')
        binary = None
        if options.config:
            binary = BinaryLink(config['binary_address'], config['binary_token'],
                                lambda header, data: connection.runtime.binary_received(header, data) if connection.runtime else None)
        try:
            runtime = connection.runtime = ElectronRuntime(profile, connection.native, connection.emit,
                isolated=isolated, window_handle=int(config.get('window_handle', 0)), binary=binary)
            if isolated and config.get('fixture') == 'phone':
                seed_fixture(runtime.workspace)
            connection.run()
        finally:
            if binary:
                binary.close()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print('The desktop service could not continue; its profile was preserved.', file=sys.stderr)
        raise SystemExit(1)
