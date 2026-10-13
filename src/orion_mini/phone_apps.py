# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone apps in their own windows on this computer, through scrcpy over authorised debugging.

scrcpy (3.x) lists the phone's apps and starts one on its own virtual display, so each
app gets a separate window on any phone brand. Only a package name from the phone's
own list is passed, as one argument; nothing else from the phone reaches a command."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+")
# scrcpy --list-apps prints " * Name   package" (system) or " - Name   package" (user).
LINE = re.compile(r"^\s*([*-])\s+(.+?)\s{2,}(\S+)\s*$")
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def parse_apps(output):
    apps = {}
    for line in output.splitlines():
        match = LINE.match(line)
        if match and PACKAGE.fullmatch(match.group(3)):
            apps[match.group(3)] = {"package": match.group(3), "name": match.group(2).strip()[:80], "system": match.group(1) == "*"}
    return sorted(apps.values(), key=lambda app: (app["system"], app["name"].lower()))


def _scrcpy():
    from .companion_tools import tool_path
    executable = tool_path("scrcpy")
    if not executable:
        raise ValueError("Install scrcpy once in Settings → Advanced to open phone apps here.")
    return executable


def _serial(serial):
    if not serial or any(c.isspace() or c in ";|&" for c in serial):
        raise ValueError("Choose an authorized phone in Settings → Advanced.")
    return serial


def list_apps(adb, serial, runner=subprocess.run):
    env = {**os.environ, "ADB": str(adb)}
    try:
        result = runner([_scrcpy(), "--serial", _serial(serial), "--list-apps"], env=env, capture_output=True,
                        text=True, timeout=30, stdin=subprocess.DEVNULL, **NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("The phone's apps could not be listed. Check its debugging connection.") from None
    apps = parse_apps((result.stdout or "") + "\n" + (result.stderr or ""))
    if not apps:
        raise ValueError("The phone's apps could not be listed. Phone app windows need Android 10 or later.")
    return {"apps": apps}


def open_app(adb, serial, package, name="", runner=subprocess.Popen):
    if not isinstance(package, str) or not PACKAGE.fullmatch(package) or len(package) > 200:
        raise ValueError("Choose an app from the list.")
    title = "".join(c for c in str(name or package) if c.isprintable())[:60] + " · Phone"
    env = {**os.environ, "ADB": str(adb)}
    runner([_scrcpy(), "--serial", _serial(serial), "--new-display", "--start-app=" + package, "--no-audio", "--window-title", title],
           env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **NO_WINDOW)
    return {"opened": True}


def pin(package, name, *, home=None):
    """A Start menu (Windows) or applications-menu (Linux) entry that opens this phone app."""
    if not isinstance(package, str) or not PACKAGE.fullmatch(package) or len(package) > 200:
        raise ValueError("Choose an app from the list.")
    from .phone_features import safe_name
    label = safe_name(str(name or package)[:60])
    if sys.platform == "win32":
        from .startup import startup_command, write_shortcut
        command = startup_command()
        executable, _, rest = command[1:].partition('"')
        arguments = (rest.strip() + " --open-phone-app " + package).strip()
        folder = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "Microsoft/Windows/Start Menu/Programs/Saiph/Phone apps"
        path = write_shortcut(folder / (label + ".lnk"), Path(executable), arguments)
        return {"pinned": True, "path": str(path)}
    applications = Path(home or os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "applications"
    applications.mkdir(parents=True, exist_ok=True)
    frozen = getattr(sys, "frozen", False)
    launcher = f'"{Path.home() / ".local/bin/orion"}"' if frozen else f'"{sys.executable}" -m orion_mini'
    path = applications / f"saiph-phone-{package}.desktop"
    text = "".join(c for c in label if c not in "\n\r")
    path.write_text(f"[Desktop Entry]\n# ORION_OWNED=1\nType=Application\nName={text} (phone)\nExec={launcher} --open-phone-app {package}\nTerminal=false\nCategories=Utility;\n",
                    encoding="utf-8")
    return {"pinned": True, "path": str(path)}
