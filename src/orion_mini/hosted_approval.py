# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public device-approval codes and root-only roster proposals.

This is a transport-independent development helper, not a QR UI or an account
recovery mechanism. Private keys are supplied in memory. A server response can
never establish the initial root pin; callers must explicitly verify its code
out of band or compare its complete fingerprint on an already trusted device.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import re
import secrets
import sqlite3
import threading
import time
from uuid import UUID
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from tink import hybrid

from .hosted_crypto import canonical, export_public, read_public
from .hosted_session import (
    ENROLL_DOMAIN, ROSTER_DOMAIN, enrollment, public_signing_key, read_signing_key, sign_roster,
)

ROOT_PREFIX = "orion-root-v1:"
REQUEST_PREFIX = "orion-approve-v1:"
MAX_CODE_BYTES = 2048
_ROOT_DOMAIN = b"Orion hosted root approval code v1\0"
_REQUEST_DOMAIN = b"Orion hosted device approval code v1\0"
_FINGERPRINT_DOMAIN = b"Orion hosted root fingerprint v1\0"
_MEMBER_KEYS = {"id", "signing_key", "encryption_key"}


class ApprovalError(ValueError):
    def __init__(self):
        super().__init__("Cannot verify device approval.")


def _deployment(value):
    if type(value) is not str or str(UUID(value)) != value:
        raise ApprovalError()


def _member(value):
    if type(value) is not dict or set(value) != _MEMBER_KEYS:
        raise ApprovalError()
    if type(value["id"]) is not str or not re.fullmatch(r"dev_[a-f0-9]{32}", value["id"]):
        raise ApprovalError()
    read_signing_key(value["signing_key"])
    read_public(value["encryption_key"])


def _verify(key, signature, data):
    if type(signature) is not str or len(signature) > 108:
        raise ApprovalError()
    raw = base64.b64decode(signature, validate=True)
    if not raw or len(raw) > 80 or base64.b64encode(raw).decode() != signature:
        raise ApprovalError()
    key.verify(raw, data, ec.ECDSA(hashes.SHA256()))


def _fresh(data):
    now = int(time.time())
    if type(data["expires_at"]) is not int or not now < data["expires_at"] <= now + 600:
        raise ApprovalError()
    if type(data["nonce"]) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{43}", data["nonce"]):
        raise ApprovalError()


def _expiry(ttl_seconds):
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 600:
        raise ApprovalError()
    return int(time.time()) + ttl_seconds


def _roster_expiry(ttl_seconds):
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 86400:
        raise ApprovalError()
    return int(time.time()) + ttl_seconds


def _code(prefix, data, signing_key, domain):
    signature = signing_key.sign(domain + canonical(data), ec.ECDSA(hashes.SHA256()))
    result = prefix + canonical({"data": data, "signature": base64.b64encode(signature).decode()}).decode()
    if len(result) > MAX_CODE_BYTES:
        raise ApprovalError()
    return result


def _parse(code, prefix):
    if type(code) is not str or len(code) > MAX_CODE_BYTES or not code.startswith(prefix) or not code.isascii():
        raise ApprovalError()

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ApprovalError()
            result[key] = value
        return result

    payload = code[len(prefix):]
    value = json.loads(payload, object_pairs_hook=unique)
    if type(value) is not dict or set(value) != {"data", "signature"} or canonical(value).decode() != payload:
        raise ApprovalError()
    return value


@dataclass(frozen=True)
class TrustedRoot:
    deployment_id: str
    device_id: str
    signing_key: str
    encryption_key: str

    def __post_init__(self):
        try:
            _deployment(self.deployment_id)
            _member(self.member())
        except Exception:
            raise ApprovalError() from None

    def member(self):
        return {"id": self.device_id, "signing_key": self.signing_key, "encryption_key": self.encryption_key}

    @property
    def fingerprint(self):
        binding = {"deployment_id": self.deployment_id, "root": self.member()}
        return hashlib.sha256(_FINGERPRINT_DOMAIN + canonical(binding)).hexdigest()

    @property
    def display_fingerprint(self):
        value = self.fingerprint.upper()
        return " ".join(value[index:index + 4] for index in range(0, len(value), 4))


def local_root(deployment_id, device_id, signing_key, encryption_key):
    """Establish a new root only from this device's caller-owned private keys."""
    try:
        encryption_key.primitive(hybrid.HybridDecrypt)
        return TrustedRoot(deployment_id, device_id, public_signing_key(signing_key.public_key()), export_public(encryption_key))
    except Exception:
        raise ApprovalError() from None


