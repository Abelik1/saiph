# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone status and quick actions, shared by the self-hosted Hub and Saiph Cloud.

One codec and one handler for both transports (docs/PHONE_LINK_PARITY.md,
"One phone feature layer"). A transport only frames and authenticates:

- Saiph Cloud (`hosted_features.py`) opens a sealed envelope, checks the sender
  is a current roster member, and passes the body (the payload without "type").
- The self-hosted Hub relays a signed event; a current Hub validates the same
  shapes in `hub/orion_hub/features.py`, an older Hub relays the new types
  unchecked, so the desktop validates every body here as well.

The shapes are exact: unknown or missing keys are refused. New behaviour arrives
as new event types, never as new fields, because older desktops and Hubs refuse
unknown fields in types they know. Two legacy differences remain and are named
by dialect: Hub phones already send media sessions with seek position and
volume, and accept seek/volume media commands; Cloud phones never did.

The quick actions a phone accepts are listed inside `phone.status` ("controls"),
never in a capabilities list: an older Cloud desktop rejects a capabilities event
with names it does not know. Desktops merge them into the phone's capabilities,
so the Phone page checks one list whichever transport carried them.
"""
from __future__ import annotations

import base64
import binascii
import time

LINK = "link"      # Self-hosted Hub events: {type, payload}.
HOSTED = "hosted"  # Saiph Cloud sealed payloads: {"type": ..., **body}.

# Phone -> computers.
PHONE_STATUS = "phone.status"
MEDIA_STATE = "media.state"
PHONE_WALLPAPER = "phone.wallpaper"  # An answer to one computer's own request, never broadcast.
# Wi-Fi and mobile bars, sent with every phone.status. Its own type, so older
# desktops (which ignore it) and older Hubs (which relay it unchecked) keep
# accepting phone.status unchanged.
PHONE_SIGNAL = "phone.signal"
# Find phone started or stopped, from wherever it was stopped. Released desktops ignore this
# type (Cloud) or never see it validated (an older Hub relays it), so phones send it to all.
PHONE_RING_STATE = "phone.ring.state"
STATUS_EVENTS = frozenset({PHONE_STATUS, MEDIA_STATE, PHONE_SIGNAL, PHONE_RING_STATE})

# Computer -> phone quick actions, each with the control the phone must list.
STATUS_REQUEST = "phone.status.request"
PHONE_RING = "phone.ring"
PHONE_RINGER = "phone.ringer"
PHONE_DND = "phone.dnd"
MEDIA_COMMAND = "media.command"
WALLPAPER_REQUEST = "phone.wallpaper.request"
PHONE_HOTSPOT = "phone.hotspot"
PHONE_MOBILE_DATA = "phone.mobile_data"
# Stop a Find phone ring from this computer. Offered only while the phone reports ringing,
# which only phones that also take this command do.
PHONE_RING_STOP = "phone.ring.stop"
CONTROL_COMMAND = {STATUS_REQUEST: "status", PHONE_RING: "ring", PHONE_RINGER: "ringer", PHONE_DND: "dnd",
                   MEDIA_COMMAND: "media", WALLPAPER_REQUEST: "wallpaper", PHONE_HOTSPOT: "hotspot",
                   PHONE_MOBILE_DATA: "mobile_data", PHONE_RING_STOP: "ring"}
CONTROL_NAMES = ("status", "ring", "ringer", "dnd", "media", "wallpaper", "hotspot", "mobile_data")
# What each transport carries. Sync over mobile data is a Cloud sync setting.
TRANSPORT_CONTROLS = {LINK: frozenset({"status", "ring", "ringer", "dnd", "media", "hotspot", "wallpaper"}),
                      HOSTED: frozenset(CONTROL_NAMES)}

STATUS_SECONDS = 900  # Phones resend an unchanged status every ten minutes; older is not shown.
REFRESH_SECONDS = 10  # Refresh asks one phone for its status at most this often.
WALLPAPER_SECONDS = 6 * 3600  # An opted-in wallpaper is asked for again after this long.
ANSWER_SECONDS = 60  # A wallpaper is accepted only this soon after this computer asked for it.
RING_SECONDS = 120  # A phone rings for 30 seconds; nothing longer is believed.
RECORD = "phone_status"
_LEGACY_RECORD = "hosted_phone_status"  # Cloud's record before the shared layer; read once, then replaced.

RINGER = ("ring", "vibrate", "silent")
MEDIA_ACTIONS = ("play", "pause", "next", "previous")
_LINK_MEDIA_ACTIONS = (*MEDIA_ACTIONS, "seek", "volume")
STATUS_KEYS = frozenset({"battery", "charging", "wifi", "cellular", "metered", "bluetooth", "signal", "ringer", "dnd",
                         "controls", "mobile_data", "paused"})
SIGNAL_KEYS = frozenset({"wifi_level", "cellular_level"})
SESSION_KEYS = frozenset({"source", "app", "title", "artist", "playing", "can_play", "can_pause", "can_next", "can_previous"})
_LINK_SESSION_KEYS = SESSION_KEYS | {"can_seek", "position_ms", "length_ms", "volume"}
_COMMAND_KEYS = {STATUS_REQUEST: set(), PHONE_RING: set(), PHONE_RINGER: {"mode"}, PHONE_DND: {"active"},
                 MEDIA_COMMAND: {"source", "action"}, WALLPAPER_REQUEST: set(), PHONE_HOTSPOT: set(),
                 PHONE_MOBILE_DATA: {"allowed"}, PHONE_RING_STOP: set()}


class ProtocolError(ValueError):
    def __init__(self):
        super().__init__("Unsupported phone status event.")


def _text(value, limit, *, empty=True):
    if type(value) is not str or len(value) > limit or (not empty and not value):
        raise ProtocolError()
    if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ProtocolError()
    return value


def _line(value, limit):
    """A media source (package name): never empty, no control characters."""
    text = _text(value, limit, empty=False)
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise ProtocolError()
    return text


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ProtocolError()
    return value


def _exact(body, keys):
    if type(body) is not dict or set(body) != set(keys):
        raise ProtocolError()
    return body


def read_status(body) -> dict:
    """A phone.status body: battery, network, sound and the quick actions it accepts."""
    _exact(body, STATUS_KEYS)
    controls = body["controls"]
    if (type(controls) is not list or len(controls) > 16 or any(type(name) is not str or len(name) > 40 for name in controls)
            or len(set(controls)) != len(controls)):
        raise ProtocolError()
    for key, high in (("battery", 100), ("signal", 4)):
        if body[key] is not None:
            _integer(body[key], 0, high)
    if body["ringer"] is not None and body["ringer"] not in RINGER:
        raise ProtocolError()
    for key in ("charging", "metered", "mobile_data", "paused"):
        if type(body[key]) is not bool:
            raise ProtocolError()
    for key in ("wifi", "cellular", "bluetooth", "dnd"):
        if body[key] is not None and type(body[key]) is not bool:
            raise ProtocolError()
    # Names from a newer phone are dropped, not refused: the rest stays usable.
    return {**{key: body[key] for key in sorted(STATUS_KEYS - {"controls"})},
            "controls": [name for name in controls if name in CONTROL_NAMES]}


def read_signal(body) -> dict:
    """A phone.signal body: Wi-Fi bars (null when not connected) and mobile bars (null without service), 0-4 each."""
    _exact(body, SIGNAL_KEYS)
    for key in SIGNAL_KEYS:
        if body[key] is not None:
            _integer(body[key], 0, 4)
    return {key: body[key] for key in sorted(SIGNAL_KEYS)}


def read_media(body, dialect) -> dict:
    """A media.state body: up to five sessions. Hub phones add seek position and volume."""
    _exact(body, {"sessions"})
    sessions = body["sessions"]
    if type(sessions) is not list or len(sessions) > 5:
        raise ProtocolError()
    keys = _LINK_SESSION_KEYS if dialect == LINK else SESSION_KEYS
    flags = ("playing", "can_play", "can_pause", "can_next", "can_previous") + (("can_seek",) if dialect == LINK else ())
    rows = []
    for session in sessions:
        _exact(session, keys)
        if any(type(session[key]) is not bool for key in flags):
            raise ProtocolError()
        row = {"source": _line(session["source"], 240), "app": _text(session["app"], 120),
               "title": _text(session["title"], 240), "artist": _text(session["artist"], 240),
               **{key: session[key] for key in flags}}
        if dialect == LINK:
            row.update(position_ms=_integer(session["position_ms"], 0, 2**40), length_ms=_integer(session["length_ms"], 0, 2**40),
                       volume=_integer(session["volume"], 0, 100))
        rows.append(row)
    return {"sessions": rows}


def bounded_jpeg(image: bytes) -> bool:
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


def read_wallpaper(body) -> dict:
    """A phone.wallpaper body: a small JPEG data URL, or "" when Android does not let Saiph read it."""
    _exact(body, {"preview"})
    preview = _text(body["preview"], 16_023)
    if preview:
        if not preview.startswith("data:image/jpeg;base64,"):
            raise ProtocolError()
        try:
            image = base64.b64decode(preview.split(",", 1)[1], validate=True)
        except (ValueError, binascii.Error):
            raise ProtocolError() from None
        if not 4 <= len(image) <= 12_000 or not image.startswith(b"\xff\xd8") or not image.endswith(b"\xff\xd9") or not bounded_jpeg(image):
            raise ProtocolError()
    return {"preview": preview}


def read_ring_state(body) -> dict:
    """A phone.ring.state body: ringing with the seconds left, or stopped (0 seconds)."""
    _exact(body, {"ringing", "seconds"})
    if type(body["ringing"]) is not bool:
        raise ProtocolError()
    seconds = _integer(body["seconds"], 1 if body["ringing"] else 0, RING_SECONDS if body["ringing"] else 0)
    return {"ringing": body["ringing"], "seconds": seconds}


def read_event(kind, body, dialect) -> dict:
    if kind == PHONE_RING_STATE:
        return read_ring_state(body)
    if kind == PHONE_STATUS:
        return read_status(body)
    if kind == MEDIA_STATE:
        return read_media(body, dialect)
    if kind == PHONE_SIGNAL:
        return read_signal(body)
    if kind == PHONE_WALLPAPER:
        return read_wallpaper(body)
    raise ProtocolError()


def read_command(kind, body, dialect) -> dict:
    """A quick action body (without "type"), exactly as the phone checks it."""
    if kind not in _COMMAND_KEYS or type(body) is not dict:
        raise ProtocolError()
    if kind == MEDIA_COMMAND:
        # Hub phones also take seek and volume with a value; Cloud phones never did.
        extended = dialect == LINK and "value" in body
        _exact(body, {"source", "action", "value"} if extended else {"source", "action"})
        actions = _LINK_MEDIA_ACTIONS if dialect == LINK else MEDIA_ACTIONS
        if body["action"] not in actions or extended != (body["action"] in ("seek", "volume")):
            raise ProtocolError()
        result = {"source": _line(body["source"], 240), "action": body["action"]}
        if extended:
            result["value"] = _integer(body["value"], 0, 100 if body["action"] == "volume" else 2**40)
        return result
    _exact(body, _COMMAND_KEYS[kind])
    if kind == PHONE_RINGER:
        if body["mode"] not in RINGER:
            raise ProtocolError()
        return {"mode": body["mode"]}
    if kind in (PHONE_DND, PHONE_MOBILE_DATA):
        key = "active" if kind == PHONE_DND else "allowed"
        if type(body[key]) is not bool:
            raise ProtocolError()
        return {key: body[key]}
    return {}


def carried(kind, dialect) -> bool:
    """Whether this transport carries the quick action at all."""
    return CONTROL_COMMAND.get(kind) in TRANSPORT_CONTROLS[dialect]


class StatusBook:
    """The latest status per phone, whichever transport delivered it.

    Kept in the workspace store under one record per phone. The view merges the
    phone's quick actions into its capabilities and hides a status that is too
    old, so the Phone page, tray and settings read Hub and Cloud phones alike.
    """

    def __init__(self, store, clock=time.time):
        self.store = store
        self.clock = clock
        self._refreshed: dict[str, float] = {}
        self._wallpaper_asked: dict[str, float] = {}
        self._ringing: dict[str, float] = {}  # phone -> when its Find phone ring ends; memory only.

    def saved(self, device) -> dict:
        for kind in (RECORD, _LEGACY_RECORD):
            try:
                return self.store.get(kind, device)
            except ValueError:
                continue
        return {}

    def save(self, device, **fields):
        self.store.save(RECORD, {**self.saved(device), **fields, "id": device})
        self.store.delete(_LEGACY_RECORD, device)

    def forget(self, device):
        self.store.delete(RECORD, device)
        self.store.delete(_LEGACY_RECORD, device)
        self._refreshed.pop(device, None)
        self._wallpaper_asked.pop(device, None)
        self._ringing.pop(device, None)

    def controls(self, device) -> list:
        return list((self.saved(device).get("status") or {}).get("controls") or [])

    def apply(self, source, kind, body, now, *, capabilities=(), features=None) -> bool:
        """Store a validated status or media body. Returns False when it is refused.

        Media needs the phone to offer "media", in its capabilities (older Hub
        phones) or its latest status (every Cloud phone, newer Hub phones).
        """
        store = self.store
        if kind == PHONE_RING_STATE:
            # Only from a phone that offers Find phone; the ring ends by itself even if "stopped" is lost.
            if "ring" not in capabilities and "ring" not in self.controls(source):
                return False
            if body["ringing"]:
                self._ringing[source] = now + body["seconds"]
            else:
                self._ringing.pop(source, None)
            return True
        if kind == PHONE_STATUS:
            self.save(source, status=body, status_at=int(now))
            if features is not None:
                ringer = next((row for row in store.all("phone_ringer") if row.get("device_id") == source), None)
                if body["ringer"] is None or "ringer" not in body["controls"]:
                    if ringer is not None:
                        store.delete("phone_ringer", ringer["id"])
                elif ringer is None or ringer.get("mode") != body["ringer"]:
                    features.event({"id": "status", "type": "ringer.state", "payload": {"mode": body["ringer"]}, "source": source}, None)
                if "media" not in body["controls"] and "media" not in capabilities:
                    for row in store.all("phone_media"):
                        if row.get("device_id") == source:
                            store.delete("phone_media", row["id"])
            return True
        if kind == PHONE_SIGNAL:
            self.save(source, signal=body, signal_at=int(now))
            return True
        if kind == MEDIA_STATE:
            if features is None or ("media" not in capabilities and "media" not in self.controls(source)):
                return False
            features.event({"id": "media", "type": MEDIA_STATE, "payload": body, "source": source}, None)
            return True
        return False

    def wallpaper_due(self, device, enabled, now=None) -> bool:
        """Ask an opted-in phone that lists "wallpaper" again after WALLPAPER_SECONDS, never twice in a minute."""
        now = self.clock() if now is None else now
        saved = self.saved(device)
        return (enabled and "wallpaper" in self.controls(device) and now - int(saved.get("wallpaper_at") or 0) >= WALLPAPER_SECONDS
                and not 0 <= now - self._wallpaper_asked.get(device, -ANSWER_SECONDS - 1) < ANSWER_SECONDS)

    def wallpaper_asked(self, device, now=None):
        self._wallpaper_asked[device] = self.clock() if now is None else now

    def wallpaper_answer(self, device, body, now=None) -> bool:
        """Keep a wallpaper only in answer to this computer's own recent request."""
        now = self.clock() if now is None else now
        asked = self._wallpaper_asked.pop(device, None)
        if asked is None or not 0 <= now - asked <= ANSWER_SECONDS:
            return False
        self.save(device, wallpaper=body["preview"], wallpaper_at=int(now))
        return True

    def view(self, device, capabilities, online, now=None) -> dict:
        """What the Phone page shows: online, merged capabilities, battery and status.

        A phone paused on mobile data said so before it stopped syncing: it is
        offline with its status kept, so the page can say why.
        """
        now = self.clock() if now is None else now
        saved = self.saved(device)
        status = saved.get("status") if 0 <= now - int(saved.get("status_at") or 0) <= STATUS_SECONDS else None
        if status is not None and status.get("paused"):
            online = False
        elif not online:
            status = None
        base = list(capabilities or [])
        controls = [name for name in (status or {}).get("controls") or [] if not status.get("paused") and name not in base]
        battery = (status or {}).get("battery")
        # Bars only beside a status that is shown, and only while they are as fresh as it.
        signal = (saved.get("signal") if status is not None and not status.get("paused")
                  and 0 <= now - int(saved.get("signal_at") or 0) <= STATUS_SECONDS else None)
        ringing = online and now < self._ringing.get(device, 0)
        return {"online": online, "capabilities": base + controls, "status": status, "signal": signal, "ringing": ringing,
                "battery": {"battery_level": battery, "is_charging": status["charging"]} if battery is not None else None}

    def refresh_due(self, device, now=None) -> bool:
        """Refresh asks a phone again at most every REFRESH_SECONDS; repeats send nothing."""
        now = self.clock() if now is None else now
        asked = self._refreshed.get(device)
        if asked is not None and 0 <= now - asked < REFRESH_SECONDS:
            return False
        self._refreshed[device] = now
        return True
