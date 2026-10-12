# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthetic token and fixed-JWKS tests; no Auth0 account/network is needed."""
import io
import json
import time
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
import pytest
pytest.importorskip("jwt")
import jwt
from starlette.requests import Request

from orion_hub.hosted_auth import AccessTokens, Auth0Config


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def config():
    return Auth0Config("https://synthetic.example/", "https://orion.example/api", ("desktop", "android"), "auth0|owner")


@pytest.fixture
def claims(config):
    now = int(time.time())
    return {"iss": config.issuer, "aud": config.audience, "sub": config.owner_subject,
            "iat": now - 5, "exp": now + 300, "azp": "desktop"}


def encode(key, claims, headers=None):
    headers = {"kid": "current", **(headers or {})}
    if headers["kid"] is None:
        del headers["kid"]
    return jwt.encode(claims, key, algorithm="RS256", headers=headers)


def assert_unauthorized(call):
    with pytest.raises(HTTPException) as error:
        call()
    assert error.value.status_code == 401
    assert error.value.detail == "Unauthorized"
    assert error.value.headers == {"WWW-Authenticate": "Bearer"}


def request(*headers):
    return Request({"type": "http", "headers": [(b"authorization", value.encode()) for value in headers]})


def test_accepts_only_owner_identity_without_profile(config, claims, key):
    verifier = AccessTokens(config, key_resolver=lambda kid: key.public_key())
    claims.update({"email": "synthetic@example.invalid", "name": "Synthetic profile"})
    assert verifier.verify(encode(key, claims)) == {"issuer": config.issuer, "subject": config.owner_subject}
    claims["aud"] = [config.audience, config.issuer + "userinfo"]
    claims["azp"] = "android"
    assert verifier.principal(request("Bearer " + encode(key, claims))) == {"issuer": config.issuer, "subject": config.owner_subject}


@pytest.mark.parametrize("claim,value", [
    ("iss", "https://other.example/"), ("iss", "https://synthetic.example"),
    ("aud", "desktop"), ("aud", ["android", "desktop"]),
    ("sub", "auth0|other"), ("sub", ""), ("azp", "unknown"), ("azp", ["desktop"]),
    ("exp", 1), ("exp", "9999999999"), ("exp", True),
    ("iat", 9999999999), ("iat", "1"), ("iat", False), ("nbf", 9999999999),
], ids=["issuer", "issuer-slash", "id-token-audience", "wrong-audiences", "other-owner", "empty-owner",
        "other-client", "nonstring-client", "expired", "string-expiry", "bool-expiry", "future-issued",
        "string-issued", "bool-issued", "not-yet-valid"])
def test_rejects_wrong_claims(config, claims, key, claim, value):
    claims[claim] = value
    assert_unauthorized(lambda: AccessTokens(config, key_resolver=lambda kid: key.public_key()).verify(encode(key, claims)))


@pytest.mark.parametrize("claim", ["iss", "aud", "sub", "azp", "iat", "exp"])
def test_requires_claims(config, claims, key, claim):
    del claims[claim]
    assert_unauthorized(lambda: AccessTokens(config, key_resolver=lambda kid: key.public_key()).verify(encode(key, claims)))


@pytest.mark.parametrize("header", [
    {"jku": "https://attacker.invalid/jwks"}, {"x5u": "https://attacker.invalid/cert"},
    {"jwk": {}}, {"crit": ["unexpected"]}, {"kid": "../../key"},
    {"kid": "https://attacker.invalid/key"}, {"kid": "a" * 129}, {"kid": None},
], ids=["jku", "x5u", "embedded-key", "critical", "kid-path", "kid-url", "kid-length", "missing-kid"])
def test_rejects_untrusted_headers_without_key_lookup(config, claims, key, header):
    calls = []
    verifier = AccessTokens(config, key_resolver=lambda kid: calls.append(kid))
    assert_unauthorized(lambda: verifier.verify(encode(key, claims, header)))
    assert calls == []


