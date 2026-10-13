# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import importlib
import hashlib
import json
import time
import threading
from uuid import uuid4
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from test_acceptance import headers, pair
from orion_hub.db import Database
from orion_hub.link import Bus, CapacityError, Session, Store, socket_timeout


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setenv("ORION_HUB_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("ORION_HUB_AUTOMATIONS", str(tmp_path / "automations.json"))
    monkeypatch.setenv("ORION_HUB_MESH_IP", "100.64.0.1")
    import orion_hub.app as mod
    mod = importlib.reload(mod)
    mod.PAIR_ATTEMPTS.clear()
    return mod


def client(hub):
    return TestClient(hub.app, base_url="http://100.64.0.1:8765", client=("100.64.0.2", 50000))


def until(ws, op, predicate=lambda _: True):
    for _ in range(20):
        value = ws.receive_json()
        if value["op"] == op and predicate(value):
            return value
    raise AssertionError(f"No {op} frame")


def event(**extra):
    return {"id": str(uuid4()), "type": "test", "ttl_seconds": 60, "payload": {}, **extra}


def test_completed_socket_send_does_not_swallow_connection_cancellation():
    async def exercise():
        sender = None
        class Socket:
            async def send_json(self, value):
                # Reproduce cancellation in the same loop turn as a successful
                # send; Python 3.10 wait_for incorrectly returns its result.
                sender.cancel()
        sender = asyncio.create_task(Session(Socket()).send({"op": "pong"}))
        done, _ = await asyncio.wait((sender,), timeout=1)
        assert done and sender.cancelled()
    asyncio.run(exercise())


def test_socket_timeout_cleans_up_child_and_preserves_inner_error():
    async def exercise():
        stopped = asyncio.Event()
        async def blocking():
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        with pytest.raises(asyncio.TimeoutError):
            await socket_timeout(blocking(), .01)
        assert stopped.is_set()
        async def failing():
            raise RuntimeError("synthetic socket failure")
        with pytest.raises(RuntimeError, match="synthetic socket failure"):
            await socket_timeout(failing(), 1)
    asyncio.run(exercise())


def seeded_pending(hub, source, target, count):
    created = time.time() - 1
    rows = []
    for index in range(count):
        prepared, _, digest = Store.prepare(event(targets=[target]))
        rows.append((prepared.id, source, prepared.type, "{}", digest, created + index / 10000, created + 60))
    with hub.DB.connect() as connection:
        connection.executemany("INSERT INTO link_events VALUES(?,?,?,?,?,?,?)", rows)
        connection.executemany("INSERT INTO link_deliveries VALUES(?,?)", ((row[0], target) for row in rows))
    return rows


def socket(c, key, device, **kwargs):
    return c.websocket_connect(str(c.base_url).replace("http", "ws", 1).rstrip("/") + "/v1/link", headers=headers(key, device, "GET", "/v1/link"), **kwargs)


def test_fanout_presence_ack_and_capabilities(hub):
    with client(hub) as c:
        a, aid = pair(hub, c)
        b, bid = pair(hub, c)
        with socket(c, a, aid) as sender, socket(c, b, bid) as receiver:
            assert until(sender, "welcome")["device_id"] == aid
            until(receiver, "welcome")
            receiver.send_json({"op": "hello", "capabilities": ["test", "battery", "call-control", "cloud.files"]})
            snapshot = until(sender, "presence", lambda v: any(d["id"] == bid and d["capabilities"] == ["battery", "call-control", "cloud.files", "test"] for d in v["devices"]))
            assert all(d["online"] for d in snapshot["devices"])
            item = event()
            started = time.monotonic()
            sender.send_json({"op": "publish", "event": item})
            assert until(sender, "accepted")["duplicate"] is False
            received = until(receiver, "event")
            assert received["id"] == item["id"] and received["source"] == aid
            assert time.monotonic() - started < 2
            receiver.send_json({"op": "ack", "id": item["id"]})
            until(receiver, "acked")
            assert hub.LINK.store.pending(bid) == []
            assert hub.LINK.sessions[bid].sent == {}
            assert hub.LINK.store.pending(aid) == []
        assert not any(d["online"] for d in hub.LINK.presence())


def test_slow_publish_does_not_block_health_or_another_socket_heartbeat(hub, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = hub.LINK.store.publish
    def slow_publish(*args, **kwargs):
        entered.set()
        if not release.wait(3):
            raise ValueError("Synthetic slow store was not released")
        return original(*args, **kwargs)
    monkeypatch.setattr(hub.LINK.store, "publish", slow_publish)
    with client(hub) as c:
        key, source = pair(hub, c)
        other_key, other = pair(hub, c)
        with socket(c, key, source) as sender, socket(c, other_key, other) as receiver:
            until(sender, "welcome")
            until(receiver, "welcome")
            item = event(targets=[other])
            sender.send_json({"op": "publish", "event": item})
            try:
                assert entered.wait(1)
                started = time.monotonic()
                assert c.get("/v1/health").status_code == 200
                receiver.send_json({"op": "ping"})
                until(receiver, "pong")
                assert time.monotonic() - started < 1
                assert not hub.LINK.store.pending(other)
            finally:
                release.set()
            assert until(sender, "accepted")["id"] == item["id"]
            assert until(receiver, "event")["id"] == item["id"]


def test_slow_periodic_cleanup_does_not_block_health(hub, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = hub.LINK.store.cleanup
    def slow_cleanup(*args, **kwargs):
        entered.set()
        if not release.wait(3):
            raise ValueError("Synthetic cleanup was not released")
        return original(*args, **kwargs)
    monkeypatch.setattr(hub.LINK.store, "cleanup", slow_cleanup)
    try:
        with client(hub) as c:
            assert entered.wait(1)
            started = time.monotonic()
            assert c.get("/v1/health").status_code == 200
            assert time.monotonic() - started < 1
            release.set()
    finally:
        release.set()


def test_pump_send_timeout_logs_only_fixed_phase_and_cause(hub, monkeypatch, caplog):
    caplog.set_level("INFO", logger="orion_hub.link")
    original = Session.send
    async def timed_send(session, value):
        if value["op"] == "presence":
            raise asyncio.TimeoutError("PRIVATE_TIMEOUT_FRAME_BODY")
        await original(session, value)
    monkeypatch.setattr(Session, "send", timed_send)
    with client(hub) as c:
        key, device = pair(hub, c)
        with socket(c, key, device) as ws:
            until(ws, "welcome")
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
    assert f"disconnected source={device} cause=timeout phase=pump" in caplog.text
    assert "PRIVATE_TIMEOUT_FRAME_BODY" not in caplog.text


def test_peer_close_logs_numeric_code_without_private_reason(hub, caplog):
    caplog.set_level("INFO", logger="orion_hub.link")
    with client(hub) as c:
        key, device = pair(hub, c)
        with socket(c, key, device) as ws:
            until(ws, "welcome")
            ws.close(code=1008, reason="PRIVATE_PEER_REASON_AND_BODY")
    assert f"disconnected source={device} cause=peer_closed phase=receive peer_code=1008" in caplog.text
    assert "PRIVATE_PEER_REASON_AND_BODY" not in caplog.text


@pytest.mark.parametrize("failure, expected", [
    (WebSocketDisconnect(999999, "PRIVATE_PEER_REASON"), "cause=peer_closed phase=receive peer_code=1006"),
    (RuntimeError("PRIVATE_RUNTIME_BODY"), "cause=runtime_error phase=receive"),
])
def test_disconnect_metadata_clamps_peer_codes_and_never_logs_exception_text(hub, monkeypatch, caplog, failure, expected):
    caplog.set_level("INFO", logger="orion_hub.link")
    async def failing_receive(*_):
        raise failure
    monkeypatch.setattr(hub.LINK, "receive", failing_receive)
    with client(hub) as c:
        key, device = pair(hub, c)
        with socket(c, key, device) as ws:
            until(ws, "welcome")
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
    assert f"disconnected source={device} {expected}" in caplog.text
    assert "PRIVATE_" not in caplog.text


def test_offline_delivery_survives_restart_and_reconnect(hub):
    with client(hub) as c:
        key, source = pair(hub, c)
        other, target = pair(hub, c)
        item = event(targets=[target])
        with socket(c, key, source) as ws:
            until(ws, "welcome")
            ws.send_json({"op": "publish", "event": item})
            until(ws, "accepted")
        # Recreate the bus/database exactly as a process restart does.
        from orion_hub.link import Bus
        hub.LINK = Bus(Database(hub.DB.path))
        with socket(c, other, target) as ws:
            until(ws, "welcome")
            assert until(ws, "event")["id"] == item["id"]
            # Disconnect before ACK; it must be replayed again.
        with socket(c, other, target) as ws:
            until(ws, "welcome")
            assert until(ws, "event")["id"] == item["id"]
            ws.send_json({"op": "ack", "id": item["id"]})
            until(ws, "acked")
        with socket(c, other, target) as ws:
            until(ws, "welcome")
            ws.send_json({"op": "ping"})
            until(ws, "pong")
            assert hub.LINK.store.pending(target) == []


def test_newer_authenticated_connection_replaces_stale_session(hub):
    # A phone that changed networks reconnects while its old socket has not
    # yet timed out. Rejecting it let a fresh clipboard copy expire unseen.
    with client(hub) as c:
        _, source = pair(hub, c)
        key, target = pair(hub, c)
        with socket(c, key, target) as stale:
            until(stale, "welcome")
            stale_session = hub.LINK.sessions[target]
            with socket(c, key, target) as fresh:
                until(fresh, "welcome")
                assert hub.LINK.sessions[target] is not stale_session
                assert stale_session.finished.is_set()
                item = event(targets=[target])
                hub.LINK.store.publish(source, item)
                assert until(fresh, "event")["id"] == item["id"]
                with pytest.raises(WebSocketDisconnect):
                    for _ in range(20):
                        assert stale.receive_json()["op"] != "event"
                # The replaced session's cleanup must not evict its successor.
                assert target in hub.LINK.sessions
                assert {d["id"]: d["online"] for d in hub.LINK.presence()}[target]
                fresh.send_json({"op": "ack", "id": item["id"]})
                until(fresh, "acked")
                assert hub.LINK.store.pending(target) == []


def test_retry_until_ack(hub, monkeypatch):
    monkeypatch.setattr("orion_hub.link.RETRY_SECONDS", 0.05)
    with client(hub) as c:
        _, source = pair(hub, c)
        key, target = pair(hub, c)
        item = event(targets=[target])
        hub.LINK.store.publish(source, item)
        with socket(c, key, target) as ws:
            until(ws, "welcome")
            assert until(ws, "event")["id"] == until(ws, "event")["id"] == item["id"]
            ws.send_json({"op": "ack", "id": item["id"]})
            until(ws, "acked")
            assert hub.LINK.store.pending(target) == []


def test_candidate_keyset_pages_stay_bounded_and_preserve_fifo_after_ack_shrink(hub):
    c = client(hub)
    _, source = pair(hub, c)
    _, target = pair(hub, c)
    rows = seeded_pending(hub, source, target, 251)
    first = hub.LINK.store.pending(target)
    assert [row["id"] for row in first] == [row[0] for row in rows[:100]]
    with hub.DB.connect() as connection:
        connection.executemany("DELETE FROM link_deliveries WHERE event_id=? AND device_id=?", ((row["id"], target) for row in first))
    second = hub.LINK.store.pending(target, (first[-1]["created_at"], first[-1]["id"]))
    assert [row["id"] for row in second] == [row[0] for row in rows[100:200]]
    third = hub.LINK.store.pending(target, (second[-1]["created_at"], second[-1]["id"]))
    assert [row["id"] for row in third] == [row[0] for row in rows[200:]]
    assert all(len(page) <= 100 for page in (first, second, third))
    assert hub.LINK.store.pending(source) == []


def test_unacknowledged_head_cannot_hide_short_lived_clipboard_and_retry_times_survive_wrap(hub, monkeypatch):
    c = client(hub)
    _, source = pair(hub, c)
    _, target = pair(hub, c)
    old = seeded_pending(hub, source, target, 201)
    clipboard = event(type="clipboard", targets=[target], ttl_seconds=30,
                      payload={"mime": "text/plain", "sha256": hashlib.sha256(b"").hexdigest(), "size": 0, "text": ""})
    hub.LINK.store.publish(source, clipboard)
    monkeypatch.setattr("orion_hub.link.POLL_SECONDS", 0.01)
    async def exercise():
        offered = asyncio.Event()
        seen = []
        class Socket:
            async def send_json(self, value):
                if value["op"] == "event":
                    seen.append(value["id"])
                    if value["id"] == clipboard["id"]: offered.set()
            async def close(self, **_): pass
        session = Session(Socket())
        bus = Bus(hub.DB)
        bus.sessions[target] = session
        task = asyncio.create_task(bus.pump(target, session))
        try:
            await asyncio.wait_for(offered.wait(), timeout=2)
            # Let a further complete cursor cycle occur. None should be sent
            # again before the original five-second retry interval.
            await asyncio.sleep(0.1)
            assert seen[:201] == [row[0] for row in old]
            assert len(seen) == len(set(seen)) == 202
            assert len(session.sent) <= 1000
            assert hub.DB.row("SELECT COUNT(*) AS n FROM link_deliveries WHERE device_id=?", (target,))["n"] == 202
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())


def test_slow_batch_records_successful_send_time_not_pump_start_for_retries(hub, monkeypatch):
    c = client(hub)
    _, source = pair(hub, c)
    _, target = pair(hub, c)
    rows = seeded_pending(hub, source, target, 2)
    clock = [time.time()]
    monkeypatch.setattr("orion_hub.link.time.time", lambda: clock[0])
    monkeypatch.setattr("orion_hub.link.POLL_SECONDS", 0.01)
    async def exercise():
        sent = asyncio.Event()
        seen = []
        class Socket:
            async def send_json(self, value):
                if value["op"] == "event":
                    seen.append(value["id"])
                    if len(seen) <= 2: clock[0] += 3
                    if len(seen) == 2: sent.set()
            async def close(self, **_): pass
        session = Session(Socket())
        bus = Bus(hub.DB)
        bus.sessions[target] = session
        task = asyncio.create_task(bus.pump(target, session))
        try:
            await asyncio.wait_for(sent.wait(), timeout=2)
            await asyncio.sleep(0.1)
            assert seen == [row[0] for row in rows]
            assert session.sent[rows[-1][0]].sent_at == clock[0]
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())


def test_full_slow_consumer_queue_backs_off_without_hiding_clipboard_and_expires(hub, monkeypatch):
    c = client(hub)
    _, source = pair(hub, c)
    _, target = pair(hub, c)
    rows = seeded_pending(hub, source, target, 999)
    clock = [time.time()]
    expires = clock[0] + 150
    hub.DB.execute("UPDATE link_events SET expires_at=?", (expires,))
    clipboard = event(type="clipboard", targets=[target], ttl_seconds=30,
                      payload={"mime": "text/plain", "sha256": hashlib.sha256(b"").hexdigest(), "size": 0, "text": ""})
    hub.LINK.store.publish(source, clipboard)
    monkeypatch.setattr("orion_hub.link.time.time", lambda: clock[0])
    monkeypatch.setattr("orion_hub.link.POLL_SECONDS", 0.001)
    async def exercise():
        counts = {}
        order = []
        class Socket:
            async def send_json(self, value):
                if value["op"] != "event": return
                counts[value["id"]] = counts.get(value["id"], 0) + 1
                order.append(value["id"])
                # A slow successful first send advances wall time; retry timing
                # starts after it completes, not at the beginning of the page.
                if len(order) == 1: clock[0] += 3
            async def close(self, **_): pass
        session = Session(Socket())
        bus = Bus(hub.DB)
        bus.sessions[target] = session
        task = asyncio.create_task(bus.pump(target, session))
        async def wait_for(predicate):
            deadline = time.monotonic() + 4
            while not predicate():
                assert time.monotonic() < deadline
                await asyncio.sleep(0.01)
        try:
            # Socket receipt precedes the pump committing retry bookkeeping;
            # wait for both rather than assuming they complete in one turn.
            await wait_for(lambda: len(counts) == 1000 and len(session.sent) == 1000)
            assert order == [row[0] for row in rows] + [clipboard["id"]]
            assert len(session.sent) == 1000
            start = clock[0]
            for elapsed, attempts in ((5, 2), (10, 2), (15, 3), (20, 3), (35, 4), (65, 5)):
                clock[0] = start + elapsed
                await wait_for(lambda: all(counts[row[0]] >= attempts for row in rows))
                # More than two full page cycles at the same time cannot cause
                # another retry, including at the old fixed-five-second points.
                await asyncio.sleep(0.15)
                assert all(counts[row[0]] == attempts for row in rows)
                assert len(session.sent) <= 1000
                assert all(state.attempts <= 4 for state in session.sent.values())
            assert counts[clipboard["id"]] == 3
            assert clipboard["id"] not in session.sent
            assert all(state.retry_at - state.sent_at == 30 for state in session.sent.values())
            clock[0] = expires - 2
            await wait_for(lambda: all(counts[row[0]] == 6 for row in rows)
                           and all(state.retry_at == expires for state in session.sent.values()))
            assert all(state.retry_at == expires for state in session.sent.values())
            # Expiry stops offering frames and clears state, even without ACK;
            # durable rows are removed only by the existing store cleanup.
            before = dict(counts)
            clock[0] = expires
            await wait_for(lambda: not session.sent)
            await asyncio.sleep(0.05)
            assert counts == before
            assert hub.LINK.store.pending(target) == []
            assert hub.DB.row("SELECT COUNT(*) AS n FROM link_deliveries WHERE device_id=?", (target,))["n"] == 1000
        finally:
            task.cancel()
            done, _ = await asyncio.wait((task,), timeout=2)
            assert done, "Cancelled delivery pump did not terminate"
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())


