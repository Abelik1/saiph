# SPDX-License-Identifier: AGPL-3.0-or-later
"""Opt-in, anonymous daily usage counts. The public field list is docs/USAGE_ANALYTICS.md.

Nothing is counted or sent until the owner agrees, and declining deletes any
local counts. Counting happens on this computer; at most one batch per past day
is sent. A batch has no install or account identifier, no IP-derived data, no
names, numbers, file names, app names or content: only which features were used,
in coarse ranges, plus app version, platform and how far setup has progressed.
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

SCHEMA = 1
KIND = "usage_day"
KEEP_DAYS = 7  # The service refuses older batches; unsent older counts are dropped.

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

# Desktop bridge actions mapped to the feature they represent.
BRIDGE_FEATURES = {
    "phone.notification": "notification_action", "phone.code.copy": "code_copy", "phone.sms.send": "sms_send",
    "phone.call": "call", "phone.ring": "find_phone", "phone.file.choose": "file_to_phone",
    "phone.file.send": "file_to_phone", "phone.photo.save": "photo_save", "phone.photo.drag": "photo_drag",
    "phone.mirror": "phone_mirror", "camera.start": "phone_camera", "microphone.start": "phone_microphone",
    "continuity.handoff": "handoff", "continuity.file.choose": "handoff", "continuity.dnd": "dnd_toggle",
    "hotspot.connect": "hotspot", "cloud.open": "cloud_open", "hosted.file.choose": "hosted_file_send",
    "hosted.file.save": "hosted_file_save", "hosted.approve": "device_approved",
}
STAGES = ("installed", "connected", "phone_added", "setup_completed")
_VERSION = re.compile(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}(?:[-+.][A-Za-z0-9.]{1,20})?")


def bucket(count: int) -> str:
    """Coarse ranges so exact activity levels are never reported."""
    return "1" if count <= 1 else "2-5" if count <= 5 else "6-20" if count <= 20 else "21+"


def age_bucket(days: int) -> str:
    return "0" if days <= 0 else "1-6" if days < 7 else "7-29" if days < 30 else "30-89" if days < 90 else "90+"


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

    def __init__(self, workspace, *, endpoint=None, post=_post, clock=time.time, version=None, platform=None):
        self.workspace, self.endpoint, self.post, self.clock = workspace, endpoint, post, clock
        self.version = version or app_version()
        self.platform = platform or ("windows" if sys.platform == "win32" else "linux")
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None

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
            self.workspace.settings["usage"] = usage
            self.workspace.save()
        return self.snapshot()

    # ----------------------------------------------------------- counting
    def count(self, feature: str, amount: int = 1) -> None:
        # The local-only "Your week" summary keeps its own counts, whatever the sharing choice.
        insights = getattr(self.workspace, "insights", None)
        if insights is not None:
            insights.count(feature, amount)
        if feature not in FEATURES or type(amount) is not int or amount < 1 or self.consent() != "granted":
            return
        with self._lock:
            day = _day(self.clock())
            try:
                row = self.workspace.store.get(KIND, day)
            except ValueError:
                row = {"id": day, "features": {}}
            features = dict(row.get("features") or {})
            features[feature] = min(int(features.get(feature, 0)) + amount, 1_000_000)
            self.workspace.store.save(KIND, {"id": day, "features": features})

    def screen(self, name) -> None:
        if name in SCREENS:
            self.count("screen_" + name)

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
            features = {name: bucket(int(value)) for name, value in sorted((row.get("features") or {}).items())
                        if name in FEATURES and int(value) > 0}
            result.append({"schema": SCHEMA, "day": day, "app": "desktop", "platform": self.platform,
                           "version": self.version, "mode": self._mode(),
                           "install_age": age_bucket(max(0, _days_between(first, day))),
                           "stage": self._stage(), "features": features})
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
