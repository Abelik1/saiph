# SPDX-License-Identifier: AGPL-3.0-or-later
"""First-run setup guide: whether to show it, and which optional tools are present.

Detection only. Saiph never downloads or installs these tools itself; the guide links
to each project's official release page or shows the package-manager command."""
from __future__ import annotations

import shutil
import sys

# Official release pages, opened only from this fixed list.
LINKS = {
    "scrcpy": "https://github.com/Genymobile/scrcpy/releases/tag/v3.3.4",
    "deskflow": "https://github.com/deskflow/deskflow/releases/tag/v1.27.0",
    "android": "https://appdistribution.firebase.google.com/testerapps",
    "adb": "https://developer.android.com/tools/releases/platform-tools",
    # Phone camera: OBS Studio's Virtual Camera on Windows, v4l2loopback on Linux.
    "obs": "https://obsproject.com/download",
    "v4l2loopback": "https://github.com/v4l2loopback/v4l2loopback#install",
}
# Linux helper commands and the Debian/Ubuntu packages that provide them.
LINUX_HELPERS = {
    "xdotool": ("xdotool", "Phone remote keys and touchpad (X11)"),
    "playerctl": ("playerctl", "Media controls and pausing music during calls"),
    "pactl": ("pulseaudio-utils", "Volume controls"),
    "bluetoothctl": ("bluez", "Lock when your phone leaves"),
    "nmcli": ("network-manager", "Phone hotspot connection"),
}


def tools():
    from .companion_tools import tool_path
    from .phone_debugging import adb_path  # Also finds the adb shipped beside scrcpy.
    found = {"scrcpy": bool(tool_path("scrcpy")), "deskflow": bool(tool_path("deskflow-core") or tool_path("deskflow"))}
    result = {
        # The phone shares its clipboard only while Saiph's helper runs, and the
        # computer starts that helper over USB or wireless debugging with adb.
        "adb": {"found": bool(adb_path(tool_path("scrcpy"))), "purpose": "Clipboard helper and phone webcam over USB or wireless debugging (included with scrcpy)", "link": "adb"},
        "scrcpy": {"found": found["scrcpy"], "purpose": "Phone screen, phone apps in windows, webcam and microphone", "link": "scrcpy"},
        "deskflow": {"found": found["deskflow"], "purpose": "Keyboard and mouse sharing between computers", "link": "deskflow"},
    }
    linux = sys.platform.startswith("linux")
    helpers = {name: {"found": bool(shutil.which(name)), "package": package, "purpose": purpose}
               for name, (package, purpose) in LINUX_HELPERS.items()} if linux else {}
    return {"tools": result, "linux": helpers, "platform": "linux" if linux else "windows" if sys.platform == "win32" else sys.platform}


def status(workspace):
    settings = workspace.settings
    hub_paired = bool((settings.get("hub") or {}).get("paired"))
    hosted = (settings.get("hosted") or {}) if isinstance(settings.get("hosted"), dict) else {}
    hosted_identity = (workspace.root / "hosted" / "identity").exists()
    connected = hub_paired or hosted_identity
    completed = (settings.get("setup") or {}).get("completed") is True
    return {"completed": completed, "connected": connected, "mode": "hub" if hub_paired else "hosted" if hosted_identity or hosted.get("enabled") else None,
            # Existing users who are already connected are never interrupted by the guide.
            "show": not completed and not connected}


def validate_options(options):
    if not isinstance(options, dict) or set(options) - {"completed"} or ("completed" in options and type(options["completed"]) is not bool):
        raise ValueError("Unknown setup preference.")
    return dict(options)
