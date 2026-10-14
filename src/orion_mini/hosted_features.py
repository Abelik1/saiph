# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hosted feature payloads carried inside sealed envelopes.

Exact-shape validation for each decrypted payload. Decryption proves origin
from a current roster member; it does not authorize an effect by itself.

Data effects: clipboard text, notification display/dismissal, explicitly
saved file offers, and the phone's texts and call state shown on the computer.

Phone actions (owner decision 2026-10-14, reversing the earlier provisional
"no SMS or calls"): the root computer may ask a phone to reply in a one-to-one
text conversation, start a new text to one number, answer or decline a ringing
call, dial an ordinary number, search contacts and list recent calls. Each is a
separate event type with an exact shape and fixed limits. Only the root may
issue them; the phone refuses them unless its owner turned on texts and calls
for Hosted and granted the matching Android permission. The computer accepts
phone data only from an approved non-root member that advertised the matching
capability, and contact results or call history only in answer to its own
recent request (kept in memory, never stored). MMS pictures, group replies and
call audio are not defined. These paths still need physical-device acceptance.
"""
from __future__ import annotations

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
PHONE_CAPABILITIES = "phone.capabilities"
SMS_THREAD = "sms.thread"
SMS_MESSAGES = "sms.messages"
SMS_REMOVE = "sms.remove"
SMS_INDEX = "sms.index"
CALL_STATE = "call.state"
CONTACTS_RESULTS = "contacts.results"
CALLS_LOG = "calls.log"
DATA_CAPABILITY = {SMS_THREAD: "sms", SMS_MESSAGES: "sms", SMS_REMOVE: "sms", SMS_INDEX: "sms",
                   CALL_STATE: "calls", CONTACTS_RESULTS: "contacts", CALLS_LOG: "call-log"}
PHONE_DATA = frozenset({PHONE_CAPABILITIES, *DATA_CAPABILITY})

# Phone actions, root computer -> phone. The phone checks the same table.
SMS_SYNC = "sms.sync"
SMS_OPEN = "sms.open"
SMS_SEND = "sms.send"
SMS_COMPOSE = "sms.compose"
CALL_COMMAND = "call.command"
CALL_DIAL = "call.dial"
CONTACTS_SEARCH = "contacts.search"
CALLS_LOG_REQUEST = "calls.log.request"
COMMAND_CAPABILITY = {SMS_SYNC: "sms", SMS_OPEN: "sms", SMS_SEND: "sms", SMS_COMPOSE: "sms",
                      CALL_COMMAND: "call-control", CALL_DIAL: "call-dial", CONTACTS_SEARCH: "contacts",
                      CALLS_LOG_REQUEST: "call-log"}
# Private answers accepted only after this computer asked for them.
ANSWERS = {CONTACTS_RESULTS: CONTACTS_SEARCH, CALLS_LOG: CALLS_LOG_REQUEST}
# "files" is the existing encrypted file offer; the rest gate the types above.
PHONE_CAPABILITY_NAMES = ("files", "sms", "calls", "call-control", "call-dial", "contacts", "call-log")
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


def _sms_text(value):
    text = _text(value, MAX_SMS_TEXT, empty=False)
    if not text.strip():
        raise FeatureError()
    return text


_COMMAND_KEYS = {SMS_SYNC: set(), CALLS_LOG_REQUEST: set(), SMS_OPEN: {"thread"}, SMS_SEND: {"thread", "text"},
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
