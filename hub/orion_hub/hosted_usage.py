# SPDX-License-Identifier: AGPL-3.0-or-later
"""Aggregate-only usage statistics for the shared Hosted service.

Apps send at most one anonymous batch per day after their owner opts in
(docs/USAGE_ANALYTICS.md). Each batch is validated against the published field
list and immediately folded into daily totals: no batch, address, account,
token or identifier is stored. Service-wide request totals are kept the same
way. Totals older than RETENTION_DAYS are deleted.
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
import re
import sqlite3
import threading
import time
from pathlib import Path

RETENTION_DAYS = 400
MAX_BATCH_BYTES = 4096
ACCEPT_PER_MINUTE = 1200  # Service-wide; abuse can inflate counts, never expose data.

APPS = {"desktop": {"windows", "linux"}, "android": {"android"}}
MODES = {"hub", "hosted", "none"}
AGES = {"0", "1-6", "7-29", "30-89", "90+"}
STAGES = {"installed", "connected", "phone_added", "setup_completed"}
BUCKETS = {"1", "2-5", "6-20", "21+"}
# The published field list. Apps may send only these names.
FEATURES = {
    "desktop": {
        "clipboard_sent", "clipboard_received", "phone_notification", "notification_action", "code_copy",
        "sms_send", "call", "find_phone", "file_to_phone", "photo_save", "photo_drag", "phone_mirror",
        "phone_camera", "phone_microphone", "handoff", "dnd_toggle", "hotspot", "cloud_open",
        "hosted_file_send", "hosted_file_save", "device_approved",
        "screen_phone", "screen_cloud", "screen_settings", "screen_messages", "screen_photos",
        "screen_calls", "screen_files", "screen_apps",
    },
    "android": {
        "app_open", "clipboard_sent", "clipboard_received", "notification_shared", "hosted_file_send",
        "hosted_file_save", "pairing_started", "hosted_enrolled", "dnd_shared",
        "screen_home", "screen_settings", "screen_advanced", "screen_hosted",
    },
}
VERSION = re.compile(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}(?:[-+.][A-Za-z0-9.]{1,20})?")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
KEYS = {"schema", "day", "app", "platform", "version", "mode", "install_age", "stage", "features"}

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS usage_active(day TEXT NOT NULL, app TEXT NOT NULL, platform TEXT NOT NULL, version TEXT NOT NULL,
    mode TEXT NOT NULL, install_age TEXT NOT NULL, stage TEXT NOT NULL, installs INTEGER NOT NULL,
    PRIMARY KEY(day, app, platform, version, mode, install_age, stage));
CREATE TABLE IF NOT EXISTS usage_feature(day TEXT NOT NULL, app TEXT NOT NULL, feature TEXT NOT NULL, bucket TEXT NOT NULL,
    installs INTEGER NOT NULL, PRIMARY KEY(day, app, feature, bucket));
CREATE TABLE IF NOT EXISTS service_daily(day TEXT NOT NULL, metric TEXT NOT NULL, status TEXT NOT NULL, requests INTEGER NOT NULL,
    PRIMARY KEY(day, metric, status));
"""


def _today(now=None) -> str:
    return datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).strftime("%Y-%m-%d")


def validate(batch, *, now=None) -> dict:
    """Return the batch if it matches the published schema exactly; otherwise ValueError."""
    if not isinstance(batch, dict) or set(batch) != KEYS or type(batch["schema"]) is not int or batch["schema"] != 1:
        raise ValueError("Unsupported usage batch")
    app, platform = batch["app"], batch["platform"]
    if app not in APPS or platform not in APPS[app]:
        raise ValueError("Unsupported usage batch")
    day = batch["day"]
    if type(day) is not str or not DAY.fullmatch(day):
        raise ValueError("Unsupported usage batch")
    today = datetime.strptime(_today(now), "%Y-%m-%d")
    try:
        sent = datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Unsupported usage batch") from None
    if not today - timedelta(days=7) <= sent <= today:
        raise ValueError("Usage batch is outside the accepted days")
    if (type(batch["version"]) is not str or len(batch["version"]) > 32 or not VERSION.fullmatch(batch["version"])
            or batch["mode"] not in MODES or batch["install_age"] not in AGES or batch["stage"] not in STAGES):
        raise ValueError("Unsupported usage batch")
    features = batch["features"]
    if (not isinstance(features, dict) or len(features) > len(FEATURES[app])
            or any(name not in FEATURES[app] or value not in BUCKETS for name, value in features.items())):
        raise ValueError("Unsupported usage batch")
    return batch


