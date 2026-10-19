# SPDX-License-Identifier: AGPL-3.0-or-later
"""Anonymous usage batches become daily totals only; hostile or identifying input is refused."""
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from orion_hub.hosted_auth import AccessTokens, ServiceAuth0Config
from orion_hub.hosted_service import AccountRegistry, SharedHosted
from orion_hub.hosted_usage import UsageStore, classify, validate

NOW = 1_800_000_000  # 2027-01-15 UTC


def batch(**changes):
    value = {"schema": 1, "day": "2027-01-14", "app": "desktop", "platform": "windows", "version": "0.1.0-beta.5",
             "mode": "hosted", "install_age": "7-29", "stage": "phone_added",
             "features": {"clipboard_sent": "6-20", "screen_messages": "1"}}
    value.update(changes)
    return value


@pytest.fixture
def service(tmp_path):
    auth = ServiceAuth0Config('https://synthetic.eu.auth0.com/', 'https://saiph.example.test/api', ('desktop', 'android'))
    registry = AccountRegistry(tmp_path / 'shared', auth)
    usage = UsageStore(registry.directory, clock=lambda: NOW)
    app = SharedHosted(registry, tokens=AccessTokens(auth, key_resolver=lambda kid: None), usage=usage)
    return TestClient(app), usage, registry


@pytest.mark.parametrize("change", [
    {"schema": 2}, {"app": "ios"}, {"platform": "android"}, {"day": "2027-01-16"}, {"day": "2027-01-01"},
    {"day": "2027-02-30"}, {"version": "latest"}, {"mode": "cloud"}, {"install_age": "12"}, {"stage": "paid"},
    {"features": {"clipboard_sent": "7"}}, {"features": {"contact_alice": "1"}}, {"features": []},
    {"install_id": "abc"}, {"account": "auth0|someone"},
])
def test_only_the_published_schema_is_accepted(change):
    with pytest.raises(ValueError):
        validate(batch(**change), now=NOW)
    assert validate(batch(), now=NOW)


