# SPDX-License-Identifier: AGPL-3.0-or-later
"""Root offline/expiry and skew boundaries without real services or clocks."""
import pytest

from orion_mini.hosted_renewal import assess


def test_renewal_waits_until_four_hours_remain_and_recovers_after_expiry():
    start = 1900000000
    expires = start + 12 * 3600
    fresh = assess(expires, start)
    assert not fresh.due and not fresh.expired
    assert fresh.next_check_in <= 900
    assert not assess(expires, expires - 4 * 3600 - 1).due
    assert assess(expires, expires - 4 * 3600).due
    expired = assess(expires, expires + 1)
    assert expired.due and expired.expired and expired.next_check_in == 30
    assert assess(None, start).due


@pytest.mark.parametrize("offset", [-3601, 3601])
def test_severe_clock_skew_blocks_new_signatures_even_for_expired_roster(offset):
    decision = assess(1900000000, 1900000001, server_offset=offset)
    assert decision.blocked and decision.skew_warning and not decision.due


@pytest.mark.parametrize("offset", [-300, 300])
def test_bounded_clock_offset_keeps_expiry_twelve_hours_after_server_time(offset):
    decision = assess(None, 1900000000, server_offset=offset)
    assert decision.due and decision.skew_warning and not decision.blocked
    assert decision.ttl_seconds == 12 * 3600 + offset


@pytest.mark.parametrize("lifetime,margin", [(86401, 1), (1, 1), (100, 0), (100, 101), (True, 1)])
def test_invalid_policy_cannot_extend_signed_roster_lifetime(lifetime, margin):
    with pytest.raises(ValueError):
        assess(None, 1900000000, lifetime=lifetime, margin=margin)
