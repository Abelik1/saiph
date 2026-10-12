# SPDX-License-Identifier: AGPL-3.0-or-later
"""Privacy-safe Link evidence; synthetic checks never certify the hardware week."""
from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from .storage import read_json, write_json

SCHEMA = "orion.link.acceptance/v1"
DEVICES = {"desktop", "laptop", "galaxy", "pi", "droplet"}
SCENARIOS = {"reboot", "sleep_wake", "home", "tcd", "hotspot", "clipboard_text", "clipboard_image",
             "clipboard_rapid", "notification", "notification_action", "sms", "photo", "file_send", "handoff", "dnd", "backup_restore"}
MAINTENANCE_BUTTONS = {"setup", "connect", "refresh", "sync", "restart_app", "start_worker", "repair_permission"}
REQUIRED = {(d, "reboot") for d in DEVICES} | {
    ("desktop", "sleep_wake"), ("laptop", "sleep_wake"), ("laptop", "home"), ("laptop", "tcd"), ("laptop", "hotspot"),
    ("galaxy", "notification"), ("galaxy", "notification_action"), ("galaxy", "sms"), ("galaxy", "photo"),
    ("galaxy", "file_send"), ("desktop", "file_send"), ("laptop", "file_send"), ("desktop", "handoff"),
    ("galaxy", "dnd"), ("pi", "backup_restore"),
} | {(d, "clipboard_rapid") for d in ("desktop", "laptop", "galaxy")}
REQUIRED_DIRECTIONS = {(source, target, kind) for source in ("desktop", "laptop", "galaxy")
                       for target in ("desktop", "laptop", "galaxy") if source != target
                       for kind in ("clipboard_text", "clipboard_image")}


def stamp(now=None):
    return datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).isoformat()


def start(path: Path, now=None):
    if path.exists():
        raise ValueError("An acceptance journal already exists")
    journal = {"schema": SCHEMA, "started_at": stamp(now), "observations": []}
    write_json(path, journal)
    return journal


def load(path: Path):
    journal = read_json(path, {})
    if journal.get("schema") != SCHEMA or not isinstance(journal.get("observations"), list):
        raise ValueError("Start an acceptance journal first")
    try:
        datetime.fromisoformat(journal["started_at"])
    except (KeyError, ValueError, TypeError):
        raise ValueError("Invalid acceptance journal") from None
    return journal


def record(path: Path, device: str, scenario: str, success: bool, button: str = "", now=None, peer: str = ""):
    if device not in DEVICES or scenario not in SCENARIOS or not isinstance(success, bool) or \
            (button and button not in MAINTENANCE_BUTTONS) or (peer and (peer not in DEVICES or peer == device)):
        raise ValueError("Use a listed device, scenario and maintenance button")
    journal = load(path)
    if len(journal["observations"]) >= 10_000:
        raise ValueError("Acceptance journal capacity reached")
    journal["observations"].append({"at": stamp(now), "device": device, "scenario": scenario, "success": success, "button": button, "peer": peer})
    write_json(path, journal)
    return report(journal, now)


def report(journal: dict, now=None):
    now = time.time() if now is None else now
    started = datetime.fromisoformat(journal["started_at"]).timestamp()
    completed = set()
    directions = set()
    failed = buttons = invalid = 0
    days = set()
    for observation in journal["observations"]:
        try:
            at = datetime.fromisoformat(observation["at"]).timestamp()
            if not started <= at <= now or observation["device"] not in DEVICES or observation["scenario"] not in SCENARIOS or \
                    not isinstance(observation["success"], bool) or observation.get("button", "") not in MAINTENANCE_BUTTONS | {""}:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            invalid += 1
            continue
        days.add(int((at - started) // 86400))
        if observation["success"]:
            completed.add((observation["device"], observation["scenario"]))
            directions.add((observation["device"], observation.get("peer", ""), observation["scenario"]))
        else:
            failed += 1
        buttons += bool(observation.get("button"))
    missing = [{"device": d, "scenario": s} for d, s in sorted(REQUIRED - completed)]
    missing.extend({"device": source, "peer": target, "scenario": scenario}
                   for source, target, scenario in sorted(REQUIRED_DIRECTIONS - directions))
    elapsed = max(0, now - started)
    eligible = elapsed >= 7 * 86400 and set(range(7)) <= days and not missing and not failed and not buttons and not invalid
    return {"schema": SCHEMA, "elapsed_days": round(elapsed / 86400, 3), "observed_days": len(days),
            "failures": failed, "maintenance_buttons": buttons, "invalid_observations": invalid, "missing": missing,
            "status": "owner_observations_complete" if eligible else "pending",
            "note": "Owner observations; automated soak alone does not establish a hardware reliability week"}


def support_snapshot(database: Path, data: Path):
    """Allowlisted database metadata only: no names, keys, tokens or payload columns."""
    snapshot = {"schema": "orion.link.support/v1", "at": stamp(), "integrity": "unavailable", "counts": {}, "release": {}}
    if database.is_file():
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            snapshot["integrity"] = "ok" if connection.execute("PRAGMA quick_check").fetchone()[0] == "ok" else "failed"
            present = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ("devices", "link_events", "link_deliveries", "phone_notifications", "phone_features", "inbox"):
                if table in present:
                    snapshot["counts"][table] = connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            if "link_deliveries" in present:
                age = connection.execute("SELECT MAX(?-e.created_at) FROM link_deliveries d JOIN link_events e ON e.id=d.event_id WHERE e.expires_at>?", (time.time(), time.time())).fetchone()[0]
                snapshot["oldest_pending_seconds"] = max(0, round(age, 2)) if age is not None else 0
        finally:
            connection.close()
    metadata = read_json(data / "releases" / "android" / "release.json", {})
    if isinstance(metadata, dict):
        for field in ("version_code", "version_name", "sha256"):
            value = metadata.get(field)
            if field == "version_code" and isinstance(value, int):
                snapshot["release"][field] = value
            elif field == "version_name" and isinstance(value, str) and re.fullmatch(r"[0-9A-Za-z.+_-]{1,80}", value):
                snapshot["release"][field] = value
            elif field == "sha256" and isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value):
                snapshot["release"][field] = value
    snapshot["backup_count"] = len(list((data / "backups").glob("orion-hub-*.sqlite3")))
    return snapshot


class ProbeEvidence:
    """Whitelist frame metadata instead of serializing arbitrary server frames."""
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.counts = {"welcome": 0, "reconnecting": 0, "accepted": 0, "received": 0, "expired": 0, "error": 0}
        self.max_latency_ms = 0

    def append(self, kind: str, *, event_id="", age_ms=0, online=None):
        if kind not in self.counts and kind not in {"presence", "heartbeat", "finished"}:
            return
        row = {"at": stamp(), "kind": kind}
        if re.fullmatch(r"[0-9a-f-]{36}", event_id):
            row["id"] = event_id
        if kind == "received" and isinstance(age_ms, (int, float)):
            latency = max(0, min(int(age_ms), 86_400_000))
            row["age_ms"] = latency
            self.max_latency_ms = max(self.max_latency_ms, latency)
        if isinstance(online, int):
            row["online"] = max(0, min(online, 1000))
        if kind in self.counts:
            self.counts[kind] += 1
        if kind in {"heartbeat", "finished"}:
            row["counts"] = dict(self.counts)
            row["max_latency_ms"] = self.max_latency_ms
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(row, separators=(",", ":")) + "\n")
