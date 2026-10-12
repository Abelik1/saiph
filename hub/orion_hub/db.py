# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations
import json, sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from . import continuity, features

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, name TEXT NOT NULL, public_key_der_b64 TEXT NOT NULL, push_token TEXT, created_at TEXT NOT NULL, last_seen_at TEXT);
CREATE TABLE IF NOT EXISTS pairing_codes(id TEXT PRIMARY KEY, salt_b64 TEXT NOT NULL, digest_b64 TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT);
CREATE TABLE IF NOT EXISTS nonces(device_id TEXT NOT NULL, nonce TEXT NOT NULL, seen_at TEXT NOT NULL, PRIMARY KEY(device_id, nonce));
CREATE TABLE IF NOT EXISTS web_sessions(id_hash TEXT PRIMARY KEY, name TEXT NOT NULL, csrf_hash TEXT NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL, scopes_json TEXT, owner_device_id TEXT);
CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, title TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', due_at TEXT, done INTEGER NOT NULL DEFAULT 0, notified_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS watches(id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL, interval_hours INTEGER NOT NULL DEFAULT 8, enabled INTEGER NOT NULL DEFAULT 1, last_checked_at TEXT, last_hash TEXT, last_status TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, data_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS inbox(id TEXT PRIMARY KEY, kind TEXT NOT NULL, source TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', link TEXT NOT NULL DEFAULT '', proposal_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL, decided_by TEXT, decided_at TEXT, result TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL, agent TEXT);
CREATE TABLE IF NOT EXISTS automation_runs(id TEXT PRIMARY KEY, automation_id TEXT NOT NULL, status TEXT NOT NULL, stdout TEXT NOT NULL DEFAULT '', stderr TEXT NOT NULL DEFAULT '', started_at TEXT NOT NULL, finished_at TEXT);
CREATE TABLE IF NOT EXISTS link_devices(device_id TEXT PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE, capabilities_json TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS link_events(id TEXT PRIMARY KEY, source TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE, type TEXT NOT NULL, payload_json TEXT, digest TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS link_events_expiry ON link_events(expires_at);
CREATE INDEX IF NOT EXISTS link_events_payload_expiry ON link_events(expires_at) WHERE payload_json IS NOT NULL;
CREATE INDEX IF NOT EXISTS link_events_created ON link_events(created_at);
CREATE TABLE IF NOT EXISTS link_deliveries(event_id TEXT NOT NULL REFERENCES link_events(id) ON DELETE CASCADE, device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE, PRIMARY KEY(event_id,device_id));
CREATE INDEX IF NOT EXISTS link_deliveries_device ON link_deliveries(device_id);
CREATE TABLE IF NOT EXISTS phone_state(device_id TEXT PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE, battery_json TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS phone_notifications(device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE, notification_key TEXT NOT NULL, data_json TEXT NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY(device_id,notification_key));
""" + continuity.SCHEMA + features.SCHEMA

class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)
            columns={row[1] for row in db.execute("PRAGMA table_info(tasks)").fetchall()}
            if "notified_at" not in columns: db.execute("ALTER TABLE tasks ADD COLUMN notified_at TEXT")
            session_columns={row[1] for row in db.execute("PRAGMA table_info(web_sessions)").fetchall()}
            if "scopes_json" not in session_columns: db.execute("ALTER TABLE web_sessions ADD COLUMN scopes_json TEXT")
            if "owner_device_id" not in session_columns: db.execute("ALTER TABLE web_sessions ADD COLUMN owner_device_id TEXT")
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path, timeout=15); db.row_factory=sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db; db.commit()
        finally: db.close()
    def rows(self, sql:str, args=()):
        with self.connect() as db: return [dict(r) for r in db.execute(sql,args).fetchall()]
    def row(self, sql:str, args=()):
        with self.connect() as db:
            r=db.execute(sql,args).fetchone(); return dict(r) if r else None
    def execute(self, sql:str,args=()):
        with self.connect() as db: db.execute(sql,args)
    def event(self, kind:str,title:str,body:str,data:dict[str,Any]|None, now:str):
        self.execute("INSERT INTO events(kind,title,body,data_json,created_at) VALUES(?,?,?,?,?)",(kind,title,body,json.dumps(data or {},separators=(",",":")),now))
