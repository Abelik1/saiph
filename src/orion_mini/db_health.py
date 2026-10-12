# SPDX-License-Identifier: AGPL-3.0-or-later
"""Startup integrity check for the desktop databases; detection and evidence only.

Runs after the single-instance lock and before the app opens its stores, so no
writer is active. A failed check preserves the database and its WAL/SHM sidecars
in a private quarantine folder and is recorded in ``db-health.jsonl``. It never
repairs, resets or deletes a profile: recovery stays an explicit owner action.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from tempfile import mkdtemp

DATABASES = ("workspace.sqlite3", "orion-mini.sqlite3")
MAX_LOG_LINES = 500


def _quick_check(path: Path) -> str:
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            rows = connection.execute("PRAGMA quick_check").fetchall()
        finally:
            connection.close()
        return "ok" if rows == [("ok",)] else "failed"
    except sqlite3.DatabaseError:
        return "failed"
    except OSError:
        return "unavailable"


def _quarantine(root: Path, path: Path, stamp: str) -> Path:
    parent = root / "db-quarantine"
    parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite earlier evidence, including a retry in the same second.
    folder = Path(mkdtemp(prefix=stamp + "-", dir=parent))
    if os.name != "nt":
        folder.chmod(0o700)
    for suffix in ("", "-wal", "-shm"):
        source = path.with_name(path.name + suffix)
        if source.is_file():
            shutil.copy2(source, folder / source.name)
    return folder


def _log(root: Path, entry: dict) -> None:
    log = root / "db-health.jsonl"
    lines = log.read_text(encoding="utf-8").splitlines()[-(MAX_LOG_LINES - 1):] if log.is_file() else []
    lines.append(json.dumps(entry, sort_keys=True))
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")


def check(root: Path, now=None) -> dict:
    """Return {name: ok|failed|missing|unavailable} and quarantine any failure."""
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    results, preserved = {}, {}
    for name in DATABASES:
        path = Path(root) / name
        results[name] = _quick_check(path) if path.is_file() else "missing"
        if results[name] == "failed":
            preserved[name] = str(_quarantine(Path(root), path, stamp))
    try:
        _log(Path(root), {"at": now.isoformat(), "results": results, "preserved": preserved})
    except OSError:
        pass
    return {"results": results, "preserved": preserved}
