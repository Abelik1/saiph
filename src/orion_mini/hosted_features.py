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
answer to its own recent request (kept in memory, never stored).

Feature parity with a self-hosted Hub (docs/PHONE_LINK_PARITY.md, "Saiph Cloud
feature parity"): notification buttons and inline replies, MMS pictures and
group replies are separate event types, gated by names the phone lists in its
own `phone.features` event (never in `phone.capabilities`, which older desktops
check name by name). MMS pictures travel as sealed attachments only when this
computer asks for one. Call audio is not defined. These paths still need
physical-device acceptance.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re

from .hosted_crypto import canonical
from . import phone_status
from .phone_status import (  # Status and quick actions: one codec for the Hub and Saiph Cloud.
    CONTROL_COMMAND, CONTROL_NAMES, MEDIA_COMMAND, MEDIA_STATE, PHONE_DND, PHONE_HOTSPOT, PHONE_MOBILE_DATA, PHONE_RING,
    PHONE_RINGER, PHONE_STATUS, STATUS_REQUEST, WALLPAPER_REQUEST, ProtocolError,
)

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
SMS_ATTACHMENTS = "sms.attachments"  # MMS parts by name, the Hub's shape; bytes only on request.
DATA_CAPABILITY = {PHOTOS_ITEM: "photos", PHOTOS_SYNC: "photos", SMS_THREAD: "sms", SMS_MESSAGES: "sms", SMS_REMOVE: "sms", SMS_INDEX: "sms",
                   CALL_STATE: "calls", CALL_HANDLED: "calls", CONTACTS_RESULTS: "contacts", CALLS_LOG: "call-log",
                   SMS_ATTACHMENTS: "sms-mms"}
# Status and quick controls (Phone Link's header and quick actions) use the shared
# codec in phone_status.py; the phone lists the controls it accepts inside
# phone.status, never in phone.capabilities.
PHONE_WALLPAPER = phone_status.PHONE_WALLPAPER  # Answers this computer's own wallpaper request only.
STATUS_DATA = frozenset({PHONE_STATUS, MEDIA_STATE, phone_status.PHONE_SIGNAL, PHONE_WALLPAPER, phone_status.PHONE_RING_STATE})
PHONE_DATA = frozenset({PHONE_CAPABILITIES, CALL_REFUSED, *DATA_CAPABILITY, *STATUS_DATA})

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
SMS_ATTACHMENT_REQUEST = "sms.attachment.request"  # One MMS part; answered with SMS_ATTACHMENT_ORIGINAL.
SMS_ATTACHMENT_ORIGINAL = "sms.attachment.original"  # Phone -> the asking computer: sealed attachment.
COMMAND_CAPABILITY = {PHOTO_REQUEST: "photos", SMS_SYNC: "sms", SMS_OPEN: "sms", SMS_SEND: "sms", SMS_COMPOSE: "sms",
                      CALL_COMMAND: "call-control", CALL_DIAL: "call-dial", CONTACTS_SEARCH: "contacts",
                      CALLS_LOG_REQUEST: "call-log", SMS_ATTACHMENT_REQUEST: "sms-mms", **CONTROL_COMMAND}
# Private answers accepted only after this computer asked for them.
ANSWERS = {CONTACTS_RESULTS: CONTACTS_SEARCH, CALLS_LOG: CALLS_LOG_REQUEST, PHONE_WALLPAPER: WALLPAPER_REQUEST}
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


# Notification buttons and replies (feature "notification-actions"). The phone
# sends `notification.actions` just before the matching `notification.upsert`;
# `timestamp` ties them together, so actions of an older post are never shown.
NOTIFICATION_ACTIONS = "notification.actions"  # Phone -> every approved computer.
NOTIFICATION_ACTION = "notification.action"  # Computer -> phone: press one of its buttons.
NOTIFICATION_REPLY = "notification.reply"  # Computer -> phone: inline reply.
NOTIFICATION_OPEN = "notification.open"  # Computer -> phone: open it on the phone.
NOTIFICATION_COMMANDS = {NOTIFICATION_ACTION: {"key", "index"}, NOTIFICATION_REPLY: {"key", "reply_key", "text"},
                         NOTIFICATION_OPEN: {"key"}}
MAX_NOTIFICATION_ACTIONS = 10
MAX_REPLY_TEXT = 4096


def _key(value):
    if type(value) is not str or not _KEY.fullmatch(value):
        raise FeatureError()
    return value


def _reply_key(value, *, empty):
    text = _text(value, 240, empty=empty)
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise FeatureError()
    return text


def read_notification_actions(payload) -> dict:
    """Buttons (index and label) and the inline-reply key ("" when none) of one notification."""
    _exact(payload, NOTIFICATION_ACTIONS, {"key", "timestamp", "actions", "reply_key"})
    actions = payload["actions"]
    if type(actions) is not list or len(actions) > MAX_NOTIFICATION_ACTIONS:
        raise FeatureError()
    rows = []
    for action in actions:
        if type(action) is not dict or set(action) != {"index", "label"}:
            raise FeatureError()
        rows.append({"index": _integer(action["index"], 0, 99), "label": _text(action["label"], 120)})
    if len({row["index"] for row in rows}) != len(rows):
        raise FeatureError()
    return {"key": _key(payload["key"]), "timestamp": _integer(payload["timestamp"], high=_MAX_TIMESTAMP),
            "actions": rows, "reply_key": _reply_key(payload["reply_key"], empty=True)}


def notification_command(kind_: str, body) -> dict:
    """Build an exact notification action from this computer's own request."""
    if kind_ not in NOTIFICATION_COMMANDS or type(body) is not dict:
        raise FeatureError()
    return read_notification_command({"type": kind_, **body})


def read_notification_command(payload) -> dict:
    kind_ = kind(payload)
    if kind_ not in NOTIFICATION_COMMANDS:
        raise FeatureError()
    _exact(payload, kind_, NOTIFICATION_COMMANDS[kind_])
    result = {"type": kind_, "key": _key(payload["key"])}
    if kind_ == NOTIFICATION_ACTION:
        result["index"] = _integer(payload["index"], 0, 99)
    elif kind_ == NOTIFICATION_REPLY:
        text = _text(payload["text"], MAX_REPLY_TEXT, empty=False)
        if not text.strip():
            raise FeatureError()
        result.update(reply_key=_reply_key(payload["reply_key"], empty=False), text=text)
        if len(canonical(result)) > MAX_PHONE_PAYLOAD_BYTES:
            raise FeatureError()
    return result


# Features a phone offers beyond `phone.capabilities`. Older desktops ignore this
# event type; names this desktop does not know are skipped, so later phones can
# add features here without another event.
PHONE_FEATURES = "phone.features"
FEATURE_NAMES = ("notification-actions", "sms-mms", "sms-group")
MAX_FEATURES = 32
_FEATURE = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")


def read_phone_features(payload) -> list:
    _exact(payload, PHONE_FEATURES, {"features"})
    names = payload["features"]
    if (type(names) is not list or len(names) > MAX_FEATURES
            or any(type(name) is not str or not _FEATURE.fullmatch(name) for name in names) or len(set(names)) != len(names)):
        raise FeatureError()
    return [name for name in names if name in FEATURE_NAMES]


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


_bounded_jpeg = phone_status.bounded_jpeg  # Photo thumbnails use the wallpaper's frame-size check.


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
    if kind_ == SMS_ATTACHMENTS:
        _exact(payload, kind_, {"thread", "message", "parts"})
        parts = payload["parts"]
        if type(parts) is not list or not 1 <= len(parts) <= 10:
            raise FeatureError()
        rows = []
        for part in parts:
            if type(part) is not dict or set(part) != {"part", "mime", "name"}:
                raise FeatureError()
            rows.append({"part": _integer(part["part"]), "mime": _address(part["mime"]), "name": _text(part["name"], 180)})
        if len({row["part"] for row in rows}) != len(rows):
            raise FeatureError()
        return kind_, {"thread": _integer(payload["thread"]), "message": _integer(payload["message"]), "parts": rows}
    if kind_ in phone_status.STATUS_EVENTS:
        body = {key: value for key, value in payload.items() if key != "type"}
        return kind_, _shared(phone_status.read_event, kind_, body, phone_status.HOSTED)
    if kind_ == PHONE_WALLPAPER:
        _exact(payload, kind_, {"preview"})
        return kind_, _shared(phone_status.read_wallpaper, {"preview": payload["preview"]})
    raise FeatureError()


def _shared(reader, *args):
    try:
        return reader(*args)
    except ProtocolError:
        raise FeatureError() from None


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
                 CONTACTS_SEARCH: {"query"}, STATUS_REQUEST: set(), PHONE_RING: set(), PHONE_RINGER: {"mode"},
                 PHONE_DND: {"active"}, MEDIA_COMMAND: {"source", "action"}, WALLPAPER_REQUEST: set(),
                 PHONE_HOTSPOT: set(), PHONE_MOBILE_DATA: {"allowed"}, SMS_ATTACHMENT_REQUEST: {"thread", "message", "part"},
                 phone_status.PHONE_RING_STOP: set()}  # Quick actions: phone_status.read_command.


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
    if kind_ in CONTROL_COMMAND:
        body = {key: value for key, value in payload.items() if key != "type"}
        return {"type": kind_, **_shared(phone_status.read_command, kind_, body, phone_status.HOSTED)}
    if kind_ in (SMS_SYNC, CALLS_LOG_REQUEST):
        return {"type": kind_}
    if kind_ == SMS_OPEN:
        return {"type": kind_, "thread": _integer(payload["thread"])}
    if kind_ == SMS_ATTACHMENT_REQUEST:
        return {"type": kind_, **{key: _integer(payload[key]) for key in ("thread", "message", "part")}}
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


