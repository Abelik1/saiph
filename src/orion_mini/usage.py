# SPDX-License-Identifier: AGPL-3.0-or-later
"""Opt-in, anonymous daily usage counts. The public field list is docs/USAGE_ANALYTICS.md.

Nothing is counted or sent until the owner agrees, and declining deletes any
local counts. Counting happens on this computer; at most one batch per past day
is sent. A batch has no install or account identifier, no IP-derived data, no
names, numbers, file names, app names or content: only which features were used,
in coarse ranges, plus app version, platform and how far setup has progressed,
the Windows or Linux family, how many of the last seven days Saiph was used,
which features are switched on, and failure and crash counts by fixed reason.
Self-hosted and development builds without a packaged Saiph service never send.
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 2
KIND = "usage_day"
KEEP_DAYS = 7  # The service refuses older batches; unsent older counts are dropped.
# Schema 1 fields; a service that refuses schema 2 still gets these.
SCHEMA_1_FIELDS = ("schema", "day", "app", "platform", "version", "mode", "install_age", "stage", "features")

# Every countable feature, as published in docs/USAGE_ANALYTICS.md. Counting an
# unknown name is ignored, so a typo can never invent a new field.
FEATURES = {
    "clipboard_sent": "Clipboard shared from this computer",
    "clipboard_received": "Clipboard received on this computer",
    "phone_notification": "Phone notification shown on this computer",
    "notification_action": "Phone notification answered or dismissed from this computer",
    "code_copy": "Verification code copied from a notification",
    "sms_send": "Text message sent through the phone",
    "call": "Phone call started from this computer",
    "find_phone": "Phone rung to find it",
    "file_to_phone": "File sent to the phone",
    "photo_save": "Phone photo saved",
    "photo_drag": "Phone photo dragged into another app",
    "phone_mirror": "Phone screen opened",
    "phone_camera": "Phone camera used as a webcam",
    "phone_microphone": "Phone microphone used",
    "handoff": "Link, text or file handed to another device",
    "dnd_toggle": "Do Not Disturb switched from Saiph",
    "hotspot": "Phone hotspot connection",
    "cloud_open": "Cloud folder opened",
    "hosted_file_send": "File sent with a Saiph account",
    "hosted_file_save": "File received with a Saiph account",
    "device_approved": "Device approved for a Saiph account",
    "screen_phone": "Phone page opened",
    "screen_cloud": "Cloud page opened",
    "screen_settings": "Settings page opened",
    "screen_messages": "Messages tab opened",
    "screen_photos": "Photos tab opened",
    "screen_calls": "Calls tab opened",
    "screen_files": "Files tab opened",
    "screen_apps": "Apps tab opened",
}
SCREENS = {name.removeprefix("screen_") for name in FEATURES if name.startswith("screen_")}
# Failures by fixed reason code. Never the error text, address or file involved.
FAILURES = {
    "hosted_send_failed": "Saiph Cloud refused or could not take an encrypted message",
    "hosted_receive_failed": "Encrypted messages could not be fetched from Saiph Cloud",
    "file_send_failed": "Part of an encrypted file could not be uploaded",
    "file_receive_failed": "Part of an encrypted file could not be downloaded",
    "hub_connection_failed": "The connection to your Hub failed or dropped",
}
# Unhandled errors, by the kind of thread they happened on. No message or stack.
CRASHES = {
    "main_thread": "Unhandled error in the window",
    "background_thread": "Unhandled error in background work",
}
# Switches reported as on or off; each is a Saiph preference, never content.
ENABLED = ("notifications", "messages", "photos", "apps", "calls", "wallpaper", "usb_debugging", "your_week")
GROUPS = {"features": FEATURES, "failures": FAILURES, "crashes": CRASHES}

# Desktop bridge actions mapped to the feature they represent.
BRIDGE_FEATURES = {
    "phone.notification": "notification_action", "hosted.notification": "notification_action", "phone.code.copy": "code_copy", "phone.sms.send": "sms_send",
    "phone.call": "call", "phone.ring": "find_phone", "phone.file.choose": "file_to_phone",
    "phone.file.send": "file_to_phone", "phone.photo.save": "photo_save", "phone.photo.drag": "photo_drag",
    "phone.mirror": "phone_mirror", "camera.start": "phone_camera", "microphone.start": "phone_microphone",
    "continuity.handoff": "handoff", "continuity.file.choose": "handoff", "continuity.dnd": "dnd_toggle",
    "hotspot.connect": "hotspot", "cloud.open": "cloud_open", "hosted.file.choose": "hosted_file_send",
    "hosted.file.save": "hosted_file_save", "hosted.approve": "device_approved",
}
STAGES = ("installed", "connected", "phone_added", "setup_completed")
# Pre-release labels may have several parts, e.g. 0.1.0-beta.30-acceptance.1.
_VERSION = re.compile(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}(?:[-+.][A-Za-z0-9.-]{1,32})?")


def bucket(count: int) -> str:
    """Coarse ranges so exact activity levels are never reported."""
    return "1" if count <= 1 else "2-5" if count <= 5 else "6-20" if count <= 20 else "21+"


def age_bucket(days: int) -> str:
    return "0" if days <= 0 else "1-6" if days < 7 else "7-29" if days < 30 else "30-89" if days < 90 else "90+"


def active_bucket(days: int) -> str:
    """How many of the last seven days had any use, as a range."""
    return "0" if days <= 0 else "1" if days == 1 else "2-3" if days <= 3 else "4-6" if days <= 6 else "7"


def os_family() -> str:
    """Windows 10 or 11, or the Linux display system; never a build or distribution."""
    if sys.platform == "win32":
        try:
            return "windows_11" if sys.getwindowsversion().build >= 22000 else "windows_10"
        except (AttributeError, OSError):
            return "windows_other"
    import os
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    return "linux_wayland" if session == "wayland" else "linux_x11" if session == "x11" else "linux_other"


def _day(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d")


def _days_between(first: str, second: str) -> int:
    return (datetime.strptime(second, "%Y-%m-%d") - datetime.strptime(first, "%Y-%m-%d")).days


def packaged_endpoint() -> str | None:
    """The Saiph service's usage address in packaged builds that include it."""
    bundle = getattr(sys, "_MEIPASS", None)
    if not getattr(sys, "frozen", False) or not bundle:
        return None
    try:
        from .hosted_distribution import read_configuration
        return read_configuration(Path(bundle) / "hosted-defaults.json")["service_url"] + "/v1/usage"
    except (OSError, ValueError, KeyError, TypeError):
        return None


