# SPDX-License-Identifier: AGPL-3.0-or-later
"""One desktop update state for the footer Update button, Settings → Updates and the tray.

The window checks this computer's own update source (package_updates: its Saiph
account or its paired Hub) a short while after start-up and then every six hours.
A background check never downloads or installs anything and never reports its own
failures: it only lights the footer button when a newer build is offered. The
footer button is the explicit action: it checks again, downloads and verifies,
then hands off to the native installer, which closes and reopens Saiph. Settings
keeps its separate Download and Restart steps through the same state.
"""
from __future__ import annotations

import threading
import time

from . import package_updates

# Long enough that start-up (Cloud sign-in, phone links) settles first.
FIRST_CHECK_MS = 2 * 60 * 1000
CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000
STATES = frozenset({'none', 'checking', 'available', 'downloading', 'ready', 'installing', 'failed'})
FAILED = 'The update did not finish. Your installed version is still available. Try again later.'


class Busy(ValueError):
    pass


class DesktopUpdates:
    """Thread-safe. ``changed`` announces a new state to the page (a Qt signal's emit,
    safe from any thread); ``restart`` closes Saiph once the installer handoff started."""

    def __init__(self, workspace, *, changed=lambda: None, restart=lambda: None, clock=time.time):
        self.workspace, self.changed, self.restart, self.clock = workspace, changed, restart, clock
        self.lock = threading.Lock()
        # One check, download or install at a time.
        self.work = threading.Lock()
        self.state, self.release, self.notes, self.source = 'none', None, '', None
        # staged: what install() takes; offer: the release it was downloaded for (a
        # Linux .run's staged release describes the archive inside it instead).
        self.staged, self.offer, self.error, self.checked_at = None, None, '', None

    def status(self):
        """Small and JSON-safe: it rides along with every dashboard snapshot."""
        with self.lock:
            release = self.release
            return {'state': self.state, 'release': dict(release) if release else None,
                    'version': release['version'] if release else None,
                    'bytes': release['bytes'] if release else None, 'notes': self.notes if release else '',
                    'source': self.source, 'error': self.error, 'checked_at': self.checked_at}

    def _set(self, state, **values):
        assert state in STATES
        with self.lock:
            self.state = state
            for key, value in values.items():
                setattr(self, key, value)
        self.changed()

    def _claim(self):
        if not self.work.acquire(blocking=False):
            raise Busy('An update is already in progress.')

    def _check(self):
        workspace = self.workspace
        return package_updates.check(workspace.root, dict(workspace.settings['hub']),
                                     cloud=package_updates.source_for(workspace))

    def _record(self, result, *, background):
        """Keep a downloaded update and a failure the person has not retried yet."""
        release = result.get('release') if result.get('available') else None
        with self.lock:
            self.checked_at = int(self.clock())
            state, offer = self.state, self.offer
        if release is None:
            self._set('none', release=None, notes='', source=result.get('source'), staged=None, offer=None, error='')
        elif state == 'ready' and offer == release:
            self._set('ready', release=release, notes=result.get('notes') or '', source=result.get('source'))
        elif state == 'failed' and background:
            self._set('failed', release=release, notes=result.get('notes') or '', source=result.get('source'))
        else:
            self._set('available', release=release, notes=result.get('notes') or '', source=result.get('source'),
                      staged=None, offer=None, error='')

    def background_check(self):
        """Timer entry point: quiet, skipped for development builds and while busy."""
        if package_updates.current() is None or not self.work.acquire(blocking=False):
            return False
        try:
            self._record(self._check(), background=True)
            return True
        except Exception:
            # Offline, signed out or a refused description: try again next time.
            return False
        finally:
            self.work.release()

    def start_background_check(self):
        threading.Thread(target=self.background_check, name='orion-update-check', daemon=True).start()

    def check(self):
        """Settings and the tray: the full result, recorded for the footer as well."""
        self._claim()
        try:
            result = self._check()
            self._record(result, background=False)
            return result
        finally:
            self.work.release()

    def _stage(self, release):
        workspace = self.workspace
        self._set('downloading', error='')
        staged = package_updates.stage(workspace.root, dict(workspace.settings['hub']), release,
                                       cloud=package_updates.source_for(workspace))
        self._set('ready', staged=staged, offer=release, release=release)
        return staged

    def _install(self, staged):
        self._set('installing')
        result = package_updates.install(self.workspace.root, staged)
        self.restart()
        return result

    def _fail(self, error):
        message = str(error) if isinstance(error, ValueError) and str(error) else FAILED
        self._set('failed', error=message)

    def download(self, release):
        """Settings → Download update: download and verify only."""
        self._claim()
        try:
            staged = self._stage(release)
            return {'staged': True, 'version': release['version']}
        except Exception as error:
            self._fail(error)
            raise
        finally:
            self.work.release()

    def restart_to_update(self):
        """Settings → Restart to update: install what Download update verified."""
        self._claim()
        try:
            with self.lock:
                staged = self.staged
            if staged is None:
                raise ValueError('Download the update first.')
            try:
                return self._install(staged)
            except Exception as error:
                self._fail(error)
                raise
        finally:
            self.work.release()

    def update_now(self):
        """The footer button: check again, download and verify, install and restart."""
        self._claim()
        try:
            with self.lock:
                previous = self.state
            self._set('checking', error='')
            try:
                result = self._check()
            except Exception as error:
                self._fail(error)
                raise
            if result.get('reason') or not result.get('available'):
                self._record(result, background=False)
                return {'started': False, 'result': result}
            release = result['release']
            with self.lock:
                self.checked_at = int(self.clock())
                staged = self.staged if previous == 'ready' and self.offer == release else None
                self.notes, self.source = result.get('notes') or '', result.get('source')
            try:
                if staged is None:
                    staged = self._stage(release)
                self._install(staged)
            except Exception as error:
                self._fail(error)
                raise
            return {'started': True, 'version': release['version']}
        finally:
            self.work.release()
