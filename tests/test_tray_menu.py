# SPDX-License-Identifier: AGPL-3.0-or-later
from orion_mini.tray_menu import phone_entries


def state(**features):
    return {"phone": {"devices": [
        {"id": "laptop", "name": "Laptop", "online": True, "capabilities": ["files"]},
        {"id": "phone", "name": "Galaxy", "online": True, "capabilities": ["battery", "media", "ringer", "files"],
         "battery": {"battery_level": 76, "is_charging": True}}]},
        "phone_features": {"media": [{"device_id": "phone", "sessions": [{"source": "com.spotify.music", "title": "Song", "playing": True,
                                                                          "can_pause": True, "can_next": True}]}],
                           "ringers": [{"device_id": "phone", "mode": "vibrate"}], **features},
        "dnd": {"enabled": True, "active": False}}


def test_quick_controls_follow_the_phone_state():
    rows = phone_entries(state())
    assert rows[0] == ("Galaxy · 76% · charging", None, None)
    labels = [label for label, method, _ in rows if method]
    assert labels == ["Pause Song", "Next track", "Set phone to ring", "Set phone to silent", "Turn on Do Not Disturb", "Send a file to phone…"]
    assert ("phone.media", {"device_id": "phone", "source": "com.spotify.music", "action": "pause"}) in [(m, a) for _, m, a in rows]


def test_offline_phone_offers_no_actions():
    offline = state()
    offline["phone"]["devices"][1]["online"] = False
    assert phone_entries(offline) == [("Phone offline", None, None)]
