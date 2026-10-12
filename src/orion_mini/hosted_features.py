# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hosted feature payloads carried inside sealed envelopes.

Exact-shape validation for each decrypted payload. Decryption proves origin
from a current roster member; it does not authorize an effect by itself.
Only data effects exist here: clipboard text, notification display/dismissal
and explicitly saved file offers. No SMS, call or other phone action is
defined (provisional decision: no SMS or calls).
"""
from __future__ import annotations

import hashlib
import re

CLIPBOARD_TEXT = "clipboard.text"
NOTIFICATION_UPSERT = "notification.upsert"
NOTIFICATION_REMOVE = "notification.remove"
NOTIFICATION_DISMISS = "notification.dismiss"
FILE_OFFER = "file.encrypted"
MAX_CLIPBOARD_TEXT_BYTES = 16_384
_KEY = re.compile(r"[A-Za-z0-9._:|/+=@-]{1,256}")


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


def kind(payload) -> str:
    if type(payload) is not dict or type(payload.get("type")) is not str:
        raise FeatureError()
    return payload["type"]
