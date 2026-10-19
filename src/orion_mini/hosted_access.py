# SPDX-License-Identifier: AGPL-3.0-or-later
"""What this Saiph account's Cloud access is, for the free trial notice.

Read from the service's ``GET /v1/access`` with the account token. It only
chooses wording (days left, trial ended, subscribe); the service alone decides
access, and nothing here unlocks content or approves devices.
"""
from __future__ import annotations

import math

# Fetched again at most this often while connected; a refusal fetches at once.
REFRESH_SECONDS = 6 * 3600
PLANS = "the Saiph website"


def parse_access(value) -> dict | None:
    """The service's answer, or None if it is not exactly the expected shape."""
    if type(value) is not dict or set(value) not in ({"entitled", "until", "kinds"}, {"entitled", "until", "kinds", "trial_until"}):
        return None
    kinds, until, trial = value["kinds"], value["until"], value.get("trial_until")
    if (type(value["entitled"]) is not bool or type(kinds) is not list or len(kinds) > 8
            or any(kind not in ("admin", "beta", "paid", "trial") for kind in kinds) or len(set(kinds)) != len(kinds)
            or (until is not None and (type(until) is not int or until <= 0))
            or value["entitled"] != (until is not None) or value["entitled"] != bool(kinds)
            or (trial is not None and (type(trial) is not int or trial <= 0))):
        return None
    return {"entitled": value["entitled"], "until": until, "kinds": kinds, "trial_until": trial}


def summarize(access: dict | None, now: float) -> dict | None:
    """``state`` is trial, trial_ended, none or active (a subscription or invitation), plus the notice text."""
    if access is None:
        return None
    trial_until = access["trial_until"]
    if access["entitled"]:
        if access["kinds"] != ["trial"] or trial_until is None or now >= trial_until:
            return {"state": "active", "days_left": None, "trial_until": trial_until, "message": ""}
        days = max(1, math.ceil((trial_until - now) / 86400))
        return {"state": "trial", "days_left": days, "trial_until": trial_until,
                "message": f"Free trial: {days} day{'s' if days != 1 else ''} left. Subscribe on {PLANS} to keep Saiph Cloud "
                           "after it ends; nothing is charged automatically."}
    if trial_until is not None:
        return {"state": "trial_ended", "days_left": 0, "trial_until": trial_until,
                "message": f"Your free trial has ended. Subscribe on {PLANS} to reconnect your devices. "
                           "Nothing was deleted: your devices, approvals and data are kept."}
    return {"state": "none", "days_left": None, "trial_until": None,
            "message": f"This Saiph account has no Saiph Cloud access yet. Start your free trial or subscribe on {PLANS} "
                       "with this same account (or activate an invitation code there), then try again."}
