# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scopes, owner revocation and approval atomicity without device keys for agents."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orion_hub import agent_api, inbox
from orion_hub.db import Database
from test_acceptance import headers, pair
from test_link import client, event, hub
from test_phone import notice


@pytest.fixture
def agents(hub):
    agent_api.initialize(hub.DB)
    c = client(hub)
    owner_key, owner = pair(hub, c)
    phone_key, phone = pair(hub, c)
    hub.DB.execute("INSERT INTO link_devices VALUES(?,?)", (phone, '["notifications","sms"]'))
    hub.LINK.store.publish(phone, event(type="notification.upsert", payload=notice()))
    return hub, c, owner_key, owner, phone


def delegate(agents, scopes=None, name="Test reader"):
    hub, c, key, owner, _ = agents
    path = "/v1/agents/grants"
    body = {"name": name, "scopes": scopes or ["devices.read", "notifications.read"]}
    response = c.post(path, content=json.dumps(body), headers=headers(key, owner, "POST", path, json.dumps(body).encode()))
    assert response.status_code == 200
    grant = response.json()
    return grant, {"Authorization": "Bearer " + grant["token"]}


def action(agents, **changes):
    return {"id": "agent-action-test", "title": "Reply to the phone notification", "body": "Owner approval required",
            "action": {"target": agents[-1], "type": "notification.command", "payload": {
                "key": "private-key", "operation": "reply", "reply_key": "reply", "text": "PRIVATE_REPLY"}}, **changes}


def test_scoped_reads_cannot_authenticate_normal_device_bus_or_browser_apis(agents, caplog):
    hub, c, _, _, phone = agents
    grant, auth = delegate(agents)
    assert c.get("/v1/agents/devices", headers=auth).status_code == 200
    notices = c.get("/v1/agents/notifications", headers=auth).json()["notifications"]
    assert notices[0]["text"] == "PRIVATE_BODY" and notices[0]["device_id"] == phone
    assert c.get("/v1/agents/messages", headers=auth).status_code == 403
    assert c.post("/v1/agents/actions", headers=auth, json=action(agents)).status_code == 403
    for path in ["/v1/link/phone", "/v1/link/events", "/v1/dashboard", "/v1/inbox"]:
        assert c.get(path, headers=auth).status_code == 401
    # A delegated session cannot become a full browser session by changing header transport.
    c.cookies.set("orion_session", grant["token"])
    assert c.get("/v1/dashboard").status_code == 401
    c.cookies.clear()
    row = hub.DB.row("SELECT * FROM web_sessions WHERE id_hash=?", (grant["id"],))
    assert grant["token"] not in json.dumps(row)
    assert "PRIVATE_BODY" not in caplog.text and grant["token"] not in caplog.text


def test_delegate_requires_mesh_no_browser_origin_and_a_live_unexpired_owner(agents):
    hub, c, _, owner, _ = agents
    grant, auth = delegate(agents)
    assert c.get("/v1/agents/devices", headers={**auth, "Origin": "https://example.com"}).status_code == 403
    public = TestClient(hub.app, base_url="http://127.0.0.1:8765", client=("100.64.0.2", 9))
    assert public.get("/v1/agents/devices", headers=auth).status_code == 403
    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    hub.DB.execute("UPDATE web_sessions SET expires_at=? WHERE id_hash=?", (expired, grant["id"]))
    assert c.get("/v1/agents/devices", headers=auth).status_code == 401
    grant, auth = delegate(agents)
    hub.DB.execute("DELETE FROM devices WHERE id=?", (owner,))
    assert c.get("/v1/agents/devices", headers=auth).status_code == 401


def test_grant_revoke_is_owner_only_and_no_scope_escalation(agents):
    hub, c, key, owner, phone = agents
    grant, auth = delegate(agents)
    for invalid in [["device.send"], ["notifications.read", "notifications.read"]]:
        body = {"name": "Invalid", "scopes": invalid}
        path = "/v1/agents/grants"
        assert c.post(path, content=json.dumps(body), headers=headers(key, owner, "POST", path, json.dumps(body).encode())).status_code == 400
    path = "/v1/agents/grants/" + grant["id"]
    assert c.delete(path, headers=auth).status_code == 401
    other_key, other = pair(hub, c)
    c.delete(path, headers=headers(other_key, other, "DELETE", path))
    assert c.get("/v1/agents/devices", headers=auth).status_code == 200
    c.delete(path, headers=headers(key, owner, "DELETE", path))
    assert c.get("/v1/agents/devices", headers=auth).status_code == 401


