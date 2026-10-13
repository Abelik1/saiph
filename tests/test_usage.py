# SPDX-License-Identifier: AGPL-3.0-or-later
"""Opt-in anonymous usage counts: nothing before consent, nothing identifying, exact batches."""
import json
import re
from pathlib import Path

import pytest

from orion_mini.link_service import LinkWorkspace
from orion_mini.usage import BRIDGE_FEATURES, FEATURES, UsageCounter, age_bucket, bucket

ROOT = Path(__file__).resolve().parents[1]
DAY = 86400
START = 1_800_000_000  # 2027-01-15 08:00 UTC


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self):
        return self.now


@pytest.fixture
def workspace(tmp_path):
    return LinkWorkspace(tmp_path)


def counter(workspace, posted, *, endpoint="https://service.example.test/v1/usage", fail=False):
    clock = Clock()

    def post(url, batch):
        if fail:
            raise OSError("synthetic offline")
        posted.append((url, batch))
    return UsageCounter(workspace, endpoint=endpoint, post=post, clock=clock, version="0.1.0-beta.5", platform="windows"), clock


def test_nothing_is_counted_or_sent_before_the_owner_agrees(workspace):
    posted = []
    usage, clock = counter(workspace, posted)
    usage.count("sms_send")
    clock.now += DAY
    assert usage.consent() is None and usage.pending() == [] and usage.flush() == 0 and posted == []
    assert workspace.store.all("usage_day") == []


def test_consented_counts_become_one_coarse_anonymous_batch_per_past_day(workspace):
    posted = []
    usage, clock = counter(workspace, posted)
    usage.set_consent(True)
    for _ in range(7):
        usage.count("clipboard_sent")
    usage.count("sms_send")
    usage.screen("messages")
    usage.screen("../../etc")  # Unknown screens and features are ignored, never invented.
    usage.count("contact_alice")
    assert usage.pending() == []  # Today is still in progress.
    clock.now += DAY
    [batch] = usage.pending()
    assert batch == {"schema": 1, "day": "2027-01-15", "app": "desktop", "platform": "windows", "version": "0.1.0-beta.5",
                     "mode": "none", "install_age": "0", "stage": "installed",
                     "features": {"clipboard_sent": "6-20", "screen_messages": "1", "sms_send": "1"}}
    assert usage.flush() == 1 and posted == [("https://service.example.test/v1/usage", batch)]
    assert usage.pending() == [] and usage.snapshot()["last_sent"] == batch
    # No identifier, address, name or content can appear: only published keys and buckets.
    assert set(batch) == {"schema", "day", "app", "platform", "version", "mode", "install_age", "stage", "features"}
    assert json.loads(json.dumps(batch)) == batch
    assert all(value in {"1", "2-5", "6-20", "21+"} for value in batch["features"].values())


def test_offline_keeps_batches_and_old_days_are_dropped(workspace):
    posted = []
    usage, clock = counter(workspace, posted, fail=True)
    usage.set_consent(True)
    usage.count("call")
    clock.now += DAY
    assert usage.flush() == 0 and len(usage.pending()) == 1
    clock.now += 9 * DAY
    usage.flush()
    assert usage.pending() == [] and workspace.store.all("usage_day") == []


def test_declining_deletes_local_counts_and_the_last_batch(workspace):
    posted = []
    usage, clock = counter(workspace, posted)
    usage.set_consent(True)
    usage.count("photo_save")
    clock.now += DAY
    usage.flush()
    usage.count("photo_save")
    snapshot = usage.set_consent(False)
    assert snapshot == {"available": True, "consent": "declined", "pending": [], "last_sent": None}
    assert workspace.store.all("usage_day") == [] and "last_sent" not in workspace.settings["usage"]
    usage.count("photo_save")
    assert workspace.store.all("usage_day") == []
    with pytest.raises(ValueError):
        usage.set_consent("yes")


def test_builds_without_a_service_never_send(workspace):
    posted = []
    usage, clock = counter(workspace, posted, endpoint=None)
    usage.set_consent(True)
    usage.count("call")
    clock.now += DAY
    assert usage.flush() == 0 and posted == [] and not usage.snapshot()["available"]
    # A development workspace built normally has no packaged service at all.
    assert workspace.usage_counter.available() is False


def test_install_age_and_count_ranges():
    assert [bucket(n) for n in (1, 2, 5, 6, 20, 21, 500)] == ["1", "2-5", "2-5", "6-20", "6-20", "21+", "21+"]
    assert [age_bucket(n) for n in (0, 1, 6, 7, 29, 30, 89, 90)] == ["0", "1-6", "1-6", "7-29", "7-29", "30-89", "30-89", "90+"]


def test_workspace_consent_and_screens_through_dispatch(workspace):
    workspace.usage_counter.endpoint = "https://service.example.test/v1/usage"
    assert workspace.state()["usage"]["consent"] is None
    workspace.dispatch("usage.consent", {"granted": True})
    workspace.dispatch("usage.screen", {"screen": "settings"})
    assert workspace.store.all("usage_day")[0]["features"] == {"screen_settings": 1}
    with pytest.raises(ValueError):
        workspace.dispatch("usage.consent", {"granted": True, "extra": 1})


def test_published_field_list_matches_the_service_and_the_documentation():
    from orion_hub.hosted_usage import FEATURES as SERVICE
    assert set(FEATURES) == SERVICE["desktop"]
    assert set(BRIDGE_FEATURES.values()) <= set(FEATURES)
    kotlin = (ROOT / "android/app/src/main/java/com/orionmini/mobile/UsageAnalytics.kt").read_text(encoding="utf-8")
    block = re.search(r"val FEATURES = setOf\((.*?)\)", kotlin, re.S).group(1)
    assert set(re.findall(r'"([a-z_]+)"', block)) == SERVICE["android"]
    document = (ROOT / "docs/USAGE_ANALYTICS.md").read_text(encoding="utf-8")
    for name in SERVICE["desktop"] | SERVICE["android"]:
        assert f"`{name}`" in document, name