# Device names. A computer introduces itself to the main computer, which shares
# the names its owner gave each approved device with member computers. Display
# only: names never authorize anything, and only the main computer's list counts.
DEVICE_HELLO = "device.hello"
DEVICE_LABELS = "device.labels"
DEVICE_KINDS = ("phone", "computer")
MAX_LABELS = 100


def device_hello(name) -> dict:
    return {"type": DEVICE_HELLO, "kind": "computer", "name": _label(_one_line(name) or "Computer")}


def read_device_hello(payload) -> dict:
    _exact(payload, DEVICE_HELLO, {"kind", "name"})
    if payload["kind"] != "computer":
        raise FeatureError()
    return {"kind": "computer", "name": _label(payload["name"])}


def device_labels(rows) -> dict:
    return read_device_labels({"type": DEVICE_LABELS, "labels": [
        {"id": row["id"], "label": _label(_one_line(row["label"]) or "Device"), "kind": row["kind"]} for row in rows][:MAX_LABELS]})


def read_device_labels(payload) -> dict:
    _exact(payload, DEVICE_LABELS, {"labels"})
    rows = payload["labels"]
    if type(rows) is not list or len(rows) > MAX_LABELS:
        raise FeatureError()
    result = []
    for row in rows:
        if (type(row) is not dict or set(row) != {"id", "label", "kind"} or type(row["id"]) is not str
                or not re.fullmatch(r"dev_[a-f0-9]{32}", row["id"]) or row["kind"] not in (*DEVICE_KINDS, None)):
            raise FeatureError()
        result.append({"id": row["id"], "label": _label(row["label"]), "kind": row["kind"]})
    if len({row["id"] for row in result}) != len(result):
        raise FeatureError()
    return {"type": DEVICE_LABELS, "labels": result}