def test_agent_action_only_proposes_and_payload_is_immutable_then_first_owner_decision_wins(agents):
    hub, c, key, owner, phone = agents
    grant, auth = delegate(agents, ["actions.propose", "inbox.read"])
    before = hub.DB.row("SELECT COUNT(*) n FROM link_events")["n"]
    response = c.post("/v1/agents/actions", headers=auth, json=action(agents))
    assert response.status_code == 200 and response.json()["item"]["status"] == "new"
    review = response.json()["item"]["proposal"]["review"]
    assert review["text"] == "PRIVATE_REPLY" and review["app"] == "Messages" and review["operation"] == "Reply to notification"
    assert hub.DB.row("SELECT COUNT(*) n FROM link_events")["n"] == before
    assert c.post("/v1/agents/actions", headers=auth, json=action(agents)).json()["created"] is False
    edited = action(agents); edited["action"]["payload"]["text"] = "DIFFERENT_PRIVATE_REPLY"
    assert c.post("/v1/agents/actions", headers=auth, json=edited).status_code == 400
    path = "/v1/inbox/agent-action-test/decide"
    assert c.post(path, headers=auth, json={"decision": "accept"}).status_code == 401
    body = b'{"decision":"accept"}'
    response = c.post(path, content=body, headers=headers(key, owner, "POST", path, body))
    assert response.status_code == 200 and response.json()["changed"] is True
    assert response.json()["item"]["status"] == "applied"
    queued = hub.DB.rows("SELECT * FROM link_events WHERE type='notification.command'")
    assert len(queued) == 1 and queued[0]["source"] == owner
    assert hub.DB.rows("SELECT * FROM link_deliveries WHERE event_id=?", (queued[0]["id"],)) == [{"event_id": queued[0]["id"], "device_id": phone}]
    body = b'{"decision":"dismiss"}'
    late = c.post(path, content=body, headers=headers(key, owner, "POST", path, body))
    assert late.json()["changed"] is False
    assert len(hub.DB.rows("SELECT * FROM link_events WHERE type='notification.command'")) == 1
    result_path = "/v1/inbox/agent-action-test/result"
    body = b'{"ok":true}'
    assert c.post(result_path, content=body, headers=headers(key, owner, "POST", result_path, body)).status_code == 400


def test_approval_queue_capacity_and_stale_notification_fail_atomically(agents, monkeypatch):
    hub, c, _, owner, phone = agents
    grant, auth = delegate(agents, ["actions.propose"])
    assert c.post("/v1/agents/actions", headers=auth, json=action(agents)).status_code == 200
    monkeypatch.setattr("orion_hub.link.MAX_PENDING", 0)
    with pytest.raises(ValueError):
        agent_api.decide_action(hub.DB, hub.LINK, "agent-action-test", "accept", {"kind": "device", "id": owner, "name": "Owner"})
    assert inbox.get(hub.DB, "agent-action-test")["status"] == "new"
    assert not hub.DB.rows("SELECT * FROM link_events WHERE type='notification.command'")
    monkeypatch.setattr("orion_hub.link.MAX_PENDING", 1000)
    hub.DB.execute("DELETE FROM phone_notifications")
    with pytest.raises(ValueError):
        agent_api.decide_action(hub.DB, hub.LINK, "agent-action-test", "accept", {"kind": "device", "id": owner, "name": "Owner"})
    assert inbox.get(hub.DB, "agent-action-test")["status"] == "new"
    _, changed = agent_api.decide_action(hub.DB, hub.LINK, "agent-action-test", "dismiss", {"kind": "device", "id": owner, "name": "Owner"})
    assert changed and not hub.DB.rows("SELECT * FROM link_events WHERE type='notification.command'")


def test_revoked_delegate_proposals_cannot_execute_and_agent_cannot_approve(agents):
    hub, c, _, owner, _ = agents
    grant, auth = delegate(agents, ["actions.propose"])
    c.post("/v1/agents/actions", headers=auth, json=action(agents))
    with pytest.raises(ValueError):
        agent_api.decide_action(hub.DB, hub.LINK, "agent-action-test", "accept", {"kind": "agent", "id": grant["id"], "name": "Agent"})
    hub.DB.execute("DELETE FROM web_sessions WHERE id_hash=?", (grant["id"],))
    with pytest.raises(ValueError):
        agent_api.decide_action(hub.DB, hub.LINK, "agent-action-test", "accept", {"kind": "device", "id": owner, "name": "Owner"})
    assert inbox.get(hub.DB, "agent-action-test")["status"] == "new"


