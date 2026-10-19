# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone Link-style preferences, tray recent content and the taskbar badge count.

Synthetic phones and notifications only; the Windows taskbar itself is not touched.
"""
from pathlib import Path

import pytest

from orion_mini import phone_settings
from orion_mini.link_service import LinkWorkspace
from orion_mini.storage import Store
from orion_mini.taskbar_badge import label, unread_count
from orion_mini.tray_menu import phone_entries


def test_preferences_default_on_except_the_wallpaper():
    options = phone_settings.preferences({})
    assert options == {"features": {name: True for name in phone_settings.FEATURES},
                       "wallpaper": False, "audio_player": True, "badges": True, "recent": True,
                       "usb_debugging": False}  # scrcpy only after the Settings → Advanced opt-in.
    saved = {"link": {"phone": {"features": {"calls": False}, "wallpaper": True}}}
    assert phone_settings.feature_on(saved, "calls") is False and phone_settings.feature_on(saved, "messages") is True
    assert phone_settings.flag(saved, "wallpaper") is True


@pytest.mark.parametrize("options", [
    {"theme": "dark"}, {"wallpaper": "yes"}, {"features": {"calls": 1}}, {"features": {"faxes": True}}, {"features": []}, [],
])
def test_preferences_refuse_unknown_or_non_boolean_values(options):
    with pytest.raises(ValueError):
        phone_settings.validate(options)


def test_preferences_merge_one_change_at_a_time():
    current = phone_settings.validate({"features": {"calls": False}})
    merged = phone_settings.validate({"features": {"photos": False}, "badges": False}, current)
    assert merged == {"features": {"calls": False, "photos": False}, "badges": False}


def test_turned_off_features_drop_only_their_own_data():
    off = {"link": {"phone": {"features": {"messages": False, "calls": False, "photos": False, "notifications": False}}}}
    for kind in ("sms.thread", "sms.index", "call.state", "calls.log", "photos.item", "notification.upsert"):
        assert phone_settings.data_allowed(off, kind) is False
        assert phone_settings.data_allowed({}, kind) is True
    for kind in ("phone.status", "media.state", "contacts.results", "battery", "clipboard"):
        assert phone_settings.data_allowed(off, kind) is True


def test_received_files_folder_follows_the_connection():
    home = Path("synthetic-home")
    assert phone_settings.received_folder({"hosted": {"enabled": True}}, home) == home / "Downloads" / "Saiph"
    assert phone_settings.received_folder({}, home) == home / "Downloads" / "Saiph"  # One folder for Cloud and Hub.


def test_help_links_are_public_pages_only():
    assert set(phone_settings.HELP_LINKS) == {"feedback", "guide", "plans"}
    assert phone_settings.HELP_LINKS["plans"] == "https://usesaiph.com/hosted.html"
    assert all(url.startswith("https://github.com/Abelik1/saiph/") for name, url in phone_settings.HELP_LINKS.items() if name != "plans")


def test_settings_save_accepts_phone_preferences(tmp_path):
    workspace = LinkWorkspace(tmp_path)
    workspace.dispatch("settings.save", {"link": {"phone": {"features": {"calls": False}}}})
    workspace.dispatch("settings.save", {"link": {"phone": {"wallpaper": True}}})
    assert workspace.settings["link"]["phone"] == {"features": {"calls": False}, "wallpaper": True}
    with pytest.raises(ValueError):
        workspace.dispatch("settings.save", {"link": {"phone": {"wallpaper": "on"}}})


def cloud_state(**settings):
    return {"settings": settings,
            "phone": {"devices": [{"id": "cloud", "name": "Pixel", "online": True, "hosted": True,
                                   "capabilities": ["files", "ring", "dnd", "media"], "battery": {"battery_level": 40, "is_charging": False},
                                   "status": {"dnd": False}}], "notifications": []},
            "hosted": {"notifications": [{"device_id": "cloud", "app": "Messages", "title": "Synthetic text", "timestamp": 3},
                                         {"device_id": "cloud", "app": "Mail", "title": "Older", "timestamp": 1},
                                         {"device_id": "other", "app": "Mail", "title": "Not this phone", "timestamp": 9}]},
            "phone_features": {"media": [{"device_id": "cloud", "sessions": [{"source": "org.example.player", "title": "Track",
                                                                             "playing": True, "can_pause": True}]}]}}


def test_tray_lists_a_cloud_phone_with_its_quick_actions_and_recent_content():
    rows = phone_entries(cloud_state())
    assert rows[0] == ("Pixel · 40%", None, None)
    assert ("Turn on phone Do Not Disturb", "phone.dnd", {"device_id": "cloud", "active": True}) in rows
    assert ("Ring phone", "phone.ring", {"device_id": "cloud"}) in rows
    assert ("Pause Track", "phone.media", {"device_id": "cloud", "source": "org.example.player", "action": "pause"}) in rows
    assert [label for label, method, _ in rows if method == "window.show"] == ["Synthetic text — Messages", "Older — Mail"]


def test_tray_hides_the_audio_player_and_recent_content_when_turned_off():
    rows = phone_entries(cloud_state(link={"phone": {"audio_player": False, "recent": False}}))
    assert not [row for row in rows if row[1] in {"phone.media", "window.show"}]


def test_badge_counts_phone_notifications_unless_turned_off(tmp_path):
    store = Store(tmp_path / "store")
    store.save("phone_notification", {"id": "a", "title": "Synthetic"})
    store.save("hosted_notification", {"id": "b", "title": "Synthetic"})
    store.save("message", {"id": "c"})
    assert unread_count(store, {}) == 2
    assert unread_count(store, {"link": {"phone": {"badges": False}}}) == 0
    assert unread_count(store, {"link": {"phone": {"features": {"notifications": False}}}}) == 0
    assert (label(0), label(7), label(120)) == ("", "7", "99+")
