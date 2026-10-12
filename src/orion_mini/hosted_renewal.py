# SPDX-License-Identifier: AGPL-3.0-or-later
"""Root roster renewal timing (PROVISIONAL: 12 h lifetime, renew at 4 h left).

Pure timing decisions, so boundaries and clock skew are testable without a
network. The server's clock decides expiry, so the decision uses the server
time estimated from HTTPS `Date` headers when one is known. Device-signed
requests already need clocks within 60 s; beyond `MAX_SIGNING_SKEW` the root
refuses to sign rosters until this computer's clock is corrected.
"""
from __future__ import annotations

from dataclasses import dataclass

ROSTER_LIFETIME_SECONDS = 12 * 3600
RENEW_MARGIN_SECONDS = 4 * 3600
SKEW_WARNING_SECONDS = 60
MAX_SIGNING_SKEW_SECONDS = 3600
MIN_CHECK_SECONDS = 30
MAX_CHECK_SECONDS = 15 * 60


@dataclass(frozen=True)
class RenewalDecision:
    due: bool
    expired: bool
    remaining: int
    next_check_in: int
    ttl_seconds: int
    skew_warning: bool
    blocked: bool


def assess(expires_at: int | None, now: float, *, server_offset: float | None = None,
           lifetime: int = ROSTER_LIFETIME_SECONDS, margin: int = RENEW_MARGIN_SECONDS) -> RenewalDecision:
    """Decide whether the root should renew now and when to look again.

    `server_offset` is server time minus local time. `ttl_seconds` is chosen so
    the signed expiry is `lifetime` after the *server's* now, because signing
    uses this computer's clock.
    """
    if type(lifetime) is not int or type(margin) is not int or not 0 < margin < lifetime <= 86400:
        raise ValueError("Invalid roster renewal policy.")
    offset = float(server_offset or 0.0)
    blocked = abs(offset) > MAX_SIGNING_SKEW_SECONDS
    skew_warning = abs(offset) > SKEW_WARNING_SECONDS
    server_now = int(now + offset)
    ttl = max(1, min(86400, int(round(lifetime + offset)))) if not blocked else lifetime
    if expires_at is None:
        return RenewalDecision(not blocked, True, 0, MIN_CHECK_SECONDS, ttl, skew_warning, blocked)
    remaining = int(expires_at) - server_now
    due = remaining <= margin
    if due:
        next_check = MIN_CHECK_SECONDS
    else:
        next_check = max(MIN_CHECK_SECONDS, min(MAX_CHECK_SECONDS, remaining - margin))
    return RenewalDecision(due and not blocked, remaining <= 0, remaining, next_check, ttl, skew_warning, blocked)
