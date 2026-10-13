# SPDX-License-Identifier: AGPL-3.0-or-later
"""Connect to the phone's hotspot through a Wi-Fi profile the owner already saved.

Saiph never stores or reads Wi-Fi passwords: Windows (netsh) and NetworkManager
(nmcli) keep them. Only a profile name chosen from the saved list is used, as a
single argument, never through a shell."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time

NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
OFFLINE_SECONDS = 30  # Hub unreachable this long, with no network route, before reconnecting.
RETRY_SECONDS = 60


def _run(command, runner=subprocess.run):
    try:
        result = runner(command, capture_output=True, timeout=15, check=False, stdin=subprocess.DEVNULL, **NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    output = result.stdout
    return output.decode("utf-8", "replace") if isinstance(output, bytes) else output


def _nmcli_fields(line):
    """Split nmcli terse output, where a literal ':' in a value is escaped as '\\:'."""
    fields, current, escaped = [], "", False
    for character in line:
        if escaped:
            current += character; escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            fields.append(current); current = ""
        else:
            current += character
    return fields + [current]


def windows_profiles(output):
    """Profile names from `netsh wlan show profiles`; labels are localised, the layout is not."""
    names = []
    for line in output.splitlines():
        if line.startswith("    ") and " : " in line:
            name = line.split(" : ", 1)[1].strip()
            if name and name not in names:
                names.append(name)
    return names


def windows_active(output, names):
    """Connected saved profile from `netsh wlan show interfaces`, matched by value since labels are localised."""
    values = {line.split(" : ", 1)[1].strip() for line in output.splitlines() if " : " in line}
    return next((name for name in names if name in values), None)


def profiles(runner=subprocess.run):
    if sys.platform == "win32":
        output = _run(["netsh", "wlan", "show", "profiles"], runner)
        return windows_profiles(output) if output else []
    if shutil.which("nmcli"):
        output = _run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"], runner) or ""
        return [fields[0] for fields in map(_nmcli_fields, output.splitlines()) if len(fields) == 2 and fields[1] == "802-11-wireless" and fields[0]]
    return []


def active(runner=subprocess.run, names=()):
    if sys.platform == "win32":
        output = _run(["netsh", "wlan", "show", "interfaces"], runner)
        return windows_active(output, names) if output else None
    if shutil.which("nmcli"):
        output = _run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"], runner) or ""
        return next((fields[0] for fields in map(_nmcli_fields, output.splitlines()) if len(fields) == 2 and fields[1] == "802-11-wireless"), None)
    return None


def has_route():
    """True when the OS has any default route. A UDP connect sends no packets."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))  # TEST-NET-1: never contacted.
        return True
    except OSError:
        return False


def validate_options(options):
    if not isinstance(options, dict) or set(options) - {"profile", "auto"}:
        raise ValueError("Unknown hotspot preference.")
    if "auto" in options and type(options["auto"]) is not bool:
        raise ValueError("Automatic hotspot reconnection is on or off.")
    if "profile" in options and (not isinstance(options["profile"], str) or len(options["profile"]) > 64
                                 or any(ord(c) < 32 for c in options["profile"])):
        raise ValueError("Choose a saved Wi-Fi network.")
    return dict(options)


class Hotspot:
    def __init__(self, settings, *, runner=subprocess.run, clock=time.monotonic, route=has_route):
        self.settings, self.runner, self.clock, self.route = settings, runner, clock, route
        self.offline_since = None
        self.next_attempt = 0
        self.error = ""
        self.last_connected = None
        self._profiles = (None, [])
        self._active = (None, None)

    def options(self):
        return (self.settings.get("link") or {}).get("hotspot") or {}

    def saved(self):
        """Saved Wi-Fi profiles, cached for the settings page."""
        if self._profiles[0] is None or self.clock() - self._profiles[0] >= 30:
            self._profiles = (self.clock(), profiles(self.runner))
        return self._profiles[1]

    def connect(self):
        profile = self.options().get("profile")
        if not profile:
            raise ValueError("Choose your phone's hotspot in Settings first.")
        self._profiles = (None, [])
        if profile not in self.saved():
            raise ValueError("Connect to your phone's hotspot once in your computer's Wi-Fi settings, then choose it here.")
        command = (["netsh", "wlan", "connect", "name=" + profile] if sys.platform == "win32"
                   else ["nmcli", "connection", "up", "id", profile])
        if _run(command, self.runner) is None:
            self.error = "Turn on your phone's hotspot, then try again."
            raise ValueError(self.error)
        self.error, self.last_connected, self._active = "", time.time(), (None, None)
        return {"connecting": True, "profile": profile}

    def poll(self, online):
        """Reconnect to the hotspot only when the Hub is unreachable and no network route exists."""
        options = self.options()
        if online or not options.get("auto") or not options.get("profile"):
            self.offline_since = None
            return False
        now = self.clock()
        if self.offline_since is None:
            self.offline_since = now
        if now - self.offline_since < OFFLINE_SECONDS or now < self.next_attempt or self.route():
            return False
        self.next_attempt = now + RETRY_SECONDS
        try:
            self.connect()
            return True
        except ValueError:
            return False

    def status(self):
        options = self.options()
        if options.get("profile") and (self._active[0] is None or self.clock() - self._active[0] >= 10):
            self._active = (self.clock(), active(self.runner, self.saved()))
        return {"profiles": self.saved(), "profile": options.get("profile", ""), "auto": bool(options.get("auto")),
                "active": self._active[1] if options.get("profile") else None, "error": self.error,
                "supported": sys.platform == "win32" or bool(shutil.which("nmcli"))}