def test_endpoint_folds_batches_into_totals_without_storing_them(service):
    client, usage, registry = service
    for _ in range(3):
        assert client.post('/v1/usage', content=json.dumps(batch())).status_code == 204
    assert client.post('/v1/usage', content=json.dumps(batch(app="android", platform="android", stage="connected",
                                                                features={"app_open": "2-5"}))).status_code == 204
    report = usage.report(30, min_cell=1)
    assert {(r["app"], r["stage"], r["installs"]) for r in report["active"]} == {("desktop", "phone_added", 3), ("android", "connected", 1)}
    assert {(r["feature"], r["bucket"], r["installs"]) for r in report["features"]} >= {("clipboard_sent", "6-20", 3), ("app_open", "2-5", 1)}
    # The file holds totals only: no table can carry a batch, address or identifier.
    with sqlite3.connect(registry.directory / 'usage.sqlite3') as db:
        tables = {name for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {column[1] for table in tables for column in db.execute(f"PRAGMA table_info({table})")}
    assert tables == {"usage_active", "usage_feature", "usage_detail", "service_daily", "service_active"}
    # No column can hold an address, account, device or install identifier.
    assert columns == {"day", "app", "platform", "version", "mode", "install_age", "stage", "installs", "feature",
                       "bucket", "metric", "status", "requests", "field", "name", "value", "accounts", "devices"}


@pytest.mark.parametrize("headers,query", [({"Authorization": "Bearer synthetic"}, ""), ({"Origin": "https://evil.example"}, ""),
                                           ({"Cookie": "session=1"}, ""), ({}, "?id=1")])
def test_endpoint_refuses_identifying_context(service, headers, query):
    client, usage, _ = service
    assert client.post('/v1/usage' + query, content=json.dumps(batch()), headers=headers).status_code == 403
    assert usage.report(30)["active"] == []


def test_endpoint_refuses_large_invalid_and_excess_batches(service, monkeypatch):
    client, usage, _ = service
    assert client.post('/v1/usage', content=json.dumps(batch(features={"x" * 5000: "1"}))).status_code == 413
    assert client.post('/v1/usage', content=json.dumps(batch(mode="cloud"))).status_code == 400
    assert client.post('/v1/usage', content=b'{"schema":1,') .status_code == 400
    assert client.get('/v1/usage').status_code == 404
    import orion_hub.hosted_usage as module
    monkeypatch.setattr(module, "ACCEPT_PER_MINUTE", 1)
    assert client.post('/v1/usage', content=json.dumps(batch())).status_code in (204, 429)
    assert client.post('/v1/usage', content=json.dumps(batch())).status_code == 429


def test_request_totals_use_fixed_route_names_and_status_classes(service):
    client, usage, _ = service
    client.get('/v1/account')  # 401 without a token
    client.get('/v1/sealed/events/0123')  # refused without device headers
    client.get('/v1/health')
    usage.flush()
    rows = {(r["metric"], r["status"]) for r in usage.report(30, min_cell=1)["service"]}
    assert ("account", "4xx") in rows and ("sealed.ack", "4xx") in rows
    assert all("0123" not in metric for metric, _ in rows) and not any(m == "health" for m, _ in rows)
    assert classify("POST", "/v1/sealed/events") == "sealed.publish" and classify("GET", "/v1/sealed/events") == "sealed.poll"
    assert classify("POST", "/v1/beta/redeem") == "beta.redeem" and classify("GET", "/v1/devices/rosters/page") == "devices.rosters"


def test_old_totals_are_deleted(tmp_path):
    clock = [NOW]
    usage = UsageStore(tmp_path, clock=lambda: clock[0])
    usage.ingest(batch())
    clock[0] += 500 * 86400
    usage.flush()
    assert usage.report(400)["active"] == []


def batch2(**changes):
    value = {**batch(), "schema": 2, "active_days": "4-6", "os": "windows_11",
             "enabled": {"notifications": True, "wallpaper": False}, "failures": {"hosted_send_failed": "2-5"},
             "crashes": {"background_thread": "1"}}
    value.update(changes)
    return value


@pytest.mark.parametrize("change", [
    {"os": "linux_x11"}, {"os": "Windows 11 Pro 26200"}, {"active_days": "5"}, {"enabled": {"notifications": "yes"}},
    {"enabled": {"contacts": True}}, {"failures": {"hosted_send_failed": "3"}}, {"failures": {"timeout talking to 10.0.0.1": "1"}},
    {"crashes": {"ZeroDivisionError": "1"}}, {"crashes": []}, {"schema": 1}, {"install_id": "abc"},
])
def test_schema_2_accepts_only_its_published_fields(change):
    with pytest.raises(ValueError):
        validate(batch2(**change), now=NOW)
    assert validate(batch2(), now=NOW)
    assert validate(batch2(app="android", platform="android", os="android_14", features={"app_open": "1"},
                           enabled={"clipboard": True, "app_lock": False}), now=NOW)


def test_schema_2_details_are_separate_totals_and_small_groups_are_hidden(service):
    client, usage, _ = service
    for index in range(5):
        assert client.post('/v1/usage', content=json.dumps(batch2(active_days="7" if index else "1"))).status_code == 204
    assert client.post('/v1/usage', content=json.dumps(batch())).status_code == 204  # Older apps still count.
    report = usage.report(30)
    details = {(r["field"], r["name"], r["value"]): r["installs"] for r in report["details"]}
    assert ("os", "", "windows_11") in details and details[("os", "", "windows_11")] == 5
    assert details[("enabled", "notifications", "on")] == 5 and details[("enabled", "wallpaper", "off")] == 5
    assert details[("failures", "hosted_send_failed", "2-5")] == 5 and details[("crashes", "background_thread", "1")] == 5
    # Four installs said "7" and one said "1": both groups are under five, so both are hidden.
    assert ("active_days", "", "7") not in details and ("active_days", "", "1") not in details
    assert report["hidden"]["details"] == 2 and report["min_cell"] == 5
    assert [r["installs"] for r in report["active"]] == [6]
    raw = usage.report(30, min_cell=1)
    assert {(r["value"], r["installs"]) for r in raw["details"] if r["field"] == "active_days"} == {("7", 4), ("1", 1)}
    with sqlite3.connect(usage.path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(usage_detail)")}
    assert columns == {"day", "app", "field", "name", "value", "installs"}
    with pytest.raises(ValueError):
        usage.report(30, min_cell=0)


def test_delivery_health_and_active_counts_keep_no_identifiers(tmp_path):
    clock = [NOW]
    usage = UsageStore(tmp_path, clock=lambda: clock[0])
    usage.sealed("published", "event-fast", NOW + 300)
    usage.sealed("published", "event-slow", NOW + 300)
    usage.sealed("published", "event-lost", NOW + 60)
    clock[0] += 0.5
    usage.sealed("acknowledged", "event-fast")
    clock[0] += 90
    usage.sealed("acknowledged", "event-slow")
    usage.sealed("acknowledged", "never-published")
    usage.sealed("blob", 50_000)
    usage.sealed("blob", 12_000_000)
    for account, device in (("acct-1", "dev-1"), ("acct-1", "dev-2"), ("acct-2", "dev-3")):
        usage.active(account, device)
    usage.metric("download.ticket", "windows")
    usage.metric("download.ticket", "synthetic@example.invalid")
    usage.metric("Bad Metric", "x")
    usage.flush()
    report = usage.report(30)
    service = {(r["metric"], r["status"]): r["requests"] for r in report["service"]}
    assert service == {("delivery.lag", "<1s"): 1, ("delivery.lag", "30s-5m"): 1, ("delivery.expired", "undelivered"): 1,
                       ("blob.size", "<100KB"): 1, ("blob.size", "5-20MB"): 1, ("download.ticket", "windows"): 1}
    assert report["accounts"] == [{"day": "2027-01-15", "accounts": 2, "devices": 3}]
    # A restart forgets today's sets; the stored count keeps the larger value.
    restarted = UsageStore(tmp_path, clock=lambda: clock[0])
    restarted.active("acct-3")
    restarted.flush()
    assert restarted.report(30)["accounts"] == [{"day": "2027-01-15", "accounts": 2, "devices": 3}]
    text = json.dumps(report) + json.dumps(restarted.report(30))
    assert "acct-" not in text and "dev-" not in text and "event-" not in text
    with sqlite3.connect(usage.path) as db:
        dump = "\n".join(db.iterdump())
    assert "acct-" not in dump and "dev-" not in dump and "event-" not in dump


def test_shared_service_times_sealed_delivery_through_the_mailbox_hook(service):
    _, usage, registry = service
    from orion_hub.hosted import Mailbox
    calls = []
    usage.sealed = lambda kind, *values: calls.append((kind, *values))
    mailbox = Mailbox.__new__(Mailbox)
    mailbox.observer = usage.sealed
    mailbox.observe("published", "event", NOW + 60)
    mailbox.observer = lambda *_: 1 / 0
    mailbox.observe("acknowledged", "event")  # A failing hook never breaks delivery.
    assert calls == [("published", "event", NOW + 60)]


def test_funnel_report_counts_accounts_access_and_devices_without_identifiers(service):
    import time
    from uuid import uuid4
    from orion_hub.hosted_usage import funnel_report
    _, _, registry = service
    issuer, until = 'https://synthetic.eu.auth0.com/', int(time.time()) + 86400
    accounts = []
    for index in range(7):
        subject = f'auth0|synthetic-{index}'
        registry.apply_paid_grant(issuer, subject, f'trial:{index:032x}', until, 1)
        if index < 5:
            registry.apply_paid_grant(issuer, subject, f'sub_synthetic{index}', until, 1)
        with registry.connect() as db:
            accounts.append(db.execute('SELECT id FROM accounts WHERE subject=?', (subject,)).fetchone()['id'])
    for index, account in enumerate(accounts):
        registry.claim_devices(account, ['dev_' + uuid4().hex for _ in range(1 if index < 5 else 3)])
    report = funnel_report(registry)
    assert report == {"min_cell": 5, "accounts": {"total": 7, "active": 7}, "access_now": {"paid": 5, "trial": 7},
                      "access_ever": {"paid": 5, "trial": 7}, "trial_then_paid": 5,
                      "devices_per_active_account": {"1": 5, "3": "<5"}, "beta_codes": {"issued": 0, "redeemed": 0}}
    assert funnel_report(registry, min_cell=1)["devices_per_active_account"] == {"1": 5, "3": 2}
    text = json.dumps(report)
    assert 'synthetic-' not in text and 'dev_' not in text and not any(account in text for account in accounts)
    with pytest.raises(ValueError):
        funnel_report(registry, min_cell=0)
