# SPDX-License-Identifier: AGPL-3.0-or-later
"""Real loopback and Authlib code-exchange tests with synthetic HTTPS transport."""
import base64
import hashlib
import json
import socket
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

import pytest
pytest.importorskip("authlib")
from authlib.integrations.requests_client import OAuth2Session
from requests import Response
from requests.adapters import BaseAdapter

from orion_mini.hosted_login import CALLBACK_PATH, HostedLoginConfig, LoginAttempt, LoginError


class TokenTransport(BaseAdapter):
    def __init__(self):
        self.calls = []
        self.status = 200
        self.payload = {"access_token": "synthetic-api-token", "token_type": "Bearer", "expires_in": 300,
                        "refresh_token": "must-not-be-kept", "id_token": "must-not-be-used"}

    def send(self, request, **kwargs):
        self.calls.append((request, kwargs))
        response = Response()
        response.status_code = self.status
        response._content = json.dumps(self.payload).encode()
        response.request = request
        response.url = request.url
        response.headers["Content-Type"] = "application/json"
        return response

    def close(self):
        pass


@pytest.fixture
def config():
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    return HostedLoginConfig("https://synthetic.example/", "https://orion.example/api", "desktop", callback_port=port)


@pytest.fixture
def harness(config):
    transport = TokenTransport()
    sessions = []
    browser_urls = []

    def factory(**kwargs):
        session = OAuth2Session(**kwargs)
        session.mount("https://", transport)
        sessions.append(session)
        return session

    with LoginAttempt(config, oauth_factory=factory, browser_opener=lambda url: browser_urls.append(url) or True) as attempt:
        yield attempt, transport, sessions, browser_urls


def callback(attempt, **changes):
    params = {"code": "synthetic-code", "state": attempt._state, **changes}
    return CALLBACK_PATH + "?" + urlencode(params)


def get(url, headers=None):
    try:
        response = urlopen(Request(url, headers=headers or {}), timeout=3)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.read(), response.headers


def test_real_loopback_pkce_exchange_returns_only_memory_token(harness, config, capsys, caplog):
    attempt, transport, sessions, browser = harness
    authorize = attempt.begin()
    assert browser == [authorize]
    parsed = urlsplit(authorize)
    params = parse_qs(parsed.query)
    assert parsed.scheme == "https" and parsed.netloc == "synthetic.example" and parsed.path == "/authorize"
    assert params["response_type"] == ["code"]
    assert params["code_challenge_method"] == ["S256"]
    expected = base64.urlsafe_b64encode(hashlib.sha256(attempt._verifier.encode()).digest()).rstrip(b"=").decode()
    assert params["code_challenge"] == [expected]
    assert params["audience"] == [config.audience]
    assert params["client_id"] == [config.client_id]
    assert params["state"] == [attempt._state] and len(attempt._state) >= 43
    assert params["nonce"] == [attempt._nonce] and len(attempt._nonce) >= 43
    assert "scope" not in params
    redirect = urlsplit(attempt.redirect_uri)
    assert redirect.hostname == "127.0.0.1" and redirect.port == config.callback_port and redirect.path == CALLBACK_PATH
    verifier = attempt._verifier
    status, body, headers = get(f"http://{redirect.netloc}" + callback(attempt))
    assert status == 200
    assert b"synthetic" not in body
    assert headers["Cache-Control"] == "no-store" and headers["Referrer-Policy"] == "no-referrer"
    assert attempt.wait() == "synthetic-api-token"
    assert sessions[0].token is None
    assert attempt._access_token is None and attempt._verifier == attempt._state == attempt._nonce == ""
    assert len(transport.calls) == 1
    request, kwargs = transport.calls[0]
    assert request.url == config.issuer + "oauth/token" and request.method == "POST"
    assert "Authorization" not in request.headers
    body = parse_qs(request.body)
    assert body["code_verifier"] == [verifier]
    assert body["code"] == ["synthetic-code"]
    assert body["client_id"] == [config.client_id]
    assert body["redirect_uri"] == [attempt.redirect_uri]
    assert "client_secret" not in body
    assert kwargs["timeout"] == 5
    assert capsys.readouterr().err == "" and caplog.records == []


