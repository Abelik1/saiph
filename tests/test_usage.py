# SPDX-License-Identifier: AGPL-3.0-or-later
"""Opt-in anonymous usage counts: nothing before consent, nothing identifying, exact batches."""
import json
import re
from pathlib import Path

import pytest

from orion_mini.link_service import LinkWorkspace
from orion_mini.usage import (BRIDGE_FEATURES, CRASHES, ENABLED, FAILURES, FEATURES, UsageCounter, active_bucket,
                               age_bucket, bucket, install_crash_counter, os_family, record_failure)

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


def counter(workspace, posted, *, endpoint="https://service.example.test/v1/usage", fail=False, refuse_schema_2=False):
    clock = Clock()

    def post(url, batch):
        if fail or (refuse_schema_2 and batch["schema"] == 2):
            raise OSError("synthetic offline")
        posted.append((url, batch))
    return UsageCounter(workspace, endpoint=endpoint, post=post, clock=clock, version="0.1.0-beta.5", platform="windows",
                        os="windows_11"), clock


ENABLED_DEFAULTS = {"notifications": True, "messages": True, "photos": True, "apps": True, "calls": True,
                    "wallpaper": False, "usb_debugging": False, "your_week": True}


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
    assert batch == {"schema": 2, "day": "2027-01-15", "app": "desktop", "platform": "windows", "version": "0.1.0-beta.5",
                     "mode": "none", "install_age": "0", "stage": "installed",
                     "features": {"clipboard_sent": "6-20", "screen_messages": "1", "sms_send": "1"},
                     "active_days": "1", "os": "windows_11", "enabled": ENABLED_DEFAULTS, "failures": {}, "crashes": {}}
    assert usage.flush() == 1 and posted == [("https://service.example.test/v1/usage", batch)]
    assert usage.pending() == [] and usage.snapshot()["last_sent"] == batch
    # No identifier, address, name or content can appear: only published keys and buckets.
    assert set(batch) == {"schema", "day", "app", "platform", "version", "mode", "install_age", "stage", "features",
                          "active_days", "os", "enabled", "failures", "crashes"}
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
    assert [active_bucket(n) for n in (0, 1, 2, 3, 4, 6, 7)] == ["0", "1", "2-3", "2-3", "4-6", "4-6", "7"]
    assert os_family() in {"windows_10", "windows_11", "windows_other", "linux_x11", "linux_wayland", "linux_other"}


def test_active_days_failures_and_crashes_are_ranges_with_fixed_names(workspace):
    posted = []
    usage, clock = counter(workspace, posted)
    workspace.usage_counter = usage
    usage.failure("hosted_send_failed")
    assert workspace.store.all("usage_day") == []  # Nothing before consent, failures included.
    usage.set_consent(True)
    for day in range(5):
        if day != 2:
            usage.count("call")
        clock.now += DAY
    for _ in range(3):
        record_failure(workspace, "hub_connection_failed")
    record_failure(workspace, "timeout talking to 192.0.2.1")  # Unknown reasons are ignored, never invented.
    usage.crash("main_thread")
    usage.crash("ZeroDivisionError: synthetic")
    clock.now += DAY
    batches = {batch["day"]: batch for batch in usage.pending()}
    assert [batches[day]["active_days"] for day in sorted(batches)] == ["1", "2-3", "2-3", "4-6", "4-6"]
    last = batches[max(batches)]
    assert last["features"] == {} and last["failures"] == {"hub_connection_failed": "2-5"}
    assert last["crashes"] == {"main_thread": "1"}
    assert usage.flush() == 5
    usage.set_consent(False)
    assert "active_days" not in workspace.settings["usage"]


def test_enabled_reports_only_the_published_switches(workspace):
    posted = []
    usage, clock = counter(workspace, posted)
    usage.set_consent(True)
    workspace.settings.setdefault("link", {})["phone"] = {"features": {"messages": False}, "usb_debugging": True}
    usage.count("call")
    clock.now += DAY
    [batch] = usage.pending()
    assert batch["enabled"] == {**ENABLED_DEFAULTS, "messages": False, "usb_debugging": True}
    assert set(batch["enabled"]) == set(ENABLED)


def test_a_service_that_refuses_schema_2_still_gets_the_schema_1_counts(workspace):
    posted = []
    usage, clock = counter(workspace, posted, refuse_schema_2=True)
    usage.set_consent(True)
    usage.count("call")
    usage.failure("file_send_failed")
    clock.now += DAY
    assert usage.flush() == 1
    [(_, sent)] = posted
    assert sent == {"schema": 1, "day": "2027-01-15", "app": "desktop", "platform": "windows", "version": "0.1.0-beta.5",
                    "mode": "none", "install_age": "0", "stage": "installed", "features": {"call": "1"}}


