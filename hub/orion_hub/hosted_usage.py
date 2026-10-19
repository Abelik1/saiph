# SPDX-License-Identifier: AGPL-3.0-or-later
"""Aggregate-only usage statistics for the shared Hosted service.

Apps send at most one anonymous batch per day after their owner opts in
(docs/USAGE_ANALYTICS.md). Each batch is validated against the published field
list and immediately folded into daily totals: no batch, address, account,
token or identifier is stored. Service-wide request totals, delivery health and
the number of active accounts and devices are kept the same way: identifiers
are held in memory only for the current day and only their count is written.
Totals older than RETENTION_DAYS are deleted. Reports hide groups smaller than
MIN_CELL so a single person cannot be picked out.
"""
from __future__ import annotations

from collections import Counter, OrderedDict
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
MIN_CELL = 5  # Report groups of fewer installs than this are hidden.
IN_FLIGHT = 20_000  # Sealed events awaiting delivery that are timed, in memory only.

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
# Schema 2 additions. Each is folded into its own daily total, never combined
# with the others, so no detailed profile of one install is ever stored.
ACTIVE_DAYS = {"0", "1", "2-3", "4-6", "7"}
OS = {"windows": {"windows_10", "windows_11", "windows_other"},
      "linux": {"linux_x11", "linux_wayland", "linux_other"},
      "android": {"android_8-9", "android_10-11", "android_12-13", "android_14", "android_15+"}}
ENABLED = {
    "desktop": {"notifications", "messages", "photos", "apps", "calls", "wallpaper", "usb_debugging", "your_week"},
    "android": {"notifications", "clipboard", "photos", "texts_and_calls", "phone_status", "dnd_sync", "mobile_data", "app_lock"},
}
FAILURES = {"hosted_send_failed", "hosted_receive_failed", "file_send_failed", "file_receive_failed", "hub_connection_failed"}
CRASHES = {"main_thread", "background_thread"}
SCHEMA_2 = {"active_days", "os", "enabled", "failures", "crashes"}
# Delivery health ranges for sealed events and file sizes.
LAG = ((1, "<1s"), (5, "1-5s"), (30, "5-30s"), (300, "30s-5m"))
SIZES = ((100_000, "<100KB"), (1_000_000, "100KB-1MB"), (5_000_000, "1-5MB"))
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
CREATE TABLE IF NOT EXISTS usage_detail(day TEXT NOT NULL, app TEXT NOT NULL, field TEXT NOT NULL, name TEXT NOT NULL,
    value TEXT NOT NULL, installs INTEGER NOT NULL, PRIMARY KEY(day, app, field, name, value));