def classify(method: str, path: str) -> str | None:
    """A fixed metric name for a request; never includes IDs or path parameters."""
    if path == "/v1/health":
        return None
    if path == "/v1/usage":
        return "usage.batch"
    if path.startswith("/v1/download/"):
        return "download.file"
    if path in ("/v1/beta/redeem", "/v1/beta/access", "/v1/beta/download"):
        return "beta." + path.rsplit("/", 1)[1]
    if path == "/v1/account":
        return "account"
    if path.startswith("/v1/devices/"):
        return "devices.requests" if path == "/v1/devices/requests" else "devices.rosters"
    if path == "/v1/sealed/events":
        return "sealed.publish" if method == "POST" else "sealed.poll"
    if path.startswith("/v1/sealed/events/"):
        return "sealed.ack"
    if path.startswith("/v1/sealed/blobs"):
        return "sealed.blobs"
    return "other"


class UsageStore:
    """One SQLite file of daily totals beside the account registry."""

    def __init__(self, directory: Path, *, clock=time.time):
        self.path = Path(directory) / "usage.sqlite3"
        self.clock = clock
        self._lock = threading.Lock()
        self._service: Counter = Counter()
        self._window = (0, 0)  # (minute, accepted) for the service-wide rate limit
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.executescript(SCHEMA)

    def _connect(self):
        return closing(sqlite3.connect(self.path, timeout=10))

    def admit(self) -> bool:
        """Service-wide acceptance budget; no per-client state or address is kept."""
        with self._lock:
            minute = int(self.clock() // 60)
            current, accepted = self._window
            if current != minute:
                current, accepted = minute, 0
            if accepted >= ACCEPT_PER_MINUTE:
                self._window = (current, accepted)
                return False
            self._window = (current, accepted + 1)
            return True

    def ingest(self, batch) -> None:
        batch = validate(batch, now=self.clock())
        with self._connect() as db, db:
            db.execute("INSERT INTO usage_active VALUES(?,?,?,?,?,?,?,1) ON CONFLICT DO UPDATE SET installs=installs+1",
                       (batch["day"], batch["app"], batch["platform"], batch["version"], batch["mode"],
                        batch["install_age"], batch["stage"]))
            db.executemany("INSERT INTO usage_feature VALUES(?,?,?,?,1) ON CONFLICT DO UPDATE SET installs=installs+1",
                           [(batch["day"], batch["app"], name, value) for name, value in sorted(batch["features"].items())])

    def request(self, method: str, path: str, status: int) -> None:
        """Count one finished request in memory; flush() writes the totals."""
        metric = classify(method, path)
        if metric is None:
            return
        status_class = f"{status // 100}xx" if 100 <= status < 600 else "other"
        with self._lock:
            self._service[(_today(self.clock()), metric, status_class)] += 1

    def flush(self) -> None:
        with self._lock:
            pending, self._service = self._service, Counter()
        cutoff = (datetime.strptime(_today(self.clock()), "%Y-%m-%d") - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%d")
        try:
            with self._connect() as db, db:
                db.executemany("INSERT INTO service_daily VALUES(?,?,?,?) ON CONFLICT DO UPDATE SET requests=requests+excluded.requests",
                               [(day, metric, status, count) for (day, metric, status), count in pending.items()])
                for table in ("usage_active", "usage_feature", "service_daily"):
                    db.execute(f"DELETE FROM {table} WHERE day<?", (cutoff,))
        except sqlite3.Error:
            with self._lock:
                self._service.update(pending)  # Keep the totals for the next attempt.
            raise

    def report(self, days: int = 30) -> dict:
        """Totals for the administrator; contains no per-install rows because none exist."""
        if type(days) is not int or not 1 <= days <= RETENTION_DAYS:
            raise ValueError("Choose 1 to 400 days")
        since = (datetime.strptime(_today(self.clock()), "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
        with self._connect() as db:
            def rows(query):
                cursor = db.execute(query, (since,))
                names = [column[0] for column in cursor.description]
                return [dict(zip(names, row)) for row in cursor.fetchall()]
            return {
                "since": since,
                "active": rows("SELECT day,app,platform,version,mode,install_age,stage,installs FROM usage_active WHERE day>=? ORDER BY day,app"),
                "features": rows("SELECT day,app,feature,bucket,installs FROM usage_feature WHERE day>=? ORDER BY day,app,feature"),
                "service": rows("SELECT day,metric,status,requests FROM service_daily WHERE day>=? ORDER BY day,metric"),
            }