def make_root_code(root, signing_key, *, ttl_seconds=300):
    try:
        if public_signing_key(signing_key.public_key()) != root.signing_key:
            raise ApprovalError()
        data = {"protocol_version": 1, "deployment_id": root.deployment_id, "root": root.member(),
                "expires_at": _expiry(ttl_seconds), "nonce": secrets.token_urlsafe(32)}
        return _code(ROOT_PREFIX, data, signing_key, _ROOT_DOMAIN)
    except Exception:
        raise ApprovalError() from None


def inspect_root_code(code):
    """Validate a self-signed public code without declaring it trusted."""
    try:
        value = _parse(code, ROOT_PREFIX)
        data = value["data"]
        if type(data) is not dict or set(data) != {"protocol_version", "deployment_id", "root", "expires_at", "nonce"}:
            raise ApprovalError()
        if type(data["protocol_version"]) is not int or data["protocol_version"] != 1:
            raise ApprovalError()
        _fresh(data)
        _member(data["root"])
        root = TrustedRoot(data["deployment_id"], data["root"]["id"], data["root"]["signing_key"], data["root"]["encryption_key"])
        _verify(read_signing_key(root.signing_key), value["signature"], _ROOT_DOMAIN + canonical(data))
        # Return display data, not the TrustedRoot authority used by approval.
        return {"deployment_id": root.deployment_id, "device_id": root.device_id,
                "fingerprint": root.fingerprint, "display_fingerprint": root.display_fingerprint}
    except Exception:
        raise ApprovalError() from None


def trust_root_code(code, *, trusted_out_of_band=False, expected_fingerprint=None):
    """Caller must confirm a trusted QR source or the complete fingerprint.

    A fingerprint copied from the same untrusted server/code is not independent
    verification. No account token, mailbox roster or shortened code suffices.
    """
    try:
        info = inspect_root_code(code)
        match = type(expected_fingerprint) is str and (
            secrets.compare_digest(expected_fingerprint, info["fingerprint"])
            or secrets.compare_digest(expected_fingerprint, info["display_fingerprint"]))
        if trusted_out_of_band is not True and not match:
            raise ApprovalError()
        data = _parse(code, ROOT_PREFIX)["data"]
        return TrustedRoot(data["deployment_id"], data["root"]["id"], data["root"]["signing_key"], data["root"]["encryption_key"])
    except Exception:
        raise ApprovalError() from None


def _enrollment(value, deployment):
    if type(value) is not dict or set(value) != {"deployment_id", "device", "proof"} or value["deployment_id"] != deployment:
        raise ApprovalError()
    _member(value["device"])
    signed = {"deployment_id": deployment, "device": value["device"]}
    _verify(read_signing_key(value["device"]["signing_key"]), value["proof"], ENROLL_DOMAIN + canonical(signed))


def make_request_code(root, device_id, signing_key, encryption_key, *, ttl_seconds=300):
    try:
        encryption_key.primitive(hybrid.HybridDecrypt)
        candidate = enrollment(root.deployment_id, device_id, signing_key, encryption_key)
        _enrollment(candidate, root.deployment_id)
        if device_id == root.device_id:
            raise ApprovalError()
        data = {"protocol_version": 1, "deployment_id": root.deployment_id, "root_fingerprint": root.fingerprint,
                "candidate": candidate, "expires_at": _expiry(ttl_seconds), "nonce": secrets.token_urlsafe(32)}
        return _code(REQUEST_PREFIX, data, signing_key, _REQUEST_DOMAIN)
    except Exception:
        raise ApprovalError() from None


def verify_request_code(code, root):
    """Verify key possession and binding to an independently pinned root."""
    try:
        value = _parse(code, REQUEST_PREFIX)
        data = value["data"]
        if type(data) is not dict or set(data) != {"protocol_version", "deployment_id", "root_fingerprint", "candidate", "expires_at", "nonce"}:
            raise ApprovalError()
        if (type(data["protocol_version"]) is not int or data["protocol_version"] != 1
                or data["deployment_id"] != root.deployment_id or data["root_fingerprint"] != root.fingerprint):
            raise ApprovalError()
        _fresh(data)
        _enrollment(data["candidate"], root.deployment_id)
        if data["candidate"]["device"]["id"] == root.device_id:
            raise ApprovalError()
        _verify(read_signing_key(data["candidate"]["device"]["signing_key"]), value["signature"], _REQUEST_DOMAIN + canonical(data))
        return json.loads(canonical(data))
    except Exception:
        raise ApprovalError() from None


