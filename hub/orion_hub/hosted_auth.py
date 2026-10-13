# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bounded Auth0 API authentication for a dedicated single-owner deployment.

An account token does not approve a device or grant access to encryption keys.
Only the configured tenant's JWKS endpoint is consulted; JWT headers never
select a URL, issuer, algorithm, or deployment owner.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
import jwt


@dataclass(frozen=True)
class Auth0Config:
    issuer: str
    audience: str
    client_ids: tuple[str, ...]
    owner_subject: str

    def __post_init__(self) -> None:
        issuer = urlsplit(self.issuer)
        if (
            issuer.scheme != "https"
            or not issuer.hostname
            or issuer.username is not None
            or issuer.password is not None
            or issuer.port not in (None, 443)
            or issuer.path != "/"
            or issuer.query
            or issuer.fragment
            or not self.issuer.endswith("/")
        ):
            raise ValueError("Auth0 issuer must be a fixed HTTPS origin with trailing slash")
        if (
            not isinstance(self.client_ids, tuple)
            or not self.client_ids
            or any(not isinstance(value, str) or not value.strip() for value in self.client_ids)
            or not isinstance(self.audience, str)
            or not self.audience.strip()
            or self.audience in self.client_ids
            or not isinstance(self.owner_subject, str)
            or not self.owner_subject.strip()
        ):
            raise ValueError("Auth0 API audience, native client IDs and deployment owner are required")


_MFA_CLAIM = re.compile(r"https://[A-Za-z0-9.-]{1,253}(?:/[A-Za-z0-9._~-]{1,64}){1,4}")


def mfa_claim(environ) -> str | None:
    """The namespaced access-token claim proving multi-factor sign-in, if required.

    Set ``ORION_AUTH0_MFA_CLAIM`` to the claim the tenant's post-login Action adds
    (for example ``https://usesaiph.com/mfa``). Every account and website token
    must then carry it with the JSON value ``true``. An invalid value refuses
    startup instead of silently disabling the requirement.
    """
    value = environ.get("ORION_AUTH0_MFA_CLAIM", "")
    if value == "":
        return None
    if not isinstance(value, str) or len(value) > 300 or _MFA_CLAIM.fullmatch(value) is None:
        raise ValueError("ORION_AUTH0_MFA_CLAIM must be a namespaced HTTPS claim name")
    return value


def _unauthorized() -> HTTPException:
    return HTTPException(401, "Unauthorized", headers={"WWW-Authenticate": "Bearer"})


@dataclass(frozen=True)
class ServiceAuth0Config:
    """One fixed provider for a shared service; account admission is separate."""
    issuer: str
    audience: str
    client_ids: tuple[str, ...]

    def __post_init__(self):
        Auth0Config(self.issuer, self.audience, self.client_ids, 'service-policy-validation')


class AccessTokens:
    def __init__(
        self,
        config: Auth0Config | ServiceAuth0Config | None,
        *,
        key_resolver: Callable[[str], Any] | None = None,
        mfa_claim: str | None = None,
    ) -> None:
        if mfa_claim is not None and (not isinstance(mfa_claim, str) or _MFA_CLAIM.fullmatch(mfa_claim) is None):
            raise ValueError("Use a namespaced HTTPS claim name for multi-factor sign-in")
        self.config = config
        self.mfa_claim = mfa_claim
        self._jwks = None
        self._key_resolver = key_resolver
        if config is not None and key_resolver is None:
            self._jwks = jwt.PyJWKClient(
                config.issuer + ".well-known/jwks.json",
                cache_keys=False,
                cache_jwk_set=True,
                lifespan=300,
                timeout=5,
                cooldown_duration=30,
            )

    def verify(self, token: str) -> dict[str, str]:
        """Return only the immutable owner identity, or a generic 401.

        The resolver injection is for offline verification tests. Production
        resolves an opaque key ID exclusively against the fixed tenant JWKS.
        No token, identity profile, or validation exception is logged.
        """
        try:
            config = self.config
            if config is None or not isinstance(token, str) or len(token) > 16384:
                raise ValueError()
            if re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token) is None:
                raise ValueError()
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if (
                header.get("alg") != "RS256"
                or not isinstance(kid, str)
                or re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", kid) is None
                or any(name in header for name in ("jku", "x5u", "jwk", "crit"))
            ):
                raise ValueError()
            if self._key_resolver is not None:
                key = self._key_resolver(kid)
            else:
                key = self._jwks.get_signing_key(kid).key
            claims = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                issuer=config.issuer,
                audience=config.audience,
                subject=config.owner_subject if isinstance(config, Auth0Config) else None,
                options={"require": ["iss", "aud", "exp", "iat", "sub", "azp"]},
                leeway=0,
            )
            if (
                type(claims["exp"]) is not int
                or type(claims["iat"]) is not int
                or claims["exp"] <= claims["iat"]
                or not isinstance(claims["azp"], str)
                or claims["azp"] not in config.client_ids
                or not isinstance(claims["sub"], str)
                or not 1 <= len(claims["sub"]) <= 256
                or any(ord(c) < 33 or ord(c) > 126 for c in claims["sub"])
                # Only the boolean true proves a completed second factor.
                or (self.mfa_claim is not None and claims.get(self.mfa_claim) is not True)
            ):
                raise ValueError()
            return {"issuer": config.issuer, "subject": claims["sub"]}
        except Exception:
            raise _unauthorized() from None

    def principal(self, request: Request) -> dict[str, str]:
        values = request.headers.getlist("authorization")
        if len(values) != 1 or not values[0].startswith("Bearer "):
            raise _unauthorized()
        return self.verify(values[0][7:])