@pytest.mark.parametrize("target", [
    "/wrong?code=x&state={state}", CALLBACK_PATH + "?code=x&state=wrong",
    CALLBACK_PATH + "?code=x&code=y&state={state}", CALLBACK_PATH + "?code=x&state={state}&state={state}",
    CALLBACK_PATH + "?state={state}", CALLBACK_PATH + "?code=&state={state}",
    CALLBACK_PATH + "?code=x&state={state}&iss=https%3A%2F%2Fother.example%2F",
    CALLBACK_PATH + "?code=x&state={state}&unknown=yes", CALLBACK_PATH + "?code=x&state={state}#fragment",
    "https://attacker.invalid" + CALLBACK_PATH + "?code=x&state={state}",
    CALLBACK_PATH + "?code=x&state={state}&error_description=unexpected",
    CALLBACK_PATH + "?code=x&state={state}&flag", CALLBACK_PATH + "?code=%00&state={state}",
], ids=["path", "state", "duplicate-code", "duplicate-state", "missing-code", "blank-code", "issuer",
        "unknown-param", "fragment", "absolute-url", "error-detail", "malformed-query", "control-code"])
def test_bad_callbacks_never_exchange_and_valid_callback_can_follow(harness, target):
    attempt, transport, _, _ = harness
    attempt.begin()
    with pytest.raises(LoginError, match="^Sign-in did not complete$"):
        attempt.consume_callback(target.format(state=attempt._state))
    assert transport.calls == []
    assert attempt.consume_callback(callback(attempt)) == "synthetic-api-token"
    assert attempt.wait() == "synthetic-api-token"


def test_real_listener_rejects_foreign_host_without_logging(harness, capsys):
    attempt, transport, _, _ = harness
    attempt.begin()
    redirect = urlsplit(attempt.redirect_uri)
    target = f"http://{redirect.netloc}" + callback(attempt)
    assert get(target, {"Host": "attacker.invalid"})[0] == 400
    assert transport.calls == []
    assert get(target)[0] == 200
    assert attempt.wait() == "synthetic-api-token"
    assert capsys.readouterr().err == ""


def test_callback_error_finishes_without_echo_or_exchange(harness):
    attempt, transport, _, _ = harness
    attempt.begin()
    target = CALLBACK_PATH + "?" + urlencode({"state": attempt._state, "error": "access_denied", "error_description": "private-detail"})
    status, body, _ = get("http://" + urlsplit(attempt.redirect_uri).netloc + target)
    assert status == 400 and b"private-detail" not in body and b"access_denied" not in body
    with pytest.raises(LoginError):
        attempt.wait()
    assert transport.calls == []


def test_callback_can_only_exchange_once(harness):
    attempt, transport, _, _ = harness
    attempt.begin()
    target = callback(attempt)
    assert attempt.consume_callback(target) == "synthetic-api-token"
    with pytest.raises(LoginError):
        attempt.consume_callback(target)
    assert len(transport.calls) == 1


def test_simultaneous_callbacks_do_not_duplicate_exchange(harness):
    attempt, transport, _, _ = harness
    attempt.begin()
    target = callback(attempt)
    start = threading.Barrier(3)
    results = []

    def consume():
        start.wait()
        try:
            results.append(attempt.consume_callback(target))
        except LoginError:
            results.append("rejected")

    workers = [threading.Thread(target=consume) for _ in range(2)]
    for worker in workers:
        worker.start()
    start.wait()
    for worker in workers:
        worker.join(timeout=2)
        assert not worker.is_alive()
    assert sorted(results) == ["rejected", "synthetic-api-token"]
    assert len(transport.calls) == 1


