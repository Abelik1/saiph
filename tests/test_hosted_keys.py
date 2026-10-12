# SPDX-License-Identifier: AGPL-3.0-or-later
"""Key-vault failure tests with real Tink plus actual Windows DPAPI checks."""
import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import os
import subprocess
import types
from uuid import uuid4

import pytest

pytest.importorskip("tink")
import tink
from tink import aead, proto_keyset_format, secret_key_access
from cryptography.hazmat.primitives.asymmetric import ec

from orion_mini.hosted_crypto import export_public, generate_recipient, open_envelope, seal
from orion_mini.hosted_session import public_signing_key
from orion_mini import hosted_keys as keys


class Protection:
    def __init__(self):
        aead.register()
        self.key = tink.new_keyset_handle(aead.aead_key_templates.AES256_GCM).primitive(aead.Aead)
        self.creates = 0
        self.loads = 0
        self.unavailable = False

    def create(self, context):
        self.creates += 1
        if self.unavailable:
            raise RuntimeError("sensitive native error")
        return self.key

    def load(self, context):
        self.loads += 1
        if self.unavailable:
            raise RuntimeError("sensitive native error")
        return self.key


@pytest.fixture
def setup(tmp_path):
    protection = Protection()
    deployment, device = str(uuid4()), "dev_" + uuid4().hex
    signing = ec.generate_private_key(ec.SECP256R1())
    public = public_signing_key(signing.public_key())
    folder = tmp_path / "recipient"
    vault = keys.RecipientVault(folder, deployment, device, public, _protection=protection)
    return vault, protection, signing


def test_roundtrip_restart_real_encryption_and_no_plaintext_file(setup):
    vault, backend, signing = setup
    handle = vault.create()
    public = export_public(handle)
    restarted = keys.RecipientVault(vault.folder, vault.binding["deployment_id"], vault.binding["device_id"],
                                    vault.binding["signing_key"], _protection=backend)
    loaded = restarted.load(public)
    header = {"protocol_version": 1, "deployment_id": vault.binding["deployment_id"], "roster_version": 1,
              "roster_hash": "a" * 64, "id": str(uuid4()), "source": "dev_" + "1" * 32,
              "target": vault.binding["device_id"], "expires_at": 1_900_000_000}
    envelope = seal(public, signing, header, {"type": "synthetic", "text": "private-vault-test"})
    assert open_envelope(loaded, signing.public_key(), header, envelope)["type"] == "synthetic"
    raw_private = proto_keyset_format.serialize(handle, secret_key_access.TOKEN)
    for file in vault.folder.iterdir():
        assert raw_private not in file.read_bytes()
        assert b"private-vault-test" not in file.read_bytes()
    assert backend.creates == 1


def test_absent_load_never_creates(setup):
    vault, backend, _ = setup
    with pytest.raises(keys.KeyStorageError):
        vault.load(export_public(generate_recipient()))
    assert backend.creates == backend.loads == 0
    assert not vault.folder.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX umask and modes")
def test_fresh_nested_vault_is_private_with_group_writable_umask(setup):
    vault, backend, _ = setup
    vault.folder = vault.folder / "hosted" / "recipient"
    previous = os.umask(0o002)
    try:
        public = export_public(vault.create())
    finally:
        os.umask(previous)
    for directory in (vault.folder, vault.folder.parent, vault.folder.parent.parent):
        assert directory.stat().st_mode & 0o777 == 0o700
    assert export_public(vault.load(public)) == public
    assert backend.creates == 1


def test_second_create_preserves_bytes(setup):
    vault, backend, _ = setup
    handle = vault.create()
    saved = (vault.folder / "recipient.enc").read_bytes()
    with pytest.raises(keys.KeyStorageError):
        vault.create()
    assert (vault.folder / "recipient.enc").read_bytes() == saved
    assert export_public(vault.load(export_public(handle))) == export_public(handle)
    assert backend.creates == 1


def test_concurrent_create_has_exactly_one_identity(setup):
    vault, backend, _ = setup
    def attempt():
        try:
            return export_public(vault.create())
        except keys.KeyStorageError:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: attempt(), range(4)))
    winners = [r for r in results if r]
    assert len(winners) == backend.creates == 1
    assert export_public(vault.load(winners[0])) == winners[0]