def test_reconnect_resets_backoff_but_preserves_unacked_id_and_durable_ack(hub, monkeypatch):
    monkeypatch.setattr("orion_hub.link.RETRY_SECONDS", 0.01)
    monkeypatch.setattr("orion_hub.link.POLL_SECONDS", 0.005)
    with client(hub) as c:
        _, source = pair(hub, c)
        key, target = pair(hub, c)
        item = event(targets=[target])
        hub.LINK.store.publish(source, item)
        with socket(c, key, target) as ws:
            until(ws, "welcome")
            assert until(ws, "event")["id"] == until(ws, "event")["id"] == item["id"]
            ws.send_json({"op": "ping"})
            until(ws, "pong")
            assert hub.LINK.sessions[target].sent[item["id"]].attempts >= 2
        monkeypatch.setattr("orion_hub.link.RETRY_SECONDS", 5)
        with socket(c, key, target) as ws:
            until(ws, "welcome")
            assert until(ws, "event")["id"] == item["id"]
            ws.send_json({"op": "ping"})
            until(ws, "pong")
            assert hub.LINK.sessions[target].sent[item["id"]].attempts == 1
            ws.send_json({"op": "ack", "id": item["id"]})
            until(ws, "acked")
            assert not hub.LINK.store.pending(target)
            assert not hub.LINK.sessions[target].sent