@pytest.mark.parametrize("payload,status", [
    ({"access_token": "token", "token_type": "Bearer"}, 302),
    ({"error": "invalid_grant", "error_description": "private-error"}, 400),
    ({"access_token": "", "token_type": "Bearer"}, 200),
    ({"access_token": "token"}, 200),
    ({"access_token": "token", "token_type": "Basic"}, 200),
    ({"access_token": "token\nsecret", "token_type": "Bearer"}, 200),
    ({"access_token": "x" * 17000, "token_type": "Bearer"}, 200),
    ({"id_token": "not-an-api-token", "token_type": "Bearer"}, 200),
], ids=["redirect", "token-error", "blank-token", "missing-type", "wrong-type", "control-token", "oversized-token", "id-token-only"])
def test_token_failures_generic_and_token_dictionary_cleared(harness, payload, status, capsys, caplog):
    attempt, transport, sessions, _ = harness
    transport.payload, transport.status = payload, status
    attempt.begin()
    with pytest.raises(LoginError, match="^Sign-in did not complete$"):
        attempt.consume_callback(callback(attempt))
    with pytest.raises(LoginError):
        attempt.wait()
    assert sessions[0].token is None
    assert attempt._verifier == ""
    assert capsys.readouterr().err == "" and caplog.records == []


def test_timeout_and_closed_port(config):
    with LoginAttempt(config, browser_opener=lambda url: True, timeout_seconds=0.05) as attempt:
        attempt.begin()
        redirect = attempt.redirect_uri
        with pytest.raises(LoginError):
            attempt.wait()
        with pytest.raises((URLError, ConnectionError, OSError)):
            urlopen(redirect, timeout=0.2)


def test_cancellation_and_single_begin(harness):
    attempt, transport, _, _ = harness
    with pytest.raises(LoginError):
        attempt.wait()
    attempt.begin()
    target = callback(attempt)
    with pytest.raises(LoginError):
        attempt.begin()
    attempt.close()
    with pytest.raises(LoginError):
        attempt.consume_callback(target)
    with pytest.raises(LoginError):
        attempt.wait()
    assert transport.calls == []


def test_browser_failure_closes_listener(config):
    with LoginAttempt(config, browser_opener=lambda url: False) as attempt:
        with pytest.raises(LoginError):
            attempt.begin()
        with pytest.raises((URLError, ConnectionError, OSError)):
            urlopen(attempt.redirect_uri, timeout=0.2)


def test_default_callback_matches_registered_auth0_port():
    config = HostedLoginConfig("https://synthetic.example/", "https://orion.example/api", "desktop")
    assert config.callback_port == 49172


def test_occupied_callback_port_fails_without_scanning_or_browser(config):
    browser = []
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", config.callback_port))
        occupied.listen()
        with LoginAttempt(config, browser_opener=lambda url: browser.append(url) or True) as attempt:
            with pytest.raises(LoginError):
                attempt.begin()
    assert browser == []


@pytest.mark.parametrize("timeout", [-1, 0, 301, float("nan")])
def test_timeout_is_bounded(config, timeout):
    with pytest.raises(ValueError):
        LoginAttempt(config, timeout_seconds=timeout)


@pytest.mark.parametrize("change", [
    {"issuer": "http://synthetic.example/"}, {"issuer": "https://synthetic.example"},
    {"issuer": "https://synthetic.example/path/"}, {"issuer": "https://synthetic.example/?a=b"},
    {"issuer": "https://user:password@synthetic.example/"}, {"issuer": "https://synthetic.example:8080/"},
    {"audience": "desktop"}, {"client_id": ""}, {"audience": ""},
    {"callback_port": 0}, {"callback_port": 1023}, {"callback_port": 65536}, {"callback_port": True},
])
def test_configuration_rejects_unsafe_or_missing_values(config, change):
    from dataclasses import asdict
    with pytest.raises(ValueError):
        HostedLoginConfig(**{**asdict(config), **change})
