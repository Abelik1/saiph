# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hosted account session: sign-in, restart, refresh, expiry and sign-out.

The access token lives only in memory. A refresh token is kept only when the
owner's configuration allows refresh tokens; it is OS-protected at rest and
replaced on every rotation. A refused refresh (expired, revoked or reused)
clears it and the account returns to "sign in again". Network failures keep
the stored token. Account tokens admit requests; they never establish device
trust or decryption authority.
"""
from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path

from .hosted_crypto import canonical
from .hosted_keys import KeyStorageError
from .hosted_login import (
    HostedLoginConfig, LoginAttempt, LoginError, RefreshRejected, refresh_access, revoke_refresh,
)
from .hosted_storage import ProtectedBlob

ACCESS_MARGIN_SECONDS = 60


class SignInRequired(Exception):
    def __init__(self):
        super().__init__("Sign in to Saiph Cloud again.")


class HostedUnavailable(Exception):
    def __init__(self):
        super().__init__("Saiph Cloud is unreachable. Your session was kept.")


class TokenVault:
    """One OS-protected rotating refresh token for one issuer/client/audience."""

    def __init__(self, folder: Path, config: HostedLoginConfig, *, protection=None):
        context = b"Orion/hosted-refresh-token/v1\0" + canonical(
            {"issuer": config.issuer, "audience": config.audience, "client_id": config.client_id})
        self._blob = ProtectedBlob(Path(folder), "refresh-token.enc", context, protection=protection)

    def present(self) -> bool:
        return self._blob.exists() and not (self._blob.folder / "signed-out").exists()

    def load(self) -> str | None:
        if (self._blob.folder / "signed-out").exists():
            return None
        raw = self._blob.load()
        if raw is None:
            return None
        try:
            token = raw.decode("ascii")
        except UnicodeError:
            raise KeyStorageError() from None
        if not token or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise KeyStorageError()
        return token

    def save(self, token: str) -> None:
        if type(token) is not str or not token.isascii():
            raise KeyStorageError()
        self._blob.save(token.encode("ascii"))
        (self._blob.folder / "signed-out").unlink(missing_ok=True)

    def clear(self) -> None:
        # A public tombstone prevents restart from restoring a token whose
        # deletion fails. A fresh explicit sign-in removes it after saving.
        if self._blob.folder.exists():
            (self._blob.folder / "signed-out").write_bytes(b"signed-out\n")
        self._blob.clear()


class HostedAccount:
    """Thread-safe account session; UI calls never wait for the browser."""

    def __init__(self, config: HostedLoginConfig, vault: TokenVault | None = None, *,
                 attempt_factory=LoginAttempt, refresher=refresh_access, revoker=revoke_refresh,
                 clock=time.time, on_change=lambda: None):
        if config.refresh_tokens and vault is None:
            raise ValueError("Refresh tokens need OS-protected storage.")
        self.config = config
        self._vault = vault if config.refresh_tokens else None
        self._attempt_factory = attempt_factory
        self._refresher, self._revoker = refresher, revoker
        self._clock, self._on_change = clock, on_change
        self._lock = threading.RLock()
        self._access = None
        self._signed_out = False
        self._expires_at = 0
        self._attempt = None
        self._thread = None
        self.error = ""
        try:
            self._stored = bool(self._vault and self._vault.present())
        except KeyStorageError:
            self._stored = False

    @property
    def status(self) -> str:
        with self._lock:
            if self._attempt is not None:
                return "signing_in"
            if self._signed_out:
                return "signed_out"
            if self._access is not None and self._expires_at - self._clock() > 0:
                return "signed_in"
            if self._access is not None and self._vault is None:
                return "expired"  # Without refresh tokens, expiry means a browser round trip.
            if self._stored:
                return "signed_in"  # Restart: refresh token restores the session lazily.
            return "expired" if self.error == SignInRequired().args[0] else "signed_out"

    def snapshot(self) -> dict:
        with self._lock:
            return {"status": self.status, "refresh_tokens": self.config.refresh_tokens, "error": self.error}

    def begin_sign_in(self, *, google: bool | None = None) -> str:
        """Open the system browser; the exchange completes on a worker thread."""
        with self._lock:
            if self._attempt is not None:
                raise ValueError("Sign-in is already open in your browser.")
            if google is not None and type(google) is not bool:
                raise ValueError("Choose a sign-in method.")
            attempt = self._attempt_factory(self.config if google is None else replace(self.config, google=google))
            self._attempt = attempt
            self.error = ""
        try:
            url = attempt.begin()
        except LoginError:
            with self._lock:
                if self._attempt is attempt:
                    self._attempt = None
                    self.error = "Sign-in did not complete."
            self._on_change()
            raise ValueError("Sign-in could not open your browser.") from None
        self._thread = threading.Thread(target=self._finish, args=(attempt,), name="orion-hosted-sign-in", daemon=True)
        self._thread.start()
        return url

    def _finish(self, attempt):
        try:
            grant = attempt.wait_grant()
            with self._lock:
                if self._attempt is attempt:
                    self._accept(grant)
        except (LoginError, KeyStorageError):
            with self._lock:
                if self._attempt is attempt:
                    self.error = "Sign-in did not complete."
        finally:
            with self._lock:
                if self._attempt is attempt:
                    self._attempt = None
            self._on_change()

    def _accept(self, grant):
        with self._lock:
            if self._vault is not None and grant.refresh_token:
                self._vault.save(grant.refresh_token)
                self._stored = True
            elif self._vault is not None:
                self._vault.clear()
                self._stored = False
            self._signed_out = False
            self._access, self._expires_at = grant.access_token, grant.expires_at
            self.error = ""

    def cancel_sign_in(self) -> None:
        with self._lock:
            attempt, self._attempt = self._attempt, None
        if attempt is not None:
            attempt.close()

    def access_token(self) -> str:
        """Return a usable access token, rotating the refresh token if needed."""
        with self._lock:
            if self._signed_out:
                raise SignInRequired()
            if self._access is not None and self._expires_at - self._clock() > ACCESS_MARGIN_SECONDS:
                return self._access
            self._access = None
            if self._vault is None:
                self._expired()
            try:
                stored = self._vault.load()
            except KeyStorageError:
                self.error = "This computer could not unlock the saved hosted session."
                raise SignInRequired() from None
            if stored is None:
                self._expired()
            try:
                grant = self._refresher(self.config, stored)
            except RefreshRejected:
                try:
                    self._vault.clear()
                finally:
                    self._stored = False
                self._expired()
            except LoginError:
                raise HostedUnavailable() from None
            # Persist the rotated token before using the new access token: a
            # crash must not leave only the already-consumed old token.
            self._vault.save(grant.refresh_token)
            self._access, self._expires_at = grant.access_token, grant.expires_at
            self.error = ""
            return self._access

    def _expired(self):
        self._stored = False
        self.error = SignInRequired().args[0]
        raise SignInRequired()

    def sign_out(self) -> None:
        """Forget local credentials first; server revocation is best effort."""
        self.cancel_sign_in()
        with self._lock:
            self._signed_out = True
            token = None
            if self._vault is not None:
                try:
                    token = self._vault.load()
                except KeyStorageError:
                    token = None
                try:
                    self._vault.clear()
                finally:
                    self._access, self._expires_at, self._stored = None, 0, False
            self._access, self._expires_at, self._stored, self.error = None, 0, False, ""
        if token:
            try:
                self._revoker(self.config, token)
            except Exception:
                pass
        self._on_change()
