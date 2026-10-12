# SPDX-License-Identifier: AGPL-3.0-or-later
"""Local metadata-only support snapshot. Never reads payload or credential columns."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

from .security import now_iso
from . import releases


def snapshot(data: Path):
    result = {"schema": "orion.link.support/v1", "at": now_iso(), "integrity": "unavailable", "counts": {}, "release": {}}
    database = data / "orion-hub.sqlite3"
    if database.is_file():
        with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as connection:
            result["integrity"] = "ok" if connection.execute("PRAGMA quick_check").fetchone()[0] == "ok" else "failed"
            present = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ("devices", "link_events", "link_deliveries", "phone_notifications", "phone_features", "inbox"):
                if table in present:
                    result["counts"][table] = connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
    release = releases.latest(data)
    if release:
        result["release"] = {field: release[field] for field in ("version_code", "version_name", "sha256")}
    result["backup_count"] = len(list((data / "backups").glob("orion-hub-*.sqlite3")))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(os.environ.get("ORION_HUB_DATA", "./data")))
    args = parser.parse_args(argv)
    try:
        result = snapshot(args.data)
    except (OSError, ValueError, sqlite3.Error):
        result = {"schema": "orion.link.support/v1", "error": "support_unavailable"}
    print(json.dumps(result, indent=2))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())
