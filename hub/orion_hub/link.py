# SPDX-License-Identifier: AGPL-3.0-or-later
"""Small mesh events. Payloads never enter logs or error messages."""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from uuid import UUID

from anyio import CancelScope
from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field

from .db import Database
from .security import now_iso, verify_device_request
from . import phone, clipboard, continuity, features

MAX_FRAME_BYTES = 65_536
MAX_EVENTS = 10_000
MAX_ID_HISTORY = 100_000
MAX_PENDING = 1_000
RETRY_SECONDS = 5
MAX_RETRY_SECONDS = 30
POLL_SECONDS = 0.25
# An idle pump (nothing pending or awaiting ACK) sleeps until woken by an
# in-process publish/presence change or by any committed database change seen
# through one shared data_version watcher, instead of querying per device.
WATCH_SECONDS = 0.25
LAST_SEEN_SECONDS = 15
ID_RETENTION_SECONDS = 86_400
MESH_V4 = ipaddress.ip_network("100.64.0.0/10")
MESH_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")
log = logging.getLogger("orion_hub.link")


class CapacityError(ValueError):
    """Bounded queue/history pressure, distinct from an invalid private frame."""


def require_mesh(connection):
    """Check the actual listener, not Host or a client-supplied forwarding header."""
    mesh_ip = os.environ.get("ORION_HUB_MESH_IP", "")
    server = connection.scope.get("server")
    peer = connection.client
    try:
        address = ipaddress.ip_address(peer.host) if peer else None
        if not mesh_ip or not server or server[0] != mesh_ip or address not in (MESH_V4 if address.version == 4 else MESH_V6):
            raise ValueError()
    except (ValueError, AttributeError):
        raise HTTPException(403, "Link requires the mesh listener") from None


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    type: str = Field(pattern=r"^[a-z][a-z0-9_.]{0,63}$")
    ttl_seconds: int = Field(default=60, ge=1, le=300)
    targets: list[str] | None = Field(default=None, max_length=32)
    payload: dict = Field(default_factory=dict)


class Store:
    def __init__(self, db: Database):
        self.db = db

    def cleanup(self, now=None):
        now = time.time() if now is None else now
        with self.db.connect() as c:
            c.execute("DELETE FROM link_deliveries WHERE EXISTS (SELECT 1 FROM link_events e WHERE e.id=link_deliveries.event_id AND e.expires_at<=?)", (now,))
            c.execute("UPDATE link_events SET payload_json=NULL WHERE expires_at<=? AND payload_json IS NOT NULL", (now,))
            c.execute("DELETE FROM link_events WHERE created_at<=?", (now - ID_RETENTION_SECONDS,))

    @staticmethod
    def prepare(raw: dict):
        try:
            event = Event.model_validate(raw)
            # UUIDs give devices globally unique IDs without hub coordination.
            if str(UUID(event.id)) != event.id:
                raise ValueError()
            if event.targets is not None and (not event.targets or len(set(event.targets)) != len(event.targets)):
                raise ValueError()
            wire = json.dumps(event.model_dump(), sort_keys=True, separators=(",", ":"), allow_nan=False)
            if len(wire.encode()) > MAX_FRAME_BYTES - 1024:
                raise ValueError()
        except (ValueError, TypeError, OverflowError, RecursionError):
            raise ValueError("Invalid event envelope") from None
        return event, wire, hashlib.sha256(wire.encode()).hexdigest()

    def publish(self, source: str, raw: dict, now=None):
        now = time.time() if now is None else now
        event, wire, digest = self.prepare(raw)
        self.cleanup(now)
        with self.db.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            result = self.insert(c, source, event, digest, now)
            destinations = c.execute("SELECT COUNT(*) FROM link_deliveries WHERE event_id=?", (event.id,)).fetchone()[0]
        if not result["duplicate"]:
            log.info("accepted type=%s id=%s source=%s bytes=%d destinations=%d", event.type, event.id, source, len(wire.encode()), destinations)
        return result

    def publish_in_transaction(self, connection, source: str, raw: dict, now):
        """Caller owns BEGIN/commit so owner approval and dispatch remain atomic."""
        event, _, digest = self.prepare(raw)
        return self.insert(connection, source, event, digest, now)

    @staticmethod
    def insert(c, source, event, digest, now):
        old = c.execute("SELECT source,digest FROM link_events WHERE id=?", (event.id,)).fetchone()
        if old:
            if old["source"] != source or old["digest"] != digest:
                raise ValueError("Event ID conflict")
            return {"op": "accepted", "id": event.id, "duplicate": True}
        devices = {r[0] for r in c.execute("SELECT id FROM devices")}
        if source not in devices:
            raise ValueError("Device revoked")
        targets = devices - {source} if event.targets is None else set(event.targets)
        if source in targets or not targets <= devices:
            raise ValueError("Invalid target devices")
        if c.execute("SELECT COUNT(*) FROM link_events WHERE expires_at>? AND payload_json IS NOT NULL", (now,)).fetchone()[0] >= MAX_EVENTS:
            raise CapacityError("Event capacity reached; retry later")
        if c.execute("SELECT COUNT(*) FROM link_events").fetchone()[0] >= MAX_ID_HISTORY:
            raise CapacityError("Event ID history capacity reached; retry later")
        for target in targets:
            if c.execute("SELECT COUNT(*) FROM link_deliveries WHERE device_id=?", (target,)).fetchone()[0] >= MAX_PENDING:
                raise CapacityError("Delivery capacity reached; retry later")
        phone.apply(c, source, event, now)
        clipboard.validate(event)
        features.apply(c, source, event, now)
        continuity.apply(c, source, event, now)
        c.execute("INSERT INTO link_events VALUES(?,?,?,?,?,?,?)", (
            event.id, source, event.type, json.dumps(event.payload, separators=(",", ":"), allow_nan=False), digest, now, now + event.ttl_seconds,
        ))
        continuity.after_insert(c, event)
        c.executemany("INSERT INTO link_deliveries VALUES(?,?)", [(event.id, target) for target in sorted(targets)])
        return {"op": "accepted", "id": event.id, "duplicate": False}

    def pending(self, device_id: str, after: tuple[float, str] | None = None):
        cursor = " AND (e.created_at>? OR (e.created_at=? AND e.id>?))" if after else ""
        arguments = (device_id, time.time(), after[0], after[0], after[1]) if after else (device_id, time.time())
        return self.db.rows("SELECT e.* FROM link_events e JOIN link_deliveries d ON d.event_id=e.id "
                            "WHERE d.device_id=? AND e.expires_at>?" + cursor + " ORDER BY e.created_at,e.id LIMIT 100", arguments)

    def acknowledge(self, device_id: str, event_id: str):
        self.db.execute("DELETE FROM link_deliveries WHERE event_id=? AND device_id=?", (event_id, device_id))

    @staticmethod
    def envelope(row):
        return {"op": "event", "id": row["id"], "type": row["type"], "source": row["source"],
                "created_at": row["created_at"], "expires_at": row["expires_at"], "payload": json.loads(row["payload_json"])}


