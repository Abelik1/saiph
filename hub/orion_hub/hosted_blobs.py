# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bounded opaque ciphertext chunks; no file metadata or decryption keys."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import time
from contextlib import contextmanager
from uuid import UUID

from fastapi import Request

from .hosted import DEVICE, binary, body, exact, reject, stable

CHUNK_SIZE = 32_768
MAX_BLOB = 20 * 1024 * 1024
DEPLOYMENT_QUOTA = 100 * 1024 * 1024
RECIPIENT_QUOTA = 4
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
SCHEMA = """
CREATE TABLE IF NOT EXISTS hosted_blobs(
 id TEXT PRIMARY KEY, deployment TEXT NOT NULL, source TEXT NOT NULL,
 target TEXT NOT NULL, version INTEGER NOT NULL, roster_hash TEXT NOT NULL,
 expires_at INTEGER NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL,
 descriptor_hash TEXT NOT NULL, ready INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS hosted_blobs_target ON hosted_blobs(target,expires_at);
CREATE TABLE IF NOT EXISTS hosted_blob_chunks(
 blob TEXT NOT NULL, position INTEGER NOT NULL, ciphertext BLOB NOT NULL,
 PRIMARY KEY(blob,position));
CREATE TRIGGER IF NOT EXISTS hosted_blobs_roster_changed AFTER INSERT ON rosters
BEGIN
 DELETE FROM hosted_blob_chunks;
 DELETE FROM hosted_blobs;
END;
"""


def identifier(value):
    try:
        if type(value) is not str or str(UUID(value)) != value:
            reject()
    except (ValueError, TypeError, AttributeError):
        reject()
    return value


