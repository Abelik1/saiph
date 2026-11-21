# SPDX-License-Identifier: AGPL-3.0-or-later
"""Native profile exclusion compatible with the existing QLockFile contract.

Create-new plus an OS lock protects the existing app.lock, including old Qt
processes that consider a 30-second file stale. Never steal a live/unknown lock.
The five newline-separated identity fields are the public Qt lock-file format.
"""
from __future__ import annotations
import ctypes
import os
from pathlib import Path
import socket
import sys
import time


class ProfileLock:
    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def _create(self):
        if sys.platform == 'win32':
            from ctypes import wintypes
            api = ctypes.WinDLL('kernel32', use_last_error=True)
            api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                       ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            api.CreateFileW.restype = wintypes.HANDLE
            handle = api.CreateFileW(str(self.path), 0xC0000000, 1, None, 1, 0x80, None)
            if handle == ctypes.c_void_p(-1).value:
                code = ctypes.get_last_error()
                if code in (5, 32, 80, 183):
                    raise FileExistsError(str(self.path))
                raise ctypes.WinError(code)
            import msvcrt
            return os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY), 'w+b', buffering=0)
        import fcntl
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return os.fdopen(fd, 'w+b', buffering=0)
        except BaseException:
            os.close(fd)
            raise

    def _remove_dead(self):
        import psutil
        try:
            before = self.path.stat()
            lines = self.path.read_text(encoding='utf-8').splitlines()
            pid = int(lines[0])
            if pid <= 0 or len(lines) < 3 or lines[2] not in ('', socket.gethostname(), os.environ.get('COMPUTERNAME')):
                return False
            if psutil.pid_exists(pid):
                return False  # Fail closed even for PID reuse; the owner can inspect it.
            if sys.platform == 'win32':
                self.path.unlink()  # A held Qt Windows handle prevents deletion.
            else:
                import fcntl
                with self.path.open('r+b') as stale:
                    fcntl.flock(stale, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    now = self.path.stat()
                    if (before.st_ino, before.st_mtime_ns) != (now.st_ino, now.st_mtime_ns):
                        return False
                    self.path.unlink()
            return True
        except (OSError, ValueError, IndexError):
            return False

    def acquire(self, timeout=0.1):
        import psutil
        if self.handle is not None:
            return False
        deadline = time.monotonic() + timeout
        while True:
            try:
                self.handle = self._create()
                name = psutil.Process().name()
                hostname = os.environ.get('COMPUTERNAME') if sys.platform == 'win32' else socket.gethostname()
                self.handle.write(f'{os.getpid()}\n{name}\n{hostname}\n\n\n'.encode('utf-8'))
                os.fsync(self.handle.fileno())
                return True
            except FileExistsError:
                if self._remove_dead():
                    continue
                if time.monotonic() >= deadline:
                    return False
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))

    def release(self):
        if self.handle is None:
            return
        if sys.platform == 'win32':
            self.handle.close()
            self.path.unlink(missing_ok=True)
        else:
            self.path.unlink(missing_ok=True)
            self.handle.close()
        self.handle = None

    def __enter__(self):
        if not self.acquire():
            raise ValueError('This Saiph profile is already in use.')
        return self

    def __exit__(self, *_):
        self.release()
