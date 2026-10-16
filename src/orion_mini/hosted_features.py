# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hosted feature payloads carried inside sealed envelopes.

Exact-shape validation for each decrypted payload. Decryption proves origin
from a current roster member; it does not authorize an effect by itself.

Data effects: clipboard text, notification display/dismissal, explicitly
saved file offers, and the phone's texts and call state shown on the computer.

Phone actions (owner decisions 2026-10-14, reversing the earlier provisional
"no SMS or calls", and then the first draft's root-only rule): any approved
computer on the roster, root or not, may ask a phone to reply in a one-to-one
text conversation, start a new text to one number, answer or decline a ringing
call, dial an ordinary number, search contacts and list recent calls. Each is a
separate event type with an exact shape and fixed limits.

A computer announces itself to a phone with `phone.subscribe` (its display
name) after the phone advertises its capabilities. The phone sends texts and
call state to each current, recently subscribed roster member, and acts only
for them, only while its owner's Texts and calls switch is on and only with the
matching Android permission. The roster has no device kinds, so any approved
device that subscribes is treated as a computer. Each sealed event has one
recipient: live updates are copied to every subscriber, a full conversation
sync goes only to the computer that asked, and contact results, call history
and refusals go only to the requester.

Calls are first come, first served: the phone carries out the first answer or
decline for a ringing call, tells every computer with `call.handled` (who and
what) and answers later attempts with `call.refused`. A dial is refused while
the phone is on a call or already placing one.

The computer accepts phone data only from an approved member that advertised
the matching capability, and contact results, call history or refusals only in
answer to its own recent request (kept in memory, never stored). MMS pictures,
group replies and call audio are not defined. These paths still need
physical-device acceptance.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re

from .hosted_crypto import canonical

CLIPBOARD_TEXT = "clipboard.text"
NOTIFICATION_UPSERT = "notification.upsert"
NOTIFICATION_REMOVE = "notification.remove"
NOTIFICATION_DISMISS = "notification.dismiss"
FILE_OFFER = "file.encrypted"
MAX_CLIPBOARD_TEXT_BYTES = 16_384
_KEY = re.compile(r"[A-Za-z0-9._:|/+=@-]{1,256}")

# Phone data, phone -> computer. Each type needs the capability named here.
PHOTOS_ITEM = "photos.item"
PHOTOS_SYNC = "photos.sync"
PHOTO_REQUEST = "photo.request"
PHOTO_ORIGINAL = "photo.original"
PHONE_CAPABILITIES = "phone.capabilities"
SMS_THREAD = "sms.thread"
SMS_MESSAGES = "sms.messages"
SMS_REMOVE = "sms.remove"
SMS_INDEX = "sms.index"
CALL_STATE = "call.state"
CALL_HANDLED = "call.handled"  # First answer/decline won; sent to every subscribed computer.
CALL_REFUSED = "call.refused"  # A later answer/decline, or a dial while busy; requester only.
CONTACTS_RESULTS = "contacts.results"
CALLS_LOG = "calls.log"
DATA_CAPABILITY = {PHOTOS_ITEM: "photos", PHOTOS_SYNC: "photos", SMS_THREAD: "sms", SMS_MESSAGES: "sms", SMS_REMOVE: "sms", SMS_INDEX: "sms",
                   CALL_STATE: "calls", CALL_HANDLED: "calls", CONTACTS_RESULTS: "contacts", CALLS_LOG: "call-log"}
PHONE_DATA = frozenset({PHONE_CAPABILITIES, CALL_REFUSED, *DATA_CAPABILITY})

# Computer -> phone: "send me your texts and calls"; the phone keeps it ten minutes.
PHONE_SUBSCRIBE = "phone.subscribe"
MAX_LABEL = 40
_REFUSED_REQUESTS = {"answer": "call.command", "reject": "call.command", "dial": "call.dial"}
_REFUSED_REASONS = ("handled", "not_ringing", "in_call", "dialing")

# Phone actions, any subscribed computer -> phone. The phone checks the same table.
SMS_SYNC = "sms.sync"
SMS_OPEN = "sms.open"
SMS_SEND = "sms.send"
SMS_COMPOSE = "sms.compose"
CALL_COMMAND = "call.command"
CALL_DIAL = "call.dial"
CONTACTS_SEARCH = "contacts.search"
CALLS_LOG_REQUEST = "calls.log.request"
COMMAND_CAPABILITY = {PHOTO_REQUEST: "photos", SMS_SYNC: "sms", SMS_OPEN: "sms", SMS_SEND: "sms", SMS_COMPOSE: "sms",
                      CALL_COMMAND: "call-control", CALL_DIAL: "call-dial", CONTACTS_SEARCH: "contacts",
                      CALLS_LOG_REQUEST: "call-log"}
# Private answers accepted only after this computer asked for them.
ANSWERS = {CONTACTS_RESULTS: CONTACTS_SEARCH, CALLS_LOG: CALLS_LOG_REQUEST}
# "files" is the existing encrypted file offer; the rest gate the types above.
PHONE_CAPABILITY_NAMES = ("files", "photos", "sms", "calls", "call-control", "call-dial", "contacts", "call-log")
MAX_SMS_TEXT = 4096
MAX_PHONE_PAYLOAD_BYTES = 20_000  # Below the sealed 24,000-byte plaintext limit.
_MAX_ID = (1 << 53) - 1
_MAX_TIMESTAMP = 253402300799999
_DIAL = re.compile(r"[0-9+() .-]{1,40}")  # No * or #: MMI codes can change call forwarding.
_CALL_STATES = ("ringing", "active", "missed", "ended")
_CALL_TYPES = ("incoming", "outgoing", "missed", "rejected", "other")


class FeatureError(ValueError):
    def __init__(self):
        super().__init__("Unsupported hosted event.")


def _text(value, limit, *, empty=True):
    if type(value) is not str or len(value) > limit or (not empty and not value):
        raise FeatureError()
    if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise FeatureError()
    return value


def clipboard_payload(data: bytes) -> dict:
    if type(data) is not bytes or not 0 < len(data) <= MAX_CLIPBOARD_TEXT_BYTES:
        raise FeatureError()
    try:
        text = data.decode("utf-8")
    except UnicodeError:
        raise FeatureError() from None
    return {"type": CLIPBOARD_TEXT, "text": text, "sha256": hashlib.sha256(data).hexdigest()}


def read_clipboard(payload) -> bytes:
    if type(payload) is not dict or set(payload) != {"type", "text", "sha256"} or payload["type"] != CLIPBOARD_TEXT:
        raise FeatureError()
    data = _text(payload["text"], MAX_CLIPBOARD_TEXT_BYTES, empty=False).encode("utf-8")
    if len(data) > MAX_CLIPBOARD_TEXT_BYTES or payload["sha256"] != hashlib.sha256(data).hexdigest():
        raise FeatureError()
    return data


def read_notification(payload) -> tuple[str, dict | str]:
    """Return ("upsert", row) or ("remove", key) for a phone notification."""
    if type(payload) is not dict or type(payload.get("type")) is not str:
        raise FeatureError()
    if payload["type"] == NOTIFICATION_REMOVE:
        if set(payload) != {"type", "key"} or type(payload["key"]) is not str or not _KEY.fullmatch(payload["key"]):
            raise FeatureError()
        return "remove", payload["key"]
    if payload["type"] != NOTIFICATION_UPSERT or set(payload) != {"type", "notification"}:
        raise FeatureError()
    item = payload["notification"]
    if type(item) is not dict or set(item) != {"key", "app", "title", "text", "timestamp"}:
        raise FeatureError()
    if type(item["key"]) is not str or not _KEY.fullmatch(item["key"]):
        raise FeatureError()
    if type(item["timestamp"]) is not int or not 0 <= item["timestamp"] <= 253402300799999:
        raise FeatureError()
    return "upsert", {"key": item["key"], "app": _text(item["app"], 120), "title": _text(item["title"], 512),
                      "text": _text(item["text"], 4096), "timestamp": item["timestamp"]}


def dismiss_payload(key: str) -> dict:
    if type(key) is not str or not _KEY.fullmatch(key):
        raise FeatureError()
    return {"type": NOTIFICATION_DISMISS, "key": key}


def _exact(payload, kind_, keys):
    if type(payload) is not dict or payload.get("type") != kind_ or set(payload) != {"type", *keys}:
        raise FeatureError()
    return payload


def _integer(value, low=0, high=_MAX_ID):
    if type(value) is not int or not low <= value <= high:
        raise FeatureError()
    return value


def _address(value, limit=120):
    """A phone number or sender name: never empty, no control characters."""
    text = _text(value, limit, empty=False)
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise FeatureError()
    return text


def _addresses(value, high=10, low=0):
    if type(value) is not list or not low <= len(value) <= high:
        raise FeatureError()
    return [_address(item) for item in value]


def _message(value) -> dict:
    keys = {"id", "addresses", "body", "timestamp", "direction", "subscription"}
    if type(value) is not dict or set(value) != keys or value["direction"] not in ("incoming", "outgoing"):
        raise FeatureError()
    return {"id": _integer(value["id"]), "addresses": _addresses(value["addresses"]),
            "body": _text(value["body"], MAX_SMS_TEXT), "timestamp": _integer(value["timestamp"], high=_MAX_TIMESTAMP),
            "direction": value["direction"], "subscription": _integer(value["subscription"], -1, 2**31 - 1)}


def _bounded_jpeg(image: bytes) -> bool:
    """Read the JPEG frame size without decoding or allocating a pixel buffer."""
    offset = 2
    while offset + 4 <= len(image):
        if image[offset] != 255:
            return False
        marker = image[offset + 1]
        offset += 2
        length = int.from_bytes(image[offset:offset + 2], "big")
        if length < 2 or offset + length > len(image):
            return False
        if marker in (0xC0, 0xC1, 0xC2):
            if length < 8:
                return False
            height = int.from_bytes(image[offset + 3:offset + 5], "big")
            width = int.from_bytes(image[offset + 5:offset + 7], "big")
            return 0 < width <= 384 and 0 < height <= 384
        offset += length
    return False


def read_phone_data(payload) -> tuple[str, dict]:
    """Return (type, body) for phone data; body uses the Link phone-feature shape."""
    kind_ = kind(payload)
    if kind_ == PHONE_CAPABILITIES:
        _exact(payload, kind_, {"capabilities"})
        names = payload["capabilities"]
        if (type(names) is not list or len(names) > len(PHONE_CAPABILITY_NAMES) or len(set(map(str, names))) != len(names)
                or any(type(name) is not str or name not in PHONE_CAPABILITY_NAMES for name in names)):
            raise FeatureError()
        return kind_, {"capabilities": list(names)}
    if kind_ == PHOTOS_ITEM:
        _exact(payload, kind_, {"id", "name", "timestamp", "preview"})
        photo_id = _text(payload["id"], 16, empty=False)
        if not re.fullmatch(r"[1-9][0-9]{0,15}", photo_id) or int(photo_id) > _MAX_ID:
            raise FeatureError()
        preview = _text(payload["preview"], 16_023, empty=False)
        if not preview.startswith("data:image/jpeg;base64,"):
            raise FeatureError()
        try:
            image = base64.b64decode(preview.split(",", 1)[1], validate=True)
        except (ValueError, binascii.Error):
            raise FeatureError() from None
        if not 4 <= len(image) <= 12_000 or not image.startswith(b"\xff\xd8") or not image.endswith(b"\xff\xd9") or not _bounded_jpeg(image):
            raise FeatureError()
        return kind_, {"photos": [{"id": photo_id, "name": _text(payload["name"], 180, empty=False),
            "timestamp": _integer(payload["timestamp"], high=_MAX_TIMESTAMP), "preview": preview,
            "thumbnail": {"sha256": hashlib.sha256(image).hexdigest()}}]}
    if kind_ == PHOTOS_SYNC:
        _exact(payload, kind_, {"ids"})
        ids = payload["ids"]
        if (type(ids) is not list or len(ids) > 100 or any(type(i) is not str or not re.fullmatch(r"[1-9][0-9]{0,15}", i)
                or int(i) > _MAX_ID for i in ids) or len(set(ids)) != len(ids)):
            raise FeatureError()
        return kind_, {"ids": ids}
    if kind_ == SMS_THREAD:
        _exact(payload, kind_, {"thread", "recipients", "message"})
        return kind_, {"thread": _integer(payload["thread"]), "recipients": _addresses(payload["recipients"]),
                       "message": _message(payload["message"])}
    if kind_ == SMS_MESSAGES:
        _exact(payload, kind_, {"thread", "messages"})
        if type(payload["messages"]) is not list or not 1 <= len(payload["messages"]) <= 10:
            raise FeatureError()
        return kind_, {"thread": _integer(payload["thread"]), "messages": [_message(m) for m in payload["messages"]]}
    if kind_ == SMS_REMOVE:
        _exact(payload, kind_, {"thread"})
        return kind_, {"thread": _integer(payload["thread"])}
    if kind_ == SMS_INDEX:
        _exact(payload, kind_, {"thread", "ids"})
        if type(payload["ids"]) is not list or len(payload["ids"]) > 1000:
            raise FeatureError()
        return kind_, {"thread": _integer(payload["thread"]), "ids": [_integer(item) for item in payload["ids"]]}
    if kind_ == CALL_STATE:
        _exact(payload, kind_, {"state", "number", "name"})
        if payload["state"] not in _CALL_STATES:
            raise FeatureError()
        number = _text(payload["number"], 120)  # Empty without call-log access.
        if number:
            _address(number)
        return kind_, {"state": payload["state"], "number": number, "name": _text(payload["name"], 240)}
    if kind_ == CALL_HANDLED:
        _exact(payload, kind_, {"operation", "by"})
        if payload["operation"] not in ("answer", "reject"):
            raise FeatureError()
        return kind_, {"operation": payload["operation"], "by": _label(payload["by"], empty=True)}
    if kind_ == CALL_REFUSED:
        _exact(payload, kind_, {"request", "reason", "handled", "by"})
        if (payload["request"] not in _REFUSED_REQUESTS or payload["reason"] not in _REFUSED_REASONS
                or payload["handled"] not in ("answer", "reject", "")
                or (payload["reason"] == "handled") != (payload["handled"] != "")
                or (payload["request"] == "dial") != (payload["reason"] in ("in_call", "dialing"))):
            raise FeatureError()
        return kind_, {"request": payload["request"], "reason": payload["reason"], "handled": payload["handled"],
                       "by": _label(payload["by"], empty=True)}
    if kind_ == CONTACTS_RESULTS:
        _exact(payload, kind_, {"query", "contacts"})
        contacts = payload["contacts"]
        if type(contacts) is not list or len(contacts) > 20:
            raise FeatureError()
        rows = []
        for contact in contacts:
            if (type(contact) is not dict or set(contact) != {"name", "numbers"} or type(contact["numbers"]) is not list
                    or len(contact["numbers"]) > 5):
                raise FeatureError()
            rows.append({"name": _text(contact["name"], 120), "numbers": [_address(n, 40) for n in contact["numbers"]]})
        return kind_, {"query": _text(payload["query"], 64), "contacts": rows}
    if kind_ == CALLS_LOG:
        _exact(payload, kind_, {"calls"})
        calls = payload["calls"]
        if type(calls) is not list or len(calls) > 50:
            raise FeatureError()
        rows = []
        for call in calls:
            if (type(call) is not dict or set(call) != {"number", "name", "timestamp", "duration", "type"}
                    or call["type"] not in _CALL_TYPES):
                raise FeatureError()
            rows.append({"number": _text(call["number"], 120), "name": _text(call["name"], 240),
                         "timestamp": _integer(call["timestamp"], high=_MAX_TIMESTAMP),
                         "duration": _integer(call["duration"], high=10**9), "type": call["type"]})
        return kind_, {"calls": rows}
    raise FeatureError()


def _label(value, *, empty=False):
    """A computer's display name as shown to other computers: one short printable line."""
    text = _text(value, MAX_LABEL, empty=empty)
    if any(ord(c) < 32 or ord(c) == 127 for c in text) or (text and not text.strip()):
        raise FeatureError()
    return text


def refused_request(body) -> str:
    """The phone action type a `call.refused` answers, for the request window."""
    return _REFUSED_REQUESTS[body["request"]]


def subscribe_payload(label) -> dict:
    """Ask a phone for its texts and calls, naming this computer to the others."""
    if type(label) is not str:
        raise FeatureError()
    clean = "".join(c for c in label if ord(c) >= 32 and ord(c) != 127 and not 0xD800 <= ord(c) <= 0xDFFF).strip()
    return {"type": PHONE_SUBSCRIBE, "label": _label(clean[:MAX_LABEL].strip() or "Computer")}


def read_subscribe(payload) -> str:
    _exact(payload, PHONE_SUBSCRIBE, {"label"})
    return _label(payload["label"])


def _sms_text(value):
    text = _text(value, MAX_SMS_TEXT, empty=False)
    if not text.strip():
        raise FeatureError()
    return text


_COMMAND_KEYS = {PHOTO_REQUEST: {"id"}, SMS_SYNC: set(), CALLS_LOG_REQUEST: set(), SMS_OPEN: {"thread"}, SMS_SEND: {"thread", "text"},
                 SMS_COMPOSE: {"addresses", "text"}, CALL_COMMAND: {"operation"}, CALL_DIAL: {"number"},
                 CONTACTS_SEARCH: {"query"}}


def phone_command(kind_: str, body) -> dict:
    """Build an exact phone action payload from the computer's own request."""
    if kind_ not in _COMMAND_KEYS or type(body) is not dict or set(body) != _COMMAND_KEYS[kind_]:
        raise FeatureError()
    return read_phone_command({"type": kind_, **body})


def read_phone_command(payload) -> dict:
    """Exact shape of a phone action; the Android phone applies the same rules."""
    kind_ = kind(payload)
    if kind_ not in _COMMAND_KEYS:
        raise FeatureError()
    _exact(payload, kind_, _COMMAND_KEYS[kind_])
    if kind_ == PHOTO_REQUEST:
        photo_id = _text(payload["id"], 16, empty=False)
        if not re.fullmatch(r"[1-9][0-9]{0,15}", photo_id) or int(photo_id) > _MAX_ID:
            raise FeatureError()
        return {"type": kind_, "id": photo_id}
    if kind_ in (SMS_SYNC, CALLS_LOG_REQUEST):
        return {"type": kind_}
    if kind_ == SMS_OPEN:
        return {"type": kind_, "thread": _integer(payload["thread"])}
    if kind_ == CALL_COMMAND:
        if payload["operation"] not in ("answer", "reject"):
            raise FeatureError()
        return {"type": kind_, "operation": payload["operation"]}
    if kind_ == CALL_DIAL:
        number = payload["number"]
        if type(number) is not str or not _DIAL.fullmatch(number) or not any(c.isdigit() for c in number):
            raise FeatureError()
        return {"type": kind_, "number": number}
    if kind_ == CONTACTS_SEARCH:
        query = _text(payload["query"], 64, empty=False)
        if not query.strip() or any(ord(c) < 32 for c in query):
            raise FeatureError()
        return {"type": kind_, "query": query}
    if kind_ == SMS_SEND:
        result = {"type": kind_, "thread": _integer(payload["thread"]), "text": _sms_text(payload["text"])}
    else:
        result = {"type": kind_, "addresses": _addresses(payload["addresses"], 1, 1), "text": _sms_text(payload["text"])}
    # Texts are the only variable-size actions; each must fit in one sealed event.
    if len(canonical(result)) > MAX_PHONE_PAYLOAD_BYTES:
        raise FeatureError()
    return result


def kind(payload) -> str:
    if type(payload) is not dict or type(payload.get("type")) is not str:
        raise FeatureError()
    return payload["type"]