@pytest.mark.parametrize("failure", ["backend", "serialization", "write"])
def test_partial_creation_is_terminal_and_native_errors_are_redacted(setup, monkeypatch, failure):
    vault, backend, _ = setup
    if failure == "backend":
        backend.unavailable = True
    elif failure == "serialization":
        monkeypatch.setattr(proto_keyset_format, "serialize_encrypted", lambda *a: (_ for _ in ()).throw(RuntimeError("private-key-material")))
    else:
        real = vault._write
        def fail(name, data):
            if name == "recipient.enc":
                raise OSError("private-key-material")
            real(name, data)
        monkeypatch.setattr(vault, "_write", fail)
    with pytest.raises(keys.KeyStorageError) as error:
        vault.create()
    assert "private-key-material" not in str(error.value)
    assert "sensitive" not in str(error.value)
    assert error.value.__cause__ is None and error.value.__suppress_context__
    assert (vault.folder / "creation.started").is_file()
    backend.unavailable = False
    creates = backend.creates
    with pytest.raises(keys.KeyStorageError):
        vault.create()
    assert backend.creates == creates


@pytest.mark.parametrize("missing", ["creation.started", "recipient.enc"])
def test_missing_existing_material_never_regenerates(setup, missing):
    vault, backend, _ = setup
    public = export_public(vault.create())
    (vault.folder / missing).unlink()
    with pytest.raises(keys.KeyStorageError):
        vault.load(public)
    with pytest.raises(keys.KeyStorageError):
        vault.create()
    assert backend.creates == 1


@pytest.mark.parametrize("content", [b"", b"broken", b"x" * 16385], ids=["empty", "invalid", "oversized"])
def test_corrupt_or_oversized_keyset_is_preserved(setup, content):
    vault, backend, _ = setup
    public = export_public(vault.create())
    path = vault.folder / "recipient.enc"
    path.write_bytes(content)
    with pytest.raises(keys.KeyStorageError):
        vault.load(public)
    assert path.read_bytes() == content
    assert backend.creates == 1


@pytest.mark.parametrize("field", ["deployment_id", "device_id", "signing_key", "recipient"])
def test_context_or_public_key_substitution_fails(setup, field):
    vault, backend, _ = setup
    public = export_public(vault.create())
    binding = dict(vault.binding)
    if field == "recipient":
        public = export_public(generate_recipient())
    else:
        binding[field] = {"deployment_id": str(uuid4()), "device_id": "dev_" + uuid4().hex,
                          "signing_key": public_signing_key(ec.generate_private_key(ec.SECP256R1()).public_key())}[field]
    changed = keys.RecipientVault(vault.folder, binding["deployment_id"], binding["device_id"],
                                 binding["signing_key"], _protection=backend)
    with pytest.raises(keys.KeyStorageError):
        changed.load(public)
    assert backend.creates == 1


def test_locked_backend_preserves_key(setup):
    vault, backend, _ = setup
    public = export_public(vault.create())
    saved = (vault.folder / "recipient.enc").read_bytes()
    backend.unavailable = True
    with pytest.raises(keys.KeyStorageError):
        vault.load(public)
    backend.unavailable = False
    assert export_public(vault.load(public)) == public
    assert (vault.folder / "recipient.enc").read_bytes() == saved


@pytest.mark.parametrize("name", ["creation.started", "recipient.enc"])
def test_symlink_material_rejected(setup, tmp_path, name):
    vault, _, _ = setup
    public = export_public(vault.create())
    path = vault.folder / name
    target = tmp_path / "original"
    path.rename(target)
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(keys.KeyStorageError):
        vault.load(public)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
