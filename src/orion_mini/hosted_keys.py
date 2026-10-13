# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicit OS-protected recipient keys; never a get-or-create identity loader."""
from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
from uuid import UUID

import tink
from tink import aead, proto_keyset_format, secret_key_access

from .hosted_crypto import canonical, export_public, generate_recipient, read_public
from .hosted_session import read_signing_key

_LIMIT = 16_384


class KeyStorageError(ValueError):
    """Generic errors never contain native exception text or private material."""

    def __init__(self):
        super().__init__("Hosted keys are unavailable. Existing enrollment was preserved.")


def _no_links(path):
    for entry in (path, *path.parents):
        try:
            value = entry.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
            raise KeyStorageError()
        if os.name != "nt":
            if value.st_uid not in {0, os.getuid()}:
                raise KeyStorageError()
            if stat.S_ISDIR(value.st_mode) and not value.st_mode & stat.S_ISVTX:
                if value.st_mode & 0o002:
                    raise KeyStorageError()
                if value.st_mode & 0o020 and not (value.st_uid == os.getuid() and _private_group(value.st_gid)):
                    raise KeyStorageError()


def _private_group(gid):
    """True for a user private group: the umask 0002 default on Debian/Ubuntu.

    Group write is then owner write. Like Debian's OpenSSH user-group-modes, the
    group must belong to this user alone: no other member and no other account's
    primary group. An unknown or shared group stays untrusted."""
    import grp
    import pwd
    try:
        user = pwd.getpwuid(os.getuid())
        group = grp.getgrgid(gid)
        accounts = pwd.getpwall()
    except (KeyError, OSError):
        return False
    if any(member != user.pw_name for member in group.gr_mem):
        return False
    if any(account.pw_gid == gid and account.pw_uid != user.pw_uid for account in accounts):
        return False
    return user.pw_gid == gid or user.pw_name in group.gr_mem


def _private_mode(value, directory=False):
    if not (stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode)):
        raise KeyStorageError()
    if os.name != "nt" and (value.st_uid != os.getuid() or value.st_mode & 0o077):
        raise KeyStorageError()


def _private_directory(folder: Path, *, create: bool) -> Path:
    """Create every missing private ancestor without depending on the umask.

    mkdir(parents=True) applies its mode only to the final directory. A fresh
    hosted profile can otherwise gain group-writable intermediate directories.
    Existing permissions are verified, never silently repaired.
    """
    folder = Path(folder)
    if not folder.is_absolute():
        raise KeyStorageError()
    _no_links(folder)
    missing = []
    if create:
        candidate = folder
        while not candidate.exists():
            missing.append(candidate)
            candidate = candidate.parent
        for candidate in reversed(missing):
            _no_links(candidate)
            new = False
            try:
                candidate.mkdir(mode=0o700)
                new = True
            except FileExistsError:
                pass  # A concurrent creator must meet the same requirements.
            _no_links(candidate)
            _private_mode(candidate.stat(), directory=True)
            if os.name == "nt":
                _windows_acl(candidate, set_private=new)
    _no_links(folder)
    _private_mode(folder.stat(), directory=True)
    if os.name == "nt":
        _windows_acl(folder)
    return folder