def test_pump_wraps_immediately_after_acks_shrink_below_cursor(hub, monkeypatch):
    c = client(hub)
    _, source = pair(hub, c)
    _, target = pair(hub, c)
    rows = seeded_pending(hub, source, target, 230)
    monkeypatch.setattr("orion_hub.link.POLL_SECONDS", 0.01)
    monkeypatch.setattr("orion_hub.link.RETRY_SECONDS", 0)
    async def exercise():
        retried = asyncio.Event()
        seen = []
        class Socket:
            async def send_json(self, value):
                if value["op"] != "event": return
                seen.append(value["id"])
                if len(seen) == 230:
                    # ACK all but the already-delivered head. The next keyset
                    # page is empty, so that surviving head must be revisited.
                    with hub.DB.connect() as connection:
                        connection.executemany("DELETE FROM link_deliveries WHERE event_id=? AND device_id=?", ((row[0], target) for row in rows[1:]))
                elif len(seen) == 231:
                    assert value["id"] == rows[0][0]
                    retried.set()
            async def close(self, **_): pass
        session = Session(Socket())
        bus = Bus(hub.DB)
        bus.sessions[target] = session
        task = asyncio.create_task(bus.pump(target, session))
        try:
            await asyncio.wait_for(retried.wait(), timeout=2)
            assert seen[:230] == [row[0] for row in rows]
            assert session.pending_after == (rows[0][5], rows[0][0])
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())


