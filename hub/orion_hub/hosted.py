# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dedicated hosted deployment: account admission and an opaque event mailbox.

This is deliberately a separate application from app.py. No legacy content API,
automation, Cloud credential registry, or plaintext push handler is mounted here.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError

from .hosted_auth import AccessTokens, Auth0Config
from .security import canonical as request_canonical

DEVICE = re.compile(r"dev_[a-f0-9]{32}\Z")
ROSTER_DOMAIN = b"Orion hosted roster v1\0"
ENROLL_DOMAIN = b"Orion hosted enrollment v1\0"
REQUEST_PREFIX = "orion-approve-v1:"
REQUEST_DOMAIN = b"Orion hosted device approval code v1\0"
MAX_BODY = 65_536
SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS deployment(id INTEGER PRIMARY KEY CHECK(id=1), deployment_id TEXT NOT NULL, issuer TEXT NOT NULL, subject TEXT NOT NULL, audience TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rosters(version INTEGER PRIMARY KEY, digest TEXT NOT NULL UNIQUE, body TEXT NOT NULL, signature TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY, signing_key TEXT NOT NULL, encryption_key TEXT NOT NULL, expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS used_devices(id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS nonces(device TEXT NOT NULL, nonce TEXT NOT NULL, seen_at INTEGER NOT NULL, PRIMARY KEY(device,nonce));
CREATE TABLE IF NOT EXISTS sealed_events(id TEXT PRIMARY KEY, source TEXT NOT NULL, target TEXT NOT NULL, version INTEGER NOT NULL, header TEXT NOT NULL, ciphertext TEXT NOT NULL, digest TEXT NOT NULL, expires_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS sealed_target ON sealed_events(target,expires_at);
CREATE TABLE IF NOT EXISTS roster_catchups(request_hash TEXT PRIMARY KEY, version INTEGER NOT NULL, digest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS approval_requests(device TEXT PRIMARY KEY, code TEXT NOT NULL, expires_at INTEGER NOT NULL);
"""


def stable(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def reject(status=400):
    raise HTTPException(status, "Hosted request rejected")


def exact(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        reject()


def binary(value, maximum):
    if not isinstance(value, str) or len(value) > ((maximum + 2) // 3) * 4:
        reject()
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        reject()
    if not raw or len(raw) > maximum or base64.b64encode(raw).decode() != value:
        reject()
    return raw


def public_key(value):
    try:
        key = serialization.load_der_public_key(binary(value, 256))
        if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "secp256r1":
            reject()
        return key
    except (ValueError, TypeError):
        reject()


def signature(key, value, data):
    try:
        key.verify(binary(value, 128), data, ec.ECDSA(hashes.SHA256()))
    except HTTPException:
        raise
    except Exception:
        reject(403)


def member(value):
    exact(value, ("id", "signing_key", "encryption_key"))
    if not isinstance(value["id"], str) or not DEVICE.fullmatch(value["id"]):
        reject()
    public_key(value["signing_key"])
    # Public Tink keysets are opaque here. Clients must validate their key type
    # and public-only material before signing admission or using a recipient.
    binary(value["encryption_key"], 2048)


@dataclass(frozen=True)
class HostedConfig:
    deployment_id: str
    database: Path
    auth: Auth0Config

    def __post_init__(self):
        if str(UUID(self.deployment_id)) != self.deployment_id:
            raise ValueError("Invalid hosted deployment configuration")


class Mailbox:
    def __init__(self, config, *, device_registry=None):
        self.config = config
        self.device_registry = device_registry
        # Optional aggregate delivery-health hook (hosted_usage.UsageStore.sealed).
        self.observer = None
        config.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            # Prevent an accidental switch from a legacy Hub database.
            if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='devices'").fetchone():
                raise ValueError("Hosted service requires a separate database")
            db.executescript(SCHEMA)
            db.execute("BEGIN IMMEDIATE")
            expected = (config.deployment_id, config.auth.issuer, config.auth.owner_subject, config.auth.audience)
            stored = db.execute("SELECT deployment_id,issuer,subject,audience FROM deployment WHERE id=1").fetchone()
            if stored:
                if tuple(stored) != expected:
                    raise ValueError("Hosted database ownership cannot be replaced")
            else:
                if db.execute("SELECT 1 FROM rosters LIMIT 1").fetchone():
                    raise ValueError("Hosted database requires explicit ownership migration")
                db.execute("INSERT INTO deployment VALUES(1,?,?,?,?)", expected)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.config.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def latest(db):
        row = db.execute("SELECT * FROM rosters ORDER BY version DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def roster(self):
        with self.connect() as db:
            if db.execute("SELECT COUNT(*) FROM rosters").fetchone()[0] > 128:
                # Legacy readers must migrate to bounded signed history pages.
                reject(409)
            return [{"roster": json.loads(r["body"]), "signature": r["signature"]}
                    for r in db.execute("SELECT * FROM rosters ORDER BY version")]

    def roster_page(self, after_version, after_hash, limit):
        if (type(after_version) is not int or not 0 <= after_version <= 2**31 - 1
                or type(limit) is not int or not 1 <= limit <= 16
                or (after_version == 0 and after_hash is not None)
                or (after_version > 0 and (type(after_hash) is not str or not re.fullmatch(r"[a-f0-9]{64}", after_hash)))):
            reject()
        with self.connect() as db:
            # One read transaction gives a coherent page/continuation hint.
            db.execute("BEGIN")
            if after_version:
                row = db.execute("SELECT digest FROM rosters WHERE version=?", (after_version,)).fetchone()
                if row is None or row[0] != after_hash:
                    reject(409)
            rows = db.execute("SELECT * FROM rosters WHERE version>? ORDER BY version LIMIT ?", (after_version, limit + 1)).fetchall()
            return {"chain": [{"roster": json.loads(r["body"]), "signature": r["signature"]} for r in rows[:limit]],
                    "more": len(rows) > limit}

    def candidate(self, value):
        exact(value, ("deployment_id", "device", "proof"))
        if value["deployment_id"] != self.config.deployment_id:
            reject()
        member(value["device"])
        signed = {k: v for k, v in value.items() if k != "proof"}
        signature(public_key(value["device"]["signing_key"]), value["proof"], ENROLL_DOMAIN + stable(signed))
        proposed = value["device"]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM candidates WHERE expires_at<=?", (int(time.time()),))
            if db.execute("SELECT 1 FROM used_devices WHERE id=?", (proposed["id"],)).fetchone():
                reject(409)
            old = db.execute("SELECT * FROM candidates WHERE id=?", (proposed["id"],)).fetchone()
            if old:
                if old["signing_key"] != proposed["signing_key"] or old["encryption_key"] != proposed["encryption_key"]:
                    reject(409)
                return {"status": "pending", "expires_at": old["expires_at"]}
            if db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] >= 10:
                reject(429)
            expiry = int(time.time()) + 600
            db.execute("INSERT INTO candidates VALUES(?,?,?,?)", (proposed["id"], proposed["signing_key"], proposed["encryption_key"], expiry))
        return {"status": "pending", "expires_at": expiry}

    def offer_request(self, value):
        """Hold a pending candidate's signed approval request for the root computer to fetch.

        The server only bounds it and binds it to the stored candidate keys; the root
        verifies it against its own pinned identity and the owner compares fingerprints."""
        exact(value, ("code",))
        code = value["code"]
        if not isinstance(code, str) or not code.startswith(REQUEST_PREFIX) or len(code) > 4096:
            reject()
        try:
            parsed = json.loads(code[len(REQUEST_PREFIX):])
        except ValueError:
            reject()
        exact(parsed, ("data", "signature"))
        data = parsed["data"]
        if (not isinstance(data, dict) or data.get("deployment_id") != self.config.deployment_id
                or not isinstance(data.get("candidate"), dict)):
            reject()
        device = data["candidate"].get("device")
        member(device)
        signature(public_key(device["signing_key"]), parsed["signature"], REQUEST_DOMAIN + stable(data))
        now = int(time.time())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM approval_requests WHERE expires_at<=?", (now,))
            row = db.execute("SELECT * FROM candidates WHERE id=? AND expires_at>?", (device["id"], now)).fetchone()
            if row is None or row["signing_key"] != device["signing_key"] or row["encryption_key"] != device["encryption_key"]:
                reject(409)
            db.execute("INSERT OR REPLACE INTO approval_requests VALUES(?,?,?)", (device["id"], code, row["expires_at"]))
        return {"status": "offered", "expires_at": row["expires_at"]}

    def offered_requests(self):
        with self.connect() as db:
            rows = db.execute("SELECT code FROM approval_requests WHERE expires_at>? AND device NOT IN "
                              "(SELECT id FROM used_devices) ORDER BY expires_at LIMIT 10", (int(time.time()),)).fetchall()
        return {"requests": [row["code"] for row in rows]}

    def admit(self, value):
        now = int(time.time())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._append_roster(db, value, now)

    def _append_roster(self, db, value, now, *, historical=False):
        """Caller holds one transaction; historical steps never become live alone."""
        exact(value, ("roster", "signature"))
        roster = value["roster"]
        exact(roster, ("deployment_id", "version", "previous_hash", "expires_at", "members"))
        if (roster["deployment_id"] != self.config.deployment_id
                or type(roster["version"]) is not int or not 1 <= roster["version"] <= 2**31 - 1
                or type(roster["expires_at"]) is not int or not 0 < roster["expires_at"] <= now + 86400
                or (not historical and roster["expires_at"] <= now)
                or not isinstance(roster["members"], list) or not 1 <= len(roster["members"]) <= 32):
            reject()
        for item in roster["members"]:
            member(item)
        ids = [item["id"] for item in roster["members"]]
        if ids != sorted(set(ids)):
            reject()
        old = self.latest(db)
        before = json.loads(old["body"]) if old else None
        if old:
            root = json.loads(db.execute("SELECT body FROM rosters WHERE version=1").fetchone()[0])["members"][0]
            if roster["version"] != old["version"] + 1 or roster["previous_hash"] != old["digest"] or root not in roster["members"]:
                reject(409)
        else:
            if roster["version"] != 1 or roster["previous_hash"] is not None or len(ids) != 1:
                reject(409)
            root = roster["members"][0]
        signature(public_key(root["signing_key"]), value["signature"], ROSTER_DOMAIN + stable(roster))
        previous = {item["id"]: item for item in before["members"]} if before else {}
        for item in roster["members"]:
            if item["id"] in previous:
                if previous[item["id"]] != item:
                    reject(409)
                continue
            if db.execute("SELECT 1 FROM used_devices WHERE id=?", (item["id"],)).fetchone():
                reject(409)
            pending = db.execute("SELECT * FROM candidates WHERE id=? AND expires_at>?", (item["id"], now)).fetchone()
            if not pending or pending["signing_key"] != item["signing_key"] or pending["encryption_key"] != item["encryption_key"]:
                reject(403)
            db.execute("INSERT INTO used_devices VALUES(?)", (item["id"],))
            db.execute("DELETE FROM candidates WHERE id=?", (item["id"],))
        body = stable(roster).decode()
        digest = hashlib.sha256(body.encode()).hexdigest()
        if self.device_registry is not None:
            # Bind only fully validated, root-approved devices. Ownership is
            # immutable across accounts, including after revocation/deactivation.
            self.device_registry.claim_devices(self.config.deployment_id, ids)
        db.execute("INSERT INTO rosters VALUES(?,?,?,?)", (roster["version"], digest, body, value["signature"]))
        # Intermediate rows in catch-up are uncommitted until a fresh final head
        # passes every check. Concurrent readers can only see old or final state.
        db.execute("DELETE FROM sealed_events")
        return {"version": roster["version"], "digest": digest}

    def catchup(self, value):
        """Commit a bounded signed suffix atomically, preserving exact retries."""
        exact(value, ("expected_hash", "chain"))
        expected = value["expected_hash"]
        if expected is not None and (type(expected) is not str or not re.fullmatch(r"[a-f0-9]{64}", expected)):
            reject()
        chain = value["chain"]
        if type(chain) is not list or not 1 <= len(chain) <= 16:
            reject()
        wire = stable(value)
        if len(wire) > MAX_BODY:
            reject(413)
        request_hash = hashlib.sha256(wire).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # A receipt acknowledges only previously committed exact public bytes.
            # It never installs an old head or reinstates expired membership.
            receipt = db.execute("SELECT version,digest FROM roster_catchups WHERE request_hash=?", (request_hash,)).fetchone()
            if receipt:
                return {"version": receipt["version"], "digest": receipt["digest"]}
            old = self.latest(db)
            if (old["digest"] if old else None) != expected:
                reject(409)
            now = int(time.time())
            for index, entry in enumerate(chain):
                result = self._append_roster(db, entry, now, historical=index < len(chain) - 1)
            db.execute("INSERT INTO roster_catchups VALUES(?,?,?)", (request_hash, result["version"], result["digest"]))
        return result

    def device(self, request, raw):
        if request.headers.get("origin") or request.cookies or request.headers.get("authorization"):
            reject(403)
        device = request.headers.get("x-orion-device-id", "")
        timestamp = request.headers.get("x-orion-timestamp", "")
        nonce = request.headers.get("x-orion-nonce", "")
        try:
            if not DEVICE.fullmatch(device) or str(UUID(nonce)) != nonce or abs(int(timestamp) - int(time.time())) > 60:
                reject(401)
        except (ValueError, TypeError):
            reject(401)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.latest(db)
            if not row:
                reject(403)
            roster = json.loads(row["body"])
            item = next((m for m in roster["members"] if m["id"] == device), None)
            if not item or roster["expires_at"] <= int(time.time()):
                reject(403)
            path = request.url.path + ("?" + request.url.query if request.url.query else "")
            signature(public_key(item["signing_key"]), request.headers.get("x-orion-signature", ""),
                      request_canonical(request.method, path, timestamp, nonce, raw))
            db.execute("DELETE FROM nonces WHERE seen_at<?", (int(time.time()) - 120,))
            # Reject replay atomically across workers/processes.
            try:
                db.execute("INSERT INTO nonces VALUES(?,?,?)", (device, nonce, int(time.time())))
            except sqlite3.IntegrityError:
                reject(409)
        return device, roster["version"]

    def observe(self, kind, *values):
        """Report an event ID, time or size to the aggregate hook; never content, never raises."""
        if self.observer is not None:
            try:
                self.observer(kind, *values)
            except Exception:
                pass

    def publish(self, source, version, value):
        exact(value, ("header", "ciphertext"))
        header = value["header"]
        exact(header, ("protocol_version", "deployment_id", "roster_version", "roster_hash", "id", "source", "target", "expires_at"))
        now = int(time.time())
        try:
            if str(UUID(header["id"])) != header["id"]:
                reject()
        except (ValueError, TypeError, AttributeError):
            reject()
        if (type(header["protocol_version"]) is not int or header["protocol_version"] != 1
                or header["deployment_id"] != self.config.deployment_id or header["source"] != source
                or not isinstance(header["target"], str) or not DEVICE.fullmatch(header["target"])
                or header["target"] == source or type(header["roster_version"]) is not int or header["roster_version"] != version
                or type(header["expires_at"]) is not int or not now < header["expires_at"] <= now + 300):
            reject()
        ciphertext = binary(value["ciphertext"], 49_152)
        if len(ciphertext) < 80:
            reject()
        digest = hashlib.sha256(stable(value)).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self.latest(db)
            roster = json.loads(current["body"])
            if current["version"] != version or header["roster_hash"] != current["digest"] or roster["expires_at"] <= now:
                reject(409)
            if not {source, header["target"]} <= {m["id"] for m in roster["members"]}:
                reject(403)
            db.execute("DELETE FROM sealed_events WHERE expires_at<=?", (now,))
            old = db.execute("SELECT digest FROM sealed_events WHERE id=?", (header["id"],)).fetchone()
            if old:
                if old[0] != digest:
                    reject(409)
                return {"accepted": True, "duplicate": True}
            if (db.execute("SELECT COUNT(*) FROM sealed_events").fetchone()[0] >= 10_000
                    or db.execute("SELECT COUNT(*) FROM sealed_events WHERE target=?", (header["target"],)).fetchone()[0] >= 1000):
                reject(429)
            db.execute("INSERT INTO sealed_events VALUES(?,?,?,?,?,?,?,?)", (header["id"], source, header["target"], version,
                       stable(header).decode(), value["ciphertext"], digest, header["expires_at"]))
        self.observe("published", header["id"], header["expires_at"])
        return {"accepted": True, "duplicate": False}

    def events(self, device, version):
        with self.connect() as db:
            if self.latest(db)["version"] != version:
                reject(409)
            db.execute("DELETE FROM sealed_events WHERE expires_at<=?", (int(time.time()),))
            return [{"header": json.loads(r["header"]), "ciphertext": r["ciphertext"]}
                    for r in db.execute("SELECT header,ciphertext FROM sealed_events WHERE target=? AND version=? ORDER BY rowid LIMIT 100", (device, version))]


async def body(request):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_BODY:
            reject(413)
        raw.extend(chunk)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: reject())
        stable(value)
    except (ValueError, TypeError, RecursionError, UnicodeError):
        reject()
    return bytes(raw), value


def create_app(config: HostedConfig, *, tokens=None, device_registry=None):
    mailbox = Mailbox(config, device_registry=device_registry)
    access = tokens or AccessTokens(config.auth)
    from .hosted_maintenance import app_lifespan, cleanup_database
    app = FastAPI(title="Saiph Hosted", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=app_lifespan(lambda: cleanup_database(config)))

    @app.middleware("http")
    async def private_response(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        return Response('{"detail":"Hosted request rejected"}', status_code=400, media_type="application/json")

    async def account(request):
        if request.headers.get("origin") or request.cookies:
            reject(403)
        return await asyncio.to_thread(access.principal, request)

    @app.get("/v1/health")
    async def health():
        return {"ok": True, "service": "orion-hosted-development"}

    @app.get("/v1/account")
    async def owner(request: Request):
        await account(request)
        return {"deployment_id": config.deployment_id, "device_trust_required": True}

    @app.get("/v1/devices/rosters")
    async def rosters(request: Request):
        await account(request)
        return {"chain": await asyncio.to_thread(mailbox.roster)}

    @app.get("/v1/devices/rosters/page")
    async def roster_page(request: Request):
        await account(request)
        query = request.query_params
        if (set(query) - {"after_version", "after_hash", "limit"}
                or any(len(query.getlist(key)) != 1 for key in query)
                or not re.fullmatch(r"0|[1-9][0-9]{0,9}", query.get("after_version", ""))
                or not re.fullmatch(r"[1-9][0-9]?", query.get("limit", "16"))):
            reject()
        return await asyncio.to_thread(mailbox.roster_page, int(query["after_version"]), query.get("after_hash"), int(query.get("limit", "16")))

    @app.post("/v1/devices/requests")
    async def request_device(request: Request):
        await account(request)
        _, value = await body(request)
        return await asyncio.to_thread(mailbox.candidate, value)

    @app.post("/v1/devices/approval-requests")
    async def offer_request(request: Request):
        await account(request)
        _, value = await body(request)
        return await asyncio.to_thread(mailbox.offer_request, value)

    @app.get("/v1/devices/approval-requests")
    async def offered_requests(request: Request):
        await account(request)
        return await asyncio.to_thread(mailbox.offered_requests)

    @app.post("/v1/devices/rosters")
    async def admit_device(request: Request):
        await account(request)
        _, value = await body(request)
        return await asyncio.to_thread(mailbox.admit, value)

    @app.post("/v1/devices/rosters/catchup")
    async def catchup_rosters(request: Request):
        await account(request)
        _, value = await body(request)
        return await asyncio.to_thread(mailbox.catchup, value)

    @app.post("/v1/sealed/events")
    async def publish(request: Request):
        raw, value = await body(request)
        device, version = await asyncio.to_thread(mailbox.device, request, raw)
        return await asyncio.to_thread(mailbox.publish, device, version, value)

    @app.get("/v1/sealed/events")
    async def events(request: Request):
        device, version = await asyncio.to_thread(mailbox.device, request, b"")
        return {"events": await asyncio.to_thread(mailbox.events, device, version)}

    @app.delete("/v1/sealed/events/{event_id}")
    async def acknowledge(request: Request, event_id: str):
        device, version = await asyncio.to_thread(mailbox.device, request, b"")
        def remove():
            with mailbox.connect() as db:
                if mailbox.latest(db)["version"] != version:
                    reject(409)
                return db.execute("DELETE FROM sealed_events WHERE id=? AND target=? AND version=?",
                                  (event_id, device, version)).rowcount
        if await asyncio.to_thread(remove):
            mailbox.observe("acknowledged", event_id)
        return {"ok": True}

    app.state.mailbox = mailbox
    from .hosted_blobs import attach
    attach(app, mailbox)
    return app
