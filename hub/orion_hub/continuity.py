# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validated continuity state and fixed Wake-on-LAN targets on the home hub."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import time
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA = """
CREATE TABLE IF NOT EXISTS link_focus(source TEXT PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE, plan_json TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS link_dnd(source TEXT PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE, active INTEGER NOT NULL, changed_at INTEGER NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS link_wake(event_id TEXT PRIMARY KEY REFERENCES link_events(id) ON DELETE CASCADE, target TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending');
"""


def validate(event):
    body = event.payload
    if event.type == "handoff":
        if set(body) != {"kind", "value"} or body["kind"] not in {"link", "text"} or not isinstance(body["value"], str) or not 0 < len(body["value"].encode()) <= 32768 or not event.targets or len(event.targets) != 1:
            raise ValueError("Invalid handoff envelope")
        if body["kind"] == "link":
            parsed = urlsplit(body["value"])
            if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password or any(ord(c) < 32 for c in body["value"]):
                raise ValueError("Invalid handoff envelope")
    elif event.type == "focus.plan":
        if set(body) != {"enabled", "timezone", "start_hour", "start_minute", "end_hour", "end_minute"} or type(body["enabled"]) is not bool or not isinstance(body["timezone"], str) or len(body["timezone"]) > 120:
            raise ValueError("Invalid Focus envelope")
        try:
            ZoneInfo(body["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Invalid Focus timezone") from None
        for key, ceiling in (("start_hour", 23), ("end_hour", 23), ("start_minute", 59), ("end_minute", 59)):
            if type(body[key]) is not int or not 0 <= body[key] <= ceiling:
                raise ValueError("Invalid Focus envelope")
        if event.targets is not None:
            raise ValueError("Focus schedules are shared with all paired devices")
    elif event.type == "focus.state":
        # Live Do Not Disturb: one boolean and the time the owner changed it.
        if set(body) != {"active", "changed_at"} or type(body["active"]) is not bool or type(body["changed_at"]) is not int or not 0 < body["changed_at"] < 2**41:
            raise ValueError("Invalid Do Not Disturb envelope")
        if event.targets is not None:
            raise ValueError("Do Not Disturb is shared with all paired devices")
    elif event.type == "wake":
        if set(body) != {"target"} or not isinstance(body["target"], str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", body["target"]) or event.targets is not None:
            raise ValueError("Invalid wake envelope")
        if body["target"] not in wake_targets():
            raise ValueError("Wake target is not configured")


def apply(connection, source, event, now):
    validate(event)
    if event.type == "focus.plan":
        connection.execute("INSERT INTO link_focus VALUES(?,?,?) ON CONFLICT(source) DO UPDATE SET plan_json=excluded.plan_json,updated_at=excluded.updated_at", (source, json.dumps(event.payload), now))
    elif event.type == "focus.state":
        connection.execute("INSERT INTO link_dnd VALUES(?,?,?,?) ON CONFLICT(source) DO UPDATE SET active=excluded.active,changed_at=excluded.changed_at,updated_at=excluded.updated_at",
                           (source, int(event.payload["active"]), event.payload["changed_at"], now))


def after_insert(connection, event):
    if event.type == "wake":
        connection.execute("INSERT INTO link_wake(event_id,target) VALUES(?,?)", (event.id, event.payload["target"]))


def snapshot(db):
    row = db.row("SELECT source,plan_json,updated_at FROM link_focus ORDER BY updated_at DESC,source LIMIT 1")
    # Devices that reconnect after the five-minute event TTL still converge.
    dnd = db.row("SELECT source,active,changed_at FROM link_dnd ORDER BY changed_at DESC,updated_at DESC,source LIMIT 1")
    return {"focus": {"source": row["source"], "payload": json.loads(row["plan_json"]), "updated_at": row["updated_at"]} if row else None,
            "dnd": {"source": dnd["source"], "active": bool(dnd["active"]), "changed_at": dnd["changed_at"]} if dnd else None,
            "wake_targets": sorted(wake_targets())}


def wake_targets():
    path = Path(os.environ.get("ORION_WAKE_TARGETS", "/etc/orion-wake-targets.json"))
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text())
        if not isinstance(raw, dict) or len(raw) > 16:
            raise ValueError()
        for name, value in raw.items():
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", name) or set(value) != {"mac", "broadcast"} or not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", value["mac"]):
                raise ValueError()
            address = ipaddress.ip_address(value["broadcast"])
            if address.version != 4 or not address.is_private or address.is_loopback or address in ipaddress.ip_network("100.64.0.0/10"):
                raise ValueError()
        return raw
    except (ValueError, TypeError, KeyError, OSError):
        return {}


def magic_packet(mac):
    if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", mac):
        raise ValueError("Invalid Wake-on-LAN target")
    return b"\xff" * 6 + bytes.fromhex(mac.replace(":", "")) * 16


def dispatch(db, now=None):
    """Maintenance loop calls this; one local UDP packet, never caller-controlled IP."""
    now = time.time() if now is None else now
    targets = wake_targets()
    rows = db.rows("SELECT w.event_id,w.target,e.expires_at FROM link_wake w JOIN link_events e ON e.id=w.event_id WHERE w.status='pending' ORDER BY e.created_at LIMIT 16")
    for row in rows:
        if row["expires_at"] <= now:
            db.execute("UPDATE link_wake SET status='expired' WHERE event_id=?", (row["event_id"],))
            continue
        value = targets.get(row["target"])
        if not value:
            continue
        # Mark first. A process crash may lose one wake request but will never emit
        # repeated packets for a duplicate event or after a service restart.
        with db.connect() as connection:
            claimed = connection.execute("UPDATE link_wake SET status='sent' WHERE event_id=? AND status='pending'", (row["event_id"],)).rowcount
        if not claimed:
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                udp.sendto(magic_packet(value["mac"]), (value["broadcast"], 9))
        except OSError:
            db.execute("UPDATE link_wake SET status='failed' WHERE event_id=?", (row["event_id"],))