def test_idle_pump_waits_without_polling_and_wakes_for_other_connection_changes(hub, monkeypatch):
    # Physical acceptance measured ~19% of a core with idle devices polling
    # SQLite every 0.25 s each. Idle pumps now wait for a change instead.
    c = client(hub)
    _, source = pair(hub, c)
    _, target = pair(hub, c)
    monkeypatch.setattr("orion_hub.link.WATCH_SECONDS", 0.02)
    async def exercise():
        delivered = asyncio.Event()
        closed = asyncio.Event()
        seen = []
        class Socket:
            async def send_json(self, value):
                if value["op"] == "event":
                    seen.append(value["id"])
                    delivered.set()
            async def close(self, **_): closed.set()
        session = Session(Socket())
        bus = Bus(hub.DB)
        bus.sessions[target] = session
        calls = []
        real_pending = bus.store.pending
        bus.store.pending = lambda *args: calls.append(args) or real_pending(*args)
        task = asyncio.create_task(bus.pump(target, session))
        try:
            await asyncio.sleep(1.2)
            # Initial pass plus at most the watcher's first baseline wake; the
            # once-a-second no-op cleanup must not wake idle pumps either.
            await asyncio.to_thread(bus.store.cleanup)
            await asyncio.sleep(0.1)
            assert len(calls) <= 3
            # A publish committed through another connection (as by the HTTP
            # approval path or another process) is delivered promptly.
            item = event(targets=[target])
            await asyncio.to_thread(Store(hub.DB).publish, source, item)
            await asyncio.wait_for(delivered.wait(), timeout=2)
            assert seen == [item["id"]]
            await asyncio.to_thread(Store(hub.DB).acknowledge, target, item["id"])
            session.sent.clear()
            # Revocation from the CLI is another process; it must still close
            # an idle connection promptly rather than at the next heartbeat.
            await asyncio.to_thread(hub.DB.execute, "DELETE FROM devices WHERE id=?", (target,))
            await asyncio.wait_for(closed.wait(), timeout=2)
            await asyncio.wait_for(task, timeout=2)
        finally:
            task.cancel()
            bus.sessions.clear()
            await asyncio.gather(task, return_exceptions=True)
            if bus.watcher:
                await asyncio.wait_for(asyncio.gather(bus.watcher, return_exceptions=True), timeout=2)
    asyncio.run(exercise())


