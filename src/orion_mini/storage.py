# SPDX-License-Identifier: AGPL-3.0-or-later
"""Small, explicit persistence layer shared by the desktop and worker processes."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .models import utc_now


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temporary.replace(path)
        except OSError as error:
            if getattr(error, "winerror", None) != 17:
                raise
            # Retain the previous version on redirected/encrypted Windows volumes.
            if path.exists():
                shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
            shutil.copy2(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, value) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = root / "workspace.sqlite3"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, data TEXT, PRIMARY KEY(kind,id))")

    @property
    def _local(self):
        local = self.__dict__.get("_thread_local")
        if local is None:
            local = self.__dict__.setdefault("_thread_local", threading.local())
        return local

    @contextmanager
    def reading(self):
        """Share one connection for every access on this thread inside the block.

        A dashboard snapshot reads the store five to ten times, and opening the
        database costs about 12 ms each on Windows. Each access still runs in its
        own transaction (committed at the end of its block), so nothing is held
        open between them; other threads keep their own connections."""
        local = self._local
        if getattr(local, "connection", None) is not None:
            yield
            return
        connection = sqlite3.connect(self.path, timeout=15)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            local.connection = connection
            yield
        finally:
            local.connection = None
            connection.close()

    @contextmanager
    def connect(self):
        shared = getattr(self._local, "connection", None)
        if shared is not None:
            with shared:
                yield shared
            return
        connection = sqlite3.connect(self.path, timeout=15)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            # sqlite3's transaction context commits/rolls back but does not close
            # the connection. State reads otherwise retain handles until GC.
            with connection:
                yield connection
        finally:
            connection.close()

    def all(self, kind: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT data FROM records WHERE kind=? ORDER BY rowid DESC", (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def get(self, kind: str, item_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT data FROM records WHERE kind=? AND id=?", (kind, item_id)).fetchone()
        if not row:
            raise ValueError("This item no longer exists. Refresh and try again.")
        return json.loads(row[0])

    def save(self, kind: str, value: dict) -> dict:
        value = {**value, "id": value.get("id") or uuid4().hex, "updated_at": utc_now()}
        with self.connect() as db:
            db.execute("INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data", (kind, value["id"], json.dumps(value)))
        return value

    def delete(self, kind: str, item_id: str):
        with self.connect() as db:
            db.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, item_id))