CREATE TABLE IF NOT EXISTS service_active(day TEXT PRIMARY KEY, accounts INTEGER NOT NULL, devices INTEGER NOT NULL);
"""


def _today(now=None) -> str:
    return datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).strftime("%Y-%m-%d")


def _range(value, ranges, last):
    return next((label for limit, label in ranges if value < limit), last)


def validate(batch, *, now=None) -> dict:
    """Return the batch if it matches a published schema exactly; otherwise ValueError."""
    if not isinstance(batch, dict) or type(batch.get("schema")) is not int or batch["schema"] not in (1, 2):
        raise ValueError("Unsupported usage batch")
    if set(batch) != (KEYS if batch["schema"] == 1 else KEYS | SCHEMA_2):
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
    if batch["schema"] == 2:
        enabled, failures, crashes = batch["enabled"], batch["failures"], batch["crashes"]
        if (batch["active_days"] not in ACTIVE_DAYS or batch["os"] not in OS[platform]
                or not isinstance(enabled, dict) or any(name not in ENABLED[app] or type(on) is not bool for name, on in enabled.items())
                or not isinstance(failures, dict) or any(name not in FAILURES or value not in BUCKETS for name, value in failures.items())
                or not isinstance(crashes, dict) or any(name not in CRASHES or value not in BUCKETS for name, value in crashes.items())):
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
    if path.startswith("/v1/app/desktop/"):
        return "desktop.release" if path.endswith("/release") else "desktop.download"
    if path == "/v1/account":
        return "account"
    if path.startswith("/v1/devices/"):
        return "devices.requests" if path in ("/v1/devices/requests", "/v1/devices/approval-requests") else "devices.rosters"
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
        # Today's active accounts and devices, held in memory; only their counts are written.
        self._active_day, self._accounts, self._devices = "", set(), set()
        # Sealed events awaiting delivery: event ID -> (published, expires), in memory only.
        self._in_flight: OrderedDict = OrderedDict()
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
            if batch["schema"] == 2:
                details = [("active_days", "", batch["active_days"]), ("os", "", batch["os"]),
                           *[("enabled", name, "on" if on else "off") for name, on in sorted(batch["enabled"].items())],
                           *[("failures", name, value) for name, value in sorted(batch["failures"].items())],
                           *[("crashes", name, value) for name, value in sorted(batch["crashes"].items())]]
                db.executemany("INSERT INTO usage_detail VALUES(?,?,?,?,?,1) ON CONFLICT DO UPDATE SET installs=installs+1",
                               [(batch["day"], batch["app"], *row) for row in details])

    def request(self, method: str, path: str, status: int) -> None:
        """Count one finished request in memory; flush() writes the totals."""
        metric = classify(method, path)
        if metric is None:
            return
        status_class = f"{status // 100}xx" if 100 <= status < 600 else "other"
        with self._lock:
            self._service[(_today(self.clock()), metric, status_class)] += 1

    def metric(self, metric: str, status: str) -> None:
        """Count one occurrence under a fixed metric name and a fixed-format status."""
        if not re.fullmatch(r"[a-z][a-z0-9_.]{0,39}", metric) or not re.fullmatch(r"[A-Za-z0-9<>+._-]{1,40}", status):
            return
        with self._lock:
            self._service[(_today(self.clock()), metric, status)] += 1

    def active(self, account, device=None) -> None:
        """Note an account (and device) that completed an authenticated request today."""
        with self._lock:
            today = _today(self.clock())
            if today != self._active_day:
                self._active_day, self._accounts, self._devices = today, set(), set()
            if isinstance(account, str) and len(self._accounts) < 1_000_000:
                self._accounts.add(account)
            if isinstance(device, str) and len(self._devices) < 1_000_000:
                self._devices.add(device)

    def sealed(self, kind: str, *values) -> None:
        """Delivery health: publish and acknowledgement times, file sizes. Never content."""
        now = self.clock()
        with self._lock:
            if kind == "published":
                event, expires = values
                self._in_flight[event] = (now, expires)
                while len(self._in_flight) > IN_FLIGHT:
                    self._in_flight.popitem(last=False)
            elif kind == "acknowledged":
                item = self._in_flight.pop(values[0], None)
                if item is not None:
                    self._service[(_today(now), "delivery.lag", _range(now - item[0], LAG, "5m+"))] += 1
            elif kind == "blob":
                self._service[(_today(now), "blob.size", _range(values[0], SIZES, "5-20MB"))] += 1

    def flush(self) -> None:
        now = self.clock()
        with self._lock:
            # Events that expired before anyone acknowledged them.
            for event, (_, expires) in list(self._in_flight.items()):
                if expires <= now:
                    del self._in_flight[event]
                    self._service[(_today(now), "delivery.expired", "undelivered")] += 1
            pending, self._service = self._service, Counter()
            active = (self._active_day, len(self._accounts), len(self._devices)) if self._active_day else None
        cutoff = (datetime.strptime(_today(self.clock()), "%Y-%m-%d") - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%d")
        try:
            with self._connect() as db, db:
                db.executemany("INSERT INTO service_daily VALUES(?,?,?,?) ON CONFLICT DO UPDATE SET requests=requests+excluded.requests",
                               [(day, metric, status, count) for (day, metric, status), count in pending.items()])
                if active:
                    # A restart starts the day's sets again, so keep the larger count.
                    db.execute("INSERT INTO service_active VALUES(?,?,?) ON CONFLICT DO UPDATE SET "
                               "accounts=max(accounts,excluded.accounts), devices=max(devices,excluded.devices)", active)
                for table in ("usage_active", "usage_feature", "usage_detail", "service_daily", "service_active"):
                    db.execute(f"DELETE FROM {table} WHERE day<?", (cutoff,))
        except sqlite3.Error:
            with self._lock:
                self._service.update(pending)  # Keep the totals for the next attempt.
            raise

    def report(self, days: int = 30, *, min_cell: int = MIN_CELL) -> dict:
        """Totals for the administrator; contains no per-install rows because none exist.

        Install groups smaller than min_cell are left out and counted in "hidden",
        so a rare combination (one version on one platform) cannot single anyone out.
        """
        if type(days) is not int or not 1 <= days <= RETENTION_DAYS:
            raise ValueError("Choose 1 to 400 days")
        if type(min_cell) is not int or not 1 <= min_cell <= 100:
            raise ValueError("Choose a minimum group size from 1 to 100")
        since = (datetime.strptime(_today(self.clock()), "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
        hidden = {}
        with self._connect() as db:
            def rows(query, name=None):
                cursor = db.execute(query, (since,))
                names = [column[0] for column in cursor.description]
                result = [dict(zip(names, row)) for row in cursor.fetchall()]
                if name is None:
                    return result
                kept = [row for row in result if row["installs"] >= min_cell]
                hidden[name] = len(result) - len(kept)
                return kept
            return {
                "since": since,
                "min_cell": min_cell,
                "active": rows("SELECT day,app,platform,version,mode,install_age,stage,installs FROM usage_active WHERE day>=? ORDER BY day,app", "active"),
                "features": rows("SELECT day,app,feature,bucket,installs FROM usage_feature WHERE day>=? ORDER BY day,app,feature", "features"),
                "details": rows("SELECT day,app,field,name,value,installs FROM usage_detail WHERE day>=? ORDER BY day,app,field,name,value", "details"),
                "service": rows("SELECT day,metric,status,requests FROM service_daily WHERE day>=? ORDER BY day,metric"),
                "accounts": rows("SELECT day,accounts,devices FROM service_active WHERE day>=? ORDER BY day"),
                "hidden": hidden,
            }


def _hide(count: int, min_cell: int):
    return f"<{min_cell}" if 0 < count < min_cell else count


def funnel_report(registry, *, min_cell: int = MIN_CELL, now=None) -> dict:
    """Account-registry totals for the administrator: accounts, access by kind, devices per account.

    Counts only; no account, subject, device or code leaves the database. Counts
    below min_cell are shown as "<min_cell". Downloads and update checks are in
    the usage report's service totals (download.ticket, desktop.release).
    """
    if type(min_cell) is not int or not 1 <= min_cell <= 100:
        raise ValueError("Choose a minimum group size from 1 to 100")
    now = int(time.time() if now is None else now)
    with registry.connect() as db:
        accounts = db.execute("SELECT count(*), coalesce(sum(active),0) FROM accounts").fetchone()
        access = db.execute("SELECT kind, count(DISTINCT account) FROM access_grants WHERE revoked=0 AND expires_at>? "
                            "GROUP BY kind ORDER BY kind", (now,)).fetchall()
        ever = db.execute("SELECT kind, count(DISTINCT account) FROM access_grants GROUP BY kind ORDER BY kind").fetchall()
        devices = db.execute("SELECT CASE WHEN n>=4 THEN '4+' ELSE CAST(n AS TEXT) END, count(*) FROM "
                             "(SELECT a.id, count(d.id) AS n FROM accounts a LEFT JOIN devices d ON d.account=a.id "
                             "WHERE a.active=1 GROUP BY a.id) GROUP BY 1 ORDER BY 1").fetchall()
        codes = db.execute("SELECT count(*), count(redeemed_by) FROM beta_codes").fetchone()
        # Accounts that had a trial and later a paid grant: trial-to-paid on the service side.
        converted = db.execute("SELECT count(DISTINCT t.account) FROM access_grants t JOIN access_grants p "
                               "ON p.account=t.account AND p.kind='paid' WHERE t.kind='trial'").fetchone()[0]
    return {
        "min_cell": min_cell,
        "accounts": {"total": _hide(accounts[0], min_cell), "active": _hide(accounts[1], min_cell)},
        "access_now": {kind: _hide(count, min_cell) for kind, count in access},
        "access_ever": {kind: _hide(count, min_cell) for kind, count in ever},
        "trial_then_paid": _hide(converted, min_cell),
        "devices_per_active_account": {bucket: _hide(count, min_cell) for bucket, count in devices},
        "beta_codes": {"issued": _hide(codes[0], min_cell), "redeemed": _hide(codes[1], min_cell)},
    }
