# SPDX-License-Identifier: AGPL-3.0-or-later
"""The handoff's acceptance checks that can run without Cloudflare, Firebase or a phone."""
import asyncio, base64, hashlib, importlib, json, sys, time, uuid
from datetime import datetime, timedelta, timezone

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
    return mod


def write_automations(hub, items):
    hub.AUTOMATIONS.write_text(json.dumps({"automations": items}), encoding="utf-8")


def pair(hub, client):
    from orion_hub.security import create_pairing_code
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    r = client.post("/v1/pairing/claim", json={"code": create_pairing_code(hub.DB), "name": "test", "public_key_der_b64": base64.b64encode(pub).decode()})
    assert r.status_code == 200
    return key, r.json()["device_id"]


def headers(key, device, method, path, body=b"", ts=None, nonce=None):
    ts = str(int(time.time()) if ts is None else ts)
    nonce = nonce or str(uuid.uuid4())
    canonical = f"{method}\n{path}\n{ts}\n{nonce}\n{hashlib.sha256(body).hexdigest()}".encode()
    sig = base64.b64encode(key.sign(canonical, ec.ECDSA(hashes.SHA256()))).decode()
    return {"X-Orion-Device-Id": device, "X-Orion-Timestamp": ts, "X-Orion-Nonce": nonce, "X-Orion-Signature": sig}


def post(client, key, device, path, payload):
    body = json.dumps(payload, separators=(",", ":")).encode()
    return client.post(path, content=body, headers={**headers(key, device, "POST", path, body), "Content-Type": "application/json"})


def test_pairing_code_cannot_be_reused(hub):
    from orion_hub.security import create_pairing_code
    client = TestClient(hub.app)
    code = create_pairing_code(hub.DB)
    pub = base64.b64encode(ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    claim = {"code": code, "name": "one", "public_key_der_b64": pub}
    assert client.post("/v1/pairing/claim", json=claim).status_code == 200
    assert client.post("/v1/pairing/claim", json=claim).status_code == 401


def test_expired_pairing_code_is_rejected(hub):
    from orion_hub.security import consume_pairing_code, create_pairing_code
    code = create_pairing_code(hub.DB)
    hub.DB.execute("UPDATE pairing_codes SET expires_at=?", ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),))
    assert consume_pairing_code(hub.DB, code) is False


def test_old_timestamp_and_bad_signature_are_rejected(hub):
    client = TestClient(hub.app)
    key, device = pair(hub, client)
    old = headers(key, device, "GET", "/v1/dashboard", ts=int(time.time()) - 120)
    assert client.get("/v1/dashboard", headers=old).status_code == 401
    other = ec.generate_private_key(ec.SECP256R1())
    assert client.get("/v1/dashboard", headers=headers(other, device, "GET", "/v1/dashboard")).status_code == 401
    # A signature for one path must not authorise another.
    assert client.get("/v1/dashboard?x=1", headers=headers(key, device, "GET", "/v1/dashboard")).status_code == 401


def test_signature_covers_the_body(hub):
    client = TestClient(hub.app)
    key, device = pair(hub, client)
    signed = headers(key, device, "POST", "/v1/tasks", b'{"title":"a"}')
    r = client.post("/v1/tasks", content=b'{"title":"b"}', headers={**signed, "Content-Type": "application/json"})
    assert r.status_code == 401


def test_revoked_device_cannot_authenticate(hub):
    client = TestClient(hub.app)
    key, device = pair(hub, client)
    assert client.get("/v1/dashboard", headers=headers(key, device, "GET", "/v1/dashboard")).status_code == 200
    hub.DB.execute("DELETE FROM devices WHERE id=?", (device,))
    assert client.get("/v1/dashboard", headers=headers(key, device, "GET", "/v1/dashboard")).status_code == 401


@pytest.mark.parametrize("url", [
    "https://127.0.0.1/", "https://[::1]/", "https://10.0.0.5/", "https://192.168.1.19/",
    "https://172.16.0.1/", "https://169.254.169.254/latest/meta-data/", "https://0.0.0.0/",
    "https://example.com:8443/", "http://example.com/", "https://user:pw@example.com/",
])
def test_watch_rejects_local_and_non_standard_targets(hub, url):
    client = TestClient(hub.app)
    key, device = pair(hub, client)
    assert post(client, key, device, "/v1/watches", {"name": "x", "url": url}).status_code == 400


def test_watch_redirect_to_private_address_is_refused(hub, monkeypatch):
    from orion_hub import watches
    monkeypatch.setattr("socket.getaddrinfo", lambda host, *a, **k: [(2, 1, 6, "", ("93.184.215.14" if host == "example.com" else "10.0.0.1", 443))])

    class Redirect:
        status_code = 302; headers = {"location": "https://intranet.local/admin"}
        def __enter__(self): return self
        def __exit__(self, *a): pass
    monkeypatch.setattr(watches.requests, "get", lambda *a, **k: Redirect())
    with pytest.raises(ValueError, match="blocked"):
        watches.fetch("https://example.com/")


def test_watch_stops_reading_past_the_size_limit(hub, monkeypatch):
    from orion_hub import watches
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.215.14", 443))])
    read = []

    class Big:
        status_code = 200; headers = {}
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def iter_content(self, size):
            for _ in range(1000):
                read.append(size); yield b"x" * size
    monkeypatch.setattr(watches.requests, "get", lambda *a, **k: Big())
    with pytest.raises(ValueError, match="2 MB"):
        watches.fetch("https://example.com/")
    assert len(read) < 40


