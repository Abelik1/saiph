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
    report = usage.report(30)
    assert {(r["app"], r["stage"], r["installs"]) for r in report["active"]} == {("desktop", "phone_added", 3), ("android", "connected", 1)}
    assert {(r["feature"], r["bucket"], r["installs"]) for r in report["features"]} >= {("clipboard_sent", "6-20", 3), ("app_open", "2-5", 1)}
    # The file holds totals only: no table can carry a batch, address or identifier.
    with sqlite3.connect(registry.directory / 'usage.sqlite3') as db:
        tables = {name for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {column[1] for table in tables for column in db.execute(f"PRAGMA table_info({table})")}
    assert tables == {"usage_active", "usage_feature", "service_daily"}
    assert columns == {"day", "app", "platform", "version", "mode", "install_age", "stage", "installs", "feature",
                       "bucket", "metric", "status", "requests"}


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
    rows = {(r["metric"], r["status"]) for r in usage.report(30)["service"]}
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
