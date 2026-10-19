# SPDX-License-Identifier: AGPL-3.0-or-later
"""Session offers: a one-use local invitation sent to an approved phone.

The camera QR carries a one-use capability for a pinned local TLS session. A
`session.offer` carries exactly the same invitation inside a sealed Cloud
envelope instead, addressed to one current roster member. The relay sees
ciphertext only; the envelope already proves which approved computer sent it.

This module is the desktop half of one shared format. Android's
`SessionOffer.kt` applies the same checks, and both test suites read
`android/app/src/test/resources/session-offer-vectors.json`.

  {"type": "session.offer", "version": 1, "id": <128-bit hex>,
   "service": "camera", "expires_at": <unix seconds>, "invite": <invitation>}

Rules (both sides):
- exact keys and JSON types; integers are never booleans or strings;
- `service` names a known invitation format, and `invite` must be valid for
  it (for the camera: the same checks as scanning `orion-camera:1:`/`:2:`);
- `expires_at` equals the invitation's own deadline, lies in the future and at
  most `MAX_LIFETIME` seconds ahead: an offer never outlives its invitation;
- the receiver accepts an offer only from a current, subscribed computer,
  shows it at most once per `id` and still requires its owner's verification,
  the foreground and Android camera access before anything starts. The desktop
  claims the invitation's bearer secret on first use, so a replayed offer or
  a second scanner gets nothing.

Adding a service (for example phone screen mirroring) means adding one entry
to `SERVICES` here and in `SessionOffer.kt`, with its own invitation parser.

The "file" service (docs/LAN_FILES.md) moves one file directly over the local
network. Its receiver acts without a tap, because the owner started the send on
their own approved device, and only stages the verified file privately until
the owner saves it. A receiver that cannot use the offer answers
  {"type": "session.refuse", "version": 1, "id": <the offer's id>,
   "reason": "unreachable" | "storage" | "busy"}
so the sender can fall back to Saiph Cloud at once. A phone, which never
listens on the network, asks a computer for an upload invitation with
  {"type": "file.lan.request", "version": 1, "id": <128-bit hex>, "name": str,
   "size": int, "sha256": <hex>, "expires_at": <unix seconds>}
and the computer answers with a "file" offer in mode "put" naming that ID.

Closing an offer: once the desktop's waiting session is answered (by this offer,
a scanned code), cancelled or expired, it sends
  {"type": "session.close", "version": 1, "id": <the offer's id>}
to the same phone, so the phone removes the notification and in-app prompt at
once instead of leaving a dead request in the shade. Only the computer that
sent an offer can close it; older phones ignore the unknown event type.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import secrets
import time

SESSION_OFFER = "session.offer"
SESSION_CLOSE = "session.close"
VERSION = 1
MAX_LIFETIME = 120
MAX_INVITE = 2048
_ID = re.compile(r"[a-f0-9]{32}")
_B64 = re.compile(r"[A-Za-z0-9_-]+")
CAMERA_PREFIX = "orion-camera:1:"
CAMERA_PROFILE_PREFIX = "orion-camera:2:"
SCREEN_PREFIX = "orion-screen:1:"
_PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+")


class OfferError(ValueError):
    def __init__(self, message="This session offer is invalid or expired."):
        super().__init__(message)


def _integer(value) -> bool:
    return type(value) is int


def _private_ipv4(value) -> bool:
    if type(value) is not str or not re.fullmatch(r"[0-9]{1,3}(\.[0-9]{1,3}){3}", value):
        return False
    parts = [int(part) for part in value.split(".")]
    if any(part > 255 for part in parts) or ".".join(map(str, parts)) != value:
        return False
    return parts[0] == 10 or (parts[0] == 172 and 16 <= parts[1] <= 31) or (parts[0] == 192 and parts[1] == 168)


def camera_invite(invite, now: int) -> int:
    """Validate a camera invitation exactly as the phone's scanner does; return its deadline."""
    if type(invite) is not str:
        raise OfferError()
    profiled = invite.startswith(CAMERA_PROFILE_PREFIX)
    prefix = CAMERA_PROFILE_PREFIX if profiled else CAMERA_PREFIX
    if not 100 <= len(invite) <= MAX_INVITE or not invite.startswith(prefix):
        raise OfferError()
    encoded = invite[len(prefix):]
    if not _B64.fullmatch(encoded):
        raise OfferError()
    try:
        value = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise OfferError() from None
    keys = {"session", "addresses", "port", "certificate", "secret", "expires"}
    if type(value) is not dict or set(value) != (keys | {"stream"} if profiled else keys):
        raise OfferError()
    session, certificate, secret = value["session"], value["certificate"], value["secret"]
    if (type(session) is not str or not re.fullmatch(r"[a-f0-9]{32}", session)
            or type(certificate) is not str or not re.fullmatch(r"[a-f0-9]{64}", certificate)
            or type(secret) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{43}", secret)
            or len(base64.urlsafe_b64decode(secret + "=")) != 32):
        raise OfferError()
    addresses = value["addresses"]
    if (type(addresses) is not list or not 1 <= len(addresses) <= 8 or len(set(map(str, addresses))) != len(addresses)
            or not all(_private_ipv4(address) for address in addresses)):
        raise OfferError()
    port, expires = value["port"], value["expires"]
    if not _integer(port) or not _integer(expires) or not 1024 <= port <= 65535 or not now < expires <= now + MAX_LIFETIME:
        raise OfferError()
    if profiled:
        stream = value["stream"]
        if (type(stream) is not dict or set(stream) != {"resolution", "fps", "quality"}
                or stream["resolution"] not in ("720p", "1080p") or type(stream["resolution"]) is not str
                or not _integer(stream["fps"]) or stream["fps"] not in (15, 20, 30)
                or type(stream["quality"]) is not str or stream["quality"] not in ("standard", "high")):
            raise OfferError()
    return expires