def test_idle_pump_wakes_immediately_for_presence_change(hub, monkeypatch):
    c = client(hub)
    _, target = pair(hub, c)
    monkeypatch.setattr("orion_hub.link.WATCH_SECONDS", 60)
    async def exercise():
        presence = []
        class Socket:
            async def send_json(self, value):
                if value["op"] == "presence": presence.append(value)
            async def close(self, **_): pass
        session = Session(Socket())
        bus = Bus(hub.DB)
        bus.sessions[target] = session
        task = asyncio.create_task(bus.pump(target, session))
        try:
            deadline = time.monotonic() + 2
            while len(presence) < 1:
                assert time.monotonic() < deadline
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.1)
            count = len(presence)
            bus.changed_presence()
            while len(presence) == count:
                assert time.monotonic() < deadline
                await asyncio.sleep(0.01)
        finally:
            task.cancel()
            bus.sessions.clear()
            await asyncio.gather(task, return_exceptions=True)
            if bus.watcher:
                bus.watcher.cancel()
                await asyncio.gather(bus.watcher, return_exceptions=True)
    asyncio.run(exercise())


def test_dedup_conflict_ttl_and_ack_isolation(hub):
    c = client(hub)
    _, source = pair(hub, c)
    _, target = pair(hub, c)
    _, excluded = pair(hub, c)
    store = hub.LINK.store
    item = event(targets=[target], ttl_seconds=1, payload={"text": "PRIVATE_BODY"})
    now = time.time()
    assert not store.publish(source, item, now)["duplicate"]
    assert store.publish(source, item, now)["duplicate"]
    assert len(store.pending(target)) == 1 and not store.pending(excluded)
    store.acknowledge(excluded, item["id"])
    assert len(store.pending(target)) == 1
    with pytest.raises(ValueError, match="conflict"):
        store.publish(excluded, item, now)
    with pytest.raises(ValueError, match="conflict"):
        store.publish(source, {**item, "payload": {}}, now)
    store.cleanup(now + 2)
    assert store.pending(target) == []
    assert hub.DB.row("SELECT payload_json FROM link_events")["payload_json"] is None
    assert store.publish(source, item, now + 2)["duplicate"]
    assert not store.pending(target)
    store.cleanup(now + 86401)
    assert hub.DB.rows("SELECT * FROM link_events") == []


