# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signed Handoff and timezone-aware Focus schedules. Never executes remote commands."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .platform import FocusAdapter


def validate_handoff(payload):
    if not isinstance(payload, dict) or set(payload) != {"kind", "value"}:
        raise ValueError("Invalid handoff.")
    kind, value = payload["kind"], payload["value"]
    if kind not in {"link", "text"} or not isinstance(value, str) or not 0 < len(value.encode()) <= 32768:
        raise ValueError("Invalid handoff.")
    if kind == "link":
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password or any(ord(c) < 32 for c in value):
            raise ValueError("Only web links can be handed off.")
    return {"kind": kind, "value": value}


def received_file_handoff(workspace, item_id):
    """Only completed local transfers may become deliberately opened file handoffs."""
    try:
        item = workspace.store.get("handoff", item_id)
        if item.get("kind") != "file" or item.get("file_id") != item_id:
            raise ValueError()
        received = workspace.store.get("phone_file", item_id)
        if received.get("device_id") != item.get("source") or not received.get("path"):
            raise ValueError()
        destination = received.get("destination", "downloads")
        if destination == "downloads":
            directory = Path.home() / "Downloads" / "Orion"
        elif destination == "cloud":
            from .cloud import ensure_layout
            directory = ensure_layout(workspace.settings) / "Shared"
        else:
            raise ValueError()
        path = Path(received["path"]).resolve(strict=True)
        if not path.is_file() or path.parent != directory.resolve():
            raise ValueError()
        return path
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("This received file is unavailable.") from None


def validate_plan(plan):
    if not isinstance(plan, dict) or set(plan) != {"enabled", "timezone", "start_hour", "start_minute", "end_hour", "end_minute"}:
        raise ValueError("Invalid Focus schedule.")
    if not isinstance(plan["enabled"], bool) or not isinstance(plan["timezone"], str):
        raise ValueError("Invalid Focus schedule.")
    try:
        ZoneInfo(plan["timezone"])
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Choose an IANA timezone for Focus.") from None
    for key, ceiling in (("start_hour", 23), ("end_hour", 23), ("start_minute", 59), ("end_minute", 59)):
        if type(plan[key]) is not int or not 0 <= plan[key] <= ceiling:
            raise ValueError("Invalid Focus schedule.")
    return dict(plan)


def focus_active(plan, now=None):
    plan = validate_plan(plan)
    if not plan["enabled"]:
        return False
    local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(plan["timezone"]))
    current = local.hour * 60 + local.minute
    start = plan["start_hour"] * 60 + plan["start_minute"]
    end = plan["end_hour"] * 60 + plan["end_minute"]
    if start == end:
        return False
    return start <= current < end if start < end else current >= start or current < end


class Continuity:
    def __init__(self, workspace, publish, focus=None):
        self.workspace, self.publish = workspace, publish
        self.focus = focus or FocusAdapter(workspace.root / "focus-system.json")
        self.last_plan = None

    def event(self, frame):
        if frame["type"] == "handoff":
            payload = validate_handoff(frame["payload"])
            self.workspace.store.save("handoff", {"id": frame["id"], "source": frame["source"], **payload, "status": "ready"})
            rows = self.workspace.store.all("handoff")
            for old in rows[100:]:
                self.workspace.store.delete("handoff", old["id"])
            return True
        if frame["type"] == "focus.plan":
            self.workspace.store.save("focus_plan", {"id": "shared", "plan": validate_plan(frame["payload"]), "source": frame["source"]})
            self.tick(publish=False)
            return True
        return False

    def tick(self, *, publish=True):
        settings = self.workspace.settings
        link = settings.get("link") or {}
        enabled = link.get("focus", True)
        # The desktop with an enabled sleep plan is the plan's publisher. A lecture
        # laptop with sleep_plan switched off follows the last shared plan instead.
        if settings["machine"]["features"].get("sleep_plan"):
            sleep = settings["sleep_plan"]
            plan = validate_plan({"enabled": bool(enabled), "timezone": link.get("timezone", "Europe/London"),
                                  "start_hour": sleep["hour"], "start_minute": sleep["minute"],
                                  "end_hour": link.get("wake_hour", 7), "end_minute": link.get("wake_minute", 0)})
            digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
            if publish and digest != self.last_plan:
                self.publish({"id": str(uuid4()), "type": "focus.plan", "ttl_seconds": 300, "payload": plan})
                self.last_plan = digest
            self.workspace.store.save("focus_plan", {"id": "local", "plan": plan})
        else:
            try:
                plan = self.workspace.store.get("focus_plan", "shared")["plan"]
            except ValueError:
                return
        self.focus.set(enabled and focus_active(plan))

    def handoff(self, target, kind, value):
        payload = validate_handoff({"kind": kind, "value": value})
        event = {"id": str(uuid4()), "type": "handoff", "ttl_seconds": 300, "targets": [target], "payload": payload}
        self.publish(event)
        return {"queued": True, "id": event["id"]}
