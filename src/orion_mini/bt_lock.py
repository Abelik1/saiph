# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lock this Linux session when the paired phone's Bluetooth connection goes away.

Windows already has Dynamic Lock (Settings → Accounts → Sign-in options), so this is
Linux-only. It is opt-in, uses the phone's existing Bluetooth pairing through
bluetoothctl, and only ever locks: it never unlocks. Mesh presence is not used,
because it says nothing about distance."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time

MAC = re.compile(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}")
DEFAULT_SECONDS = 30


def validate_options(options):
    if not isinstance(options, dict) or set(options) - {"enabled", "device", "seconds"}:
        raise ValueError("Unknown automatic lock preference.")
    if "enabled" in options and type(options["enabled"]) is not bool:
        raise ValueError("Automatic lock is on or off.")
    if "device" in options and (not isinstance(options["device"], str) or not (MAC.fullmatch(options["device"]) or options["device"] == "")):
        raise ValueError("Choose a paired Bluetooth phone.")
    if "seconds" in options and (type(options["seconds"]) is not int or not 10 <= options["seconds"] <= 600):
        raise ValueError("Choose between 10 seconds and 10 minutes.")
    return dict(options)


class BluetoothLock:
    def __init__(self, settings, *, runner=subprocess.run, clock=time.monotonic):
        self.settings, self.runner, self.clock = settings, runner, clock
        self.seen = False        # The phone has been connected since start or the last lock.
        self.gone_since = None
        self.error = ""
        self.locked_at = None
        self._paired = (None, [])

    def supported(self):
        return sys.platform.startswith("linux") and bool(shutil.which("bluetoothctl") and shutil.which("loginctl"))

    def options(self):
        return (self.settings.get("link") or {}).get("bt_lock") or {}

    def _run(self, *arguments):
        try:
            result = self.runner(list(arguments), capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout if result.returncode == 0 else None

    def paired(self):
        """Paired Bluetooth devices as [{address, name}]; empty when unavailable."""
        if not self.supported():
            return []
        output = self._run("bluetoothctl", "devices", "Paired") or self._run("bluetoothctl", "paired-devices") or ""
        devices = []
        for line in output.splitlines():
            parts = line.split(" ", 2)
            if len(parts) >= 2 and parts[0] == "Device" and MAC.fullmatch(parts[1]):
                devices.append({"address": parts[1], "name": (parts[2] if len(parts) > 2 else parts[1])[:80]})
        return devices

    def cached_paired(self):
        if self._paired[0] is None or self.clock() - self._paired[0] >= 30:
            self._paired = (self.clock(), self.paired())
        return self._paired[1]

    def connected(self, address):
        output = self._run("bluetoothctl", "info", address)
        if output is None:
            return None
        return re.search(r"^\s*Connected:\s*yes\s*$", output, re.MULTILINE) is not None

    def poll(self):
        """Locks once after the phone has been gone for the chosen time. True when it locked."""
        options = self.options()
        address = options.get("device", "")
        if not options.get("enabled") or not MAC.fullmatch(address or "") or not self.supported():
            self.seen, self.gone_since = False, None
            return False
        state = self.connected(address)
        if state is None:
            self.error = "Bluetooth is unavailable; automatic lock is paused."
            return False
        self.error = ""
        if state:
            self.seen, self.gone_since = True, None
            return False
        if not self.seen:
            return False  # Never lock just because the phone was away when Saiph started.
        now = self.clock()
        if self.gone_since is None:
            self.gone_since = now
            return False
        if now - self.gone_since < options.get("seconds", DEFAULT_SECONDS):
            return False
        self.seen, self.gone_since = False, None
        if self._run("loginctl", "lock-session") is None:
            self.error = "This session could not be locked."
            return False
        self.locked_at = time.time()
        return True

    def status(self):
        options = self.options()
        return {"supported": self.supported(), "enabled": bool(options.get("enabled")), "device": options.get("device", ""),
                "seconds": options.get("seconds", DEFAULT_SECONDS), "devices": self.cached_paired(),
                "error": self.error, "windows": sys.platform == "win32"}