@pytest.mark.parametrize("change", [
    {"id": "bad"}, {"source": "spoofed"}, {"ttl_seconds": 0}, {"ttl_seconds": 301},
    {"ttl_seconds": True}, {"type": "PRIVATE\nBODY"}, {"payload": []},
    {"payload": {"text": "x" * 65536}}, {"payload": {"number": float("nan")}},
    {"targets": []}, {"targets": ["unknown"]},
])
def test_rejected_envelopes_do_not_store_payloads(hub, change):
    c = client(hub)
    _, source = pair(hub, c)
    with pytest.raises(ValueError):
        hub.LINK.store.publish(source, event(**change))
    assert hub.DB.rows("SELECT * FROM link_events") == []


def test_queue_limits_are_atomic(hub, monkeypatch):
    c = client(hub)
    _, source = pair(hub, c)
    _, target = pair(hub, c)
    monkeypatch.setattr("orion_hub.link.MAX_PENDING", 1)
    hub.LINK.store.publish(source, event())
    with pytest.raises(ValueError, match="capacity"):
        hub.LINK.store.publish(source, event())
    assert len(hub.LINK.store.pending(target)) == 1
    assert len(hub.DB.rows("SELECT * FROM link_events")) == 1
    monkeypatch.setattr("orion_hub.link.MAX_EVENTS", 1)
    with pytest.raises(ValueError, match="capacity"):
        hub.LINK.store.publish(source, event())


def test_ten_thousand_expired_ids_allow_new_event_and_preserve_duplicate_protection(hub):
    c = client(hub)
    _, source = pair(hub, c)
    _, target = pair(hub, c)
    now = time.time()
    original = event(targets=[target], payload={"synthetic": True})
    prepared, _, digest = Store.prepare(original)
    rows = [(prepared.id, source, prepared.type, None, digest, now - 600, now - 540)]
    rows.extend((str(uuid4()), source, "test", None, "retained-synthetic-digest", now - 600, now - 540) for _ in range(9999))
    with hub.DB.connect() as connection:
        connection.executemany("INSERT INTO link_events VALUES(?,?,?,?,?,?,?)", rows)
    assert hub.LINK.store.publish(source, original, now)["duplicate"] is True
    assert not hub.LINK.store.pending(target)
    fresh = event(targets=[target])
    assert hub.LINK.store.publish(source, fresh, now)["duplicate"] is False
    assert hub.DB.row("SELECT COUNT(*) AS n FROM link_events")["n"] == 10001
    assert [r["id"] for r in hub.LINK.store.pending(target)] == [fresh["id"]]
    assert hub.DB.row("SELECT payload_json FROM link_events WHERE id=?", (original["id"],))["payload_json"] is None


