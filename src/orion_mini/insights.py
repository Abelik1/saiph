# SPDX-License-Identifier: AGPL-3.0-or-later
"""Your week: a personal summary computed and kept only on this computer.

Nothing here is ever sent, including with anonymous usage statistics turned on
(those come from separate, coarser counts in usage.py). Feature counts are kept
for 14 days. "People you talked with most" is calculated when the summary is
opened, from the text messages already synced to this computer for the Phone
page; no list of people is stored. Turning the summary off deletes its counts.
"""
from __future__ import annotations

import threading
import time
from collections import Counter
from datetime import datetime, timezone

from .usage import FEATURES

KIND = "insight_day"
KEEP_DAYS = 14
WEEK_DAYS = 7


def _day(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d")


class Insights:
    def __init__(self, workspace, *, clock=time.time):
        self.workspace, self.clock = workspace, clock
        self._lock = threading.Lock()
        self._generation = 0

    def enabled(self) -> bool:
        value = self.workspace.settings.get("insights")
        return not (isinstance(value, dict) and value.get("enabled") is False)

    def set_enabled(self, enabled) -> dict:
        if type(enabled) is not bool:
            raise ValueError("Your week is on or off.")
        with self._lock:
            self._generation += 1
            self.workspace.settings["insights"] = {"enabled": enabled}
            if not enabled:
                self._delete()
            self.workspace.save()
        return {"enabled": enabled}

    def clear(self) -> dict:
        with self._lock:
            self._generation += 1
            self._delete()
        return {"cleared": True}

    def _delete(self):
        for row in self.workspace.store.all(KIND):
            self.workspace.store.delete(KIND, row["id"])

    def count(self, feature: str, amount: int = 1, *, generation=None) -> None:
        if feature not in FEATURES or type(amount) is not int or amount < 1:
            return
        with self._lock:
            if not self.enabled() or (generation is not None and generation != self._generation):
                return
            day = _day(self.clock())
            try:
                row = self.workspace.store.get(KIND, day)
            except ValueError:
                row = {"id": day, "features": {}}
            features = dict(row.get("features") or {})
            features[feature] = min(int(features.get(feature, 0)) + amount, 1_000_000)
            self.workspace.store.save(KIND, {"id": day, "features": features})
            oldest = _day(self.clock() - KEEP_DAYS * 86400)
            for old in self.workspace.store.all(KIND):
                if old["id"] < oldest:
                    self.workspace.store.delete(KIND, old["id"])

    def _people(self, since_ms: int) -> list[dict]:
        """Top conversations this week from synced messages; computed, never stored."""
        threads = {(row.get("device_id"), row.get("thread")): row for row in self.workspace.store.all("phone_thread")}
        sent, received = Counter(), Counter()
        for message in self.workspace.store.all("phone_message"):
            timestamp = message.get("timestamp")
            if type(timestamp) is not int or timestamp < since_ms:
                continue
            key = (message.get("device_id"), message.get("thread"))
            (sent if message.get("direction") == "outgoing" else received)[key] += 1
        result = []
        for key in set(sent) | set(received):
            recipients = (threads.get(key) or {}).get("recipients") or []
            name = ", ".join(str(item) for item in recipients[:3]) if recipients else "Unknown conversation"
            result.append({"name": name, "sent": sent[key], "received": received[key], "total": sent[key] + received[key]})
        return sorted(result, key=lambda item: (-item["total"], item["name"]))[:5]

    def week(self) -> dict:
        """The last seven days, for the person at this computer only."""
        if not self.enabled():
            return {"enabled": False}
        now = self.clock()
        days = [_day(now - offset * 86400) for offset in range(WEEK_DAYS)]
        rows = {row["id"]: row.get("features") or {} for row in self.workspace.store.all(KIND) if row["id"] in days}
        totals, per_day = Counter(), {}
        for day, features in rows.items():
            counts = {name: int(value) for name, value in features.items() if name in FEATURES}
            totals.update(counts)
            per_day[day] = sum(value for name, value in counts.items() if not name.startswith("screen_"))
        actions = {name: value for name, value in totals.items() if not name.startswith("screen_")}
        screens = {name.removeprefix("screen_"): value for name, value in totals.items() if name.startswith("screen_")}
        busiest = max(per_day.items(), key=lambda item: (item[1], item[0]), default=(None, 0))
        since_ms = int((now - WEEK_DAYS * 86400) * 1000)
        return {
            "enabled": True,
            "from": days[-1], "to": days[0],
            "actions": sum(actions.values()),
            "days": [{"date": day, "actions": per_day.get(day, 0)} for day in reversed(days)],
            "top": [{"feature": name, "label": FEATURES[name], "count": value}
                    for name, value in sorted(actions.items(), key=lambda item: (-item[1], item[0]))[:6]],
            "screen": max(screens.items(), key=lambda item: (item[1], item[0]))[0] if screens else None,
            "busiest_day": datetime.strptime(busiest[0], "%Y-%m-%d").strftime("%A") if busiest[0] and busiest[1] else None,
            "people": self._people(since_ms),
        }
