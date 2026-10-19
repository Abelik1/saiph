# SPDX-License-Identifier: AGPL-3.0-or-later
"""Free trial notice wording from the service's /v1/access answer. Synthetic values only."""
import pytest

from orion_mini.hosted_access import parse_access, summarize

NOW = 1_800_000_000


def test_strict_shape_with_and_without_a_trial():
    assert parse_access({"entitled": False, "until": None, "kinds": []}) == {
        "entitled": False, "until": None, "kinds": [], "trial_until": None}
    assert parse_access({"entitled": True, "until": NOW + 5, "kinds": ["trial"], "trial_until": NOW + 5})["trial_until"] == NOW + 5


@pytest.mark.parametrize("value", [
    None, [], {"entitled": True, "until": None, "kinds": ["paid"]}, {"entitled": False, "until": NOW, "kinds": []},
    {"entitled": True, "until": NOW, "kinds": []}, {"entitled": True, "until": NOW, "kinds": ["root"]},
    {"entitled": True, "until": NOW, "kinds": ["paid", "paid"]}, {"entitled": True, "until": "soon", "kinds": ["paid"]},
    {"entitled": False, "until": None, "kinds": [], "trial_until": -1}, {"entitled": False, "until": None, "kinds": [], "extra": 1},
    {"entitled": 1, "until": NOW, "kinds": ["paid"]},
])
def test_anything_else_is_ignored(value):
    assert parse_access(value) is None


def test_days_left_round_up_and_the_notice_offers_to_subscribe():
    trial = parse_access({"entitled": True, "until": NOW + 86400 + 1, "kinds": ["trial"], "trial_until": NOW + 86400 + 1})
    summary = summarize(trial, NOW)
    assert summary["state"] == "trial" and summary["days_left"] == 2
    assert summary["message"].startswith("Free trial: 2 days left.") and "Subscribe" in summary["message"]
    assert summarize(trial, NOW + 86400)["message"].startswith("Free trial: 1 day left.")


def test_ended_trial_and_no_access_explain_what_to_do_and_that_nothing_was_deleted():
    ended = summarize(parse_access({"entitled": False, "until": None, "kinds": [], "trial_until": NOW - 10}), NOW)
    assert ended["state"] == "trial_ended" and "Nothing was deleted" in ended["message"]
    none = summarize(parse_access({"entitled": False, "until": None, "kinds": []}), NOW)
    assert none["state"] == "none" and "Start your free trial or subscribe" in none["message"]


def test_subscribers_and_invitation_holders_see_no_notice():
    for kinds in (["paid"], ["beta"], ["paid", "trial"], ["admin"]):
        value = parse_access({"entitled": True, "until": NOW + 99, "kinds": kinds, "trial_until": NOW + 50})
        assert summarize(value, NOW) == {"state": "active", "days_left": None, "trial_until": NOW + 50, "message": ""}
    assert summarize(None, NOW) is None