def valid_package(value) -> bool:
    """An Android package name, the only app reference a phone screen invitation carries."""
    return type(value) is str and len(value) <= 200 and _PACKAGE.fullmatch(value) is not None


def _decode(invite, prefix):
    if type(invite) is not str or not 100 <= len(invite) <= MAX_INVITE or not invite.startswith(prefix):
        raise OfferError()
    encoded = invite[len(prefix):]
    if not _B64.fullmatch(encoded):
        raise OfferError()
    try:
        return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise OfferError() from None


def screen_invite(invite, now: int) -> int:
    """Validate a phone screen invitation (docs/PHONE_SCREEN.md) as the phone does; return its deadline.

    The camera's local trust fields, a required stream profile and `launch`: "" or
    one package name the phone opens through its own launch intent.
    """
    value = _decode(invite, SCREEN_PREFIX)
    keys = {"session", "addresses", "port", "certificate", "secret", "expires", "stream", "launch"}
    if type(value) is not dict or set(value) != keys:
        raise OfferError()
    session, certificate, secret = value["session"], value["certificate"], value["secret"]
    if (type(session) is not str or not re.fullmatch(r"[a-f0-9]{32}", session)
            or type(certificate) is not str or not re.fullmatch(r"[a-f0-9]{64}", certificate)
            or type(secret) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{43}", secret)
            or len(base64.urlsafe_b64decode(secret + "=")) != 32):
        raise OfferError()
    addresses = value["addresses"]
    if (type(addresses) is not list or not 1 <= len(addresses) <= 8 or len(set(map(str, addresses))) != len(addresses)
            or not all(_private_ipv4(address) for address in addresses)):
        raise OfferError()
    port, expires = value["port"], value["expires"]
    if not _integer(port) or not _integer(expires) or not 1024 <= port <= 65535 or not now < expires <= now + MAX_LIFETIME:
        raise OfferError()
    stream = value["stream"]
    if (type(stream) is not dict or set(stream) != {"resolution", "fps", "quality"}
            or type(stream["resolution"]) is not str or stream["resolution"] not in ("720p", "1080p")
            or not _integer(stream["fps"]) or stream["fps"] not in (15, 20, 30)
            or type(stream["quality"]) is not str or stream["quality"] not in ("standard", "high")):
        raise OfferError()
    if value["launch"] != "" and not valid_package(value["launch"]):
        raise OfferError()
    return expires


def screen_invite_code(value: dict, now: int | None = None) -> str:
    """Encode a phone screen invitation; the same text is shown as the QR fallback."""
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    invite = SCREEN_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")
    screen_invite(invite, int(time.time()) if now is None else now)
    return invite


