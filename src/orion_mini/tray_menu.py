# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone quick controls for the tray menu, computed from app state. No side effects."""
from __future__ import annotations


def phone_entries(state):
    """(label, method, args) rows; method None marks a status line. Uses the first online phone."""
    phones = [d for d in (state.get("phone") or {}).get("devices", []) if "battery" in d.get("capabilities", [])]
    phone = next((d for d in phones if d.get("online")), None)
    if phone is None:
        return [("Phone offline", None, None)]
    rows = []
    battery = phone.get("battery") or {}
    level = f" · {battery['battery_level']}%" if isinstance(battery.get("battery_level"), int) else ""
    rows.append((phone.get("name", "Phone") + level + (" · charging" if battery.get("is_charging") else ""), None, None))
    features = state.get("phone_features") or {}
    capabilities = phone.get("capabilities", [])
    sessions = next((m.get("sessions", []) for m in features.get("media", []) if m.get("device_id") == phone["id"]), [])
    session = next((s for s in sessions if s.get("playing")), sessions[0] if sessions else None)
    if session and "media" in capabilities:
        title = (session.get("title") or session.get("app") or "media")[:40]
        if session.get("playing") and session.get("can_pause"):
            rows.append(("Pause " + title, "phone.media", {"device_id": phone["id"], "source": session["source"], "action": "pause"}))
        elif session.get("can_play"):
            rows.append(("Play " + title, "phone.media", {"device_id": phone["id"], "source": session["source"], "action": "play"}))
        if session.get("can_next"):
            rows.append(("Next track", "phone.media", {"device_id": phone["id"], "source": session["source"], "action": "next"}))
    if "ringer" in capabilities:
        current = next((r.get("mode") for r in features.get("ringers", []) if r.get("device_id") == phone["id"]), None)
        for mode, label in (("ring", "Ring"), ("vibrate", "Vibrate"), ("silent", "Silent")):
            if mode != current:
                rows.append(("Set phone to " + label.lower(), "phone.ringer", {"device_id": phone["id"], "mode": mode}))
    dnd = state.get("dnd") or {}
    if dnd.get("enabled"):
        rows.append(("Turn off Do Not Disturb" if dnd.get("active") else "Turn on Do Not Disturb", "continuity.dnd", {"active": not dnd.get("active")}))
    if "files" in capabilities:
        rows.append(("Send a file to phone…", "phone.file.choose", {"device_id": phone["id"]}))
    return rows
