# SPDX-License-Identifier: AGPL-3.0-or-later
"""The inbox: one record of notices and calendar proposals, decided once, from any device."""
import base64, hashlib, importlib, json, time, uuid

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setenv("ORION_HUB_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("ORION_HUB_AUTOMATIONS", str(tmp_path / "automations.json"))
    import orion_hub.app as mod
    mod = importlib.reload(mod)
    mod.PAIR_ATTEMPTS.clear()
    pushes = []
    monkeypatch.setattr(mod, "push_data", lambda db, data: pushes.append(data) or 1)
    http = TestClient(mod.app)
    from orion_hub.security import create_pairing_code

    def device(name):
        key = ec.generate_private_key(ec.SECP256R1())
        pub = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        claimed = http.post("/v1/pairing/claim", json={"code": create_pairing_code(mod.DB), "name": name,
                                                       "public_key_der_b64": base64.b64encode(pub).decode()})
        device_id = claimed.json()["device_id"]

        def call(method, path, body=None):
            raw = json.dumps(body).encode() if body is not None else b""
            ts, nonce = str(int(time.time())), str(uuid.uuid4())
            canonical = f"{method}\n{path}\n{ts}\n{nonce}\n{hashlib.sha256(raw).hexdigest()}".encode()
            headers = {"X-Orion-Device-Id": device_id, "X-Orion-Timestamp": ts, "X-Orion-Nonce": nonce,
                       "X-Orion-Signature": base64.b64encode(key.sign(canonical, ec.ECDSA(hashes.SHA256()))).decode(),
                       "Content-Type": "application/json"}
            return http.request(method, path, content=raw or None, headers=headers)
        return call
    return device, pushes, http


SEMINAR = {"id": "demo-workshop-session", "kind": "proposal", "source": "schedule-agent",
           "title": "Synthetic workshop presentation", "body": "Your slot, from the seminar schedule email.",
           "proposal": {"events": [
               {"title": "Synthetic workshop presentation", "start": "2026-11-16T14:00:00+00:00",
                "end": "2026-11-16T15:00:00+00:00", "reminders": [1440]},
               {"title": "Email the workshop coordinator about the paper", "start": "2026-11-02", "all_day": True,
                "reminders": [540]}]}}


def test_a_proposal_is_decided_once_and_every_device_sees_the_result(hub):
    device, pushes, _http = hub
    desktop, phone = device("desktop"), device("Pixel")
    posted = desktop("POST", "/v1/inbox", SEMINAR).json()
    assert posted["created"] and posted["item"]["status"] == "new"
    assert pushes[-1]["title"] == "Needs your OK: Synthetic workshop presentation" and pushes[-1]["status"] == "new"
    accepted = phone("POST", "/v1/inbox/demo-workshop-session/decide", {"decision": "accept"}).json()
    assert accepted["changed"] and accepted["item"]["status"] == "accepted" and accepted["item"]["decided_by"] == "Pixel"
    # The phone's notification is withdrawn on the other devices too.
    assert pushes[-1] == {**pushes[-1], "id": "demo-workshop-session", "status": "accepted"}
    late = desktop("POST", "/v1/inbox/demo-workshop-session/decide", {"decision": "dismiss"}).json()
    assert not late["changed"] and late["item"]["status"] == "accepted"
    assert [row["id"] for row in desktop("GET", "/v1/inbox?status=accepted").json()["items"]] == ["demo-workshop-session"]


def test_reposting_never_reopens_a_decided_item(hub):
    device, pushes, _http = hub
    desktop = device("desktop")
    desktop("POST", "/v1/inbox", SEMINAR)
    desktop("POST", "/v1/inbox/demo-workshop-session/decide", {"decision": "dismiss"})
    count = len(pushes)
    again = desktop("POST", "/v1/inbox", {**SEMINAR, "title": "Changed"}).json()
    assert not again["created"] and again["item"]["status"] == "dismissed" and again["item"]["title"] == SEMINAR["title"]
    assert len(pushes) == count


def test_the_calendar_automation_reports_applied_or_keeps_it_for_a_retry(hub):
    device, _pushes, _http = hub
    desktop = device("desktop")
    desktop("POST", "/v1/inbox", SEMINAR)
    assert desktop("POST", "/v1/inbox/demo-workshop-session/result", {"ok": True}).status_code == 400  # not accepted yet
    desktop("POST", "/v1/inbox/demo-workshop-session/decide", {"decision": "accept"})
    failed = desktop("POST", "/v1/inbox/demo-workshop-session/result", {"ok": False, "result": "Calendar unavailable"}).json()
    assert failed["item"]["status"] == "accepted" and failed["item"]["result"] == "Calendar unavailable"
    done = desktop("POST", "/v1/inbox/demo-workshop-session/result", {"ok": True, "result": "2 events added"}).json()
    assert done["item"]["status"] == "applied"


def test_notices_are_cleared_not_accepted(hub):
    device, _pushes, _http = hub
    phone = device("Pixel")
    notice = {"id": "bb-cs7cs4-week-5", "kind": "notice", "source": "blackboard", "title": "CS7CS4: Week 5 Assignment posted",
              "link": "https://tcd.blackboard.com/"}
    assert phone("POST", "/v1/inbox", notice).json()["item"]["proposal"] is None
    assert phone("POST", "/v1/inbox/bb-cs7cs4-week-5/decide", {"decision": "accept"}).status_code == 400
    assert phone("POST", "/v1/inbox/bb-cs7cs4-week-5/decide", {"decision": "done"}).json()["item"]["status"] == "done"


@pytest.mark.parametrize("body, message", [
    ({**SEMINAR, "id": "Bad Id"}, "id must"),
    ({**SEMINAR, "kind": "task"}, "kind must"),
    ({**SEMINAR, "title": ""}, "title is required"),
    ({**SEMINAR, "link": "http://example.com"}, "https"),
    ({**SEMINAR, "proposal": {"events": []}}, "needs"),
    ({**SEMINAR, "proposal": {"events": [{"title": "x", "start": "next week"}]}}, "ISO"),
    ({**SEMINAR, "proposal": {"events": [{"title": "x", "start": "2026-11-02", "reminders": [99999]}]}}, "reminders"),
])
def test_inbox_items_are_validated(hub, body, message):
    device, _pushes, _http = hub
    response = device("desktop")("POST", "/v1/inbox", body)
    assert response.status_code == 400 and message in response.json()["detail"]


def test_the_inbox_needs_a_paired_device(hub):
    _device, _pushes, http = hub
    assert http.get("/v1/inbox").status_code == 401
    assert http.post("/v1/inbox", json=SEMINAR).status_code == 401
