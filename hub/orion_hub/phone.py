# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bounded phone state. All content stays in SQLite/API responses, never logs."""
from __future__ import annotations

import json
import time
from pydantic import BaseModel, ConfigDict, Field

class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

class Action(Payload):
    index: int = Field(ge=0, le=99)
    label: str = Field(max_length=120)

class Notification(Payload):
    key: str = Field(min_length=1, max_length=512)
    app: str = Field(min_length=1, max_length=240)
    package: str = Field(min_length=1, max_length=240)
    title: str = Field(max_length=512)
    text: str = Field(default="", max_length=4096)
    timestamp: int = Field(ge=0)
    actions: list[Action] = Field(default_factory=list, max_length=10)
    reply_key: str | None = Field(default=None, max_length=240)
    silent: bool = False

class Removed(Payload):
    key: str = Field(min_length=1, max_length=512)

class Snapshot(Payload):
    keys: list[str] = Field(max_length=500)

class Command(Payload):
    key: str = Field(min_length=1, max_length=512)
    operation: str = Field(pattern=r"^(dismiss|action|reply|open)$")
    index: int | None = Field(default=None, ge=0, le=99)
    text: str | None = Field(default=None, max_length=4096)
    reply_key: str | None = Field(default=None, max_length=240)

class Battery(Payload):
    battery_level: int = Field(ge=0, le=100)
    is_charging: bool

MODELS = {"notification.upsert": Notification, "notification.remove": Removed,
          "notification.sync": Snapshot, "notification.command": Command, "battery": Battery}

def apply(connection, source: str, event, now: float):
    model = MODELS.get(event.type)
    if model is None:
        return
    try:
        value = model.model_validate(event.payload)
        if isinstance(value, Snapshot) and (len(set(value.keys)) != len(value.keys) or
                any(not 0 < len(key) <= 512 for key in value.keys)):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("Invalid feature envelope") from None
    if isinstance(value, Battery):
        connection.execute("INSERT INTO phone_state VALUES(?,?,?) ON CONFLICT(device_id) DO UPDATE SET battery_json=excluded.battery_json,updated_at=excluded.updated_at",
                           (source, value.model_dump_json(), now))
    elif isinstance(value, Notification):
        if connection.execute("SELECT COUNT(*) FROM phone_notifications WHERE device_id=?", (source,)).fetchone()[0] >= 500 and not connection.execute(
                "SELECT 1 FROM phone_notifications WHERE device_id=? AND notification_key=?", (source, value.key)).fetchone():
            raise ValueError("Notification capacity reached")
        if len({action.index for action in value.actions}) != len(value.actions):
            raise ValueError("Invalid feature envelope")
        connection.execute("INSERT INTO phone_notifications VALUES(?,?,?,?) ON CONFLICT(device_id,notification_key) DO UPDATE SET data_json=excluded.data_json,updated_at=excluded.updated_at",
                           (source, value.key, value.model_dump_json(), now))
    elif isinstance(value, Removed):
        connection.execute("DELETE FROM phone_notifications WHERE device_id=? AND notification_key=?", (source, value.key))
    elif isinstance(value, Snapshot):
        rows = connection.execute("SELECT notification_key FROM phone_notifications WHERE device_id=?", (source,)).fetchall()
        current = set(value.keys)
        connection.executemany("DELETE FROM phone_notifications WHERE device_id=? AND notification_key=?",
                               [(source, row[0]) for row in rows if row[0] not in current])
    elif isinstance(value, Command):
        if event.targets is None or len(event.targets) != 1:
            raise ValueError("Notification commands require one owning phone")
        owner = event.targets[0]
        row = connection.execute("SELECT data_json FROM phone_notifications WHERE device_id=? AND notification_key=?", (owner, value.key)).fetchone()
        if row is None:
            raise ValueError("Notification no longer active")
        notification = json.loads(row[0])
        if value.operation == "action":
            if value.index not in {a["index"] for a in notification["actions"]} or value.text is not None or value.reply_key is not None:
                raise ValueError("Notification action unavailable")
        elif value.operation == "reply":
            if not value.text or value.reply_key != notification["reply_key"] or not value.reply_key or value.index is not None:
                raise ValueError("Notification reply unavailable")
        elif any(v is not None for v in (value.index, value.text, value.reply_key)):
            raise ValueError("Invalid feature envelope")

def snapshot(db, devices):
    battery = {r["device_id"]: {**json.loads(r["battery_json"]), "updated_at": r["updated_at"]}
               for r in db.rows("SELECT * FROM phone_state")}
    notices = [{**json.loads(r["data_json"]), "device_id": r["device_id"], "updated_at": r["updated_at"]}
               for r in db.rows("SELECT * FROM phone_notifications ORDER BY updated_at DESC LIMIT 1000")]
    return {"devices": [{**d, "battery": battery.get(d["id"])} for d in devices], "notifications": notices, "server_time": time.time()}