class BlobStore:
    def __init__(self, mailbox):
        self.mailbox = mailbox
        with mailbox.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def transaction(self, device, version):
        with self.mailbox.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            now = int(time.time())
            current = self.mailbox.latest(db)
            if current is None or current["version"] != version:
                reject(409)
            roster = json.loads(current["body"])
            members = {item["id"] for item in roster["members"]}
            if roster["expires_at"] <= now or device not in members:
                reject(403)
            db.execute("DELETE FROM hosted_blob_chunks WHERE blob IN (SELECT id FROM hosted_blobs WHERE expires_at<=?)", (now,))
            db.execute("DELETE FROM hosted_blobs WHERE expires_at<=?", (now,))
            yield db, current, members, now

    def allocate(self, source, version, value):
        exact(value, ("id", "target", "roster_version", "roster_hash", "expires_at", "size", "sha256"))
        identifier(value["id"])
        if (type(value["target"]) is not str or not DEVICE.fullmatch(value["target"])
                or value["target"] == source or type(value["roster_version"]) is not int
                or value["roster_version"] != version or type(value["roster_hash"]) is not str
                or not SHA256.fullmatch(value["roster_hash"]) or type(value["size"]) is not int
                or not 1 <= value["size"] <= MAX_BLOB or type(value["expires_at"]) is not int
                or type(value["sha256"]) is not str or not SHA256.fullmatch(value["sha256"])):
            reject()
        deployment = self.mailbox.config.deployment_id
        digest = hashlib.sha256(stable({"deployment": deployment, "source": source, **value})).hexdigest()
        with self.transaction(source, version) as (db, current, members, now):
            if current["digest"] != value["roster_hash"]:
                reject(409)
            if value["target"] not in members:
                reject(403)
            if not now < value["expires_at"] <= now + 300:
                reject()
            old = db.execute("SELECT descriptor_hash FROM hosted_blobs WHERE id=?", (value["id"],)).fetchone()
            if old:
                if old["descriptor_hash"] != digest:
                    reject(409)
                return {"accepted": True, "duplicate": True}
            if (db.execute("SELECT COALESCE(sum(size),0) FROM hosted_blobs").fetchone()[0] + value["size"] > DEPLOYMENT_QUOTA
                    or db.execute("SELECT count(*) FROM hosted_blobs WHERE target=?", (value["target"],)).fetchone()[0] >= RECIPIENT_QUOTA):
                reject(429)
            db.execute("INSERT INTO hosted_blobs VALUES(?,?,?,?,?,?,?,?,?,?,0)",
                       (value["id"], deployment, source, value["target"], version, value["roster_hash"],
                        value["expires_at"], value["size"], value["sha256"], digest))
        return {"accepted": True, "duplicate": False}

    def _blob(self, db, current, members, blob_id, device, *, recipient=False):
        row = db.execute("SELECT * FROM hosted_blobs WHERE id=?", (identifier(blob_id),)).fetchone()
        if row is None:
            reject(404)
        if (row["deployment"] != self.mailbox.config.deployment_id or row["version"] != current["version"]
                or row["roster_hash"] != current["digest"] or not {row["source"], row["target"]} <= members):
            reject(409)
        if row["target" if recipient else "source"] != device:
            reject(403)
        return row

    @staticmethod
    def _length(blob, index):
        if type(index) is not int or not 0 <= index < (blob["size"] + CHUNK_SIZE - 1) // CHUNK_SIZE:
            reject()
        return min(CHUNK_SIZE, blob["size"] - index * CHUNK_SIZE)

    def chunk(self, device, version, blob_id, index, value):
        exact(value, ("data",))
        raw = binary(value["data"], CHUNK_SIZE)
        with self.transaction(device, version) as (db, current, members, _):
            blob = self._blob(db, current, members, blob_id, device)
            if len(raw) != self._length(blob, index):
                reject()
            previous = db.execute("SELECT ciphertext FROM hosted_blob_chunks WHERE blob=? AND position=?", (blob_id, index)).fetchone()
            if previous:
                if previous["ciphertext"] != raw:
                    reject(409)
                return {"accepted": True, "duplicate": True}
            if blob["ready"] or db.execute("SELECT count(*) FROM hosted_blob_chunks WHERE blob=?", (blob_id,)).fetchone()[0] != index:
                reject(409)
            db.execute("INSERT INTO hosted_blob_chunks VALUES(?,?,?)", (blob_id, index, raw))
        return {"accepted": True, "duplicate": False}

    def complete(self, device, version, blob_id, value):
        exact(value, ())
        with self.transaction(device, version) as (db, current, members, _):
            blob = self._blob(db, current, members, blob_id, device)
            digest, count, size = hashlib.sha256(), 0, 0
            for row in db.execute("SELECT position,ciphertext FROM hosted_blob_chunks WHERE blob=? ORDER BY position", (blob_id,)):
                if row["position"] != count or len(row["ciphertext"]) != self._length(blob, count):
                    reject(409)
                digest.update(row["ciphertext"])
                size += len(row["ciphertext"])
                count += 1
            if size != blob["size"] or digest.hexdigest() != blob["sha256"]:
                reject(409)
            db.execute("UPDATE hosted_blobs SET ready=1 WHERE id=?", (blob_id,))
        return {"ready": True}

    def download(self, device, version, blob_id, index):
        with self.transaction(device, version) as (db, current, members, _):
            blob = self._blob(db, current, members, blob_id, device, recipient=True)
            length = self._length(blob, index)
            if not blob["ready"]:
                reject(409)
            row = db.execute("SELECT ciphertext FROM hosted_blob_chunks WHERE blob=? AND position=?", (blob_id, index)).fetchone()
            if row is None or len(row["ciphertext"]) != length:
                reject(409)
            return {"data": base64.b64encode(row["ciphertext"]).decode("ascii")}

    def remove(self, device, version, blob_id):
        identifier(blob_id)
        with self.transaction(device, version) as (db, current, members, _):
            blob = db.execute("SELECT * FROM hosted_blobs WHERE id=?", (blob_id,)).fetchone()
            if blob:
                if device not in (blob["source"], blob["target"]):
                    reject(403)
                if (blob["deployment"] != self.mailbox.config.deployment_id or blob["version"] != current["version"]
                        or blob["roster_hash"] != current["digest"] or not {blob["source"], blob["target"]} <= members):
                    reject(409)
                db.execute("DELETE FROM hosted_blob_chunks WHERE blob=?", (blob_id,))
                db.execute("DELETE FROM hosted_blobs WHERE id=?", (blob_id,))
        return {"ok": True}


def attach(app, mailbox):
    """Mount only on the dedicated hosted app; no account-token content routes."""
    store = BlobStore(mailbox)

    async def authenticated(request, has_body):
        raw, value = await body(request) if has_body else (b"", None)
        device, version = await asyncio.to_thread(mailbox.device, request, raw)
        return device, version, value

    @app.post("/v1/sealed/blobs")
    async def allocate(request: Request):
        device, version, value = await authenticated(request, True)
        return await asyncio.to_thread(store.allocate, device, version, value)

    @app.post("/v1/sealed/blobs/{blob_id}/chunks/{index}")
    async def chunk(request: Request, blob_id: str, index: int):
        device, version, value = await authenticated(request, True)
        return await asyncio.to_thread(store.chunk, device, version, blob_id, index, value)

    @app.post("/v1/sealed/blobs/{blob_id}/complete")
    async def complete(request: Request, blob_id: str):
        device, version, value = await authenticated(request, True)
        return await asyncio.to_thread(store.complete, device, version, blob_id, value)

    @app.get("/v1/sealed/blobs/{blob_id}/chunks/{index}")
    async def download(request: Request, blob_id: str, index: int):
        device, version, _ = await authenticated(request, False)
        return await asyncio.to_thread(store.download, device, version, blob_id, index)

    @app.delete("/v1/sealed/blobs/{blob_id}")
    async def remove(request: Request, blob_id: str):
        device, version, _ = await authenticated(request, False)
        return await asyncio.to_thread(store.remove, device, version, blob_id)

    app.state.blobs = store
    return store