def test_unhandled_errors_are_counted_by_thread_kind_and_still_reported(workspace, monkeypatch):
    import sys
    import threading
    seen = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: seen.append("sys"))
    monkeypatch.setattr(threading, "excepthook", lambda args: seen.append("thread"))
    posted = []
    usage, clock = counter(workspace, posted)
    workspace.usage_counter = usage
    usage.set_consent(True)
    install_crash_counter(workspace)
    try:
        raise ValueError("synthetic secret message")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    worker = threading.Thread(target=lambda: 1 / 0)
    worker.start()
    worker.join()
    assert seen == ["sys", "thread"]
    clock.now += DAY
    [batch] = usage.pending()
    assert batch["crashes"] == {"main_thread": "1", "background_thread": "1"}
    assert "synthetic secret" not in json.dumps(batch) and "ZeroDivision" not in json.dumps(batch)


def test_workspace_consent_and_screens_through_dispatch(workspace):
    workspace.usage_counter.endpoint = "https://service.example.test/v1/usage"
    assert workspace.state()["usage"]["consent"] is None
    workspace.dispatch("usage.consent", {"granted": True})
    workspace.dispatch("usage.screen", {"screen": "settings"})
    assert workspace.store.all("usage_day")[0]["features"] == {"screen_settings": 1}
    with pytest.raises(ValueError):
        workspace.dispatch("usage.consent", {"granted": True, "extra": 1})


def test_published_field_list_matches_the_service_and_the_documentation():
    from orion_hub import hosted_usage as service
    assert set(FEATURES) == service.FEATURES["desktop"]
    assert set(BRIDGE_FEATURES.values()) <= set(FEATURES)
    assert set(FAILURES) == service.FAILURES and set(CRASHES) == service.CRASHES
    assert set(ENABLED) == service.ENABLED["desktop"]
    kotlin = (ROOT / "android/app/src/main/java/com/orionmini/mobile/UsageAnalytics.kt").read_text(encoding="utf-8")

    def kotlin_set(name):
        block = re.search(r"val " + name + r" = setOf\((.*?)\)", kotlin, re.S).group(1)
        return set(re.findall(r'"([a-z0-9_+-]+)"', block))
    assert kotlin_set("FEATURES") == service.FEATURES["android"]
    assert kotlin_set("FAILURES") == service.FAILURES and kotlin_set("CRASHES") == service.CRASHES
    assert kotlin_set("ENABLED") == service.ENABLED["android"] and kotlin_set("OS") == service.OS["android"]
    transport = (ROOT / "android/core/network/src/main/java/sefirah/network/orion/HostedHttpTransport.kt").read_text(encoding="utf-8")
    link = (ROOT / "android/core/network/src/main/java/sefirah/network/orion/OrionLink.kt").read_text(encoding="utf-8")
    assert set(re.findall(r'"([a-z_]+_failed)"', transport + link)) <= service.FAILURES
    document = (ROOT / "docs/USAGE_ANALYTICS.md").read_text(encoding="utf-8")
    names = (service.FEATURES["desktop"] | service.FEATURES["android"] | service.FAILURES | service.CRASHES
             | service.ENABLED["desktop"] | service.ENABLED["android"] | service.ACTIVE_DAYS - {"0"}
             | {os for values in service.OS.values() for os in values})
    for name in names:
        assert f"`{name}`" in document, name


def test_multi_part_prerelease_versions_are_reported_not_dev():
    from orion_mini.usage import _VERSION
    for value in ("0.1.0-beta.7", "0.1.0-beta.30-acceptance.1", "1.2.3+build.5"):
        assert _VERSION.fullmatch(value)
    for value in ("0.1.0-", "0.1.0-beta 1", "x.1.0", "0.1.0-" + "a" * 40):
        assert not _VERSION.fullmatch(value)


def test_hosted_transport_reports_only_a_fixed_failure_reason(monkeypatch):
    from orion_mini import hosted_transport
    from orion_mini.hosted_transport import HostedTransport, TransportError, failure_code
    assert failure_code("POST", "/v1/sealed/events") == "hosted_send_failed"
    assert failure_code("GET", "/v1/sealed/events") == "hosted_receive_failed"
    assert failure_code("POST", "/v1/sealed/blobs/x/chunks/1") == "file_send_failed"
    assert failure_code("GET", "/v1/sealed/blobs/x/chunks/1") == "file_receive_failed"
    assert failure_code("GET", "/v1/devices/rosters") is None
    transport = HostedTransport("https://service.example.test", None)
    reasons = []
    transport.failed = reasons.append

    def refuse(*args, **kwargs):
        raise TransportError(503)
    monkeypatch.setattr(transport, "_request", refuse)
    for method, path in (("POST", "/v1/sealed/events"), ("GET", "/v1/devices/rosters")):
        with pytest.raises(TransportError):
            transport._call(method, path)
    transport.failed = lambda code: 1 / 0  # A failing counter never hides the original error.
    with pytest.raises(TransportError):
        transport._call("GET", "/v1/sealed/events")
    assert reasons == ["hosted_send_failed"]
    transport.close()
