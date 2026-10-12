# SPDX-License-Identifier: AGPL-3.0-or-later
"""Crash-safe ciphertext queues for the isolated hosted client.

The relay is acknowledged only after replay identity and original ciphertext
commit together. A side effect is claimed before payload is exposed. A crashed
claim stays uncertain: external SMS/call effects cannot be made exactly-once by
SQLite, and are never automatically repeated. No decrypted content is stored.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time

from .hosted_crypto import EnvelopeError, export_public
from .hosted_session import public_signing_key
from .hosted_transport import wire


class DurableMailbox:
    def __init__(self, session):
        self.session = session
        with session.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS hosted_mailbox_identity(id INTEGER PRIMARY KEY CHECK(id=1),binding BLOB NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS hosted_incoming(id TEXT PRIMARY KEY, envelope BLOB NOT NULL, digest TEXT NOT NULL, expires_at INTEGER NOT NULL, status TEXT NOT NULL, result TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS hosted_outgoing(id TEXT PRIMARY KEY, envelope BLOB NOT NULL, expires_at INTEGER NOT NULL, version INTEGER NOT NULL, roster_hash TEXT NOT NULL)")
            db.execute("BEGIN IMMEDIATE")
            binding = wire({"deployment": session.deployment, "device": session.device, "root_pin": session.pin,
                            "signing_key": public_signing_key(session.signing.public_key()),
                            "encryption_key": export_public(session.encryption)})
            old = db.execute("SELECT binding FROM hosted_mailbox_identity WHERE id=1").fetchone()
            if old and old != (binding,):
                raise EnvelopeError("Encrypted mailbox identity cannot be replaced.")
            if old is None:
                if (db.execute("SELECT 1 FROM hosted_incoming LIMIT 1").fetchone()
                        or db.execute("SELECT 1 FROM hosted_outgoing LIMIT 1").fetchone()):
                    raise EnvelopeError("Encrypted mailbox requires explicit migration.")
                db.execute("INSERT INTO hosted_mailbox_identity VALUES(1,?)", (binding,))

    def _authority(self, db, header):
        if (header["expires_at"] <= int(time.time()) or db.execute("SELECT version,digest FROM trust WHERE id=1").fetchone()
                != (header["roster_version"], header["roster_hash"])):
            raise EnvelopeError("Current device approval is required.")

    def ingest(self, envelope):
        """Return True once; identical redelivery is safe to ACK after commit."""
        raw = wire(envelope)
        detached = json.loads(raw)
        self.session.authenticate(detached)
        header = detached["header"]
        digest = hashlib.sha256(raw).hexdigest()
        with self.session.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._authority(db, header)
            row = db.execute("SELECT digest FROM hosted_incoming WHERE id=?", (header["id"],)).fetchone()
            if row:
                if row[0] != digest:
                    raise EnvelopeError("Conflicting encrypted delivery.")
                return False
            # Never silently mix the older data-only receive API and this inbox.
            if db.execute("SELECT 1 FROM received WHERE id=?", (header["id"],)).fetchone():
                raise EnvelopeError("Delivery was claimed outside the encrypted inbox.")
            now = int(time.time())
            db.execute("DELETE FROM hosted_incoming WHERE expires_at<=? AND status IN ('pending','completed')", (now,))
            db.execute("DELETE FROM received WHERE expires_at<=?", (now,))
            if db.execute("SELECT count(*) FROM hosted_incoming").fetchone()[0] >= 1000:
                raise EnvelopeError("Encrypted inbox is full.")
            db.execute("INSERT INTO received VALUES(?,?)", (header["id"], header["expires_at"]))
            db.execute("INSERT INTO hosted_incoming VALUES(?,?,?,?, 'pending',NULL)",
                       (header["id"], raw, digest, header["expires_at"]))
        return True

    def pending(self):
        """Return verified ciphertexts only. Use claim() to obtain action data."""
        self.session.current()
        with self.session.connect() as db:
            # The queue is bounded to 1000. Filter before applying a dispatch
            # batch limit: old-generation entries must not hide fresh arrivals.
            rows = db.execute("SELECT envelope FROM hosted_incoming WHERE status='pending' ORDER BY rowid LIMIT 1000").fetchall()
        result = []
        for (raw,) in rows:
            envelope = json.loads(raw)
            try:
                self.session.authenticate(envelope)
            except EnvelopeError:
                continue  # Expired/old generation never grants dispatch access.
            result.append(envelope)
            if len(result) == 100:
                break
        return result

    def claim(self, event_id):
        """Expose plaintext once after a durable claim; never retry a claim."""
        with self.session.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT envelope,digest,status FROM hosted_incoming WHERE id=?", (event_id,)).fetchone()
            if not row or row[2] != "pending" or hashlib.sha256(row[0]).hexdigest() != row[1]:
                raise EnvelopeError("Encrypted delivery is unavailable or already claimed.")
            envelope = json.loads(row[0])
            payload = self.session.authenticate(envelope)
            self._authority(db, envelope["header"])
            db.execute("UPDATE hosted_incoming SET status='claimed' WHERE id=?", (event_id,))
        return payload

    def complete(self, event_id, result):
        if result not in ("succeeded", "failed", "uncertain"):
            raise EnvelopeError("Invalid action outcome.")
        with self.session.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,result FROM hosted_incoming WHERE id=?", (event_id,)).fetchone()
            if row == ("completed", result):
                return
            if row != ("claimed", None):
                raise EnvelopeError("Encrypted delivery has not been claimed.")
            db.execute("UPDATE hosted_incoming SET status='completed',result=? WHERE id=?", (result, event_id))

    def uncertain(self):
        """Public IDs only; a claim surviving a crash needs explicit resolution."""
        with self.session.connect() as db:
            return [row[0] for row in db.execute("SELECT id FROM hosted_incoming WHERE status='claimed' ORDER BY rowid")]

    def stage(self, target, payload, *, ttl_seconds=60):
        envelope = self.session.encrypt(target, payload, ttl_seconds=ttl_seconds)
        raw, header = wire(envelope), envelope["header"]
        with self.session.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._authority(db, header)
            db.execute("DELETE FROM hosted_outgoing WHERE expires_at<=?", (int(time.time()),))
            if db.execute("SELECT count(*) FROM hosted_outgoing").fetchone()[0] >= 1000:
                raise EnvelopeError("Encrypted outbox is full.")
            db.execute("INSERT INTO hosted_outgoing VALUES(?,?,?,?,?)", (header["id"], raw, header["expires_at"],
                                                                       header["roster_version"], header["roster_hash"]))
        return header["id"]

    def flush(self, transport):
        """Retry exact ciphertext after timeout. Never re-encrypt a sent action."""
        self.session.current()
        with self.session.connect() as db:
            db.execute("DELETE FROM hosted_outgoing WHERE expires_at<=? OR version!=? OR roster_hash!=?",
                       (int(time.time()), self.session.roster["version"], self.session.digest))
            rows = db.execute("SELECT id,envelope FROM hosted_outgoing ORDER BY rowid LIMIT 100").fetchall()
        sent = 0
        for event_id, raw in rows:
            transport.publish(json.loads(raw))
            with self.session.connect() as db:
                db.execute("DELETE FROM hosted_outgoing WHERE id=? AND envelope=?", (event_id, raw))
            sent += 1
        return sent

    def poll(self, transport):
        received = 0
        for envelope in transport.events():
            received += int(self.ingest(envelope))
            transport.acknowledge(envelope["header"]["id"])
        return received