def test_watch_change_records_event_and_pushes(hub, monkeypatch):
    from orion_hub import push, watches
    sent = []
    monkeypatch.setattr(push, "send_fcm", lambda token, title, body, data=None: sent.append(title) or True)
    hub.DB.execute("INSERT INTO devices(id,name,public_key_der_b64,push_token,created_at) VALUES('d','p','k','tok','now')")
    pages = iter([b"one", b"one", b"two"])
    monkeypatch.setattr(watches, "fetch", lambda url: (200, next(pages), url))
    now = datetime.now(timezone.utc).isoformat()
    hub.DB.execute("INSERT INTO watches(id,name,url,created_at,updated_at) VALUES('w','Site','https://example.com/',?,?)", (now, now))
    row = lambda: hub.DB.row("SELECT * FROM watches WHERE id='w'")
    assert watches.check_watch(hub.DB, row())["changed"] is False   # first sight is not a change
    assert watches.check_watch(hub.DB, row())["changed"] is False
    assert watches.check_watch(hub.DB, row())["changed"] is True
    assert sent == ["Saiph update"]
    assert [e["kind"] for e in hub.DB.rows("SELECT kind FROM events")] == ["watch_changed"]


def test_due_task_pushes_once(hub, monkeypatch):
    from orion_hub import push
    sent = []
    monkeypatch.setattr(push, "send_fcm", lambda token, title, body, data=None: sent.append(title) or True)
    hub.DB.execute("INSERT INTO devices(id,name,public_key_der_b64,push_token,created_at) VALUES('d','p','k','tok','now')")
    client = TestClient(hub.app)
    key, device = pair(hub, client)
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    assert post(client, key, device, "/v1/tasks", {"title": "Call", "due_at": past}).status_code == 200
    asyncio.run(hub.scheduler_cycle())
    asyncio.run(hub.scheduler_cycle())
    assert sent == ["Saiph task due"]


def test_due_times_are_stored_as_utc(hub):
    client = TestClient(hub.app)
    key, device = pair(hub, client)
    r = post(client, key, device, "/v1/tasks", {"title": "x", "due_at": "2030-01-01T09:00:00+01:00"})
    assert r.json()["due_at"] == "2030-01-01T08:00:00+00:00"
    assert post(client, key, device, "/v1/tasks", {"title": "x", "due_at": "tomorrow"}).status_code == 400


def test_unknown_and_disabled_automations_cannot_run(hub):
    write_automations(hub, [{"id": "off", "enabled": False, "command": [sys.executable, "-c", "print(1)"]}])
    client = TestClient(hub.app)
    key, device = pair(hub, client)
    assert post(client, key, device, "/v1/automations/off/run", {}).status_code == 404
    assert post(client, key, device, "/v1/automations/nope/run", {}).status_code == 404
    assert hub.DB.rows("SELECT * FROM automation_runs") == []


def test_enabled_automation_runs_with_bounded_output(hub, monkeypatch):
    write_automations(hub, [{"id": "big", "enabled": True, "command": [sys.executable, "-c", "print('y'*50000)"], "timeout_seconds": 60}])
    monkeypatch.setenv("SECRET_THING", "should-not-leak")
    client = TestClient(hub.app)
    key, device = pair(hub, client)
    r = post(client, key, device, "/v1/automations/big/run", {})
    assert r.status_code == 200 and r.json()["status"] == "succeeded"
    assert len(r.json()["stdout"]) <= 16000
    stored = hub.DB.row("SELECT * FROM automation_runs")
    assert stored["status"] == "succeeded" and len(stored["stdout"]) <= 16000


def test_automation_run_survives_a_push_failure(hub, monkeypatch):
    from orion_hub import push
    def broken(*a, **k): raise RuntimeError("bad Firebase credential")
    monkeypatch.setattr(push, "send_fcm", broken)
    hub.DB.execute("INSERT INTO devices(id,name,public_key_der_b64,push_token,created_at) VALUES('d','p','k','tok','now')")
    write_automations(hub, [{"id": "ok", "enabled": True, "command": [sys.executable, "-c", "print('ok')"]}])
    client = TestClient(hub.app)
    key, device = pair(hub, client)
    assert post(client, key, device, "/v1/automations/ok/run", {}).status_code == 200


def test_scheduler_keeps_running_after_a_failed_cycle(hub, monkeypatch):
    calls = []
    async def cycle():
        calls.append(1)
        if len(calls) == 1: raise RuntimeError("broken automations.json")
        raise asyncio.CancelledError
    async def no_sleep(_): pass
    monkeypatch.setattr(hub, "scheduler_cycle", cycle)
    monkeypatch.setattr(hub.asyncio, "sleep", no_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(hub.scheduler())
    assert len(calls) == 2


def test_web_session_requires_csrf_for_writes(hub):
    from orion_hub.security import create_pairing_code
    client = TestClient(hub.app, base_url="https://testserver")
    r = client.post("/web/session", json={"code": create_pairing_code(hub.DB)})
    assert r.status_code == 200
    csrf = r.json()["csrf"]
    assert client.get("/v1/dashboard").status_code == 200
    assert client.post("/v1/tasks", json={"title": "x"}).status_code == 403
    assert client.post("/v1/tasks", json={"title": "x"}, headers={"x-orion-csrf": csrf}).status_code == 200


def test_pairing_is_rate_limited(hub):
    client = TestClient(hub.app)
    codes = [client.post("/v1/pairing/claim", json={"code": "00000000", "name": "x", "public_key_der_b64": "AA=="}).status_code for _ in range(12)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]


def test_web_page_hides_pairing_after_sign_in(hub):
    page = TestClient(hub.app).get("/").text
    assert "id=pairing" in page and "pairing.hidden=true" in page
    assert "login.hidden" not in page