def _one_line(value) -> str:
    text = value if type(value) is str else ""
    return "".join(ch for ch in text if ch.isprintable()).strip()[:MAX_LABEL].strip()


def kind(payload) -> str:
    if type(payload) is not dict or type(payload.get("type")) is not str:
        raise FeatureError()
    return payload["type"]


# Phone screen and app list (docs/PHONE_SCREEN.md). Kept outside `phone.capabilities`
# and PHONE_DATA: desktops released before this feature reject unknown capability
# names, so a phone advertises these in their own event, which older computers ignore.
SCREEN_CAPABILITIES = "screen.capabilities"  # Phone -> computer, with each capabilities heartbeat.
APPS_REQUEST = "apps.request"  # Computer -> phone: list launchable apps (capability "apps").
APPS_LIST = "apps.list"  # Phone -> the requesting computer only, in pages.
SCREEN_CAPABILITY_NAMES = ("screen", "apps")
MAX_APP_PAGES = 10


def read_screen_capabilities(payload) -> list:
    _exact(payload, SCREEN_CAPABILITIES, {"capabilities"})
    names = payload["capabilities"]
    if (type(names) is not list or len(names) > len(SCREEN_CAPABILITY_NAMES) or len(set(map(str, names))) != len(names)
            or any(type(name) is not str or name not in SCREEN_CAPABILITY_NAMES for name in names)):
        raise FeatureError()
    return list(names)