def _windows_acl(path, *, set_private=False):
    """Set on new objects or verify an owner-only native DACL on existing ones."""
    from ctypes import wintypes as w
    advapi = ctypes.WinDLL("advapi32.dll", use_last_error=True, winmode=0x800)
    kernel = ctypes.WinDLL("kernel32.dll", use_last_error=True, winmode=0x800)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [w.HLOCAL], w.HLOCAL
    advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    advapi.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes = [w.LPVOID, ctypes.POINTER(w.LPWSTR)]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(w.LPVOID), ctypes.POINTER(w.DWORD)]
    advapi.SetFileSecurityW.argtypes = [w.LPCWSTR, w.DWORD, w.LPVOID]
    advapi.GetNamedSecurityInfoW.argtypes = [w.LPWSTR, w.DWORD, w.DWORD, ctypes.POINTER(w.LPVOID),
                                           w.LPVOID, ctypes.POINTER(w.LPVOID), w.LPVOID, ctypes.POINTER(w.LPVOID)]
    advapi.GetNamedSecurityInfoW.restype = w.DWORD
    advapi.GetAclInformation.argtypes = [w.LPVOID, w.LPVOID, w.DWORD, ctypes.c_int]
    advapi.GetAce.argtypes = [w.LPVOID, w.DWORD, ctypes.POINTER(w.LPVOID)]
    token, length, sid, descriptor = w.HANDLE(), w.DWORD(), w.LPWSTR(), w.LPVOID()
    try:
        if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
            raise KeyStorageError()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(length))
        if not 0 < length.value <= 4096:
            raise KeyStorageError()
        buffer = ctypes.create_string_buffer(length.value)
        if not advapi.GetTokenInformation(token, 1, buffer, length, ctypes.byref(length)):
            raise KeyStorageError()
        if not advapi.ConvertSidToStringSidW(ctypes.cast(buffer, ctypes.POINTER(w.LPVOID))[0], ctypes.byref(sid)):
            raise KeyStorageError()
        current_sid = sid.value
        if set_private:
            # Elevated tokens default new objects' owner to BUILTIN\Administrators,
            # so set the user as owner explicitly with the protected DACL.
            if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                    "O:" + current_sid + "D:P(A;OICI;FA;;;" + current_sid + ")", 1, ctypes.byref(descriptor), None):
                raise KeyStorageError()
            if not advapi.SetFileSecurityW(str(path), 0x80000005, descriptor):
                raise KeyStorageError()
            kernel.LocalFree(descriptor)
            descriptor = w.LPVOID()
        owner, dacl = w.LPVOID(), w.LPVOID()
        if advapi.GetNamedSecurityInfoW(str(path), 1, 5, ctypes.byref(owner), None,
                                       ctypes.byref(dacl), None, ctypes.byref(descriptor)) or not dacl:
            raise KeyStorageError()
        def sid_text(pointer):
            result = w.LPWSTR()
            if not advapi.ConvertSidToStringSidW(pointer, ctypes.byref(result)):
                raise KeyStorageError()
            try:
                return result.value
            finally:
                kernel.LocalFree(result)
        if sid_text(owner) != current_sid:
            raise KeyStorageError()
        counts = (w.DWORD * 3)()
        if not advapi.GetAclInformation(dacl, counts, ctypes.sizeof(counts), 2) or not counts[0]:
            raise KeyStorageError()
        owner_allowed = False
        for index in range(counts[0]):
            ace = w.LPVOID()
            if not advapi.GetAce(dacl, index, ctypes.byref(ace)):
                raise KeyStorageError()
            # Only ordinary allow ACEs for the current owner or SYSTEM. Unknown
            # ACE forms fail closed rather than guessing their effective rights.
            if ctypes.c_ubyte.from_address(ace.value).value != 0:
                raise KeyStorageError()
            principal = sid_text(ace.value + 8)
            if principal not in {current_sid, "S-1-5-18"}:
                raise KeyStorageError()
            owner_allowed |= principal == current_sid
        if not owner_allowed:
            raise KeyStorageError()
    finally:
        if descriptor:
            kernel.LocalFree(descriptor)
        if sid:
            kernel.LocalFree(sid)
        if token:
            kernel.CloseHandle(token)


