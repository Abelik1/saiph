# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orion_mini import agent_client, agent_grants
from orion_mini.storage import read_json, write_json


def test_agent_client_does_not_load_device_key_or_follow_redirects(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_client, "mesh_url", lambda url: "ws://100.64.0.1:8765/v1/link")
    write_json(tmp_path / "agent.json", {"token": "PRIVATE_TOKEN" * 4})
    client = agent_client.AgentClient(tmp_path / "agent.json")
    with pytest.raises(ValueError):
        client.request("../link/events")
    assert agent_client.NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://example.com") is None
    assert not (tmp_path / "hub-device-key.pem").exists()


def test_assistant_retrieves_only_requested_evidence_without_credentials(tmp_path, monkeypatch):
    path = tmp_path / "agent-grants" / "assistant.json"
    write_json(path, {"token": "PRIVATE_TOKEN" * 4})
    calls = []
    class FakeClient:
        def __init__(self, path):
            pass
        def request(self, resource):
            calls.append(resource)
            return {"notifications": [{"text": "PRIVATE_BODY"}], "messages": [{"body": "PRIVATE_SMS"}]}
    monkeypatch.setattr(agent_client, "AgentClient", FakeClient)
    assert agent_client.assistant_context(tmp_path, "Plan my coursework") == "" and calls == []
    assert agent_client.assistant_context(tmp_path, "Turn off notifications") == "" and calls == []
    assert agent_client.assistant_context(tmp_path, "Summarize my day without notifications") == "" and calls == []
    evidence = agent_client.assistant_context(tmp_path, "Summarize my notifications")
    assert "PRIVATE_BODY" in evidence and "PRIVATE_SMS" not in evidence and "PRIVATE_TOKEN" not in evidence
    assert len(calls) == 1 and calls[0].startswith("notifications?")
    evidence = agent_client.assistant_context(tmp_path, "What did the bank text say?")
    assert "PRIVATE_SMS" in evidence and "PRIVATE_TOKEN" not in evidence


def test_trusted_broker_renews_finite_scopes_and_never_returns_token(tmp_path, monkeypatch):
    (tmp_path / "hub-device-key.pem").write_text("FAKE_KEY_NOT_READ_BY_TEST")
    config = {"device_id": "dev_owner", "base_url": "http://100.64.0.1:8765"}
    calls = []
    def signed(root, config, path, method, body=None):
        calls.append((path, method, body))
        if method == "DELETE":
            return {"ok": True}
        return {"id": "hash", "token": "PRIVATE_TOKEN" * 4, "scopes": sorted(body["scopes"]),
                "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()}
    monkeypatch.setattr(agent_grants.hub_client, "signed", signed)
    grants = {"assistant": ["notifications.read"], "schedule-agent": ["inbox.read", "inbox.propose"]}
    config["delegate_grants"] = grants
    result = agent_grants.ensure(tmp_path, config)
    assert "PRIVATE_TOKEN" not in json.dumps(result) and len(calls) == 2
    assert read_json(tmp_path / "agent-grants" / "assistant.json")["owner_device_id"] == "dev_owner"
    assert agent_grants.ensure(tmp_path, config)["renewed"] == [] and len(calls) == 2
    assert all(set(call[2]["scopes"]) <= {"devices.read", "notifications.read", "sms.read", "actions.propose", "inbox.read", "inbox.propose", "inbox.result"}
               for call in calls)
    with pytest.raises(ValueError):
        agent_grants.ensure(tmp_path, config, {"assistant": ["device.send"]})


def test_post_reports_each_refused_item_without_dropping_the_rest(tmp_path, monkeypatch, capsys):
    write_json(tmp_path / "items.json", [{"id": "taken"}, {"id": "fresh"}])
    posted = []
    class FakeClient:
        def __init__(self, path):
            pass
        def request(self, resource, method="GET", body=None):
            if body["id"] == "taken":
                raise agent_client.DelegateError("Scoped hub API returned HTTP 409: " + agent_client.HINTS[409], 409)
            posted.append(body["id"])
            return {"item": body, "created": True}
    monkeypatch.setattr(agent_client, "AgentClient", FakeClient)
    assert agent_client.main(["--credential", str(tmp_path / "agent.json"), "post", str(tmp_path / "items.json")]) == 1
    results = json.loads(capsys.readouterr().out)["results"]
    assert posted == ["fresh"] and results[0] == {"id": "taken", "error": "Scoped hub API returned HTTP 409: " + agent_client.HINTS[409]}


def test_expired_grant_stops_the_whole_post_with_a_specific_error(tmp_path, monkeypatch, capsys):
    write_json(tmp_path / "items.json", [{"id": "one"}, {"id": "two"}])
    class FakeClient:
        def __init__(self, path):
            pass
        def request(self, resource, method="GET", body=None):
            raise agent_client.DelegateError("Scoped hub API returned HTTP 401: " + agent_client.HINTS[401], 401)
    monkeypatch.setattr(agent_client, "AgentClient", FakeClient)
    assert agent_client.main(["--credential", str(tmp_path / "agent.json"), "post", str(tmp_path / "items.json")]) == 1
    assert "expired or was revoked" in json.loads(capsys.readouterr().out)["error"]


@pytest.mark.parametrize("configured, explicit", [(None, None), ({}, None), ({"reader": ["inbox.read"]}, {})])
def test_broker_never_issues_implicit_or_explicitly_empty_grants(tmp_path, monkeypatch, configured, explicit):
    (tmp_path / "hub-device-key.pem").write_text("SYNTHETIC_KEY")
    config = {"device_id": "dev_owner", "base_url": "https://hub.example.invalid"}
    if configured is not None:
        config["delegate_grants"] = configured
    monkeypatch.setattr(agent_grants.hub_client, "signed", lambda *args: pytest.fail("Implicit grant request"))
    assert agent_grants.ensure(tmp_path, config, explicit) == {"configured": True, "renewed": []}
    assert not (tmp_path / "agent-grants").exists()
    assert agent_grants.DEFAULT_GRANTS == {}


@pytest.mark.parametrize("invalid", [
    None, [], {"../escape": ["inbox.read"]}, {"reader": []},
    {"reader": ["inbox.read", "inbox.read"]}, {"reader": [None]},
    {"reader": "inbox.read"}, {"reader": ["device.send"]},
    {"valid": ["inbox.read"], "invalid": ["device.send"]},
])
def test_broker_validates_all_owner_opt_ins_before_issuing_any_grant(tmp_path, monkeypatch, invalid):
    (tmp_path / "hub-device-key.pem").write_text("SYNTHETIC_KEY")
    config = {"device_id": "dev_owner", "base_url": "https://hub.example.invalid", "delegate_grants": invalid}
    monkeypatch.setattr(agent_grants.hub_client, "signed", lambda *args: pytest.fail("Grant before full validation"))
    with pytest.raises(ValueError):
        agent_grants.ensure(tmp_path, config)
    assert not (tmp_path / "agent-grants").exists()


def test_hub_cli_requires_an_explicit_delegate_credential(monkeypatch):
    from orion_mini import hub_client
    with pytest.raises(SystemExit) as missing:
        hub_client.main(["list"])
    assert missing.value.code == 2
    calls = []
    monkeypatch.setattr(agent_client, "main", lambda args: calls.append(args) or 0)
    assert hub_client.main(["--credential", "synthetic-reader.json", "list"]) == 0
    assert calls == [["--credential", "synthetic-reader.json", "list"]]