def test_cleanup_with_forty_thousand_tombstones_has_bounded_work_and_preserves_history(hub, monkeypatch):
    c = client(hub)
    _, source = pair(hub, c)
    _, target = pair(hub, c)
    _, other = pair(hub, c)
    now = time.time()
    protected = event(targets=[target])
    prepared, _, digest = Store.prepare(protected)
    rows = [(prepared.id, source, prepared.type, None, digest, now - 600, now - 540)]
    rows.extend((str(uuid4()), source, "test", None, "synthetic-digest", now - 600, now - 540) for _ in range(39999))
    old, expired, expired_null, live, acked = [str(uuid4()) for _ in range(5)]
    rows.extend([
        (old, source, "test", None, "synthetic-digest", now - 86401, now - 86341),
        (expired, source, "test", "{}", "synthetic-digest", now - 60, now),
        (expired_null, source, "test", None, "synthetic-digest", now - 60, now),
        (live, source, "test", "{}", "synthetic-digest", now, now + 60),
        (acked, source, "test", "{}", "synthetic-digest", now, now + 60),
    ])
    with hub.DB.connect() as connection:
        connection.executemany("INSERT INTO link_events VALUES(?,?,?,?,?,?,?)", rows)
        connection.executemany("INSERT INTO link_deliveries VALUES(?,?)", ((ident, device) for ident in (old, expired, expired_null, live, acked) for device in (target, other)))
    hub.LINK.store.acknowledge(target, acked)
    steps = [0]
    original_connect = hub.DB.connect
    @contextmanager
    def measured_connect():
        with original_connect() as connection:
            def progress():
                steps[0] += 100
                # Abort a full history scan without relying on machine speed.
                return steps[0] > 10000
            connection.set_progress_handler(progress, 100)
            try:
                yield connection
            finally:
                connection.set_progress_handler(None, 0)
    with monkeypatch.context() as patch:
        patch.setattr(hub.DB, "connect", measured_connect)
        hub.LINK.store.cleanup(now)
    assert steps[0] <= 10000
    assert hub.DB.row("SELECT COUNT(*) AS n FROM link_events")["n"] == 40004
    assert hub.DB.row("SELECT id FROM link_events WHERE id=?", (old,)) is None
    assert hub.DB.row("SELECT payload_json FROM link_events WHERE id=?", (expired,))["payload_json"] is None
    assert hub.DB.row("SELECT payload_json FROM link_events WHERE id=?", (live,))["payload_json"] == "{}"
    assert {row["id"] for row in hub.LINK.store.pending(target)} == {live}
    assert {row["id"] for row in hub.LINK.store.pending(other)} == {live, acked}
    assert not hub.DB.row("SELECT event_id FROM link_deliveries WHERE event_id IN (?,?)", (expired, expired_null))
    assert hub.LINK.store.publish(source, protected, now)["duplicate"] is True
    assert not hub.DB.row("SELECT event_id FROM link_deliveries WHERE event_id=?", (protected["id"],))


@pytest.mark.parametrize("limit_name", ["MAX_EVENTS", "MAX_ID_HISTORY"])
def test_live_and_history_limits_reject_before_state_changes_and_replay_stays_duplicate(hub, monkeypatch, limit_name):
    c = client(hub)
    _, source = pair(hub, c)
    _, target = pair(hub, c)
    monkeypatch.setattr("orion_hub.link." + limit_name, 1)
    now = time.time()
    first = event(targets=[target], ttl_seconds=1)
    hub.LINK.store.publish(source, first, now)
    later = now + 2 if limit_name == "MAX_ID_HISTORY" else now
    rejected = event(type="battery", targets=[target], payload={"battery_level": 42, "is_charging": False})
    with pytest.raises(CapacityError, match="capacity"):
        hub.LINK.store.publish(source, rejected, later)
    assert not hub.DB.rows("SELECT * FROM phone_state")
    assert hub.DB.row("SELECT COUNT(*) AS n FROM link_events")["n"] == 1
    assert hub.DB.row("SELECT id FROM link_events WHERE id=?", (rejected["id"],)) is None
    assert hub.LINK.store.publish(source, first, later)["duplicate"] is True
    assert len(hub.LINK.store.pending(target)) == (limit_name == "MAX_EVENTS")


def test_socket_capacity_error_is_fixed_retryable_and_keeps_connection(hub, monkeypatch):
    with client(hub) as c:
        key, source = pair(hub, c)
        _, target = pair(hub, c)
        monkeypatch.setattr("orion_hub.link.MAX_ID_HISTORY", 0)
        with socket(c, key, source) as ws:
            until(ws, "welcome")
            ws.send_json({"op": "publish", "event": event(targets=[target])})
            assert until(ws, "error") == {"op": "error", "code": "capacity_reached", "retryable": True}
            ws.send_json({"op": "ping"})
            until(ws, "pong")
        assert not hub.DB.rows("SELECT * FROM link_events")


