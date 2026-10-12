# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guided upstream mesh component setup, without owning a VPN or account."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

from .enrollment import login_server


def tailscale_executable():
    if sys.platform == 'win32':
        candidate = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Tailscale/tailscale.exe'
        if candidate.is_file():
            return str(candidate)
    return shutil.which('tailscale')


def run(argv, timeout=15):
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, **options)


def auth_url(value, controller):
    try:
        parsed = urlsplit(value)
        allowed = {'login.tailscale.com', 'controlplane.tailscale.com'}
        if controller:
            allowed = {urlsplit(controller).hostname}
        port = urlsplit(controller).port or 443 if controller else 443
        return (parsed.scheme == 'https' and parsed.hostname in allowed and (parsed.port or 443) == port and parsed.username is None
                and parsed.password is None and len(value) <= 4096
                and all(ord(char) > 32 for char in value))
    except (TypeError, ValueError):
        return False


class Components:
    def __init__(self):
        self._state = {'mesh_installed': False, 'mesh_running': False, 'busy': False, 'message': 'Checking setup…'}
        self._lock = threading.RLock()
        self._next_poll = 0

    def snapshot(self):
        with self._lock:
            return dict(self._state)

    def poll(self):
        with self._lock:
            if time.monotonic() < self._next_poll or self._state['busy']:
                return self.snapshot()
            self._next_poll = time.monotonic() + 15
        executable = tailscale_executable()
        active = False
        if executable:
            try:
                result = run([executable, 'status', '--json'])
                active = result.returncode == 0 and json.loads(result.stdout).get('BackendState') == 'Running'
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
        with self._lock:
            self._state.update(mesh_installed=bool(executable), mesh_running=active,
                               message='Secure connection ready' if active else 'Complete secure connection setup')
            return self.snapshot()

    def install(self):
        if tailscale_executable():
            return self.poll()
        if sys.platform == 'win32':
            winget = shutil.which('winget')
            if not winget:
                webbrowser.open('https://tailscale.com/download/windows')
                return {'opened': True, 'message': 'Install the official component, then return to Saiph.'}
            command = [winget, 'install', '--id', 'Tailscale.Tailscale', '--exact', '--source', 'winget',
                       '--accept-source-agreements', '--accept-package-agreements', '--silent', '--disable-interactivity']
        elif sys.platform.startswith('linux'):
            helper = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2])) / 'assets/install-mesh-linux.sh'
            pkexec = shutil.which('pkexec')
            if not pkexec or not helper.is_file():
                raise ValueError('Operating-system installation approval is unavailable. Use the official Linux instructions in Advanced.')
            command = [pkexec, '/bin/sh', str(helper)]
        else:
            raise ValueError('This operating system is not supported.')
        with self._lock:
            if self._state['busy']:
                raise ValueError('Setup is already running.')
            self._state.update(busy=True, message='Installing the official connection component…')
        try:
            result = run(command, timeout=600)
            if result.returncode or not tailscale_executable():
                raise ValueError('Component installation did not finish. Accept the operating-system prompt and try setup again.')
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError('The official connection component could not be installed.') from None
        finally:
            with self._lock:
                self._state['busy'] = False; self._next_poll = 0
        return self.poll()

    def sign_in(self, controller=None):
        controller = login_server(controller)
        executable = tailscale_executable()
        if not executable:
            raise ValueError('Install the connection component first.')
        state = self.poll()
        if state['mesh_running']:
            return state  # Never switch a working network during ordinary setup.
        # Preserve an existing configured profile rather than resetting preferences.
        try:
            prefs = json.loads(run([executable, 'debug', 'prefs']).stdout)
            existing = login_server(prefs.get('ControlURL'))
            if existing and controller and existing.rstrip('/') != controller and prefs.get('Persist'):
                raise ValueError('An existing network uses another provider. Choose its account in Advanced before continuing.')
        except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired):
            raise ValueError('The connection component is unavailable. Check its operating-system service.') from None
        if prefs.get('Persist'):
            if not existing:
                raise ValueError('The existing network profile needs account review in Advanced.')
            # Upstream treats ONLY a genuinely bare up as resume-without-changes.
            # Even --json/--timeout disable that path and can reject saved flags.
            command = [executable, 'up']
            if sys.platform.startswith('linux'):
                pkexec = shutil.which('pkexec')
                if not pkexec:
                    raise ValueError('Operating-system sign-in approval is unavailable.')
                command.insert(0, pkexec)
            with self._lock:
                if self._state['busy']:
                    raise ValueError('Setup is already running.')
                self._state.update(busy=True, message='Resuming your existing secure connection…')
            try:
                result = run(command, timeout=125)
                if result.returncode:
                    raise ValueError('The existing network needs account review in Advanced. Its preferences were preserved.')
            except (OSError, subprocess.TimeoutExpired):
                raise ValueError('The existing network could not resume. Its preferences were preserved.') from None
            finally:
                with self._lock:
                    self._state['busy'] = False
                    self._next_poll = 0
            return self.poll()
        command = [executable, 'up', '--json', '--timeout=120s']
        if controller:
            command.append('--login-server=' + controller)
        if sys.platform.startswith('linux'):
            pkexec = shutil.which('pkexec')
            if not pkexec:
                raise ValueError('Operating-system sign-in approval is unavailable.')
            command.insert(0, pkexec)
        with self._lock:
            if self._state['busy']:
                raise ValueError('Setup is already running.')
            self._state.update(busy=True, message='Complete the browser sign-in and return to Saiph…')
        process = None
        try:
            options = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, **options)
            timer = threading.Timer(130, process.kill); timer.daemon = True; timer.start()
            try:
                buffer = ''; opened = False
                while line := process.stdout.readline():
                    buffer += line
                    if len(buffer) > 16384:
                        raise ValueError('The connection component returned an unsupported reply.')
                    try:
                        value, consumed = json.JSONDecoder().raw_decode(buffer.lstrip())
                    except ValueError:
                        continue
                    buffer = buffer.lstrip()[consumed:].lstrip()
                    url = value.get('AuthURL') if isinstance(value, dict) else None
                    if url and not opened:
                        if not auth_url(url, controller):
                            raise ValueError('Sign-in returned an unexpected provider. Review the network in Advanced.')
                        webbrowser.open(url); opened = True
                process.wait(timeout=5)
            finally:
                timer.cancel()
                process.stdout.close()
            if process.returncode:
                raise ValueError('Network sign-in did not finish. Your existing network settings were preserved.')
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError('Network sign-in could not finish.') from None
        finally:
            if process and process.poll() is None:
                process.kill(); process.wait(timeout=5)
            with self._lock:
                self._state['busy'] = False; self._next_poll = 0
        return self.poll()
