# SPDX-License-Identifier: AGPL-3.0-or-later
"""Native API authorization for the opt-in Saiph Cloud preview.

Uses the system browser and Authlib's OAuth2/PKCE implementation. Requests no
OpenID scope and consumes no ID token. By default it requests no offline scope
and keeps no refresh token. Only a configuration that explicitly enables
refresh tokens requests `offline_access`; the caller then owns OS-protected
storage of the rotating refresh token (see `hosted_tokens`). This module never
persists credentials. The hosted API authenticates access tokens independently.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import secrets
import socket
import threading
import time
from typing import Callable
from urllib.parse import parse_qs, urlsplit
import webbrowser

from authlib.integrations.requests_client import OAuth2Session
import requests


CALLBACK_PATH = "/orion/auth/callback"


class LoginError(Exception):
    def __init__(self) -> None:
        super().__init__("Sign-in did not complete")


class RefreshRejected(LoginError):
    """The authorization server refused the refresh token: sign in again.

    Covers expiry, revocation and rotating-token reuse detection. Network
    failures raise plain LoginError so a still-valid token is kept.
    """


@dataclass(frozen=True)
class TokenGrant:
    access_token: str = field(repr=False)
    expires_at: int
    refresh_token: str | None = field(default=None, repr=False)


def _token_text(value, limit=16384):
    return (isinstance(value, str) and 0 < len(value) <= limit
            and not any(ord(c) < 33 or ord(c) > 126 for c in value))


def _grant(payload, *, refresh_allowed, now=None):
    """Validate a token response; never retain an ID token or extra fields."""
    if type(payload) is not dict:
        raise LoginError()
    access = payload.get("access_token")
    if not _token_text(access) or str(payload.get("token_type", "")).lower() != "bearer":
        raise LoginError()
    expires_in = payload.get("expires_in", 300)
    if type(expires_in) is not int or not 1 <= expires_in <= 86400:
        raise LoginError()
    refresh = payload.get("refresh_token") if refresh_allowed else None
    if refresh is not None and not _token_text(refresh, 4096):
        raise LoginError()
    return TokenGrant(access, int(time.time() if now is None else now) + expires_in, refresh)


@dataclass(frozen=True)
class HostedLoginConfig:
    issuer: str
    audience: str
    client_id: str
    callback_port: int = 49172
    refresh_tokens: bool = False
    google: bool = False

    def __post_init__(self) -> None:
        issuer = urlsplit(self.issuer)
        if (
            issuer.scheme != "https" or not issuer.hostname
            or issuer.username is not None or issuer.password is not None
            or issuer.port not in (None, 443) or issuer.path != "/"
            or issuer.query or issuer.fragment or not self.issuer.endswith("/")
            or not isinstance(self.audience, str) or not self.audience.strip()
            or not isinstance(self.client_id, str) or not self.client_id.strip()
            or self.audience == self.client_id
            or type(self.callback_port) is not int or not 1024 <= self.callback_port <= 65535
            or type(self.refresh_tokens) is not bool
            or type(self.google) is not bool
        ):
            raise ValueError("Fixed HTTPS issuer, API audience and public native client ID are required")


class LoginAttempt:
    def __init__(
        self,
        config: HostedLoginConfig,
        *,
        browser_opener: Callable[[str], bool] = webbrowser.open,
        oauth_factory=OAuth2Session,
        timeout_seconds: float = 300,
    ) -> None:
        if not 0 < timeout_seconds <= 300:
            raise ValueError("Sign-in timeout must be between zero and 300 seconds")
        self.config = config
        self._browser_opener = browser_opener
        self._oauth_factory = oauth_factory
        self._timeout_seconds = timeout_seconds
        self._server = None
        self._thread = None
        self._session = None
        self._state = ""
        self._verifier = ""
        self._nonce = ""
        self._deadline = 0.0
        self._redirect_uri = ""
        self._access_token = None
        self._grant = None
        self._claimed = False
        self._closed = False
        self._started = False
        self._lock = threading.Lock()
        self._done = threading.Event()

    @property
    def redirect_uri(self) -> str:
        return self._redirect_uri

    def begin(self) -> str:
        """Start a single loopback attempt, open the browser and return its URL."""
        with self._lock:
            if self._started or self._closed:
                raise LoginError()
            self._started = True
        attempt = self

        class QuietServer(HTTPServer):
            def server_bind(self):
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    self.allow_reuse_address = False
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                super().server_bind()

            def handle_error(self, request, client_address):
                pass

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                self.request.settimeout(2)
                super().setup()

            def log_message(self, format, *args):
                pass  # The default HTTP logger would disclose authorization codes.

            def send_error(self, code, message=None, explain=None):
                self.respond(code, False)

            def respond(self, status, success):
                body = ("Sign-in complete. You may close this window." if success
                        else "Sign-in did not complete. Return to Saiph.").encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                try:
                    if self.headers.get_all("Host") != [urlsplit(attempt.redirect_uri).netloc]:
                        raise LoginError()
                    attempt.consume_callback(self.path)
                except LoginError:
                    self.respond(400, False)
                else:
                    self.respond(200, True)

            def do_POST(self):
                self.respond(405, False)

        try:
            # Auth0 registration uses this exact callback. Never fall back to
            # another port or widen the listener when it is already occupied.
            self._server = QuietServer(("127.0.0.1", self.config.callback_port), Handler)
            self._server.timeout = 0.1
            self._redirect_uri = f"http://127.0.0.1:{self._server.server_port}{CALLBACK_PATH}"
            self._state = secrets.token_urlsafe(32)
            self._verifier = secrets.token_urlsafe(64)
            self._nonce = secrets.token_urlsafe(32)
            self._deadline = time.monotonic() + self._timeout_seconds
            self._session = self._oauth_factory(
                client_id=self.config.client_id,
                token_endpoint_auth_method="none",
                scope="offline_access" if self.config.refresh_tokens else "",
                state=self._state,
                redirect_uri=self.redirect_uri,
                code_challenge_method="S256",
                default_timeout=5,
            )
            def check_response(response):
                if response.status_code != 200 or len(response.content) > 65536:
                    raise LoginError()
                return response
            self._session.register_compliance_hook("access_token_response", check_response)
            url, state = self._session.create_authorization_url(
                self.config.issuer + "authorize",
                state=self._state,
                code_verifier=self._verifier,
                audience=self.config.audience,
                nonce=self._nonce,
                response_mode="query",
                **({"connection": "google-oauth2"} if self.config.google
                   and urlsplit(self.config.issuer).hostname.endswith(".auth0.com") else {}),
            )
            if state != self._state:
                raise LoginError()
            self._thread = threading.Thread(target=self._listen, name="orion-hosted-login", daemon=True)
            self._thread.start()
            if not self._browser_opener(url):
                raise LoginError()
            return url
        except Exception:
            self.close()
            raise LoginError() from None

    def _listen(self) -> None:
        try:
            while not self._done.is_set() and time.monotonic() < self._deadline:
                self._server.handle_request()
        except Exception:
            pass  # No callback or transport details may reach logs.
        finally:
            self._done.set()
            self._server.server_close()

    def consume_callback(self, target: str) -> str:
        """Validate an origin-form callback and perform one PKCE exchange."""
        try:
            if not isinstance(target, str) or len(target) > 4096:
                raise LoginError()
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or parsed.fragment or parsed.path != CALLBACK_PATH:
                raise LoginError()
            params = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=8)
            if any(len(values) != 1 for values in params.values()):
                raise LoginError()
            if set(params) - {"code", "state", "iss", "error", "error_description", "error_uri"}:
                raise LoginError()
            state = params.get("state", [""])[0]
            if not state or not secrets.compare_digest(state, self._state):
                raise LoginError()
            if "iss" in params and params["iss"][0] != self.config.issuer:
                raise LoginError()
            code = params.get("code", [""])[0]
            if "error" not in params and (not code or len(code) > 2048 or any(ord(c) < 33 or ord(c) > 126 for c in code)):
                raise LoginError()
            if "error" not in params and any(name in params for name in ("error_description", "error_uri")):
                raise LoginError()
            with self._lock:
                if not self._started or self._closed or self._claimed or time.monotonic() >= self._deadline:
                    raise LoginError()
                self._claimed = True
            if "error" in params:
                self._done.set()
                raise LoginError()
            try:
                token = self._session.fetch_token(
                    self.config.issuer + "oauth/token",
                    grant_type="authorization_code",
                    code=code,
                    code_verifier=self._verifier,
                    redirect_uri=self.redirect_uri,
                    timeout=5,
                    allow_redirects=False,
                )
                access = token.get("access_token")
                if (not isinstance(access, str) or not access or len(access) > 16384
                        or any(ord(c) < 33 or ord(c) > 126 for c in access)
                        or token.get("token_type", "").lower() != "bearer"):
                    raise LoginError()
                grant = _grant(dict(token), refresh_allowed=self.config.refresh_tokens)
                with self._lock:
                    if self._closed or time.monotonic() >= self._deadline:
                        raise LoginError()
                    self._access_token = access
                    self._grant = grant
                return access
            finally:
                self._session.token = None
                self._verifier = ""
                self._done.set()
        except Exception:
            raise LoginError() from None

    def wait(self) -> str:
        return self.wait_grant().access_token

    def wait_grant(self) -> TokenGrant:
        """Like wait(), plus expiry and (only when enabled) the refresh token."""
        if not self._started:
            raise LoginError()
        self._done.wait(max(0, self._deadline - time.monotonic()))
        with self._lock:
            access, grant = self._access_token, self._grant
        self.close()
        if access is None or grant is None:
            raise LoginError()
        return grant

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._access_token = None
            self._grant = None
            self._state = self._verifier = self._nonce = ""
        self._done.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=0.3)
        if self._server is not None:
            self._server.server_close()
        if self._session is not None:
            self._session.token = None
            self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _post_form(config, path, form, http):
    session = http or requests.Session()
    try:
        session.trust_env = False
        response = session.post(config.issuer + path, data=form, timeout=(5, 10), allow_redirects=False,
                                headers={"Accept": "application/json"})
        raw = response.content
        if len(raw) > 65536:
            raise LoginError()
        return response.status_code, raw
    except requests.RequestException:
        raise LoginError() from None
    finally:
        if http is None:
            session.close()


def refresh_access(config: HostedLoginConfig, refresh_token: str, *, http=None, now=None) -> TokenGrant:
    """Exchange a rotating refresh token once. The caller must store the new one.

    A 400/401/403 answer means the token is expired, revoked or was reused
    (rotation reuse detection); raise RefreshRejected so the caller clears it.
    """
    if not config.refresh_tokens or not _token_text(refresh_token, 4096):
        raise RefreshRejected()
    status, raw = _post_form(config, "oauth/token", {
        "grant_type": "refresh_token", "client_id": config.client_id, "refresh_token": refresh_token,
    }, http)
    if status in (400, 401, 403):
        raise RefreshRejected()
    if status != 200:
        raise LoginError()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise LoginError() from None
    grant = _grant(payload, refresh_allowed=True, now=now)
    if grant.refresh_token is None:
        # Rotation is required: never keep reusing a token the server rotated.
        raise RefreshRejected()
    return grant


def revoke_refresh(config: HostedLoginConfig, refresh_token: str, *, http=None) -> bool:
    """Best-effort revocation at sign-out; local deletion never depends on it."""
    if not _token_text(refresh_token, 4096):
        return False
    try:
        status, _ = _post_form(config, "oauth/revoke", {"client_id": config.client_id, "token": refresh_token}, http)
    except LoginError:
        return False
    return status == 200