def app_version() -> str:
    try:
        from .package_updates import current
        release = current()
        if release and _VERSION.fullmatch(release["version"]):
            return release["version"]
    except (ImportError, KeyError, TypeError):
        pass
    from . import __version__
    return __version__ + "-dev"


def _post(endpoint: str, batch: dict) -> None:
    import requests
    response = requests.post(endpoint, data=json.dumps(batch, separators=(",", ":")), timeout=15, allow_redirects=False,
                             headers={"Content-Type": "application/json"})
    if response.status_code not in (200, 202, 204):
        raise OSError("Usage batch was not accepted.")


class UsageCounter:
    """Local counts plus the owner's choice; safe to call from any thread."""

    def __init__(self, workspace, *, endpoint=None, post=_post, clock=time.time, version=None, platform=None, os=None):
        self.workspace, self.endpoint, self.post, self.clock = workspace, endpoint, post, clock
        self.version = version or app_version()
        self.platform = platform or ("windows" if sys.platform == "win32" else "linux")
        self.os = os or os_family()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._generation = 0

    # ------------------------------------------------------------ consent
    def _settings(self) -> dict:
        value = self.workspace.settings.get("usage")
        return value if isinstance(value, dict) else {}

    def available(self) -> bool:
        return self.endpoint is not None

    def consent(self) -> str | None:
        value = self._settings().get("consent")
        return value if value in ("granted", "declined") else None

    def set_consent(self, granted) -> dict:
        if type(granted) is not bool:
            raise ValueError("Choose whether to share anonymous usage counts.")
        with self._lock:
            self._generation += 1
            usage = dict(self._settings())
            today = _day(self.clock())
            usage.update(consent="granted" if granted else "declined", decided_on=today)
            if granted:
                usage.setdefault("first_day", today)
            else:
                # Declining removes everything counted so far, including the last batch shown.
                for row in self.workspace.store.all(KIND):
                    self.workspace.store.delete(KIND, row["id"])
                usage.pop("last_sent", None)
                usage.pop("first_day", None)
                usage.pop("active_days", None)
            self.workspace.settings["usage"] = usage
            self.workspace.save()
        return self.snapshot()

    # ----------------------------------------------------------- counting
    def count(self, feature: str, amount: int = 1, *, generations=None) -> None:
        # The local-only "Your week" summary keeps its own counts, whatever the sharing choice.
        insights = getattr(self.workspace, "insights", None)
        if insights is not None:
            if generations is None or generations[1] is None:
                insights.count(feature, amount)
            else:
                insights.count(feature, amount, generation=generations[1])
        self._add("features", feature, amount, generations=generations)

    def failure(self, code: str) -> None:
        """Count a failure by its fixed reason code; unknown codes are ignored."""
        self._add("failures", code, 1)

    def crash(self, thread: str) -> None:
        self._add("crashes", thread, 1)

    def _add(self, group, name, amount, *, generations=None) -> None:
        if name not in GROUPS[group] or type(amount) is not int or amount < 1:
            return
        with self._lock:
            if self.consent() != "granted" or (generations is not None and generations[0] != self._generation):
                return
            day = _day(self.clock())
            try:
                row = self.workspace.store.get(KIND, day)
            except ValueError:
                row = {"id": day}
            counts = dict(row.get(group) or {})
            counts[name] = min(int(counts.get(name, 0)) + amount, 1_000_000)
            self.workspace.store.save(KIND, {**row, "id": day, group: counts})
            if group == "features":
                # Days with any use, kept 14 days, for the "active days in the last week" range.
                usage = self._settings()
                days = [d for d in usage.get("active_days") or [] if isinstance(d, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)]
                if day not in days:
                    days = sorted([*days, day])[-14:]
                    self.workspace.settings["usage"] = {**usage, "active_days": days}
                    self.workspace.save()

    def screen(self, name) -> None:
        if name in SCREENS:
            self.count("screen_" + name)

    def screen_action(self, name):
        """A deferred counter action invalidated by later consent/summary changes."""
        insights = getattr(self.workspace, 'insights', None)
        generations = (self._generation, getattr(insights, '_generation', None))
        def run():
            if name in SCREENS:
                self.count('screen_' + name, generations=generations)
            return {'ok': True}
        return run

    # ------------------------------------------------------------ batches
    def _stage(self) -> str:
        try:
            from .setup_guide import status
            setup = status(self.workspace)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return "installed"
        if setup["completed"]:
            return "setup_completed"
        # Same rule as the setup guide: a phone reports battery; Hosted counts approvals.
        phone = getattr(self.workspace, "phone", None)
        devices = (phone.snapshot().get("devices") if phone is not None else None) or []
        hosted = self.workspace.store.all("hosted_security_event") if setup["mode"] == "hosted" else []
        if any("battery" in (d.get("capabilities") or []) for d in devices) or any(e.get("kind") == "added" for e in hosted):
            return "phone_added"
        return "connected" if setup["connected"] else "installed"

    def _enabled(self) -> dict:
        try:
            from .phone_settings import preferences
            prefs = preferences(self.workspace.settings)
            values = {**prefs["features"], "wallpaper": prefs["wallpaper"], "usb_debugging": prefs["usb_debugging"]}
            insights = getattr(self.workspace, "insights", None)
            values["your_week"] = bool(insights.enabled()) if insights is not None else False
            return {name: values[name] is True for name in ENABLED}
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return {}

    def _active_days(self, day: str) -> str:
        days = self._settings().get("active_days") or []
        return active_bucket(sum(1 for d in set(days) if isinstance(d, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)
                                 and 0 <= _days_between(d, day) < 7))

    def _mode(self) -> str:
        try:
            from .setup_guide import status
            return status(self.workspace)["mode"] or "none"
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return "none"

    def pending(self) -> list[dict]:
        """Exactly the batches that would be sent: completed past days only."""
        usage = self._settings()
        today = _day(self.clock())
        first = usage.get("first_day") or today
        result = []
        for row in sorted(self.workspace.store.all(KIND), key=lambda item: item["id"]):
            day = row["id"]
            if day >= today or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or _days_between(day, today) > KEEP_DAYS:
                continue
            counts = {group: {name: bucket(int(value)) for name, value in sorted((row.get(group) or {}).items())
                              if name in names and int(value) > 0} for group, names in GROUPS.items()}
            result.append({"schema": SCHEMA, "day": day, "app": "desktop", "platform": self.platform,
                           "version": self.version, "mode": self._mode(),
                           "install_age": age_bucket(max(0, _days_between(first, day))),
                           "stage": self._stage(), "features": counts["features"],
                           "active_days": self._active_days(day), "os": self.os, "enabled": self._enabled(),
                           "failures": counts["failures"], "crashes": counts["crashes"]})
        return result

    def flush(self) -> int:
        """Send due batches; failures keep them for the next attempt."""
        if not self.available() or self.consent() != "granted":
            return 0
        sent = 0
        with self._lock:
            today = _day(self.clock())
            for row in self.workspace.store.all(KIND):
                if row["id"] < today and _days_between(row["id"], today) > KEEP_DAYS:
                    self.workspace.store.delete(KIND, row["id"])
            for batch in self.pending():
                try:
                    self.post(self.endpoint, batch)
                except Exception:
                    # A service that predates schema 2 refuses it; send the schema 1 subset.
                    try:
                        self.post(self.endpoint, {**{key: batch[key] for key in SCHEMA_1_FIELDS}, "schema": 1})
                    except Exception:
                        break  # Offline or refused (network libraries raise their own types); retry later.
                self.workspace.store.delete(KIND, batch["day"])
                self.workspace.settings["usage"] = {**self._settings(), "last_sent": batch}
                self.workspace.save()
                sent += 1
        return sent

    def snapshot(self) -> dict:
        usage = self._settings()
        return {"available": self.available(), "consent": self.consent(),
                "pending": self.pending() if self.consent() == "granted" else [],
                "last_sent": usage.get("last_sent") if self.consent() == "granted" else None}

    # ------------------------------------------------------------- thread
    def start(self, interval: float = 1800, first: float = 60) -> None:
        if self._thread is not None:
            return

        def run():
            wait = first
            while not self._stop.wait(wait):
                try:
                    self.flush()
                except Exception:
                    pass  # Never let usage reporting affect the app.
                wait = interval
        self._thread = threading.Thread(target=run, name="orion-usage", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


def record(workspace, feature: str, amount: int = 1) -> None:
    """Count a feature if this workspace has a counter; never raises."""
    counter = getattr(workspace, "usage_counter", None)
    if counter is not None:
        try:
            counter.count(feature, amount)
        except Exception:
            pass


def record_failure(workspace, code: str) -> None:
    """Count a failure by fixed reason code if this workspace has a counter; never raises."""
    counter = getattr(workspace, "usage_counter", None)
    if counter is not None:
        try:
            counter.failure(code)
        except Exception:
            pass


def install_crash_counter(workspace) -> None:
    """Count unhandled errors by thread kind, then hand them to the previous hooks."""
    previous_sys, previous_thread = sys.excepthook, threading.excepthook

    def count(kind):
        counter = getattr(workspace, "usage_counter", None)
        if counter is not None:
            try:
                counter.crash(kind)
            except Exception:
                pass

    def sys_hook(kind, value, trace):
        count("main_thread" if threading.current_thread() is threading.main_thread() else "background_thread")
        previous_sys(kind, value, trace)

    def thread_hook(args):
        if args.exc_type is not SystemExit:
            count("background_thread")
        previous_thread(args)

    sys.excepthook, threading.excepthook = sys_hook, thread_hook
