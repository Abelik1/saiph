# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signed Handoff, timezone-aware Focus schedules and shared Do Not Disturb. Never executes remote commands."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .platform import FocusAdapter, system_dnd


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
            from .paths import received_dir
            # Files received before every transfer used Downloads → Saiph stay openable.
            directories = (received_dir(), Path.home() / "Downloads" / "Orion")
        elif destination == "cloud":
            from .cloud import ensure_layout
            directories = (ensure_layout(workspace.settings) / "Shared",)
        else:
            raise ValueError()
        path = Path(received["path"]).resolve(strict=True)
        if not path.is_file() or path.parent not in {directory.resolve() for directory in directories}:
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


def validate_dnd(payload):
    if (not isinstance(payload, dict) or set(payload) != {"active", "changed_at"} or type(payload["active"]) is not bool
            or type(payload["changed_at"]) is not int or not 0 < payload["changed_at"] < 2**41):
        raise ValueError("Invalid Do Not Disturb state.")
    return dict(payload)


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
    def __init__(self, workspace, publish, focus=None, system=system_dnd, clock=time.time):
        self.workspace, self.publish = workspace, publish
        self.focus = focus or FocusAdapter(workspace.root / "focus-system.json")
        self.last_plan = None
        self.system, self.clock = system, clock
        self.last_system = None  # The first reading is a baseline, never a change.
        self.dnd_unsent = False
        self.dnd_released = False
        self.plan_quiet = False

    def event(self, frame):
        if frame["type"] == "handoff":
            payload = validate_handoff(frame["payload"])
            self.workspace.store.save("handoff", {"id": frame["id"], "source": frame["source"], **payload, "status": "ready"})
            rows = self.workspace.store.all("handoff")
            for old in rows[100:]:
                self.workspace.store.delete("handoff", old["id"])
            return True
        if frame["type"] == "focus.state":
            if self.remember_dnd(validate_dnd(frame["payload"]), frame["source"]):
                self.dnd_unsent = False  # A newer change from another device supersedes ours.
                self.apply()
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
                plan = None
        self.plan_quiet = bool(enabled and plan and focus_active(plan))
        self.apply()

    # Live Do Not Disturb. The newest change from any device wins; a device only
    # publishes changes its owner made, so applying a shared state never echoes.
    def dnd_enabled(self):
        return (self.workspace.settings.get("link") or {}).get("dnd_sync", True) is not False

    def dnd_state(self):
        try:
            return self.workspace.store.get("focus_state", "shared")
        except ValueError:
            return None

    def remember_dnd(self, payload, source):
        current = self.dnd_state()
        if current and current["changed_at"] > payload["changed_at"]:
            return False
        self.workspace.store.save("focus_state", {"id": "shared", "active": payload["active"], "changed_at": payload["changed_at"], "source": source})
        if current and current["active"] and not payload["active"]:
            self.dnd_released = True
        return True

    def apply(self):
        state = self.dnd_state()
        quiet = self.plan_quiet or bool(self.dnd_enabled() and state and state["active"])
        if not quiet and self.dnd_released and getattr(self.focus, "quiet", False) and getattr(self.focus, "previous", None) is not None:
            # Ending shared Do Not Disturb means notifications return, even when
            # GNOME banners were already off because the owner started it there.
            self.focus.previous = True
        self.dnd_released = False
        self.focus.set(quiet)

    def set_dnd(self, active, *, publish=True):
        if type(active) is not bool:
            raise ValueError("Do Not Disturb is on or off.")
        if not self.dnd_enabled():
            raise ValueError("Turn on Do Not Disturb sync in Settings first.")
        current = self.dnd_state()
        changed_at = max(int(self.clock()), current["changed_at"] + 1 if current else 0)
        self.remember_dnd({"active": active, "changed_at": changed_at}, (self.workspace.settings.get("hub") or {}).get("device_id", ""))
        self.dnd_unsent = True
        self.apply()
        if publish:
            self.flush_dnd()
        return {"active": active, "shared": not self.dnd_unsent}

    def flush_dnd(self):
        state = self.dnd_state()
        if not self.dnd_unsent or not state:
            return
        try:
            self.publish({"id": str(uuid4()), "type": "focus.state", "ttl_seconds": 300,
                          "payload": {"active": state["active"], "changed_at": state["changed_at"]}})
            self.dnd_unsent = False
        except ValueError:
            pass  # Offline: the next connected poll sends the newest state.

    def poll_dnd(self, *, publish=True):
        """Share the owner's own Do Not Disturb changes on this computer. True when state changed."""
        reading = self.system(self.focus)
        previous, changed = self.last_system, False
        if reading is not None:
            self.last_system = reading
        if self.dnd_enabled() and reading is not None and previous is not None and reading != previous:
            state = self.dnd_state()
            if not state or state["active"] != reading:
                self.set_dnd(reading, publish=False)
                changed = True
        if publish:
            self.flush_dnd()
        return changed

    def dnd_status(self):
        state = self.dnd_state() or {}
        return {"enabled": self.dnd_enabled(), "active": bool(state.get("active")), "source": state.get("source", ""),
                "changed_at": state.get("changed_at"), "quiet": bool(getattr(self.focus, "quiet", False))}

    def handoff(self, target, kind, value):
        payload = validate_handoff({"kind": kind, "value": value})
        event = {"id": str(uuid4()), "type": "handoff", "ttl_seconds": 300, "targets": [target], "payload": payload}
        self.publish(event)
        return {"queued": True, "id": event["id"]}
