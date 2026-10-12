# SPDX-License-Identifier: AGPL-3.0-or-later
"""Small OS-protected secrets for the opt-in hosted preview.

Holds one hosted device's signing key and, when the owner allows refresh
tokens, one rotating refresh token. Each value is wrapped by DPAPI (Windows)
or Secret Service (Linux) through the same backends as `hosted_keys`, bound to
a public context, written with an owner-only ACL and replaced atomically.
There is no plaintext fallback and no implicit reset of an unreadable value.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys

from .hosted_keys import (
    KeyStorageError, _SecretServiceProtection, _WindowsProtection, _no_links, _private_mode, _windows_acl,
    _private_directory,
)

_LIMIT = 16_384


def default_protection():
    if sys.platform == "win32":
        return _WindowsProtection()
    if sys.platform.startswith("linux"):
        return _SecretServiceProtection()
    raise KeyStorageError()


def private_folder(folder: Path) -> Path:
    """Create (owner-only) or verify an application-private folder."""
    return _private_directory(folder, create=True)


class ProtectedBlob:
    """One wrapped secret file; `save` replaces it atomically (rotation-safe)."""

    def __init__(self, folder: Path, name: str, context: bytes, *, protection=None):
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,40}\.enc", name) or type(context) is not bytes or not context:
            raise KeyStorageError()
        self.folder, self.name, self.context = Path(folder), name, context
        self._protection = protection

    @property
    def path(self) -> Path:
        return self.folder / self.name

    def _aead(self, create):
        backend = self._protection or default_protection()
        if not create:
            return backend.load(self.context)
        try:
            return backend.load(self.context)
        except Exception:
            if self.path.exists():
                raise KeyStorageError() from None
            # Secret Service needs an explicit wrapping item on first use; DPAPI
            # create/load are identical. Never replaces an unreadable item.
            return backend.create(self.context)

    def exists(self) -> bool:
        return self.path.exists()

    def save(self, secret: bytes) -> None:
        try:
            if type(secret) is not bytes or not 0 < len(secret) <= 8192:
                raise KeyStorageError()
            private_folder(self.folder)
            encrypted = self._aead(True).encrypt(secret, self.context)
            if not 0 < len(encrypted) <= _LIMIT:
                raise KeyStorageError()
            temporary = self.folder / (self.name + ".tmp")
            _no_links(temporary)
            temporary.unlink(missing_ok=True)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
            try:
                with os.fdopen(fd, "wb") as output:
                    _private_mode(os.fstat(output.fileno()))
                    if os.name == "nt":
                        _windows_acl(temporary, set_private=True)
                    output.write(encrypted)
                    output.flush()
                    os.fsync(output.fileno())
                _no_links(self.path)
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
            if os.name != "nt":
                directory = os.open(self.folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        except Exception:
            raise KeyStorageError() from None

    def load(self) -> bytes | None:
        """Return None only when nothing was ever saved; fail closed otherwise."""
        try:
            if not self.path.exists():
                return None
            private_folder(self.folder)
            _no_links(self.path)
            if os.name == "nt":
                _windows_acl(self.path)
            fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
            with os.fdopen(fd, "rb") as source:
                _private_mode(os.fstat(source.fileno()))
                data = source.read(_LIMIT + 1)
            if not 0 < len(data) <= _LIMIT:
                raise KeyStorageError()
            return self._aead(False).decrypt(data, self.context)
        except Exception:
            raise KeyStorageError() from None

    def clear(self) -> None:
        try:
            _no_links(self.path)
            self.path.unlink(missing_ok=True)
        except Exception:
            raise KeyStorageError() from None
