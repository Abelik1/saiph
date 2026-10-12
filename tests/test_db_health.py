# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from orion_mini import db_health


def make(path, rows=400):
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE records (kind TEXT, id TEXT, data TEXT, PRIMARY KEY(kind,id))")
        db.executemany("INSERT INTO records VALUES(?,?,?)", [("synthetic", str(i), "x" * 200) for i in range(rows)])
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        db.close()


def test_healthy_and_missing_databases_are_logged_without_quarantine(tmp_path):
    make(tmp_path / "workspace.sqlite3")
    result = db_health.check(tmp_path)
    assert result == {"results": {"workspace.sqlite3": "ok", "orion-mini.sqlite3": "missing"}, "preserved": {}}
    assert not (tmp_path / "db-quarantine").exists()
    entry = json.loads((tmp_path / "db-health.jsonl").read_text().splitlines()[-1])
    assert entry["results"]["workspace.sqlite3"] == "ok"


def test_corruption_is_preserved_with_sidecars_and_never_repaired(tmp_path):
    path = tmp_path / "orion-mini.sqlite3"
    make(path)
    (tmp_path / "orion-mini.sqlite3-wal").write_bytes(b"synthetic-wal")
    data = bytearray(path.read_bytes())
    # Damage an interior b-tree page header (page 2 onwards), as index corruption would.
    for offset in range(4096, 4096 + 64):
        data[offset] = 0xFF
    path.write_bytes(bytes(data))
    original = path.read_bytes()
    result = db_health.check(tmp_path, now=datetime(2026, 10, 11, 3, 0, tzinfo=timezone.utc))
    assert result["results"]["orion-mini.sqlite3"] == "failed"
    folder = Path(result["preserved"]["orion-mini.sqlite3"])
    assert folder.parent == tmp_path / "db-quarantine"
    assert folder.name.startswith("20261011T030000Z-")
    assert (folder / "orion-mini.sqlite3").read_bytes() == original
    assert (folder / "orion-mini.sqlite3-wal").read_bytes() == b"synthetic-wal"
    # The live profile is left exactly as found; recovery is an owner action.
    assert path.read_bytes() == original


def test_health_log_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(db_health, "MAX_LOG_LINES", 3)
    for _ in range(5):
        db_health.check(tmp_path)
    assert len((tmp_path / "db-health.jsonl").read_text().splitlines()) == 3


def test_same_second_retry_never_overwrites_earlier_evidence(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    now = datetime(2026, 10, 11, 3, 0, tzinfo=timezone.utc)
    path.write_bytes(b"first damaged database")
    first = Path(db_health.check(tmp_path, now=now)["preserved"][path.name])
    path.write_bytes(b"second damaged database")
    second = Path(db_health.check(tmp_path, now=now)["preserved"][path.name])
    assert first != second
    assert (first / path.name).read_bytes() == b"first damaged database"
    assert (second / path.name).read_bytes() == b"second damaged database"