@dataclass
class DeliveryRetry:
    sent_at: float
    retry_at: float
    attempts: int
    expires_at: float


async def socket_timeout(awaitable, seconds):
    """Bound socket I/O without Python 3.10 wait_for losing cancellation.

    In that runtime wait_for can return a just-completed child after its caller
    was cancelled. A pump would then keep running during connection teardown.
    wait propagates caller cancellation even when socket I/O completes at once.
    """
    operation = asyncio.ensure_future(awaitable)
    try:
        done, _ = await asyncio.wait((operation,), timeout=seconds)
        if not done:
            raise asyncio.TimeoutError()
        return operation.result()
    finally:
        operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)


@dataclass
class Session:
    socket: WebSocket
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    sent: dict[str, DeliveryRetry] = field(default_factory=dict)
    pending_after: tuple[float, str] | None = None
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    superseded: asyncio.Event = field(default_factory=asyncio.Event)
    finished: asyncio.Event = field(default_factory=asyncio.Event)

    async def send(self, value):
        async with self.lock:
            await socket_timeout(self.socket.send_json(value), 5)


class DataVersionReader:
    """Serialize connection creation, querying and close across worker threads.

    Cancelling asyncio.to_thread does not stop its worker. A watcher must never
    close SQLite while that worker is still executing, even during loop teardown.
    """
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.connection = None
        self.closed = False

    def read(self):
        with self.lock:
            if self.closed:
                return None
            if self.connection is None:
                self.connection = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
            cursor = self.connection.execute("PRAGMA data_version")
            try:
                return cursor.fetchone()[0]
            finally:
                cursor.close()

    def close(self):
        with self.lock:
            self.closed = True
            if self.connection is not None:
                self.connection.close()
                self.connection = None