def test_concurrent_accept_creates_one_event_and_expiry_cannot_requeue_it(agents):
    hub, c, _, owner, phone = agents
    _, auth = delegate(agents, ["actions.propose"])
    c.post("/v1/agents/actions", headers=auth, json=action(agents))
    approver = {"kind": "device", "id": owner, "name": "Owner"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: agent_api.decide_action(hub.DB, hub.LINK, "agent-action-test", "accept", approver), range(2)))
    assert sum(changed for row, changed in results) == 1
    queued = hub.DB.rows("SELECT * FROM link_events WHERE type='notification.command'")
    assert len(queued) == 1 and queued[0]["expires_at"] - queued[0]["created_at"] == 30
    hub.LINK.store.cleanup(time.time() + 31)
    assert hub.LINK.store.pending(phone) == []
    assert agent_api.decide_action(hub.DB, hub.LINK, "agent-action-test", "accept", approver)[1] is False
    assert hub.DB.row("SELECT payload_json FROM link_events WHERE type='notification.command'")["payload_json"] is None


def test_changed_authoritative_review_requires_a_fresh_owner_proposal(agents):
    hub, c, _, owner, phone = agents
    _, auth = delegate(agents, ["actions.propose"])
    c.post("/v1/agents/actions", headers=auth, json=action(agents))
    hub.LINK.store.publish(phone, event(type="notification.upsert", payload=notice(title="Different conversation")))
    with pytest.raises(ValueError, match="context changed"):
        agent_api.decide_action(hub.DB, hub.LINK, "agent-action-test", "accept", {"kind": "device", "id": owner, "name": "Owner"})
    assert inbox.get(hub.DB, "agent-action-test")["status"] == "new"
    assert not hub.DB.rows("SELECT * FROM link_events WHERE type='notification.command'")


def test_delegate_request_bounds_and_deep_json_return_fixed_errors(agents):
    _, c, _, _, _ = agents
    _, auth = delegate(agents, ["actions.propose"])
    assert c.post("/v1/agents/actions", headers=auth, content=b'x' * (agent_api.MAX_BODY + 1)).status_code == 413
    assert c.post("/v1/agents/actions", headers=auth, content=b'[' * 1200 + b']' * 1200).status_code == 400


def test_phone_action_push_contains_only_fixed_review_hint_and_metadata(agents, monkeypatch):
    hub, c, _, _, _ = agents
    captured = []
    monkeypatch.setattr(hub, "push_data", lambda db, data: captured.append(data))
    _, auth = delegate(agents, ["actions.propose"])
    proposal = action(agents, title="PRIVATE_TITLE", body="PRIVATE_NOTIFICATION_QUOTE")
    response = c.post("/v1/agents/actions", headers=auth, json=proposal)
    assert response.status_code == 200 and captured[-1]["proposal_type"] == "phone_action"
    assert "PRIVATE" not in json.dumps(captured)


def test_sms_read_scope_and_approval_uses_retained_phone_thread_only(agents):
    from orion_hub import features
    from orion_hub.link import Event
    hub, c, _, owner, phone = agents
    payload = {"thread": 7, "recipients": ["test"], "message": {"id": 1, "addresses": ["test"], "body": "PRIVATE_SMS",
               "timestamp": 1, "direction": "incoming", "subscription": 0}}
    with hub.DB.connect() as connection:
        features.apply(connection, phone, Event.model_validate(event(type="sms.thread", payload=payload)), time.time())
    _, auth = delegate(agents, ["sms.read", "actions.propose"])
    assert c.get("/v1/agents/messages", headers=auth).json()["messages"][0]["body"] == "PRIVATE_SMS"
    assert c.get("/v1/agents/notifications", headers=auth).status_code == 403
    proposal = action(agents, id="agent-sms-test", action={"target": phone, "type": "sms.send", "payload": {"thread": 7, "text": "PRIVATE_REPLY"}})
    assert c.post("/v1/agents/actions", headers=auth, json=proposal).status_code == 200
    injected = {**proposal, "id": "agent-sms-injected", "action": {**proposal["action"], "payload": {"thread": 7, "text": "PRIVATE_REPLY", "recipients": ["other"]}}}
    assert c.post("/v1/agents/actions", headers=auth, json=injected).status_code == 400
    row, changed = agent_api.decide_action(hub.DB, hub.LINK, "agent-sms-test", "accept", {"kind": "device", "id": owner, "name": "Owner"})
    assert changed and row["status"] == "applied"
    queued = hub.DB.row("SELECT * FROM link_events WHERE type='sms.send'")
    assert json.loads(queued["payload_json"]) == {"thread": 7, "text": "PRIVATE_REPLY"}


