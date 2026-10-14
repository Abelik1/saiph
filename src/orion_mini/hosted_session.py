# SPDX-License-Identifier: AGPL-3.0-or-later
"""Client-side trust gate for the experimental hosted envelope transport.

The root pin comes from an explicitly verified device QR/fingerprint, never an
Auth0 response or the mailbox. Public trust/replay state is durable; encryption
and signing private keys are supplied in memory by the caller.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .hosted_crypto import (
    EnvelopeError, canonical, export_public, open_envelope, read_public, seal, validate_header,
)

ROSTER_DOMAIN = b"Orion hosted roster v1\0"
ENROLL_DOMAIN = b"Orion hosted enrollment v1\0"


def public_signing_key(key):
    return base64.b64encode(key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()


def read_signing_key(value):
    try:
        if type(value) is not str or len(value) > 344:
            raise ValueError()
        raw = base64.b64decode(value, validate=True)
        key = serialization.load_der_public_key(raw)
        if (not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "secp256r1"
                or public_signing_key(key) != value):
            raise ValueError()
        return key
    except Exception:
        raise EnvelopeError("Invalid device trust.") from None


def enrollment(deployment_id, device_id, signing_key, encryption_key):
    candidate = {"deployment_id": deployment_id, "device": {
        "id": device_id, "signing_key": public_signing_key(signing_key.public_key()),
        "encryption_key": export_public(encryption_key),
    }}
    proof = signing_key.sign(ENROLL_DOMAIN + canonical(candidate), ec.ECDSA(hashes.SHA256()))
    return {**candidate, "proof": base64.b64encode(proof).decode()}


def sign_roster(roster, root_key):
    signature = root_key.sign(ROSTER_DOMAIN + canonical(roster), ec.ECDSA(hashes.SHA256()))
    return {"roster": roster, "signature": base64.b64encode(signature).decode()}


class SealedSession:
    def __init__(self, state: Path, deployment_id: str, root_pin: str, device_id: str,
                 signing_key, encryption_key):
        self.state = state
        self.deployment = str(UUID(deployment_id))
        if self.deployment != deployment_id:
            raise EnvelopeError("Invalid device trust.")
        self.root = read_signing_key(root_pin)
        self.pin, self.device = root_pin, device_id
        self.signing, self.encryption = signing_key, encryption_key
        self.roster = None
        self.digest = None
        state.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS trust(id INTEGER PRIMARY KEY CHECK(id=1), deployment TEXT NOT NULL, root_pin TEXT NOT NULL, version INTEGER NOT NULL, digest TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS received(id TEXT PRIMARY KEY, expires_at INTEGER NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS history_anchor(id INTEGER PRIMARY KEY CHECK(id=1), entry TEXT NOT NULL, root TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS history_used(id TEXT PRIMARY KEY)")
            old = db.execute("SELECT deployment,root_pin FROM trust WHERE id=1").fetchone()
            if old and old != (deployment_id, root_pin):
                raise EnvelopeError("Device trust cannot be replaced.")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.state, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def accept_chain(self, chain):
        """Verify from the pinned root, then atomically advance rollback state."""
        return self._accept_chain(chain, root_history=False)

    def invalidate(self):
        """Discard content authority without resetting durable verification state."""
        self.roster, self.digest = None, None

    def migrate_chain(self, chain):
        """Seed an old profile from verified genesis history, without activation.

        Expired or revoked intermediate profiles can migrate and then continue
        paging. No server-provided head hint substitutes for the signed history.
        """
        self.invalidate()
        return self._accept_chain(chain, root_history=False, historical_only=True)

    def root_history(self, chain=None):
        """Verify expired history only for the sole pinned root's renewal.

        Preserves rollback/high-water checks, but always clears normal content
        authority. The returned public snapshot may only authorize signing a
        fresh successor; ordinary send/receive still needs accept_chain().
        """
        if chain is not None:
            return self._accept_chain(chain, root_history=True)
        self.roster, self.digest = None, None
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                anchor = self._load_anchor(db)
                if anchor is None:
                    raise ValueError()
                entry, root, used = anchor
                self._root_identity(root)
                if entry["roster"]["expires_at"] > int(time.time()) + 86400:
                    raise ValueError()
                return {"roster": entry["roster"], "digest": self._digest(entry), "used_device_ids": sorted(used)}
        except Exception:
            raise EnvelopeError("Cannot verify device trust.") from None

    @staticmethod
    def _digest(entry):
        return hashlib.sha256(canonical(entry["roster"])).hexdigest()

    def _root_identity(self, root):
        if (root["id"] != self.device or root["signing_key"] != public_signing_key(self.signing.public_key())
                or root["encryption_key"] != export_public(self.encryption)):
            raise ValueError()

    def _verify_entries(self, chain, *, version=0, previous_hash=None, previous_members=None, used=None, root=None):
        previous_members = {} if previous_members is None else dict(previous_members)
        used = set() if used is None else set(used)
        entry = None
        for entry in chain:
            version += 1
            if type(entry) is not dict or set(entry) != {"roster", "signature"}:
                raise ValueError()
            roster = entry["roster"]
            if (type(roster) is not dict or set(roster) != {"deployment_id", "version", "previous_hash", "expires_at", "members"}
                    or roster["deployment_id"] != self.deployment or type(roster["version"]) is not int
                    or roster["version"] != version or not 1 <= version <= 2**31 - 1
                    or roster["previous_hash"] != previous_hash or type(roster["expires_at"]) is not int
                    or not 0 < roster["expires_at"] <= 253402300799 or type(roster["members"]) is not list
                    or not 1 <= len(roster["members"]) <= 32):
                raise ValueError()
            members = {}
            for item in roster["members"]:
                if type(item) is not dict or set(item) != {"id", "signing_key", "encryption_key"}:
                    raise ValueError()
                validate_header({"protocol_version": 1, "deployment_id": self.deployment, "id": str(uuid4()),
                                 "roster_version": version, "roster_hash": "0" * 64, "source": item["id"],
                                 "target": item["id"], "expires_at": roster["expires_at"]})
                read_signing_key(item["signing_key"])
                read_public(item["encryption_key"])
                if item["id"] in members:
                    raise ValueError()
                members[item["id"]] = item
                if item["id"] in previous_members:
                    if item != previous_members[item["id"]]:
                        raise ValueError()
                elif item["id"] in used:
                    raise ValueError()
            if list(members) != sorted(members):
                raise ValueError()
            if root is None:
                if version != 1 or len(members) != 1:
                    raise ValueError()
                root = roster["members"][0]
                if root["signing_key"] != self.pin:
                    raise ValueError()
            if members.get(root["id"]) != root:
                raise ValueError()
            signature = base64.b64decode(entry["signature"], validate=True)
            if len(signature) > 80:
                raise ValueError()
            self.root.verify(signature, ROSTER_DOMAIN + canonical(roster), ec.ECDSA(hashes.SHA256()))
            previous_hash = self._digest(entry)
            previous_members = members
            used.update(members)
        return entry, root, used

    def _load_anchor(self, db):
        highwater = db.execute("SELECT deployment,root_pin,version,digest FROM trust WHERE id=1").fetchone()
        saved = db.execute("SELECT entry,root FROM history_anchor WHERE id=1").fetchone()
        used = {row[0] for row in db.execute("SELECT id FROM history_used")}
        if saved is None:
            # Old trust-only state must migrate using a complete verified chain.
            if highwater is not None or used:
                raise ValueError()
            return None
        if highwater is None:
            raise ValueError()
        entry, root = json.loads(saved[0]), json.loads(saved[1])
        roster = entry["roster"]
        if (highwater != (self.deployment, self.pin, roster["version"], self._digest(entry))
                or root["signing_key"] != self.pin or root not in roster["members"]
                or not {item["id"] for item in roster["members"]}.issubset(used)):
            raise ValueError()
        # Recheck the signed retained snapshot. The private local SQLite state
        # carries historical used IDs; no server-provided checkpoint can seed it.
        self._verify_entries([entry], version=roster["version"] - 1,
                             previous_hash=roster["previous_hash"],
                             previous_members={item["id"]: item for item in roster["members"]}, used=used, root=root)
        return entry, root, used

    def _save_anchor(self, db, entry, root, used):
        roster = entry["roster"]
        db.execute("INSERT OR REPLACE INTO trust VALUES(1,?,?,?,?)", (self.deployment, self.pin, roster["version"], self._digest(entry)))
        db.execute("INSERT OR REPLACE INTO history_anchor VALUES(1,?,?)", (canonical(entry).decode(), canonical(root).decode()))
        db.executemany("INSERT OR IGNORE INTO history_used VALUES(?)", ((device,) for device in used))

    def history_cursor(self):
        """Return only a locally verified cursor, never a server head hint."""
        try:
            with self.connect() as db:
                db.execute("BEGIN")
                anchor = self._load_anchor(db)
                if anchor is None:
                    return {"after_version": 0, "after_hash": None}
                return {"after_version": anchor[0]["roster"]["version"], "after_hash": self._digest(anchor[0])}
        except Exception:
            raise EnvelopeError("Cannot verify device trust.") from None

    def accept_page(self, chain, *, final):
        """Verify a bounded signed suffix and atomically retain its exact anchor.

        A partial/expired history is a verification checkpoint only. It never
        grants content authority, including after restart or malformed pages.
        """
        self.roster, self.digest = None, None
        try:
            if type(chain) is not list or len(chain) > 16 or type(final) is not bool:
                raise ValueError()
            frozen = json.loads(canonical(chain))
            if len(canonical(frozen)) > 1_048_576:
                raise ValueError()
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                anchor = self._load_anchor(db)
                if anchor is None:
                    entry, root, used = self._verify_entries(frozen)
                else:
                    old_entry, root, used = anchor
                    entry, root, used = self._verify_entries(frozen, version=old_entry["roster"]["version"],
                        previous_hash=self._digest(old_entry),
                        previous_members={item["id"]: item for item in old_entry["roster"]["members"]}, used=used, root=root)
                    entry = old_entry if entry is None else entry
                if entry is None:
                    raise ValueError()
                self._save_anchor(db, entry, root, used)
            if final:
                if not int(time.time()) < entry["roster"]["expires_at"] <= int(time.time()) + 86400:
                    raise ValueError()
                own = {item["id"]: item for item in entry["roster"]["members"]}.get(self.device)
                if (not own or own["signing_key"] != public_signing_key(self.signing.public_key())
                        or own["encryption_key"] != export_public(self.encryption)):
                    raise ValueError()
                self.roster, self.digest = entry["roster"], self._digest(entry)
        except Exception:
            self.roster, self.digest = None, None
            raise EnvelopeError("Cannot verify device trust.") from None

    def _accept_chain(self, chain, *, root_history, historical_only=False):
        try:
            if type(chain) is not list or not 1 <= len(chain) <= 128:
                raise ValueError()
            chain = json.loads(canonical(chain))
            previous_hash = None
            previous_members = {}
            used = set()
            root = None
            for version, entry in enumerate(chain, 1):
                if type(entry) is not dict or set(entry) != {"roster", "signature"}:
                    raise ValueError()
                roster = entry["roster"]
                if (type(roster) is not dict or set(roster) != {"deployment_id", "version", "previous_hash", "expires_at", "members"}
                        or roster["deployment_id"] != self.deployment or type(roster["version"]) is not int
                        or roster["version"] != version or roster["previous_hash"] != previous_hash
                        or type(roster["expires_at"]) is not int or not 0 < roster["expires_at"] <= 253402300799
                        or type(roster["members"]) is not list or not 1 <= len(roster["members"]) <= 32):
                    raise ValueError()
                members = {}
                for item in roster["members"]:
                    if type(item) is not dict or set(item) != {"id", "signing_key", "encryption_key"}:
                        raise ValueError()
                    # Reuse the envelope's exact device-ID structural validation.
                    validate_header({"protocol_version": 1, "deployment_id": self.deployment, "id": str(uuid4()),
                                     "roster_version": version, "roster_hash": "0" * 64, "source": item["id"],
                                     "target": item["id"], "expires_at": roster["expires_at"]})
                    read_signing_key(item["signing_key"])
                    read_public(item["encryption_key"])
                    if item["id"] in members:
                        raise ValueError()
                    members[item["id"]] = item
                    if item["id"] in previous_members:
                        if item != previous_members[item["id"]]:
                            raise ValueError()
                    elif item["id"] in used:
                        raise ValueError()
                if list(members) != sorted(members):
                    raise ValueError()
                if root is None:
                    if len(members) != 1:
                        raise ValueError()
                    root = roster["members"][0]
                    if root["signing_key"] != self.pin:
                        raise ValueError()
                if members.get(root["id"]) != root:
                    raise ValueError()
                signature = base64.b64decode(entry["signature"], validate=True)
                if len(signature) > 80:
                    raise ValueError()
                self.root.verify(signature, ROSTER_DOMAIN + canonical(roster), ec.ECDSA(hashes.SHA256()))
                previous_hash = hashlib.sha256(canonical(roster)).hexdigest()
                previous_members = members
                used.update(members)
            now = int(time.time())
            if root_history:
                if (root["id"] != self.device
                        or root["signing_key"] != public_signing_key(self.signing.public_key())
                        or root["encryption_key"] != export_public(self.encryption)
                        or roster["expires_at"] > now + 86400):
                    raise ValueError()
            elif not historical_only and not now < roster["expires_at"] <= now + 86400:
                raise ValueError()
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                old = db.execute("SELECT deployment,root_pin,version,digest FROM trust WHERE id=1").fetchone()
                if old and (old[:2] != (self.deployment, self.pin) or version < old[2]
                            or hashlib.sha256(canonical(chain[old[2] - 1]["roster"])).hexdigest() != old[3]):
                    raise ValueError()
                saved = db.execute("SELECT 1 FROM history_anchor WHERE id=1").fetchone()
                retained_used = self._load_anchor(db)[2] if saved else {row[0] for row in db.execute("SELECT id FROM history_used")}
                if not retained_used.issubset(used):
                    raise ValueError()
                self._save_anchor(db, chain[-1], root, used)
            if historical_only:
                self.invalidate()
                return
            # Persist a valid revocation before rejecting our removed membership;
            # a compromised server must not re-enable us with an older roster.
            own = members.get(self.device)
            if (not own or own["signing_key"] != public_signing_key(self.signing.public_key())
                    or own["encryption_key"] != export_public(self.encryption)):
                raise ValueError()
            # Never retain caller-owned mutable objects as verified authority.
            snapshot = json.loads(canonical(roster))
            if root_history:
                self.roster, self.digest = None, None
                return {"roster": snapshot, "digest": previous_hash, "used_device_ids": sorted(used)}
            self.roster, self.digest = snapshot, previous_hash
        except Exception:
            # A bad/expired/revoked view invalidates the in-memory authority.
            self.roster, self.digest = None, None
            raise EnvelopeError("Cannot verify device trust.") from None

    def membership(self):
        """This device's place in the newest verified roster, without granting authority.

        "pending" before any verified roster lists it, "member" when the newest one
        lists it with these keys (it may still be expired), "removed" after a
        verified roster dropped it. Only `current()` authorizes content.
        """
        with self.connect() as db:
            anchor = self._load_anchor(db)
        if anchor is None:
            return "pending"
        entry, _, used = anchor
        own = {item["id"]: item for item in entry["roster"]["members"]}.get(self.device)
        if own and own["signing_key"] == public_signing_key(self.signing.public_key())                 and own["encryption_key"] == export_public(self.encryption):
            return "member"
        return "removed" if self.device in used else "pending"

    def current(self):
        if self.roster is None or self.roster["expires_at"] <= int(time.time()):
            raise EnvelopeError("Current device approval is required.")
        wire = canonical(self.roster)
        if hashlib.sha256(wire).hexdigest() != self.digest:
            raise EnvelopeError("Current device approval is required.")
        with self.connect() as db:
            row = db.execute("SELECT version,digest FROM trust WHERE id=1").fetchone()
            if row != (self.roster["version"], self.digest):
                raise EnvelopeError("Current device approval is required.")
        return {item["id"]: item for item in json.loads(wire)["members"]}

    def encrypt(self, target, payload, *, ttl_seconds=60):
        members = self.current()
        if target not in members or target == self.device or type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 300:
            raise EnvelopeError("Invalid encrypted destination.")
        header = {"protocol_version": 1, "deployment_id": self.deployment, "roster_version": self.roster["version"],
                  "roster_hash": self.digest, "id": str(uuid4()), "source": self.device, "target": target,
                  "expires_at": int(time.time()) + ttl_seconds}
        ciphertext = seal(members[target]["encryption_key"], self.signing, header, payload)
        return {"header": header, "ciphertext": ciphertext}

    def authenticate(self, envelope):
        """Verify and decrypt without claiming delivery or executing an effect.

        DurableMailbox commits the original ciphertext and replay claim in one
        transaction before acknowledging delivery. Callers must not dispatch
        actions directly from this pure verification method.
        """
        members = self.current()
        if type(envelope) is not dict or set(envelope) != {"header", "ciphertext"}:
            raise EnvelopeError("Invalid encrypted event.")
        header = envelope["header"]
        validate_header(header)
        now = int(time.time())
        if (header["deployment_id"] != self.deployment or header["roster_version"] != self.roster["version"]
                or header["roster_hash"] != self.digest or header["source"] not in members
                or header["source"] == self.device or header["target"] != self.device
                or not now < header["expires_at"] <= now + 300):
            raise EnvelopeError("Invalid encrypted event.")
        return open_envelope(self.encryption, read_signing_key(members[header["source"]]["signing_key"]),
                             header, envelope["ciphertext"])

    def receive(self, envelope):
        """Legacy data-only replay gate; action adapters use DurableMailbox."""
        payload = self.authenticate(envelope)
        header = envelope["header"]
        now = int(time.time())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT version,digest FROM trust WHERE id=1").fetchone() != (header["roster_version"], header["roster_hash"]):
                raise EnvelopeError("Current device approval is required.")
            db.execute("DELETE FROM received WHERE expires_at<=?", (now,))
            try:
                db.execute("INSERT INTO received VALUES(?,?)", (header["id"], header["expires_at"]))
            except sqlite3.IntegrityError:
                raise EnvelopeError("Encrypted event was already received.") from None
        return payload