class Bus:
    def __init__(self, db: Database):
        self.db = db
        self.store = Store(db)
        self.sessions: dict[str, Session] = {}
        self.revision = 0
        self.watcher: asyncio.Task | None = None
        self.takeovers: dict[str, asyncio.Lock] = {}

    def wake_all(self):
        for session in list(self.sessions.values()):
            session.wake.set()

    def changed_presence(self):
        self.revision += 1
        self.wake_all()

    def ensure_watcher(self):
        if self.watcher is None or self.watcher.done():
            self.watcher = asyncio.get_running_loop().create_task(self.watch())

    async def watch(self):
        """Wake idle pumps after any commit by another connection or process.

        Every Hub query uses its own connection, so this read-only connection
        observes in-process writes too, including revocation through the CLI.
        """
        reader = DataVersionReader(self.db.path)
        try:
            version = None
            while self.sessions:
                current = await asyncio.to_thread(reader.read)
                # The first wake covers changes made before the baseline read.
                if current != version:
                    self.wake_all()
                version = current
                await asyncio.sleep(WATCH_SECONDS)
        finally:
            # The lock also covers a read still running after cancellation.
            with CancelScope(shield=True):
                await asyncio.to_thread(reader.close)

    def presence(self):
        rows = self.db.rows("SELECT d.id,d.name,d.last_seen_at,l.capabilities_json FROM devices d "
                            "LEFT JOIN link_devices l ON l.device_id=d.id ORDER BY d.created_at")
        return [{"id": r["id"], "name": r["name"], "online": r["id"] in self.sessions,
                 "last_seen_at": r["last_seen_at"], "capabilities": json.loads(r["capabilities_json"] or "[]")} for r in rows]

    async def pump(self, device_id, session):
        revision = -1
        last_seen = 0
        while True:
            # Clear before reading so a change during this pass wakes the next one.
            session.wake.clear()
            if not await asyncio.to_thread(self.db.row, "SELECT id FROM devices WHERE id=?", (device_id,)):
                await session.socket.close(code=1008, reason="Device revoked")
                return
            if revision != self.revision:
                revision = self.revision
                await session.send({"op": "presence", "devices": await asyncio.to_thread(self.presence)})
            now = time.time()
            if now - last_seen >= LAST_SEEN_SECONDS:
                await asyncio.to_thread(self.db.execute, "UPDATE devices SET last_seen_at=? WHERE id=?", (now_iso(), device_id))
                last_seen = now
            pending = await asyncio.to_thread(self.store.pending, device_id, session.pending_after)
            if not pending and session.pending_after:
                # Keyset paging preserves FIFO when ACKs remove earlier rows.
                # Wrap immediately at the tail, including after expiry/shrink.
                session.pending_after = None
                pending = await asyncio.to_thread(self.store.pending, device_id)
            if pending:
                last = pending[-1]
                session.pending_after = (last["created_at"], last["id"])
            # Retain bounded retry state across pages until ACK or expiry. A
            # slow consumer must not receive every pending row every five seconds.
            session.sent = {k: v for k, v in session.sent.items() if v.expires_at > now}
            for row in pending:
                current = time.time()
                previous = session.sent.get(row["id"])
                if row["expires_at"] <= current:
                    session.sent.pop(row["id"], None)
                    continue
                if previous is None or current >= previous.retry_at:
                    await session.send(self.store.envelope(row))
                    delivered_at = time.time()
                    attempts = min(previous.attempts + 1, 4) if previous else 1
                    delay = min(RETRY_SECONDS * (2 ** (attempts - 1)), MAX_RETRY_SECONDS)
                    session.sent.pop(row["id"], None)
                    session.sent[row["id"]] = DeliveryRetry(delivered_at, min(delivered_at + delay, row["expires_at"]), attempts, row["expires_at"])
                    if len(session.sent) > MAX_PENDING:
                        session.sent.pop(next(iter(session.sent)))
                    log.info("delivered type=%s id=%s source=%s destination=%s bytes=%d age_ms=%d", row["type"], row["id"], row["source"], device_id, len(row["payload_json"].encode()), max(0, int((delivered_at-row["created_at"])*1000)))
            if pending or session.sent:
                # Paging and retry timing keep the established fixed cadence.
                await asyncio.sleep(POLL_SECONDS)
            else:
                self.ensure_watcher()
                try:
                    await socket_timeout(session.wake.wait(), max(0.0, last_seen + LAST_SEEN_SECONDS - time.time()))
                except asyncio.TimeoutError:
                    pass

    async def receive(self, device_id, session):
        while True:
            packet = await socket_timeout(session.socket.receive(), 45)
            if packet["type"] == "websocket.disconnect":
                raise WebSocketDisconnect(packet.get("code", 1000))
            text = packet.get("text")
            if text is None:
                await session.socket.close(code=1003, reason="Text JSON required")
                return
            if len(text.encode()) > MAX_FRAME_BYTES:
                await session.socket.close(code=1009, reason="Frame too large")
                return
            if not await asyncio.to_thread(self.db.row, "SELECT id FROM devices WHERE id=?", (device_id,)):
                await session.socket.close(code=1008, reason="Device revoked")
                return
            try:
                message = json.loads(text)
                if not isinstance(message, dict):
                    raise ValueError()
                op = message.get("op")
                if op == "publish" and set(message) == {"op", "event"}:
                    result = await asyncio.to_thread(self.store.publish, device_id, message["event"])
                    if not result["duplicate"]:
                        self.wake_all()
                    await session.send(result)
                elif op == "ack" and set(message) == {"op", "id"} and isinstance(message["id"], str) and len(message["id"]) <= 36:
                    await asyncio.to_thread(self.store.acknowledge, device_id, message["id"])
                    session.sent.pop(message["id"], None)
                    await session.send({"op": "acked", "id": message["id"]})
                elif op == "hello" and set(message) == {"op", "capabilities"}:
                    caps = message["capabilities"]
                    if not isinstance(caps, list) or len(caps) > 32 or not all(isinstance(v, str) and 0 < len(v) <= 64 and v.isascii() and all(ch.isalnum() or ch in "_.-" for ch in v) for v in caps):
                        raise ValueError()
                    await asyncio.to_thread(self.db.execute, "INSERT INTO link_devices VALUES(?,?) ON CONFLICT(device_id) DO UPDATE SET capabilities_json=excluded.capabilities_json", (device_id, json.dumps(sorted(set(caps)))))
                    self.changed_presence()
                elif op == "ping" and set(message) == {"op"}:
                    await session.send({"op": "pong"})
                else:
                    raise ValueError()
            except CapacityError:
                log.warning("rejected source=%s code=capacity_reached", device_id)
                await session.send({"op": "error", "code": "capacity_reached", "retryable": True})
            except (ValueError, TypeError, RecursionError):
                # Never echo a rejected frame or Pydantic's payload-bearing errors.
                log.warning("rejected source=%s code=invalid_message", device_id)
                await session.send({"op": "error", "code": "invalid_message"})
            # Buffered socket frames and sends can complete without yielding.
            # Keep heartbeats and unrelated HTTP requests runnable during sync.
            await asyncio.sleep(0)

    async def connect(self, socket: WebSocket):
        try:
            require_mesh(socket)
            if socket.headers.get("origin"):
                raise HTTPException(403, "Browser connections are not supported")
            principal = await asyncio.to_thread(verify_device_request, self.db, socket, b"")
        except HTTPException:
            await socket.close(code=1008)
            return
        device_id = principal["id"]
        # One connection per identity. A reconnect cannot leave an old fan-out
        # reader. A newer signed (nonce-checked) connection replaces the old
        # one: after a network change the old socket can look alive for up to
        # the 45 s receive timeout, and rejecting the reconnect meanwhile let
        # short-lived events such as clipboard copies expire undelivered.
        async with self.takeovers.setdefault(device_id, asyncio.Lock()):
            old = self.sessions.get(device_id)
            if old is not None:
                old.superseded.set()
                try:
                    await socket_timeout(old.finished.wait(), 10)
                except asyncio.TimeoutError:
                    await socket.close(code=1013, reason="Device already connected; retry")
                    return
            await socket.accept()
            session = Session(socket)
            self.sessions[device_id] = session
            self.changed_presence()
        tasks = []
        phase = "welcome"
        try:
            await session.send({"op": "welcome", "device_id": device_id, "heartbeat_seconds": 15, "max_frame_bytes": MAX_FRAME_BYTES})
            tasks = [asyncio.create_task(self.pump(device_id, session)), asyncio.create_task(self.receive(device_id, session)),
                     asyncio.create_task(session.superseded.wait())]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if tasks[2] in done:
                log.info("disconnected source=%s cause=superseded", device_id)
            for task in done - {tasks[2]}:
                phase = "pump" if task is tasks[0] else "receive"
                task.result()
        except WebSocketDisconnect as error:
            # Peers control reasons and can supply unusual close values. Only a
            # finite numeric protocol code enters diagnostics, never reason/text.
            code = error.code if type(error.code) is int and 1000 <= error.code <= 4999 else 1006
            log.info("disconnected source=%s cause=peer_closed phase=%s peer_code=%d", device_id, phase, code)
        except asyncio.TimeoutError:
            log.info("disconnected source=%s cause=timeout phase=%s", device_id, phase)
        except RuntimeError:
            log.info("disconnected source=%s cause=runtime_error phase=%s", device_id, phase)
        finally:
            # A replacement session may already be registered; never remove it.
            if self.sessions.get(device_id) is session:
                self.sessions.pop(device_id)
            self.changed_presence()
            # ASGI cancellation must not interrupt cleanup and leave a stale
            # presence entry or reader task that blocks the next reconnect.
            with CancelScope(shield=True):
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                # Reader and pump have stopped; a replacement may now start.
                session.finished.set()
                try:
                    await socket_timeout(socket.close(), 5)
                except (RuntimeError, WebSocketDisconnect, asyncio.TimeoutError):
                    pass