def test_calendar_delegates_keep_existing_approval_and_result_without_cross_agent_reads(agents):
    hub, c, key, owner, _ = agents
    _, auth = delegate(agents, ["inbox.propose", "inbox.read", "inbox.result"], "schedule-agent")
    _, other = delegate(agents, ["inbox.propose", "inbox.read", "inbox.result"], "other-agent")
    proposal = {"id": "calendar-agent-seminar", "kind": "proposal", "source": "blackboard", "title": "Seminar", "proposal": {
        "events": [{"title": "Seminar", "start": "2026-11-01"}]}}
    assert c.post("/v1/agents/inbox", headers=auth, json=proposal).json()["item"]["source"] == "blackboard"
    assert len(c.get("/v1/agents/inbox", headers=auth).json()["items"]) == 1
    assert c.get("/v1/agents/inbox", headers=other).json()["items"] == []
    assert c.post("/v1/agents/inbox", headers=other, json=proposal).status_code == 409
    # Posting an item again only refreshes it.
    assert c.post("/v1/agents/inbox", headers=auth, json=proposal).json()["created"] is False
    path = "/v1/inbox/calendar-agent-seminar/decide"; body = b'{"decision":"accept"}'
    assert c.post(path, content=body, headers=headers(key, owner, "POST", path, body)).status_code == 200
    path = "/v1/agents/inbox/calendar-agent-seminar/result"
    assert c.post(path, headers=other, json={"ok": True}).status_code == 404
    assert c.post(path, headers=auth, json={"ok": True, "result": "Added"}).json()["item"]["status"] == "applied"


def test_calendar_items_follow_the_delegate_name_across_token_rotation(agents):
    hub, c, *_ = agents
    _, old = delegate(agents, ["inbox.propose", "inbox.read", "inbox.result"], "schedule-agent")
    notice = {"id": "mail-rotation", "kind": "notice", "source": "email", "title": "Strike"}
    assert c.post("/v1/agents/inbox", headers=old, json=notice).status_code == 200
    _, new = delegate(agents, ["inbox.propose", "inbox.read", "inbox.result"], "schedule-agent")
    assert [r["id"] for r in c.get("/v1/agents/inbox", headers=new).json()["items"]] == ["mail-rotation"]
    assert c.post("/v1/agents/inbox", headers=new, json=notice).json()["created"] is False
    # A label that could pass for something else is replaced rather than trusted.
    odd = {"id": "mail-odd-source", "kind": "notice", "source": "Orion Hub!", "title": "Odd"}
    assert c.post("/v1/agents/inbox", headers=new, json=odd).json()["item"]["source"] == "agent"


def test_legacy_owner_items_are_not_assigned_by_source_label(tmp_path):
    db = Database(tmp_path / "legacy.db")
    with db.connect() as c:
        c.execute("ALTER TABLE inbox RENAME TO inbox_new")
        c.execute("CREATE TABLE inbox AS SELECT id,kind,source,title,body,link,proposal_json,status,decided_by,decided_at,"
                  "result,created_at,updated_at FROM inbox_new")
        c.execute("DROP TABLE inbox_new")
        for item_id, source, proposal in [("mail-legacy", "email", "{}"), ("bb-legacy", "blackboard", '{"events":[]}'),
                                          ("owner-note", "orion", "{}"),
                                          ("old-action", "agent", '{"action":{"type":"sms.send"}}')]:
            c.execute("INSERT INTO inbox(id,kind,source,title,body,link,proposal_json,status,created_at,updated_at) "
                      "VALUES(?,?,?,?,'','',?,'new','t','t')", (item_id, "notice", source, item_id, proposal))
    agent_api.initialize(db)
    owners = {r["id"]: r["agent"] for r in db.rows("SELECT id, agent FROM inbox")}
    assert owners == {"mail-legacy": None, "bb-legacy": None, "owner-note": None, "old-action": None}


def test_legacy_token_label_preserves_only_explicit_delegate_ownership(tmp_path):
    db = Database(tmp_path / "legacy-delegate.db")
    with db.connect() as c:
        c.execute("ALTER TABLE inbox RENAME TO inbox_new")
        c.execute("CREATE TABLE inbox AS SELECT id,kind,source,title,body,link,proposal_json,status,decided_by,decided_at,"
                  "result,created_at,updated_at FROM inbox_new")
        c.execute("DROP TABLE inbox_new")
        c.execute("INSERT INTO web_sessions(id_hash,name,csrf_hash,expires_at,created_at,scopes_json,owner_device_id) "
                  "VALUES(?,?,?,'future','past','[]','dev_owner')", ("a" * 64, "schedule-agent", ""))
        c.execute("INSERT INTO inbox(id,kind,source,title,body,link,proposal_json,status,created_at,updated_at) "
                  "VALUES('explicit-item','notice',?,'Synthetic','','','{}','new','t','t')", ("agent:" + "a" * 16,))
    agent_api.initialize(db)
    assert db.row("SELECT agent FROM inbox WHERE id='explicit-item'")["agent"] == "schedule-agent"
    agent_api.initialize(db)
    assert db.row("SELECT agent FROM inbox WHERE id='explicit-item'")["agent"] == "schedule-agent"
