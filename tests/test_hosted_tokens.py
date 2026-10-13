# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthetic session lifecycle and real encrypted refresh-storage regressions."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import os

import pytest
import tink
from tink import aead

from orion_mini.hosted_keys import KeyStorageError
from orion_mini.hosted_login import HostedLoginConfig, TokenGrant, LoginError, RefreshRejected
from orion_mini.hosted_storage import ProtectedBlob
from orion_mini.hosted_tokens import HostedAccount, TokenVault, SignInRequired, HostedUnavailable


class Protection:
    def __init__(self):
        aead.register()
        self.key = tink.new_keyset_handle(aead.aead_key_templates.AES256_GCM).primitive(aead.Aead)
        self.unavailable = False
        self.creates = 0

    def load(self, context):
        if self.unavailable:
            raise RuntimeError("synthetic sensitive native error")
        return self.key

    def create(self, context):
        self.creates += 1
        return self.key


class MemoryVault:
    def __init__(self, value=None):
        self.value = value
        self.saved = []

    def present(self):
        return self.value is not None

    def load(self):
        return self.value

    def save(self, value):
        self.saved.append(value)
        self.value = value

    def clear(self):
        self.value = None


def config(refresh=True, client="synthetic-desktop"):
    return HostedLoginConfig("https://synthetic.example/", "https://synthetic.example/api", client,
                             refresh_tokens=refresh)


def test_encrypted_refresh_token_survives_restart_but_not_context_substitution(tmp_path):
    protection = Protection()
    vault = TokenVault(tmp_path / "tokens", config(), protection=protection)
    vault.save("synthetic-old-refresh")
    raw = vault._blob.path.read_bytes()
    assert b"synthetic-old-refresh" not in raw
    restarted = TokenVault(vault._blob.folder, config(), protection=protection)
    assert restarted.load() == "synthetic-old-refresh"
    with pytest.raises(KeyStorageError):
        TokenVault(vault._blob.folder, config(client="different-client"), protection=protection).load()
    vault.save("synthetic-rotated-refresh")
    assert restarted.load() == "synthetic-rotated-refresh"
    assert vault._blob.path.read_bytes() != raw
    vault.clear()
    assert restarted.load() is None


def test_unavailable_wrapping_key_never_recreates_or_replaces_existing_secret(tmp_path):
    protection = Protection()
    blob = ProtectedBlob(tmp_path / "protected", "token.enc", b"synthetic-context", protection=protection)
    blob.save(b"synthetic-original")
    original = blob.path.read_bytes()
    protection.unavailable = True
    with pytest.raises(KeyStorageError):
        blob.save(b"synthetic-replacement")
    assert protection.creates == 0
    assert blob.path.read_bytes() == original
    protection.unavailable = False
    assert blob.load() == b"synthetic-original"


@pytest.mark.skipif(os.name == "nt", reason="POSIX umask and modes")
@pytest.mark.parametrize("profile_entry", ["default", "store"])
def test_fresh_nested_secret_storage_is_private_with_group_writable_umask(tmp_path, monkeypatch, profile_entry):
    from orion_mini.paths import app_data_dir
    from orion_mini.storage import Store
    profile = tmp_path / "profile"
    monkeypatch.setenv("ORION_MINI_DATA_DIR", str(profile))
    folder = profile / "hosted" / "account"
    blob = ProtectedBlob(folder, "token.enc", b"synthetic-context", protection=Protection())
    previous = os.umask(0o002)
    try:
        if profile_entry == "default":
            assert app_data_dir() == profile
        else:
            Store(profile)
        blob.save(b"synthetic-refresh")
    finally:
        os.umask(previous)
    for directory in (folder, folder.parent, folder.parent.parent):
        assert directory.stat().st_mode & 0o777 == 0o700
    assert blob.load() == b"synthetic-refresh"
    assert b"synthetic-refresh" not in blob.path.read_bytes()


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory modes")
def test_existing_group_writable_parent_is_rejected_without_repair(tmp_path, monkeypatch):
    import grp
    import types
    # A group shared with another account; a user private group is accepted (see test_hosted_keys).
    monkeypatch.setattr(grp, "getgrgid", lambda gid: types.SimpleNamespace(gr_gid=gid, gr_mem=["synthetic-other"]))
    parent = tmp_path / "shared"
    parent.mkdir()
    parent.chmod(0o770)
    blob = ProtectedBlob(parent / "account", "token.enc", b"synthetic-context", protection=Protection())
    with pytest.raises(KeyStorageError):
        blob.save(b"synthetic-refresh")
    assert parent.stat().st_mode & 0o777 == 0o770
    assert not blob.folder.exists()


def test_restart_and_concurrent_expiry_rotate_once_before_returning_access():
    vault = MemoryVault("synthetic-old-refresh")
    calls = []

    def refresh(_, token):
        calls.append(token)
        return TokenGrant("synthetic-new-access", 5000, "synthetic-rotated-refresh")

    account = HostedAccount(config(), vault, refresher=refresh, clock=lambda: 1000)
    assert account.status == "signed_in"
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: account.access_token(), range(4)))
    assert results == ["synthetic-new-access"] * 4
    assert calls == ["synthetic-old-refresh"]
    assert vault.saved == ["synthetic-rotated-refresh"]


def test_refresh_network_failure_preserves_credentials_but_never_returns_expired_access():
    vault = MemoryVault("synthetic-refresh")

    def unavailable(*_):
        raise LoginError()

    account = HostedAccount(config(), vault, refresher=unavailable, clock=lambda: 1000)
    account._accept(TokenGrant("synthetic-expired-access", 999, "synthetic-refresh"))
    with pytest.raises(HostedUnavailable):
        account.access_token()
    assert vault.value == "synthetic-refresh"
    assert account._access is None


