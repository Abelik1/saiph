# SPDX-License-Identifier: AGPL-3.0-or-later
"""Start other programs with the user's environment, not the frozen bundle's.

A frozen Linux build runs with LD_LIBRARY_PATH pointing at its bundled libraries;
PyInstaller keeps any original value in LD_LIBRARY_PATH_ORIG. System programs
(xdg-open, coreutils, nmcli, pactl, browsers) then load those older libraries and
fail, often silently. Every launch of another program goes through here; the
guard in tests/test_child_process.py rejects direct subprocess, webbrowser,
QProcess and QDesktopServices use elsewhere in the package.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from collections.abc import Mapping

# Set by the PyInstaller bootloader for its own child processes only.
_BUNDLE_KEYS = frozenset({'_MEIPASS2'})


def system_environment(base: Mapping[str, str] | None = None, *, drop_library_path: bool = False) -> dict[str, str]:
    """`base` (default: this process's environment) without the bundle's own variables.

    The bundle's LD_LIBRARY_PATH is replaced by the user's original value (or removed)
    wherever it appears, so applying this twice changes nothing. `drop_library_path`
    also replaces any other value, for helpers that must only see the system's libraries.
    """
    environment = {key: value for key, value in (os.environ if base is None else base).items()
                   if not key.startswith('_PYI') and key not in _BUNDLE_KEYS and key != 'LD_LIBRARY_PATH_ORIG'}
    if sys.platform == 'win32' and not drop_library_path:
        return environment
    original = os.environ.get('LD_LIBRARY_PATH_ORIG')
    bundled = os.environ.get('LD_LIBRARY_PATH') if original is not None or getattr(sys, 'frozen', False) else None
    current = environment.get('LD_LIBRARY_PATH')
    if current is not None and (drop_library_path or current == bundled):
        del environment['LD_LIBRARY_PATH']
        if original:
            environment['LD_LIBRARY_PATH'] = original
    return environment


def run(args, *, env: Mapping[str, str] | None = None, **options) -> subprocess.CompletedProcess:
    """subprocess.run with a system environment."""
    return subprocess.run(args, env=system_environment(env), **options)


def popen(args, *, env: Mapping[str, str] | None = None, **options) -> subprocess.Popen:
    """subprocess.Popen with a system environment."""
    return subprocess.Popen(args, env=system_environment(env), **options)


def _reap(process: subprocess.Popen) -> None:
    threading.Thread(target=process.wait, name='saiph-opener-reaper', daemon=True).start()


def open_url(target: str, *, start=popen, which=shutil.which, wait: float = 1.5) -> bool:
    """Open a URL or local path in the user's default application. False when nothing opened it.

    On Linux xdg-open (then gio) runs with a system environment. A non-zero exit
    within `wait` seconds is a failure; still running means it is opening (some
    xdg-open back ends run the browser in the foreground).
    """
    if not isinstance(target, str) or not target or target.startswith('-'):
        return False  # never let a target be read as an opener option
    if sys.platform in {'win32', 'darwin'}:
        return bool(webbrowser.open(target))
    for name, *arguments in (('xdg-open',), ('gio', 'open')):
        executable = which(name)
        if executable is None:
            continue
        try:
            process = start([executable, *arguments, target], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
        except OSError:
            continue
        try:
            if process.wait(timeout=wait) == 0:
                return True
        except subprocess.TimeoutExpired:
            _reap(process)
            return True
    return False
