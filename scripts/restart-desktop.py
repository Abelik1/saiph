# SPDX-License-Identifier: AGPL-3.0-or-later
"""Close the running desktop app and relaunch the same build, e.g. after a source update.

Uses the local API's token from api.json. Exits non-zero if the app is not running,
is too old to support restart, or no new instance appears within the deadline.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from orion_mini.paths import app_data_dir  # noqa: E402


def read_discovery():
    return json.loads((app_data_dir() / "api.json").read_text(encoding="utf-8"))


def healthy(url):
    try:
        with urllib.request.urlopen(url + "/v1/health", timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def main(deadline_seconds=60):
    info = read_discovery()
    if not healthy(info["url"]):
        print("The desktop app is not running.", file=sys.stderr)
        return 2
    request = urllib.request.Request(info["url"] + "/v1/app/restart", method="POST",
                                     headers={"Authorization": "Bearer " + info["token"]})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.status != 202:
                raise urllib.error.HTTPError(request.full_url, response.status, "", {}, None)
    except urllib.error.HTTPError as error:
        print(f"Restart was refused ({error.code}); this build may predate restart support. Quit it from the tray.", file=sys.stderr)
        return 3
    old = info["pid"]
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        time.sleep(1)
        try:
            current = read_discovery()
        except (OSError, ValueError):
            continue
        if current.get("pid") != old and healthy(current["url"]):
            print(f"Restarted: pid {old} -> {current['pid']}")
            return 0
    print("No relaunched instance became healthy before the deadline.", file=sys.stderr)
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
