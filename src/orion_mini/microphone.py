# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deliberate phone microphone via scrcpy and existing virtual audio adapters."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

from .adb_worker import AdbWorker
from .companion_tools import tool_path

CABLE_INPUT = 'CABLE Input (VB-Audio Virtual Cable)'
CABLE_OUTPUT = 'CABLE Output (VB-Audio Virtual Cable)'
_SDL_LOCK = threading.Lock()


def validate_options(options):
    if not isinstance(options, dict) or set(options) - {'enabled', 'scrcpy_executable'}:
        raise ValueError('Unknown phone microphone preference.')
    if 'enabled' in options and type(options['enabled']) is not bool:
        raise ValueError('Phone microphone is on or off.')
    value = options.get('scrcpy_executable', '')
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise ValueError('Choose a local scrcpy executable.')
    return dict(options)


def windows_cable(scrcpy):
    """Enumerate the selected scrcpy's SDL2 WASAPI endpoints without opening audio."""
    folder = Path(scrcpy).resolve().parent
    library = folder / 'SDL2.dll'
    if os.name != 'nt' or not library.is_file() or (folder / 'SDL3.dll').exists():
        return False
    with _SDL_LOCK, os.add_dll_directory(str(folder)):
        try:
            sdl = ctypes.CDLL(str(library))
            sdl.SDL_WasInit.argtypes = [ctypes.c_uint32]
            sdl.SDL_WasInit.restype = ctypes.c_uint32
            sdl.SDL_AudioInit.argtypes = [ctypes.c_char_p]
            sdl.SDL_AudioInit.restype = ctypes.c_int
            sdl.SDL_GetNumAudioDevices.argtypes = [ctypes.c_int]
            sdl.SDL_GetNumAudioDevices.restype = ctypes.c_int
            sdl.SDL_GetAudioDeviceName.argtypes = [ctypes.c_int, ctypes.c_int]
            sdl.SDL_GetAudioDeviceName.restype = ctypes.c_char_p
            sdl.SDL_AudioQuit.argtypes = []
            sdl.SDL_AudioQuit.restype = None
            if sdl.SDL_WasInit(0x10):
                return False  # Do not reconfigure another in-process SDL audio user.
            if sdl.SDL_AudioInit(b'wasapi') != 0:
                return False
            try:
                names = []
                for capture in (0, 1):
                    count = sdl.SDL_GetNumAudioDevices(capture)
                    if not 0 <= count <= 256:
                        return False
                    names.append({(sdl.SDL_GetAudioDeviceName(i, capture) or b'').decode('utf-8') for i in range(count)})
                return CABLE_INPUT in names[0] and CABLE_OUTPUT in names[1]
            finally:
                sdl.SDL_AudioQuit()
        except (OSError, AttributeError, UnicodeError):
            return False


