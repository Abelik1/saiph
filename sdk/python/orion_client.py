# SPDX-License-Identifier: MIT
"""Report a tool's status to Orion Mini (API schema orion.api/v1). Standard library only.

Copy this file into any repo that wants to show up in Orion. It never raises and
never blocks a tool for more than a few seconds:

    from orion_client import Orion
    orion = Orion("example-tool")
    orion.status("running", "Checking for updates")
    orion.event("2 new items in example project")
    orion.ticker("example-update-1", "example project: New update posted", expires_hours=36)
    orion.status("ok", "2 new, 0 changed", next_run=next_check, metrics={"new": 2})
    orion.calendar([{"id": "example-deadline", "kind": "deadline", "title": "Example deadline", "start": "2026-10-09T22:59"}])

* Orion running: the request goes to its local API.
* Orion installed but closed: the request is saved in its inbox and applied when it starts.
* Orion not installed, or the plugin not added on this computer: nothing happens.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

__version__ = "1.2"


def data_dir() -> Path:
    if os.environ.get("ORION_MINI_DATA_DIR"):
        return Path(os.environ["ORION_MINI_DATA_DIR"])
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "OrionMini"


def iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.astimezone()).isoformat(timespec="seconds")
    return str(value)


class Orion:
    def __init__(self, plugin_id: str, timeout: float = 3.0, root: Path | None = None):
        self.plugin_id = plugin_id
        self.timeout = timeout
        self.root = Path(root) if root else data_dir()
        self.last_error = ""

    # ---------------------------------------------------------------- public
    def status(self, state: str, summary: str = "", detail: str = "", next_run=None, metrics: dict | None = None,
               links: list[dict] | None = None) -> bool:
        """state: ok, warning, error, running, login_required or idle.
        links: up to 12 {"label", "file"} (paths inside the repo) the run wrote, so Orion can open them."""
        body = {"state": state, "summary": summary, "detail": detail, "next_run": iso(next_run),
                "metrics": metrics or {}, "links": links or [], "at": iso(datetime.now(timezone.utc))}
        return self.send("PUT", f"/v1/plugins/{self.plugin_id}/status", body)

    def event(self, message: str, level: str = "info") -> bool:
        """level: info, warning or error."""
        return self.send("POST", f"/v1/plugins/{self.plugin_id}/events",
                         {"message": message, "level": level, "at": iso(datetime.now(timezone.utc))})

    def ticker(self, item_id: str, text: str, severity: str = "info", expires_hours: float = 24) -> bool:
        """Add or replace one status-bar item. Ids use lowercase letters, digits and dashes."""
        expires = datetime.now(timezone.utc) + timedelta(hours=expires_hours)
        return self.send("PUT", f"/v1/plugins/{self.plugin_id}/ticker/{item_id}",
                         {"text": text, "severity": severity, "expires_at": iso(expires)})

    def reviews(self, items: list[dict]) -> bool:
        """Replace everything waiting for a human decision. Each item:
        {"id", "title", "detail", "flags": [...], "actions": [{"action": <manifest action id>, "value": <token>, "label"}]}"""
        return self.send("PUT", f"/v1/plugins/{self.plugin_id}/reviews", {"items": items})

    def calendar(self, events: list[dict]) -> bool:
        """Replace every date this tool knows about, shown on Orion's Calendar page. Each event:
        {"id", "title", "kind": deadline|exam|class|event, "start": "2026-10-09T22:59" or "2026-10-09" (all day),
         "end", "detail", "location", "group", "tentative", "repeat": {"every": "week", "until", "skip": [dates]}}"""
        return self.send("PUT", f"/v1/plugins/{self.plugin_id}/calendar", {"events": events})

    def clear_ticker(self, item_id: str) -> bool:
        return self.send("DELETE", f"/v1/plugins/{self.plugin_id}/ticker/{item_id}", None)

    # ---------------------------------------------------------------- transport
    def send(self, method: str, path: str, body: dict | None) -> bool:
        try:
            return self._send(method, path, body)
        except Exception as error:  # a status report must never break the tool
            self.last_error = f"{error.__class__.__name__}: {error}"
            return False

    def _send(self, method: str, path: str, body: dict | None) -> bool:
        if not self.root.is_dir():
            self.last_error = "Orion Mini is not installed on this computer."
            return False
        try:
            discovery = json.loads((self.root / "api.json").read_text(encoding="utf-8-sig"))
            request = urllib.request.Request(
                discovery["url"] + path, method=method,
                data=json.dumps(body).encode() if body is not None else None,
                headers={"Authorization": "Bearer " + discovery["token"], "Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=self.timeout):
                return True
        except urllib.error.HTTPError as error:
            # Orion answered: a 404 means this plugin is not added on this computer.
            try:
                self.last_error = json.loads(error.read()).get("message", str(error))
            except ValueError:
                self.last_error = str(error)
            return False
        except (OSError, ValueError, KeyError) as error:
            # Closed (connection refused) or never started: queue it for next launch.
            self.last_error = f"Orion is not running ({error}); queued."
            inbox = self.root / "inbox"
            inbox.mkdir(exist_ok=True)
            name = f"{time.time_ns()}-{self.plugin_id}-{uuid.uuid4().hex[:8]}"
            temporary = inbox / (name + ".tmp")
            temporary.write_text(json.dumps({"method": method, "path": path, "body": body}), encoding="utf-8")
            temporary.replace(inbox / (name + ".json"))
            return True