@pytest.mark.parametrize("algorithm", ["HS256", "none"])
def test_rejects_unsupported_algorithm_without_key_lookup(config, claims, algorithm):
    calls = []
    token = jwt.encode(claims, "x" * 32 if algorithm == "HS256" else None, algorithm=algorithm, headers={"kid": "current"})
    assert_unauthorized(lambda: AccessTokens(config, key_resolver=lambda kid: calls.append(kid)).verify(token))
    assert calls == []


def test_rejects_invalid_signature(config, claims, key):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert_unauthorized(lambda: AccessTokens(config, key_resolver=lambda kid: key.public_key()).verify(encode(other, claims)))


@pytest.mark.parametrize("header", [None, "", "Basic abc", "bearer abc", "Bearer", "Bearer  abc", "Bearer abc ", "Bearer abc\t"])
def test_exact_bearer_format(config, header):
    verifier = AccessTokens(config, key_resolver=lambda kid: None)
    assert_unauthorized(lambda: verifier.principal(request() if header is None else request(header)))


def test_duplicate_authorization_rejected(config, claims, key):
    token = encode(key, claims)
    verifier = AccessTokens(config, key_resolver=lambda kid: key.public_key())
    assert_unauthorized(lambda: verifier.principal(request("Bearer " + token, "Bearer " + token)))


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "a" * 16385, None, b"a.b.c"])
def test_malformed_and_oversized_tokens_fail_closed(config, token):
    assert_unauthorized(lambda: AccessTokens(config).verify(token))


def test_unconfigured_fails_closed(claims, key):
    token = encode(key, claims)
    assert_unauthorized(lambda: AccessTokens(None).verify(token))
    assert_unauthorized(lambda: AccessTokens(None).principal(request("Bearer " + token)))


def test_jwks_uses_only_fixed_url_caches_and_bounds_refresh(config, claims, key, monkeypatch):
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    payload = {"keys": [{**jwk, "kid": "current", "alg": "RS256", "use": "sig"}]}
    calls = []

    def open_jwks(req, timeout):
        calls.append((req.full_url, timeout))
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr("urllib.request.build_opener", lambda *args: SimpleNamespace(open=open_jwks))
    verifier = AccessTokens(config)
    for _ in range(3):
        assert verifier.verify(encode(key, claims))["subject"] == config.owner_subject
    for kid in ("unknown", "unknown-again"):
        assert_unauthorized(lambda: verifier.verify(encode(key, claims, {"kid": kid})))
    assert calls == [(config.issuer + ".well-known/jwks.json", 5)]
    assert verifier._jwks.jwk_set_cache.lifespan == 300

    # Tenant key rotation is accepted after the bounded unknown-kid cooldown.
    payload["keys"][0]["kid"] = "rotated"
    verifier._jwks._last_successful_fetch = 0
    assert verifier.verify(encode(key, claims, {"kid": "rotated"}))["subject"] == config.owner_subject
    assert len(calls) == 2


def test_jwks_failure_is_generic_and_silent(config, claims, key, monkeypatch, caplog):
    def fail(req, timeout):
        raise TimeoutError("synthetic internal transport failure")

    monkeypatch.setattr("urllib.request.build_opener", lambda *args: SimpleNamespace(open=fail))
    assert_unauthorized(lambda: AccessTokens(config).verify(encode(key, claims)))
    assert caplog.records == []


@pytest.mark.parametrize("change", [
    {"issuer": "http://synthetic.example/"}, {"issuer": "https://synthetic.example"},
    {"issuer": "https://synthetic.example/path/"}, {"issuer": "https://synthetic.example/?other=value"},
    {"issuer": "https://user:pass@synthetic.example/"}, {"issuer": "https://synthetic.example:8080/"},
    {"audience": "desktop"}, {"audience": ""}, {"client_ids": ()}, {"client_ids": ["desktop"]},
    {"client_ids": ("",)}, {"owner_subject": ""},
])
def test_rejects_incomplete_or_unsafe_configuration(config, change):
    from dataclasses import asdict
    with pytest.raises(ValueError):
        Auth0Config(**{**asdict(config), **change})