FILE_PREFIX = "orion-file:1:"
FILE_REQUEST = "file.lan.request"
SESSION_REFUSE = "session.refuse"
MAX_FILE_BYTES = 1 << 40
FILE_MODES = ("get", "put")
REFUSALS = ("unreachable", "storage", "busy")
_RESERVED = {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}


def valid_filename(name) -> bool:
    """A file name both platforms can create as is: at most 255 UTF-8 bytes, no path or reserved name."""
    if type(name) is not str or not name or name in (".", "..") or name[-1] in " .":
        return False
    if any(ord(c) < 32 or c in '/\\:*?"<>|' or 0xD800 <= ord(c) <= 0xDFFF for c in name):
        return False
    return len(name.encode("utf-8")) <= 255 and name.split(".", 1)[0].upper() not in _RESERVED


def _size(value) -> bool:
    return _integer(value) and 0 <= value <= MAX_FILE_BYTES


def read_file_invite(invite, now: int) -> dict:
    """Validate a local file invitation (docs/LAN_FILES.md); return its fields.

    The camera's local trust fields plus what the receiver verifies: `mode` "get"
    (the computer serves the file) or "put" (a phone uploads to the computer),
    the file's name, exact size and SHA-256, and for "put" the phone's request ID.
    """
    value = _decode(invite, FILE_PREFIX)
    keys = {"session", "addresses", "port", "certificate", "secret", "expires", "mode", "name", "size", "sha256", "request"}
    if type(value) is not dict or set(value) != keys:
        raise OfferError()
    session, certificate, secret = value["session"], value["certificate"], value["secret"]
    if (type(session) is not str or not _ID.fullmatch(session)
            or type(certificate) is not str or not re.fullmatch(r"[a-f0-9]{64}", certificate)
            or type(secret) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{43}", secret)
            or len(base64.urlsafe_b64decode(secret + "=")) != 32):
        raise OfferError()
    addresses = value["addresses"]
    if (type(addresses) is not list or not 1 <= len(addresses) <= 8 or len(set(map(str, addresses))) != len(addresses)
            or not all(_private_ipv4(address) for address in addresses)):
        raise OfferError()
    port, expires = value["port"], value["expires"]
    if not _integer(port) or not _integer(expires) or not 1024 <= port <= 65535 or not now < expires <= now + MAX_LIFETIME:
        raise OfferError()
    mode, request = value["mode"], value["request"]
    if (type(mode) is not str or mode not in FILE_MODES or not valid_filename(value["name"]) or not _size(value["size"])
            or type(value["sha256"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", value["sha256"])
            or type(request) is not str or (request != "" if mode == "get" else not _ID.fullmatch(request))):
        raise OfferError()
    return dict(value)


def file_invite(invite, now: int) -> int:
    return read_file_invite(invite, now)["expires"]


def file_invite_code(value: dict, now: int | None = None) -> str:
    """Encode a local file invitation; names stay UTF-8 so long names still fit."""
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")
    invite = FILE_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")
    file_invite(invite, int(time.time()) if now is None else now)
    return invite


def file_request(name, size, sha256, now: int | None = None) -> dict:
    """A phone asks a computer for an upload invitation ("put") for one file."""
    now = int(time.time()) if now is None else now
    return read_file_request({"type": FILE_REQUEST, "version": VERSION, "id": secrets.token_hex(16), "name": name,
                              "size": size, "sha256": sha256, "expires_at": now + 100}, now)


def read_file_request(payload, now: int | None = None) -> dict:
    now = int(time.time()) if now is None else now
    if (type(payload) is not dict or set(payload) != {"type", "version", "id", "name", "size", "sha256", "expires_at"}
            or payload["type"] != FILE_REQUEST or not _integer(payload["version"]) or payload["version"] != VERSION
            or type(payload["id"]) is not str or not _ID.fullmatch(payload["id"]) or not valid_filename(payload["name"])
            or not _size(payload["size"]) or type(payload["sha256"]) is not str
            or not re.fullmatch(r"[a-f0-9]{64}", payload["sha256"])
            or not _integer(payload["expires_at"]) or not now < payload["expires_at"] <= now + MAX_LIFETIME):
        raise OfferError()
    return dict(payload)


def refuse_payload(offer_id, reason) -> dict:
    """The receiver of a file offer (or request) cannot use it: the sender may fall back at once."""
    return read_refuse({"type": SESSION_REFUSE, "version": VERSION, "id": offer_id, "reason": reason})


def read_refuse(payload) -> dict:
    if (type(payload) is not dict or set(payload) != {"type", "version", "id", "reason"} or payload["type"] != SESSION_REFUSE
            or not _integer(payload["version"]) or payload["version"] != VERSION
            or type(payload["id"]) is not str or not _ID.fullmatch(payload["id"])
            or type(payload["reason"]) is not str or payload["reason"] not in REFUSALS):
        raise OfferError()
    return dict(payload)


# Each service maps to the parser of its own invitation format.
SERVICES = {"camera": camera_invite, "screen": screen_invite, "file": file_invite}


def read_offer(payload, now: int | None = None) -> dict:
    """Return the validated offer; raise OfferError for anything else."""
    now = int(time.time()) if now is None else now
    if type(payload) is not dict or set(payload) != {"type", "version", "id", "service", "expires_at", "invite"}:
        raise OfferError()
    if payload["type"] != SESSION_OFFER or not _integer(payload["version"]) or payload["version"] != VERSION:
        raise OfferError()
    offer_id, service, expires_at = payload["id"], payload["service"], payload["expires_at"]
    if type(offer_id) is not str or not _ID.fullmatch(offer_id) or type(service) is not str or service not in SERVICES:
        raise OfferError()
    if not _integer(expires_at) or not now < expires_at <= now + MAX_LIFETIME:
        raise OfferError()
    if SERVICES[service](payload["invite"], now) != expires_at:
        raise OfferError()
    return {"type": SESSION_OFFER, "version": VERSION, "id": offer_id, "service": service,
            "expires_at": expires_at, "invite": payload["invite"]}


def build_offer(service: str, invite: str, now: int | None = None) -> dict:
    """A fresh offer for a valid invitation; validated before it is sealed."""
    now = int(time.time()) if now is None else now
    if type(service) is not str or service not in SERVICES:
        raise OfferError("This session cannot be offered to a phone.")
    expires_at = SERVICES[service](invite, now)
    return read_offer({"type": SESSION_OFFER, "version": VERSION, "id": secrets.token_hex(16), "service": service,
                       "expires_at": expires_at, "invite": invite}, now)


def close_payload(offer_id) -> dict:
    """The phone may drop the prompt for this offer: it was answered, cancelled or expired."""
    if type(offer_id) is not str or not _ID.fullmatch(offer_id):
        raise OfferError()
    return {"type": SESSION_CLOSE, "version": VERSION, "id": offer_id}


def read_close(payload) -> str:
    if (type(payload) is not dict or set(payload) != {"type", "version", "id"} or payload["type"] != SESSION_CLOSE
            or not _integer(payload["version"]) or payload["version"] != VERSION
            or type(payload["id"]) is not str or not _ID.fullmatch(payload["id"])):
        raise OfferError()
    return payload["id"]


def watch_offer(waiting, close, *, interval=0.5, limit=MAX_LIFETIME + 5, sleep=time.sleep):
    """Call `close()` once `waiting()` turns false (answered, cancelled or expired).

    Runs on its own daemon thread; `close` errors are ignored because the phone's
    own expiry timer still removes the prompt."""
    import threading

    def run():
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            try:
                if not waiting():
                    break
            except Exception:
                break
            sleep(interval)
        try:
            close()
        except Exception:
            pass
    thread = threading.Thread(target=run, name="orion-offer-close", daemon=True)
    thread.start()
    return thread


class OfferReceipts:
    """Show each offer at most once. Bounded memory; expired entries drop out."""

    def __init__(self, limit=64):
        self.limit, self.seen = limit, {}

    def claim(self, offer: dict, now: int | None = None) -> bool:
        now = int(time.time()) if now is None else now
        self.seen = {key: expiry for key, expiry in self.seen.items() if expiry > now}
        if offer["id"] in self.seen or len(self.seen) >= self.limit:
            return False
        self.seen[offer["id"]] = offer["expires_at"]
        return True