def test_revoked_refresh_clears_saved_session_and_requires_browser_sign_in():
    vault = MemoryVault("synthetic-revoked-refresh")

    def rejected(*_):
        raise RefreshRejected()

    account = HostedAccount(config(), vault, refresher=rejected, clock=lambda: 1000)
    with pytest.raises(SignInRequired):
        account.access_token()
    assert vault.value is None
    assert account.status == "expired"
    assert "synthetic-revoked" not in str(account.snapshot())


def test_session_without_refresh_expires_without_writing_any_vault():
    vault = MemoryVault()
    now = [1000]
    account = HostedAccount(config(refresh=False), vault, clock=lambda: now[0])
    account._accept(TokenGrant("synthetic-memory-access", 1200, "must-not-be-saved"))
    assert account.access_token() == "synthetic-memory-access"
    assert vault.saved == []
    assert "synthetic-memory-access" not in str(account.snapshot())
    now[0] = 1201
    with pytest.raises(SignInRequired):
        account.access_token()


def test_browser_reauthentication_without_refresh_does_not_restore_previous_grant():
    vault = MemoryVault("synthetic-previous-account-refresh")
    calls = []

    def refresh(*args):
        calls.append(args)
        return TokenGrant("previous-account-access", 9000, "previous-account-refresh")

    account = HostedAccount(config(), vault, refresher=refresh, clock=lambda: 1000)
    account._accept(TokenGrant("synthetic-new-account-access", 1100, None))
    assert vault.value is None
    account._expires_at = 999
    with pytest.raises(SignInRequired):
        account.access_token()
    assert calls == []


def test_sign_out_cannot_be_undone_by_a_late_browser_exchange():
    entered, release = Event(), Event()

    class Attempt:
        def __init__(self, _):
            pass

        def begin(self):
            return "https://synthetic.example/authorize"

        def wait_grant(self):
            entered.set()
            assert release.wait(3)
            return TokenGrant("synthetic-late-access", 5000, "synthetic-late-refresh")

        def close(self):
            pass

    vault = MemoryVault()
    account = HostedAccount(config(), vault, attempt_factory=Attempt, clock=lambda: 1000)
    account.begin_sign_in()
    assert entered.wait(3)
    account.sign_out()
    release.set()
    account._thread.join(3)
    assert not account._thread.is_alive()
    assert account.status == "signed_out"
    assert vault.value is None and account._access is None


def test_sign_out_clears_local_credentials_even_when_remote_revocation_fails():
    vault = MemoryVault("synthetic-refresh")
    revoked = []

    def revoke(_, token):
        revoked.append(token)
        raise LoginError()

    account = HostedAccount(config(), vault, revoker=revoke, clock=lambda: 1000)
    account._accept(TokenGrant("synthetic-access", 5000, "synthetic-refresh"))
    account.sign_out()
    assert revoked == ["synthetic-refresh"]
    assert vault.value is None and account._access is None
    assert account.status == "signed_out"


def test_token_deletion_failure_signs_out_in_memory_and_cannot_refresh_old_grant():
    class LockedVault(MemoryVault):
        fail_clear = True

        def clear(self):
            if self.fail_clear:
                raise KeyStorageError()
            super().clear()

    vault = LockedVault("synthetic-saved-refresh")
    refreshed = []

    def refresh(_, token):
        refreshed.append(token)
        return TokenGrant("synthetic-resurrected-access", 5000, "synthetic-resurrected-refresh")

    account = HostedAccount(config(), vault, refresher=refresh, clock=lambda: 1000)
    account._accept(TokenGrant("synthetic-access", 5000, "synthetic-saved-refresh"))
    with pytest.raises(KeyStorageError):
        account.sign_out()
    assert account._access is None and account._expires_at == 0
    assert account.status == "signed_out"
    assert vault.value == "synthetic-saved-refresh"  # Do not claim disk erasure succeeded.
    with pytest.raises(SignInRequired):
        account.access_token()
    assert refreshed == []  # Scheduler must not revive the token that survived unlink.
    vault.fail_clear = False
    account._accept(TokenGrant("synthetic-explicit-new-login", 5000, "synthetic-new-refresh"))
    assert account.access_token() == "synthetic-explicit-new-login"


def test_cancelled_browser_open_failure_cannot_erase_newer_sign_in():
    old_entered, old_release, new_entered, new_release = Event(), Event(), Event(), Event()
    attempts = []

    class Attempt:
        def __init__(self, _):
            self.number = len(attempts)
            attempts.append(self)

        def begin(self):
            if self.number == 0:
                old_entered.set()
                assert old_release.wait(5)
                raise LoginError()
            return "https://synthetic.example/authorize"

        def wait_grant(self):
            new_entered.set()
            assert new_release.wait(5)
            return TokenGrant("synthetic-current-access", 5000, "synthetic-current-refresh")

        def close(self):
            pass

    vault = MemoryVault()
    account = HostedAccount(config(), vault, attempt_factory=Attempt, clock=lambda: 1000)
    with ThreadPoolExecutor(max_workers=1) as executor:
        old_result = executor.submit(account.begin_sign_in)
        try:
            assert old_entered.wait(5)
            account.cancel_sign_in()
            account.begin_sign_in()
            assert new_entered.wait(5)
            old_release.set()
            with pytest.raises(ValueError, match="could not open"):
                old_result.result(timeout=5)
            assert account.status == "signing_in"
            assert account.error == ""
        finally:
            old_release.set()
            new_release.set()
    account._thread.join(5)
    assert not account._thread.is_alive()
    assert account.access_token() == "synthetic-current-access"
    assert vault.value == "synthetic-current-refresh"