def _pending(candidate, member):
    if type(candidate) is not dict or set(candidate) != _MEMBER_KEYS | {"expires_at"}:
        raise ApprovalError()
    if {key: candidate[key] for key in _MEMBER_KEYS} != member:
        raise ApprovalError()
    expiry = candidate["expires_at"]
    if type(expiry) is not int or not int(time.time()) < expiry <= int(time.time()) + 600:
        raise ApprovalError()


def _stored_proposal(root, template, stored):
    if type(stored) is not str or len(stored) > 49152:
        raise ApprovalError()
    proposal = json.loads(stored)
    if canonical(proposal).decode() != stored or set(proposal) != {"roster", "signature"}:
        raise ApprovalError()
    roster = proposal["roster"]
    if (type(roster) is not dict or {key: value for key, value in roster.items() if key != "expires_at"} != template
            or type(roster.get("expires_at")) is not int or not 0 < roster["expires_at"] <= 253402300799):
        raise ApprovalError()
    _verify(read_signing_key(root.signing_key), proposal["signature"], ROSTER_DOMAIN + canonical(roster))
    return proposal


def _journal_sign(state, root, signing_key, template, ttl_seconds, *, predecessor):
    """Atomically persist one public signed result per predecessor before return."""
    # Expiry is chosen on the first attempt. An identical intent retry must
    # return that precise existing expiry/signature, even after a process crash.
    _roster_expiry(ttl_seconds)
    intent = canonical({"roster": template, "ttl_seconds": ttl_seconds}).decode()
    state = Path(state)
    state.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(state, timeout=10)
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS approval_owner(id INTEGER PRIMARY KEY CHECK(id=1), deployment TEXT NOT NULL, root_device TEXT NOT NULL, signing_key TEXT NOT NULL, encryption_key TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS approval_proposals(predecessor TEXT PRIMARY KEY, intent TEXT NOT NULL, proposal TEXT NOT NULL)")
            owner = (root.deployment_id, root.device_id, root.signing_key, root.encryption_key)
            old_owner = db.execute("SELECT deployment,root_device,signing_key,encryption_key FROM approval_owner WHERE id=1").fetchone()
            if old_owner is not None and old_owner != owner:
                raise ApprovalError()
            if old_owner is None:
                db.execute("INSERT INTO approval_owner VALUES(1,?,?,?,?)", owner)
            has_trust = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='trust'").fetchone()
            highwater = db.execute("SELECT deployment,root_pin,version,digest FROM trust WHERE id=1").fetchone() if has_trust else None
            if highwater is not None and highwater[:2] != (root.deployment_id, root.signing_key):
                raise ApprovalError()
            if predecessor != "genesis" and (highwater is None or highwater[2:] != (template["version"] - 1, predecessor)):
                raise ApprovalError()
            old = db.execute("SELECT intent,proposal FROM approval_proposals WHERE predecessor=?", (predecessor,)).fetchone()
            if old is not None:
                if old[0] != intent:
                    raise ApprovalError()
                return _stored_proposal(root, template, old[1])
            if predecessor == "genesis" and highwater is not None:
                raise ApprovalError()
            roster = {**template, "expires_at": _roster_expiry(ttl_seconds)}
            proposal = sign_roster(roster, signing_key)
            db.execute("INSERT INTO approval_proposals VALUES(?,?,?)", (predecessor, intent, canonical(proposal).decode()))
        return proposal
    finally:
        db.close()


def initialize_root(root, signing_key, encryption_key, pending_candidate, *, state, roster_ttl_seconds=3600):
    """Propose first roster using locally generated root keys and exact pending keys."""
    try:
        if local_root(root.deployment_id, root.device_id, signing_key, encryption_key) != root:
            raise ApprovalError()
        _pending(pending_candidate, root.member())
        template = {"deployment_id": root.deployment_id, "version": 1, "previous_hash": None, "members": [root.member()]}
        return _journal_sign(state, root, signing_key, template, roster_ttl_seconds, predecessor="genesis")
    except Exception:
        raise ApprovalError() from None


def prepare_catchup(session, root, committed_chain, *, expected_hash, roster_ttl_seconds=3600):
    """Extend exact committed history; return a bounded suffix with a fresh head.

    The caller preserves the complete verified history, including journaled but
    unaccepted steps. This helper performs no HTTP, resets no trust/journal and
    never enables expired content. All newly introduced keys still need current
    pending enrollment proof on the server before submitting the returned suffix.
    """
    try:
        if type(committed_chain) is not list or not 1 <= len(committed_chain) <= 127:
            raise ApprovalError()
        chain = [json.loads(canonical(entry)) for entry in committed_chain]
        if expected_hash is None:
            start = 0
        elif type(expected_hash) is str and re.fullmatch(r"[a-f0-9]{64}", expected_hash):
            hashes = [hashlib.sha256(canonical(entry["roster"])).hexdigest() for entry in chain]
            if expected_hash not in hashes:
                raise ApprovalError()
            start = hashes.index(expected_hash) + 1
        else:
            raise ApprovalError()
        if len(chain) - start + 1 > 16:
            raise ApprovalError()
        approval = RootApproval(session, root, chain)
        proposal = approval.renew(roster_ttl_seconds=roster_ttl_seconds)
        if proposal["roster"]["expires_at"] <= int(time.time()):
            # Preserve this further commitment too. The caller must include it
            # in retained history before preparing its next successor.
            raise ApprovalError()
        result = {"expected_hash": expected_hash, "chain": chain[start:] + [proposal]}
        if len(canonical(result)) > 49152:
            raise ApprovalError()
        return result
    except Exception:
        raise ApprovalError() from None


def prepare_anchored_catchup(session, root, *, expected_hash, roster_ttl_seconds=3600):
    """Recover an exact journal suffix without reconstructing lifetime history.

    The server hash only selects locally journaled public commitments. It cannot
    set trust, skip a signature, replace a pending intent, or reset a journal.
    A bounded expired pending commitment is retained as historical authority
    before signing its successor, never as permission to send or receive data.
    """
    try:
        if expected_hash is not None and (type(expected_hash) is not str or not re.fullmatch(r"[a-f0-9]{64}", expected_hash)):
            raise ApprovalError()
        for _ in range(16):
            approval = RootApproval(session, root)
            pending = approval.pending_proposal()
            if pending is None or pending["roster"]["expires_at"] > int(time.time()):
                break
            session.accept_page([pending], final=False)
        else:
            raise ApprovalError()
        cursor = session.history_cursor()
        suffix = []
        digest = expected_hash
        with session.connect() as db:
            while digest != cursor["after_hash"]:
                if len(suffix) >= 15:
                    raise ApprovalError()
                predecessor = "genesis" if digest is None else digest
                row = db.execute("SELECT intent,proposal FROM approval_proposals WHERE predecessor=?", (predecessor,)).fetchone()
                if row is None or len(row[0]) > 49152:
                    raise ApprovalError()
                intent = json.loads(row[0])
                if canonical(intent).decode() != row[0] or set(intent) != {"roster", "ttl_seconds"}:
                    raise ApprovalError()
                proposal = _stored_proposal(root, intent["roster"], row[1])
                roster = proposal["roster"]
                if (roster["deployment_id"] != root.deployment_id or roster["previous_hash"] != digest
                        or (suffix and roster["version"] != suffix[-1]["roster"]["version"] + 1)
                        or (digest is None and roster["version"] != 1)):
                    raise ApprovalError()
                suffix.append(proposal)
                digest = hashlib.sha256(canonical(roster)).hexdigest()
                if roster["version"] > cursor["after_version"]:
                    raise ApprovalError()
        if suffix and suffix[-1]["roster"]["version"] != cursor["after_version"]:
            raise ApprovalError()
        proposal = pending if pending is not None else approval.renew(roster_ttl_seconds=roster_ttl_seconds)
        if proposal["roster"]["expires_at"] <= int(time.time()):
            raise ApprovalError()
        result = {"expected_hash": expected_hash, "chain": suffix + [proposal]}
        if len(canonical(result)) > 49152:
            raise ApprovalError()
        return result
    except Exception:
        raise ApprovalError() from None


class RootApproval:
    """One durable roster proposal per predecessor; identical retries reuse it.

    The root device is the sole signer. No recovery/root replacement is offered.
    All history is verified through SealedSession before any proposal is signed.
    """
    def __init__(self, session, root, chain=None):
        try:
            if (session.pin != root.signing_key or session.deployment != root.deployment_id
                    or session.device != root.device_id
                    or local_root(root.deployment_id, session.device, session.signing, session.encryption) != root):
                raise ApprovalError()
            if chain is None:
                history = session.root_history()
            else:
                if type(chain) is not list or not 1 <= len(chain) <= 128:
                    raise ApprovalError()
                frozen_chain = [json.loads(canonical(entry)) for entry in tuple(chain)]
                history = session.root_history(frozen_chain)
            self.session, self.root = session, root
            self._used = set(history["used_device_ids"])
            self._roster = history["roster"]
            self._version, self._digest = self._roster["version"], history["digest"]
            self._lock = threading.Lock()
        except Exception:
            raise ApprovalError() from None

    def _propose(self, members, ttl_seconds):
        with self._lock:
            if (hashlib.sha256(canonical(self._roster)).hexdigest() != self._digest or self._version >= 2**31 - 1
                    or not 1 <= len(members) <= 32):
                raise ApprovalError()
            template = {"deployment_id": self.root.deployment_id, "version": self._version + 1,
                      "previous_hash": self._digest,
                      "members": sorted(members, key=lambda member: member["id"])}
            return _journal_sign(self.session.state, self.root, self.session.signing, template, ttl_seconds, predecessor=self._digest)

    def pending_proposal(self):
        """Recover exact public bytes without reauthorizing or signing anything.

        May return an expired proposal. Such a proposal remains a commitment,
        not permission to reset the journal or silently create a conflicting one.
        """
        try:
            with self.session.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                highwater = db.execute("SELECT deployment,root_pin,version,digest FROM trust WHERE id=1").fetchone()
                if highwater != (self.root.deployment_id, self.root.signing_key, self._version, self._digest):
                    raise ApprovalError()
                exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='approval_proposals'").fetchone()
                if not exists:
                    return None
                owner = db.execute("SELECT deployment,root_device,signing_key,encryption_key FROM approval_owner WHERE id=1").fetchone()
                if owner != (self.root.deployment_id, self.root.device_id, self.root.signing_key, self.root.encryption_key):
                    raise ApprovalError()
                row = db.execute("SELECT intent,proposal FROM approval_proposals WHERE predecessor=?", (self._digest,)).fetchone()
                if row is None:
                    return None
                if len(row[0]) > 49152:
                    raise ApprovalError()
                intent = json.loads(row[0])
                if canonical(intent).decode() != row[0] or set(intent) != {"roster", "ttl_seconds"}:
                    raise ApprovalError()
                template = intent["roster"]
                if (template["deployment_id"] != self.root.deployment_id or template["version"] != self._version + 1
                        or template["previous_hash"] != self._digest):
                    raise ApprovalError()
                return _stored_proposal(self.root, template, row[1])
        except Exception:
            raise ApprovalError() from None

    def approve(self, request_code, pending_candidate, *, roster_ttl_seconds=3600):
        try:
            request = verify_request_code(request_code, self.root)
            member = request["candidate"]["device"]
            _pending(pending_candidate, member)
            if member["id"] in self._used:
                raise ApprovalError()
            members = list(self._roster["members"]) + [member]
            return self._propose(members, roster_ttl_seconds)
        except Exception:
            raise ApprovalError() from None

    def revoke(self, device_id, *, roster_ttl_seconds=3600):
        try:
            members = {member["id"]: member for member in self._roster["members"]}
            if device_id == self.root.device_id or device_id not in members:
                raise ApprovalError()
            return self._propose([member for key, member in members.items() if key != device_id], roster_ttl_seconds)
        except Exception:
            raise ApprovalError() from None

    def renew(self, *, roster_ttl_seconds=3600):
        try:
            return self._propose(list(self._roster["members"]), roster_ttl_seconds)
        except Exception:
            raise ApprovalError() from None

    @property
    def expires_at(self):
        return self._roster["expires_at"]

    def renewal_due(self, *, margin_seconds=900, now=None):
        """True once the verified current roster is within margin of expiry.

        The server refuses every device after the latest roster expires and only
        this root can renew it, so a root scheduler must renew before then.
        """
        if type(margin_seconds) is not int or not 0 < margin_seconds < 86400:
            raise ApprovalError()
        now = int(time.time()) if now is None else now
        return self.expires_at - now <= margin_seconds