class _DPAPI(aead.Aead):
    def _run(self, data, context, protect):
        from ctypes import wintypes as w

        class Blob(ctypes.Structure):
            _fields_ = [("size", w.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

        crypt = ctypes.WinDLL("crypt32.dll", use_last_error=True, winmode=0x800)
        kernel = ctypes.WinDLL("kernel32.dll", use_last_error=True, winmode=0x800)
        kernel.LocalFree.argtypes, kernel.LocalFree.restype = [w.HLOCAL], w.HLOCAL
        incoming, entropy = ctypes.create_string_buffer(data), ctypes.create_string_buffer(context)
        value = Blob(len(data), ctypes.cast(incoming, ctypes.POINTER(ctypes.c_ubyte)))
        extra = Blob(len(context), ctypes.cast(entropy, ctypes.POINTER(ctypes.c_ubyte)))
        output = Blob()
        function = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(Blob), w.LPVOID, ctypes.POINTER(Blob), w.LPVOID, w.LPVOID, w.DWORD, ctypes.POINTER(Blob)]
        function.restype = w.BOOL
        try:
            # UI_FORBIDDEN only. Never LOCAL_MACHINE: no other-user decryption.
            if not function(ctypes.byref(value), None, ctypes.byref(extra), None, None, 1, ctypes.byref(output)):
                raise KeyStorageError()
            if not 0 < output.size <= _LIMIT:
                raise KeyStorageError()
            return ctypes.string_at(output.data, output.size)
        finally:
            if output.data:
                ctypes.memset(output.data, 0, output.size)
                kernel.LocalFree(output.data)

    def encrypt(self, plaintext, associated_data):
        return self._run(plaintext, associated_data, True)

    def decrypt(self, ciphertext, associated_data):
        return self._run(ciphertext, associated_data, False)


class _WindowsProtection:
    def create(self, context):
        return _DPAPI()

    def load(self, context):
        return _DPAPI()


class _SecretServiceProtection:
    def _get(self, context, create):
        # Explicit backend, no keyring auto-discovery or plaintext fallback.
        import secretstorage
        from secretstorage.collection import Collection, get_collection_by_alias
        from secretstorage.util import open_session

        connection = secretstorage.dbus_init()
        try:
            session = open_session(connection)
            if session.encrypted is not True:
                raise KeyStorageError()
            original = get_collection_by_alias(connection, "default")
            if original.collection_path.endswith("/session"):
                raise KeyStorageError()
            collection = Collection(connection, original.collection_path, session=session)
            collection.ensure_not_locked()
            attributes = {"application": "orion-hosted-v1", "scope": hashlib.sha256(context).hexdigest()}
            def matches(item):
                found = item.get_attributes()
                # Providers may add metadata such as xdg:schema on disk/restart.
                # Only the two exact Orion lookup bindings authorize this item.
                return all(found.get(name) == value for name, value in attributes.items())
            items = list(collection.search_items(attributes))
            aead.register()
            if create:
                if items:
                    raise KeyStorageError()
                key = tink.new_keyset_handle(aead.aead_key_templates.AES256_GCM)
                # Serialization stays in memory; Secret Service is the only sink.
                raw = proto_keyset_format.serialize(key, secret_key_access.TOKEN)
                item = collection.create_item("Saiph hosted recipient wrapping key", attributes, raw,
                                              replace=False, content_type="application/octet-stream")
                if not matches(item) or item.get_secret() != raw:
                    raise KeyStorageError()
            else:
                if len(items) != 1 or not matches(items[0]):
                    raise KeyStorageError()
                raw = items[0].get_secret()
                if not 0 < len(raw) <= 1024:
                    raise KeyStorageError()
                key = proto_keyset_format.parse(raw, secret_key_access.TOKEN)
            return key.primitive(aead.Aead)
        finally:
            connection.close()

    def create(self, context):
        return self._get(context, True)

    def load(self, context):
        return self._get(context, False)


class RecipientVault:
    """One hosted device's recipient key. No implicit initialization or reset.

    Use an application-private folder, never a selected sync/backup folder.
    Signing identity is supplied by the existing device identity subsystem.
    """

    def __init__(self, folder: Path, deployment_id: str, device_id: str, signing_public: str, *, _protection=None):
        try:
            self.folder = Path(folder)
            if not self.folder.is_absolute() or str(UUID(deployment_id)) != deployment_id:
                raise KeyStorageError()
            if type(device_id) is not str or not re.fullmatch(r"dev_[a-f0-9]{32}", device_id):
                raise KeyStorageError()
            read_signing_key(signing_public)
            self.binding = {"protocol_version": 1, "deployment_id": deployment_id,
                            "device_id": device_id, "signing_key": signing_public}
            self._protection = _protection
        except Exception:
            raise KeyStorageError() from None

    def _backend(self):
        if self._protection is not None:
            return self._protection
        if sys.platform == "win32":
            return _WindowsProtection()
        if sys.platform.startswith("linux"):
            return _SecretServiceProtection()
        raise KeyStorageError()

    def _context(self, public):
        read_public(public)
        return b"Orion/hosted-recipient-storage/v1\0" + canonical({**self.binding, "encryption_key": public})

    def _directory(self, create):
        _private_directory(self.folder, create=create)

    def _write(self, name, data):
        path = self.folder / name
        _no_links(path)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as output:
            _private_mode(os.fstat(output.fileno()))
            if os.name == "nt":
                _windows_acl(path, set_private=True)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        if os.name != "nt":
            directory = os.open(self.folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)

    def _read(self, name):
        path = self.folder / name
        _no_links(path)
        if os.name == "nt":
            _windows_acl(path)
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        with os.fdopen(fd, "rb") as source:
            _private_mode(os.fstat(source.fileno()))
            data = source.read(_LIMIT + 1)
        if not 0 < len(data) <= _LIMIT:
            raise KeyStorageError()
        return data

    def create(self):
        """Explicit new enrollment only; interrupted attempts are not retried."""
        try:
            self._directory(True)
            if (self.folder / "recipient.enc").exists():
                raise KeyStorageError()
            self._write("creation.started", b"Orion hosted recipient creation v1\n")
            key = generate_recipient()
            public = export_public(key)
            context = self._context(public)
            protection = self._backend().create(context)
            encrypted = proto_keyset_format.serialize_encrypted(key, protection, context)
            self._write("recipient.enc", encrypted)
            # Verify the durable bytes before returning a key for enrollment.
            loaded = self.load(public)
            return loaded
        except Exception:
            raise KeyStorageError() from None

    def load(self, expected_public: str):
        """Load only the exact already-enrolled recipient; never repair/reset."""
        try:
            self._directory(False)
            if self._read("creation.started") != b"Orion hosted recipient creation v1\n":
                raise KeyStorageError()
            context = self._context(expected_public)
            encrypted = self._read("recipient.enc")
            protection = self._backend().load(context)
            key = proto_keyset_format.parse_encrypted(encrypted, protection, context)
            if export_public(key) != expected_public:
                raise KeyStorageError()
            return key
        except Exception:
            raise KeyStorageError() from None