class PulseInput:
    """Own only two ephemeral modules; never touch existing modules or defaults."""
    def __init__(self, executable, run=subprocess.run, popen=subprocess.Popen):
        self.executable, self.run, self.popen = executable, run, popen
        suffix = uuid.uuid4().hex
        self.description = 'Saiph Phone Capture ' + suffix
        self.sink = 'orion_phone_sink_' + suffix
        self.source = 'orion_phone_mic_' + suffix
        self.modules = []
        self.loopback = None

    def command(self, *args):
        try:
            result = self.run([self.executable, *args], capture_output=True, text=True, timeout=5)
            if result.returncode:
                raise ValueError('Phone microphone audio routing is unavailable.')
            return result.stdout
        except (OSError, subprocess.SubprocessError):
            raise ValueError('Phone microphone audio routing is unavailable.') from None

    def listing(self, kind):
        if kind == 'modules':
            # Ubuntu 22.04's pactl JSON omits module indices. The documented
            # short form supplies stable IDs and retains exact argument text.
            rows = []
            for line in self.command('list', 'short', 'modules').splitlines():
                columns = line.split('\t')
                if len(columns) < 2 or not re.fullmatch(r'[0-9]{1,10}', columns[0]):
                    # PipeWire includes multi-line configuration for unrelated
                    # core modules. Only indexed rows can establish ownership.
                    continue
                rows.append({'index': int(columns[0]), 'name': columns[1], 'argument': columns[2] if len(columns) > 2 else ''})
            return rows
        value = json.loads(self.command('--format=json', 'list', kind))
        if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
            raise ValueError('Phone microphone audio routing is unavailable.')
        return value

    def start(self):
        sink_args = ('sink_name=' + self.sink, 'sink_properties=\'device.description="' + self.description + '" device.class=filter\'',
                     'rate=48000', 'channels=2', 'channel_map=front-left,front-right')
        source_args = ('master=' + self.sink + '.monitor', 'source_name=' + self.source,
                       'source_properties=\'device.description="Saiph Phone Microphone" device.class=filter\'',
                       'rate=48000', 'channels=2', 'channel_map=front-left,front-right')
        try:
            server = json.loads(self.command('--format=json', 'info'))
            pipewire = 'PipeWire' in server.get('server_name', '')
            specs = [('module-null-sink', sink_args)]
            if not pipewire:specs.append(('module-remap-source', source_args))
            loopback = shutil.which('pw-loopback') if pipewire else None
            if pipewire and not loopback:
                raise ValueError('Phone microphone audio routing is unavailable.')
            for name, args in specs:
                identifier = self.command('load-module', name, *args).strip()
                if not re.fullmatch(r'[0-9]{1,10}', identifier):
                    raise ValueError('Phone microphone audio routing is unavailable.')
                self.modules.append((int(identifier), name, args))
            if pipewire:
                # Older PipeWire remap-source implementations can interpret a
                # missing monitor target as the default computer microphone.
                # The upstream CLI lets us forbid fallback/reconnection and
                # bind the actual sink monitor explicitly on all supported PW.
                capture = {'node.target': self.sink, 'target.object': self.sink, 'stream.capture.sink': True,
                           'node.dont-reconnect': True, 'node.dont-fallback': True, 'node.passive': True}
                playback = {'media.class': 'Audio/Source', 'node.name': self.source,
                            'node.description': 'Saiph Phone Microphone', 'device.class': 'filter',
                            'node.virtual': True, 'priority.session': 0}
                self.loopback = self.popen([loopback, '-c', '2', '-m', '[ FL FR ]',
                    '--capture-props', json.dumps(capture), '--playback-props', json.dumps(playback)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if any(row.get('name') == self.source for row in self.listing('sources')):break
                    if self.loopback.poll() is not None:break
                    time.sleep(.1)
            if not self.alive():
                raise ValueError('Phone microphone audio routing is unavailable.')
        except (OSError, ValueError, TypeError, KeyError):
            self.stop()
            raise ValueError('Phone microphone audio routing is unavailable.') from None

    def alive(self):
        rows = self.listing('modules')
        for identifier, name, args in self.modules:
            row = next((r for r in rows if r.get('index') == identifier), {})
            if row.get('name') != name or row.get('argument') != ' '.join(args):
                return False
        expected = 1 if self.loopback else 2
        return (len(self.modules) == expected and (not self.loopback or self.loopback.poll() is None)
                and any(r.get('name') == self.sink for r in self.listing('sinks'))
                and any(r.get('name') == self.source for r in self.listing('sources')))

    def stop(self):
        if self.loopback:
            if self.loopback.poll() is None:
                self.loopback.terminate()
                try:self.loopback.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.loopback.kill();self.loopback.wait(timeout=3)
            self.loopback = None
        try:
            rows = self.listing('modules')
        except (ValueError, TypeError, KeyError):
            rows = []  # A restarted audio server no longer owns our old IDs.
        for identifier, name, args in reversed(self.modules):
            row = next((r for r in rows if r.get('index') == identifier), {})
            if row.get('name') == name and row.get('argument') == ' '.join(args):
                try:
                    self.command('unload-module', str(identifier))
                except ValueError:
                    pass
        self.modules.clear()


class Microphone:
    def __init__(self, workspace, *, system=None, popen=subprocess.Popen, run=subprocess.run,
                 worker_factory=AdbWorker, cable_probe=windows_cable, pulse_factory=PulseInput):
        self.workspace, self.system = workspace, system or sys.platform
        self.popen, self.run, self.worker_factory = popen, run, worker_factory
        self.cable_probe, self.pulse_factory = cable_probe, pulse_factory
        self.lock = threading.RLock()
        self.process = self.adapter = None
        self.device_id = None
        self.muted = False
        self.error = ''
        self.finished = None
        self._prepared_cache = None
        self._probe_at = 0
        self._config_cache = None
        self.prepared = None

    def _config(self):
        return (self.workspace.settings.get('link') or {}).get('microphone') or {}

    def _prepare(self, fresh=False):
        config = self._config()
        if not fresh and self._config_cache == config and time.monotonic() < self._probe_at:
            return self._prepared_cache
        self._config_cache = dict(config)
        self._probe_at = time.monotonic() + 15
        prepared, message = None, 'Set up the phone microphone in Settings → Devices.'
        scrcpy = tool_path('scrcpy', config.get('scrcpy_executable')) if config.get('enabled', False) else None
        if not config.get('enabled', False):
            message = 'Phone microphone is switched off in Settings.'
        elif not scrcpy:
            message = 'Install scrcpy (Settings → Devices explains how) to use the phone microphone.'
        elif self.system.startswith('linux') or self.system == 'win32':
            try:
                result = self.run([scrcpy, '--version'], capture_output=True, text=True, timeout=5,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                compatible = result.returncode == 0 and re.search(r'^scrcpy 3\.3\.4(?:\s|$)', result.stdout)
                if compatible and self.system.startswith('linux') and shutil.which('pactl'):
                    prepared = {'mode': 'linux-pulse', 'scrcpy': scrcpy, 'pactl': shutil.which('pactl')}
                elif compatible and self.system == 'win32' and self.cable_probe(scrcpy):
                    prepared = {'mode': 'windows-cable', 'scrcpy': scrcpy}
            except (OSError, subprocess.SubprocessError):
                pass
        self._prepared_cache = prepared, message
        return self._prepared_cache

    def _phone(self):
        return next((r for r in self.workspace.phone.snapshot()['devices'] if r.get('id') == self.device_id), None)

    def _check(self):
        if not self.device_id:
            return
        phone = self._phone()
        reason = None
        if not self._config().get('enabled', False) or not phone or not phone.get('online', False):
            reason = 'Phone microphone stopped. Your phone must stay online and paired.'
        elif not self.muted and (self.process is None or self.process.poll() is not None):
            reason = 'Phone microphone stopped. Start it again when you are ready.'
        else:
            try:
                if self.adapter and not self.adapter.alive():
                    reason = 'Phone microphone stopped because its audio route changed.'
                elif self.prepared and self.prepared['mode'] == 'windows-cable' and self._prepare()[0] is None:
                    reason = 'Phone microphone stopped because its audio route changed.'
            except (ValueError, TypeError, KeyError):
                reason = 'Phone microphone stopped because its audio route changed.'
        if reason:
            self.stop()
            self.error = reason

    def _monitor(self, finished):
        while not finished.wait(1):
            with self.lock:
                if finished.is_set():
                    return
                self._check()

    def status(self):
        with self.lock:
            self._check()
            prepared, message = self._prepare()
            active = self.device_id is not None
            return {'available': prepared is not None, 'running': active, 'muted': self.muted if active else False,
                    'verified': False, 'mode': prepared['mode'] if prepared else 'unavailable',
                    'device_id': self.device_id,
                    'message': self.error or ('Phone microphone is muted; capture is stopped.' if active and self.muted else
                        'Phone microphone capture is running. Check audio in your meeting app.' if active else
                        'Ready to start the phone microphone.' if prepared else message)}

    def _capture(self):
        worker = self.worker_factory()
        serial = worker.paired_serial(self.device_id)
        if not isinstance(serial, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:\[\]-]{0,199}', serial) or not worker.adb:
            raise ValueError('Authorized debugging is unavailable for this phone. Connect it over USB or wireless debugging and allow this computer. Optional tools in the setup guide shows whether adb is installed.')
        env = os.environ.copy()
        env['ADB'] = str(worker.adb)
        # Do not inherit a route that could override the deliberate private sink.
        for key in ('SDL_AUDIO_DEVICE_NAME', 'PULSE_SINK', 'PULSE_SOURCE'):
            env.pop(key, None)
        if self.prepared['mode'] == 'linux-pulse':
            env.update(SDL_AUDIODRIVER='pulseaudio', SDL_AUDIO_DRIVER='pulseaudio', PULSE_SINK=self.adapter.sink,
                       SDL_AUDIO_DEVICE_NAME=self.adapter.description,
                       PULSE_PROP='application.name=Orion_Phone_Microphone')
        else:
            env.update(SDL_AUDIODRIVER='wasapi', SDL_AUDIO_DEVICE_NAME=CABLE_INPUT)
        args = [self.prepared['scrcpy'], '--serial', serial, '--no-video', '--no-control', '--no-window',
                '--audio-source=mic', '--audio-codec=raw', '--require-audio', '--audio-buffer=50']
        self.process = self.popen(args, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)

    def start(self, device_id):
        with self.lock:
            self._check()
            if self.device_id:
                if device_id != self.device_id:
                    raise ValueError('Stop the current phone microphone first.')
                return self.status()  # Start never silently unmutes an existing session.
            validate_options(self._config())
            self.device_id = device_id
            phone = self._phone()
            if not phone or not phone.get('online', False):
                self.device_id = None
                raise ValueError('Choose an online paired phone.')
            try:
                self.prepared, message = self._prepare(fresh=True)
                if not self.prepared:
                    raise ValueError(message)
                if self.prepared['mode'] == 'linux-pulse':
                    self.adapter = self.pulse_factory(self.prepared['pactl'])
                    self.adapter.start()
                self._capture()
                self.error, self.muted = '', False
                self.finished = threading.Event()
                threading.Thread(target=self._monitor, args=(self.finished,), name='orion-microphone', daemon=True).start()
                return self.status()
            except (OSError, subprocess.SubprocessError, ValueError):
                self.stop()
                raise ValueError('Phone microphone could not start. Check Settings → Devices.') from None

    def _stop_capture(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            except OSError:
                if self.process.poll() is None:
                    raise ValueError('Phone microphone could not stop; its private audio route is retained.') from None
        self.process = None

    def mute(self, muted):
        if type(muted) is not bool:
            raise ValueError('Phone microphone mute is on or off.')
        with self.lock:
            self._check()
            if not self.device_id:
                raise ValueError('Start the phone microphone first.')
            try:
                if muted:
                    self._stop_capture()
                elif self.muted:
                    if self._prepare(fresh=True)[0] is None:
                        raise ValueError('Phone microphone audio routing is unavailable.')
                    self._capture()
                self.muted = muted
                return self.status()
            except (OSError, subprocess.SubprocessError, ValueError):
                self.stop()
                raise ValueError('Phone microphone stopped. Check Settings → Devices.') from None

    def stop(self):
        with self.lock:
            # Retain the private route and monitor if termination fails. Never
            # remove the route underneath a possibly still capturing process.
            self._stop_capture()
            if self.finished:
                self.finished.set()
            if self.adapter:
                self.adapter.stop()
            self.adapter = self.prepared = None
            self.device_id, self.muted = None, False
            return {'stopped': True}