@pytest.mark.parametrize("name", [None, "creation.started", "recipient.enc"])
def test_broad_permissions_rejected(setup, name):
    vault, _, _ = setup
    public = export_public(vault.create())
    (vault.folder / name if name else vault.folder).chmod(0o777)
    with pytest.raises(keys.KeyStorageError):
        vault.load(public)


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows DPAPI")
def test_native_dpapi_persistence_context_and_tamper(tmp_path):
    vault = keys.RecipientVault(tmp_path / "native", str(uuid4()), "dev_" + uuid4().hex,
                                public_signing_key(ec.generate_private_key(ec.SECP256R1()).public_key()))
    public = export_public(vault.create())
    assert export_public(vault.load(public)) == public
    path = vault.folder / "recipient.enc"
    content = bytearray(path.read_bytes())
    content[-1] ^= 1
    path.write_bytes(content)
    with pytest.raises(keys.KeyStorageError):
        vault.load(public)


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows DPAPI")
def test_native_dpapi_rejects_other_binding():
    native = keys._DPAPI()
    sealed = native.encrypt(b"synthetic-dpapi-secret", b"bound-device")
    assert native.decrypt(sealed, b"bound-device") == b"synthetic-dpapi-secret"
    with pytest.raises(keys.KeyStorageError):
        native.decrypt(sealed, b"other-device")


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows DACL")
@pytest.mark.parametrize("name", [None, "creation.started", "recipient.enc"])
def test_native_windows_rejects_existing_broad_acl_without_repair(setup, name):
    vault, _, _ = setup
    public = export_public(vault.create())
    path = vault.folder / name if name else vault.folder
    tool = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/icacls.exe"
    try:
        subprocess.run([str(tool), str(path), "/grant", "*S-1-1-0:(F)"], check=True,
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        with pytest.raises(keys.KeyStorageError):
            vault.load(public)
        # Rejection must not silently repair or erase the caller's original ACL.
        checked = subprocess.run([str(tool), str(path)], check=True, capture_output=True,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        assert b"Everyone" in checked.stdout or b"S-1-1-0" in checked.stdout
    finally:
        keys._windows_acl(path, set_private=True)


def _windows_owner_sid(path):
    from ctypes import wintypes as w
    import ctypes
    advapi = ctypes.WinDLL("advapi32.dll", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    advapi.GetNamedSecurityInfoW.argtypes = [w.LPWSTR, w.DWORD, w.DWORD, ctypes.POINTER(w.LPVOID),
                                           w.LPVOID, w.LPVOID, w.LPVOID, ctypes.POINTER(w.LPVOID)]
    advapi.ConvertSidToStringSidW.argtypes = [w.LPVOID, ctypes.POINTER(w.LPWSTR)]
    kernel.LocalFree.argtypes = [w.HLOCAL]
    owner, descriptor, text = w.LPVOID(), w.LPVOID(), w.LPWSTR()
    assert advapi.GetNamedSecurityInfoW(str(path), 1, 1, ctypes.byref(owner), None, None, None,
                                        ctypes.byref(descriptor)) == 0
    try:
        assert advapi.ConvertSidToStringSidW(owner, ctypes.byref(text))
        try:
            return text.value
        finally:
            kernel.LocalFree(text)
    finally:
        kernel.LocalFree(descriptor)


def _windows_elevated():
    import ctypes
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows owner")
def test_native_windows_private_material_is_owned_by_user_even_when_elevated(setup):
    # Elevated tokens (e.g. CI runners) default new objects' owner to Administrators.
    vault, _, _ = setup
    vault.create()
    user = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], check=True, capture_output=True,
                          text=True, creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip().split(",")[-1].strip('"')
    for path in (vault.folder, vault.folder / "creation.started", vault.folder / "recipient.enc"):
        assert _windows_owner_sid(path) == user


@pytest.mark.skipif(sys.platform != "win32" or not _windows_elevated(), reason="Needs elevated Windows token")
@pytest.mark.parametrize("name", [None, "recipient.enc"])
def test_native_windows_rejects_administrators_owner_without_repair(setup, name):
    vault, _, _ = setup
    public = export_public(vault.create())
    path = vault.folder / name if name else vault.folder
    tool = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/icacls.exe"
    try:
        subprocess.run([str(tool), str(path), "/setowner", "*S-1-5-32-544"], check=True,
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        with pytest.raises(keys.KeyStorageError):
            vault.load(public)
        assert _windows_owner_sid(path) == "S-1-5-32-544"
    finally:
        keys._windows_acl(path, set_private=True)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX ancestor permissions")
def test_other_user_writable_parent_rejected(tmp_path):
    parent = tmp_path / "untrusted"
    parent.mkdir(mode=0o777)
    parent.chmod(0o777)
    vault = keys.RecipientVault(parent / "vault", str(uuid4()), "dev_" + uuid4().hex,
                                public_signing_key(ec.generate_private_key(ec.SECP256R1()).public_key()),
                                _protection=Protection())
    with pytest.raises(keys.KeyStorageError):
        vault.create()
    assert not vault.folder.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX directory fsync")
def test_marker_directory_sync_failure_prevents_master_creation(setup, monkeypatch):
    vault, backend, _ = setup
    original = os.fsync
    def fail_directory(fd):
        import stat
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("directory sync unavailable")
        original(fd)
    monkeypatch.setattr(os, "fsync", fail_directory)
    with pytest.raises(keys.KeyStorageError):
        vault.create()
    assert backend.creates == 0
    assert (vault.folder / "creation.started").exists()


def test_secret_service_rejects_plain_session_before_any_secret_access(monkeypatch):
    calls = []
    connection = types.SimpleNamespace(close=lambda: calls.append("close"))
    monkeypatch.setitem(sys.modules, "secretstorage", types.SimpleNamespace(dbus_init=lambda: connection))
    monkeypatch.setitem(sys.modules, "secretstorage.collection", types.SimpleNamespace(
        Collection=lambda *a, **k: calls.append("collection"),
        get_collection_by_alias=lambda *a: calls.append("alias")))
    monkeypatch.setitem(sys.modules, "secretstorage.util", types.SimpleNamespace(
        open_session=lambda *a: types.SimpleNamespace(encrypted=False)))
    for action in (keys._SecretServiceProtection().create, keys._SecretServiceProtection().load):
        with pytest.raises(keys.KeyStorageError):
            action(b"public-context")
    assert calls == ["close", "close"]


@pytest.mark.parametrize("failure", [None, "wrong_scope", "wrong_app", "duplicate", "locked"])
def test_secret_service_exact_binding_accepts_native_extra_metadata(monkeypatch, failure):
    context = b"synthetic-binding"
    attrs = {"application": "orion-hosted-v1", "scope": hashlib.sha256(context).hexdigest(),
             "xdg:schema": "org.freedesktop.Secret.Generic"}
    aead.register()
    raw = proto_keyset_format.serialize(tink.new_keyset_handle(aead.aead_key_templates.AES256_GCM), secret_key_access.TOKEN)
    if failure == "wrong_scope":
        attrs["scope"] = "0" * 64
    if failure == "wrong_app":
        attrs["application"] = "other-app"
    item = types.SimpleNamespace(get_attributes=lambda: dict(attrs), get_secret=lambda: raw)
    calls = []
    def unlocked():
        if failure == "locked":
            raise keys.KeyStorageError()
    collection = types.SimpleNamespace(ensure_not_locked=unlocked,
                                       search_items=lambda a: [item, item] if failure == "duplicate" else [item])
    connection = types.SimpleNamespace(close=lambda: calls.append("closed"))
    monkeypatch.setitem(sys.modules, "secretstorage", types.SimpleNamespace(dbus_init=lambda: connection))
    monkeypatch.setitem(sys.modules, "secretstorage.collection", types.SimpleNamespace(
        Collection=lambda *a, **k: collection,
        get_collection_by_alias=lambda *a: types.SimpleNamespace(collection_path="/collection/login")))
    monkeypatch.setitem(sys.modules, "secretstorage.util", types.SimpleNamespace(
        open_session=lambda *a: types.SimpleNamespace(encrypted=True)))
    if failure:
        with pytest.raises(keys.KeyStorageError):
            keys._SecretServiceProtection().load(context)
    else:
        loaded = keys._SecretServiceProtection().load(context)
        assert loaded.decrypt(loaded.encrypt(b"synthetic", b"context"), b"context") == b"synthetic"
    assert calls == ["closed"]