def test_auth_replay_wrong_key_path_time_and_browser(hub):
    from cryptography.hazmat.primitives.asymmetric import ec
    c = client(hub)
    key, device = pair(hub, c)
    signed = headers(key, device, "GET", "/v1/link")
    with c.websocket_connect("ws://100.64.0.1:8765/v1/link", headers=signed) as ws:
        until(ws, "welcome")
    invalid = [signed, {}, headers(ec.generate_private_key(ec.SECP256R1()), device, "GET", "/v1/link"),
               headers(key, device, "GET", "/v1/dashboard"), headers(key, device, "GET", "/v1/link", ts=int(time.time()) - 61),
               {**headers(key, device, "GET", "/v1/link"), "Origin": "https://example.com"}]
    for h in invalid:
        with pytest.raises(WebSocketDisconnect) as error:
            with c.websocket_connect("ws://100.64.0.1:8765/v1/link", headers=h):
                pass
        assert error.value.code == 1008


def test_link_denies_loopback_cloudflare_and_nonmesh_peers(hub):
    c = client(hub)
    key, device = pair(hub, c)
    for origin, peer in [("http://127.0.0.1:8765", "100.64.0.2"), ("https://public.example.com", "127.0.0.1"),
                         ("http://100.64.0.1:8765", "192.168.1.2")]:
        other = TestClient(hub.app, base_url=origin, client=(peer, 123))
        with pytest.raises(WebSocketDisconnect):
            with socket(other, key, device):
                pass
        assert other.get("/v1/link/devices", headers=headers(key, device, "GET", "/v1/link/devices")).status_code == 403
    assert c.get("/v1/link/devices").status_code == 401
    assert c.get("/v1/link/devices", headers=headers(key, device, "GET", "/v1/link/devices")).status_code == 200


def test_revocation_closes_open_socket_and_cascades_queue(hub):
    with client(hub) as c:
        _, source = pair(hub, c)
        key, target = pair(hub, c)
        hub.LINK.store.publish(source, event())
        with socket(c, key, target) as ws:
            until(ws, "welcome")
            hub.DB.execute("DELETE FROM devices WHERE id=?", (target,))
            with pytest.raises(WebSocketDisconnect) as error:
                while True:
                    ws.receive_json()
            assert error.value.code == 1008
        assert not hub.DB.rows("SELECT * FROM link_deliveries")
        with pytest.raises(WebSocketDisconnect):
            with socket(c, key, target):
                pass


def test_invalid_frames_and_logs_never_contain_bodies(hub, caplog):
    caplog.set_level("INFO", logger="orion_hub.link")
    with client(hub) as c:
        key, source = pair(hub, c)
        with socket(c, key, source) as ws:
            until(ws, "welcome")
            ws.send_json({"op": "publish", "event": event(payload={"text": "PRIVATE_BODY"})})
            until(ws, "accepted")
            ws.send_json({"op": "publish", "event": {"id": "bad", "payload": {"text": "PRIVATE_BODY"}}})
            assert until(ws, "error") == {"op": "error", "code": "invalid_message"}
            ws.send_text("PRIVATE_BODY")
            until(ws, "error")
            ws.send_text("x" * 65537)
            with pytest.raises(WebSocketDisconnect) as error:
                while True:
                    ws.receive_json()
            assert error.value.code == 1009
    assert "PRIVATE_BODY" not in caplog.text


def test_binary_frames_are_rejected(hub):
    with client(hub) as c:
        key, source = pair(hub, c)
        with socket(c, key, source) as ws:
            until(ws, "welcome")
            ws.send_bytes(b"PRIVATE_BODY")
            with pytest.raises(WebSocketDisconnect) as error:
                while True:
                    ws.receive_json()
            assert error.value.code == 1003


def test_server_only_binds_loopback_and_configured_mesh(monkeypatch):
    from orion_hub.server import listener_hosts
    monkeypatch.delenv("ORION_HUB_MESH_IP", raising=False)
    assert listener_hosts() == ["127.0.0.1"]
    monkeypatch.setenv("ORION_HUB_MESH_IP", "100.64.0.1")
    assert listener_hosts() == ["127.0.0.1", "100.64.0.1"]
    for value in ["0.0.0.0", "192.168.1.19", "::", "127.0.0.1"]:
        monkeypatch.setenv("ORION_HUB_MESH_IP", value)
        with pytest.raises(ValueError):
            listener_hosts()


def test_rejected_link_logs_the_fixed_reason_such_as_a_stale_clock(hub, caplog):
    # A Raspberry Pi that booted with a stale clock sees every device's signed time as wrong.
    caplog.set_level("INFO", logger="orion_hub.link")
    with client(hub) as c:
        key, device = pair(hub, c)
        url = str(c.base_url).replace("http", "ws", 1).rstrip("/") + "/v1/link"
        stale = headers(key, device, "GET", "/v1/link", ts=int(time.time()) - 600)
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(url, headers=stale) as ws:
                ws.receive_json()
    assert "rejected link connection reason=Expired request" in caplog.text
    assert stale["X-Orion-Signature"] not in caplog.text