def apps_request_payload() -> dict:
    return {"type": APPS_REQUEST}


def read_apps_list(payload) -> tuple[int, int, list]:
    """(page, pages, apps) of one bounded page; names and package names only."""
    from .screen_session import read_apps
    _exact(payload, APPS_LIST, {"page", "pages", "apps"})
    pages = _integer(payload["pages"], 1, MAX_APP_PAGES)
    page = _integer(payload["page"], 0, pages - 1)
    if type(payload["apps"]) is not list or len(payload["apps"]) > 200:
        raise FeatureError()
    try:
        return page, pages, read_apps(payload["apps"])
    except ValueError:
        raise FeatureError() from None


# App icons for the Apps grid (docs/PHONE_SCREEN.md). New event types: computers and
# phones released before them ignore unknown types, and `apps.list` keeps its exact shape.
APPS_ICONS_REQUEST = "apps.icons.request"  # Computer -> phone: icons for up to 24 packages.
APPS_ICONS = "apps.icons"  # Phone -> the requesting computer only; several events per request.
MAX_ICON_ROWS = 24
MAX_ICON_BASE64 = 16_000  # 12,000 bytes, the per-icon bound in phone_app_library.py.


def _icon_package(value):
    from .session_offer import valid_package
    if not valid_package(value):
        raise FeatureError()
    return value


def apps_icons_request_payload(rows) -> dict:
    """`rows`: [{"package", "version"}], version being the cached one (0 when none)."""
    if type(rows) is not list or not 0 < len(rows) <= MAX_ICON_ROWS:
        raise FeatureError()
    result = []
    for row in rows:
        if type(row) is not dict or set(row) != {"package", "version"}:
            raise FeatureError()
        result.append({"package": _icon_package(row["package"]), "version": _integer(row["version"])})
    if len({row["package"] for row in result}) != len(result):
        raise FeatureError()
    return {"type": APPS_ICONS_REQUEST, "apps": result}


def read_apps_icons(payload) -> tuple[list, list]:
    """([(package, version, image bytes)], [packages with nothing new]) from one bounded event."""
    import base64
    import binascii
    from .phone_app_library import icon_format
    _exact(payload, APPS_ICONS, {"icons", "same"})
    icons, same = payload["icons"], payload["same"]
    if type(icons) is not list or type(same) is not list or len(icons) + len(same) > MAX_ICON_ROWS:
        raise FeatureError()
    result = []
    for row in icons:
        if type(row) is not dict or set(row) != {"package", "version", "data"} or type(row["data"]) is not str                 or not 0 < len(row["data"]) <= MAX_ICON_BASE64:
            raise FeatureError()
        try:
            data = base64.b64decode(row["data"], validate=True)
            icon_format(data)
        except (binascii.Error, ValueError):
            raise FeatureError() from None
        result.append((_icon_package(row["package"]), _integer(row["version"]), data))
    unchanged = [_icon_package(package) for package in same]
    packages = [row[0] for row in result] + unchanged
    if len(set(packages)) != len(packages):
        raise FeatureError()
    return result, unchanged
