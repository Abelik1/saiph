# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone Link-style preferences for the Phone page: which features show and sync,
the wallpaper background, the audio player and the taskbar badge.

Stored under settings["link"]["phone"]. Everything is on by default except the
wallpaper, which copies a picture of the phone's home screen to this computer, and
`usb_debugging`: the explicit Settings → Advanced opt-in to scrcpy windows over
authorised USB or wireless debugging. Without it nothing offers or asks to install
scrcpy or adb; the phone screen uses the local network (docs/PHONE_SCREEN.md).
"""
from __future__ import annotations

FEATURES = ("notifications", "messages", "photos", "apps", "calls")
# Help & feedback: public pages only, from a fixed list. No support mailbox is
# published yet (website/LAUNCH.md), so feedback goes to the public issue tracker.
HELP_LINKS = {
    "feedback": "https://github.com/Abelik1/saiph/issues/new",
    "guide": "https://github.com/Abelik1/saiph/blob/main/docs/USER_GUIDE.md#troubleshooting-and-privacy",
    # Saiph Cloud plans, free trial and subscribing (same page as the Android app's Subscribe).
    "plans": "https://usesaiph.com/hosted.html",
}
FLAGS = {"wallpaper": False, "audio_player": True, "badges": True, "recent": True, "usb_debugging": False}


def validate(options, current=None) -> dict:
    """Merge one change into the saved preferences; unknown keys are refused."""
    current = current if isinstance(current, dict) else {}
    if not isinstance(options, dict) or set(options) - {"features", *FLAGS}:
        raise ValueError("Unknown phone preference.")
    result = {key: value for key, value in current.items() if key in {"features", *FLAGS}}
    if "features" in options:
        features = options["features"]
        if not isinstance(features, dict) or set(features) - set(FEATURES) or any(type(v) is not bool for v in features.values()):
            raise ValueError("Phone features are on or off.")
        result["features"] = {**(current.get("features") if isinstance(current.get("features"), dict) else {}), **features}
    for key in FLAGS:
        if key in options:
            if type(options[key]) is not bool:
                raise ValueError("Phone preferences are on or off.")
            result[key] = options[key]
    return result


def preferences(settings) -> dict:
    """The effective preferences with defaults filled in."""
    link = settings.get("link") if isinstance(settings, dict) else None
    saved = (link or {}).get("phone") if isinstance(link, dict) else None
    saved = saved if isinstance(saved, dict) else {}
    features = saved.get("features") if isinstance(saved.get("features"), dict) else {}
    return {"features": {name: features.get(name) is not False for name in FEATURES},
            **{key: saved.get(key) if type(saved.get(key)) is bool else default for key, default in FLAGS.items()}}


def feature_on(settings, name) -> bool:
    return preferences(settings)["features"][name]


def flag(settings, name) -> bool:
    return preferences(settings)[name]


# Phone data types the desktop drops when the owner turns that feature off.
_DATA_FEATURE = {"sms.": "messages", "call.": "calls", "calls.": "calls", "photos.": "photos", "notification.": "notifications"}


def data_allowed(settings, kind) -> bool:
    for prefix, feature in _DATA_FEATURE.items():
        if kind.startswith(prefix):
            return feature_on(settings, feature)
    return True


def received_folder(settings, home=None):
    """Where files from the phone are saved: Downloads → Saiph, with Saiph Cloud or a Hub.

    Downloads is the Windows Known Folder or XDG_DOWNLOAD_DIR on Linux."""
    from .paths import received_dir
    return received_dir(home)
