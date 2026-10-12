# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call an allowlisted desktop app action through the local API (opt-in; see orion_mini/automation.py).

    python scripts/desktop-call.py state
    python scripts/desktop-call.py phone.photo.save '{"device_id": "...", "photo_id": "..."}'
"""
from __future__ import annotations

import json
import argparse
import os
import sys
from contextlib import contextmanager
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from orion_mini.paths import app_data_dir  # noqa: E402


@contextmanager
def temporary_automation():
    """Enable an absent opt-in for an explicitly requested run, then restore it.

    Existing enabled opt-ins are retained. Existing disabled/malformed settings
    are never replaced. A concurrent change is preserved during cleanup.
    """
    flag = app_data_dir() / "automation.json"
    body = '{"enabled": true}\n'
    created = False
    try:
        try:
            fd = os.open(flag, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if json.loads(flag.read_text(encoding="utf-8")).get("enabled") is not True:
                raise SystemExit("Existing automation setting is disabled; preserved.")
        else:
            created = True
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(body)
        yield
    finally:
        if created:
            try:
                if flag.read_text(encoding="utf-8") == body:
                    flag.unlink()
            except FileNotFoundError:
                pass


def call(method, args=None, timeout=40):
    info = json.loads((app_data_dir() / "api.json").read_text(encoding="utf-8"))
    request = urllib.request.Request(info["url"] + "/v1/app/call", method="POST",
                                     data=json.dumps({"method": method, "args": args or {}}).encode(),
                                     headers={"Authorization": "Bearer " + info["token"], "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())["result"]
    except urllib.error.HTTPError as error:
        raise SystemExit(f"{error.code}: {json.loads(error.read()).get('message')}") from None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("method")
    parser.add_argument("args", nargs="?", default="{}")
    parser.add_argument("--temporary-enable", action="store_true", help="Explicitly opt in for this call and remove the newly created opt-in afterward.")
    parser.add_argument("--summary", action="store_true", help="For state, print only connection/feature metadata and counts.")
    options = parser.parse_args()
    if options.summary and options.method != "state":
        parser.error("--summary requires state")

    def execute():
        result = call(options.method, json.loads(options.args))
        if options.summary:
            phone = result.get("phone", {})
            features = result.get("phone_features", {})
            result = {"status": phone.get("status"), "error": phone.get("error"),
                      "devices": [{k: d.get(k) for k in ("id", "name", "online", "capabilities")} for d in phone.get("devices", [])],
                      "notification_count": len(phone.get("notifications", [])),
                      "feature_counts": {k: len(features.get(k, [])) for k in ("threads", "messages", "calls", "photos", "files")}}
        print(json.dumps(result, indent=2))

    if options.temporary_enable:
        with temporary_automation():
            execute()
    else:
        execute()
