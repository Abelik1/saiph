# SPDX-License-Identifier: AGPL-3.0-or-later
"""Small Windows/Linux adapters with no input content or application tracking."""
from __future__ import annotations

import os
import ctypes
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def qt_platform_for_background_clipboard(environ=None):
    """Qt platform that keeps clipboard sharing alive while the window is unfocused.

    A Wayland compositor tells only the focused client about clipboard changes and
    lets only it take ownership. Qt implements no data-control protocol, and Mutter
    offers none, so a native Wayland Qt client is deaf and mute whenever Orion is in
    the background on GNOME, KDE Plasma and wlroots desktops alike. Qt's xcb platform
    goes through XWayland, whose selection bridge works unfocused. ``xcb;wayland``
    falls back to Wayland if the xcb plugin cannot load. A QT_QPA_PLATFORM the user set
    wins; ORION_MINI_QT_PLATFORM (for example ``wayland``) opts out of the choice.
    Returns the value to export, or None to leave Qt's default alone."""
    environ = os.environ if environ is None else environ
    if not sys.platform.startswith("linux") or environ.get("QT_QPA_PLATFORM"):
        return None
    override = environ.get("ORION_MINI_QT_PLATFORM", "").strip()
    if override:
        return override
    wayland = environ.get("XDG_SESSION_TYPE") == "wayland" or bool(environ.get("WAYLAND_DISPLAY"))
    if wayland and environ.get("DISPLAY"):  # XWayland is running
        return "xcb;wayland"
    return None


def beep(urgent=False):
    if sys.platform == "win32":
        import winsound
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION if urgent else winsound.MB_ICONASTERISK)
    else:
        from PySide6.QtWidgets import QApplication
        QApplication.beep()


def open_target(value):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    url = QUrl.fromLocalFile(str(Path(value).resolve())) if isinstance(value, Path) else QUrl(str(value))
    if not QDesktopServices.openUrl(url):
        raise ValueError("This computer could not open the item.")


def set_startup(enabled, *, config_home=None):
    if sys.platform == "win32":
        from .startup import set_start_with_windows
        return set_start_with_windows(enabled)
    config = Path(config_home or os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    if not config.is_absolute():
        raise ValueError("The startup configuration must use an absolute local folder.")
    frozen = bool(getattr(sys, "frozen", False))
    directory = config / "autostart"
    entry = directory / ("orion.desktop" if frozen else "orion-mini.desktop")
    command_path = Path.home() / '.local/bin/orion' if frozen else Path(sys.executable)
    command = _desktop_quote(command_path) + ("" if frozen else " -m orion_mini")
    name = "Saiph"
    body = ("Type=Application\nName=" + name + "\nExec=" + command
            + "\nTerminal=false\nX-GNOME-Autostart-enabled=")
    prefix = "[Desktop Entry]\n# ORION_OWNED=1\n"
    allowed = {prefix + body + flag + "\n" for flag in ("true", "false")}
    legacy_body = body.replace("Name=Saiph\n", "Name=" + ("Orion" if frozen else "Orion Mini") + "\n")
    allowed.update(prefix + legacy_body + flag + "\n" for flag in ("true", "false"))
    if not frozen:
        # Previous source builds used the legacy label without the marker.
        allowed.add("[Desktop Entry]\n" + legacy_body + "true\n")
    _startup_plain_path(entry)
    if entry.exists():
        if entry.stat().st_size > 16384 or entry.read_text(encoding="utf-8") not in allowed:
            raise ValueError("An unrelated startup entry was preserved. Review startup in Settings → General.")
    if not enabled:
        entry.unlink(missing_ok=True)
        return
    if frozen:
        # A stable installed launcher follows updates; a release-specific binary
        # becomes stale after an upgrade. Portable/source copies cannot install it.
        _startup_plain_path(command_path)
        try:
            with command_path.open(encoding="utf-8") as source:
                header = source.read(256)
            if not header.startswith("#!/bin/sh\n# ORION_OWNED=1\n"):
                raise ValueError
        except (OSError, ValueError):
            raise ValueError("Install Saiph before enabling session startup.") from None
    directory.mkdir(parents=True, exist_ok=True)
    _startup_plain_path(entry)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=directory, prefix=".orion-startup-", delete=False) as output:
            temporary = Path(output.name)
            output.write(prefix + body + "true\n")
            output.flush()
            os.fsync(output.fileno())
        _startup_plain_path(entry)
        os.replace(temporary, entry)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _desktop_quote(path):
    value = str(path)
    if any(ord(character) < 32 for character in value):
        raise ValueError("The startup path contains unsupported characters.")
    for character in ("\\", '"', "`", "$"):
        value = value.replace(character, "\\" + character)
    return '"' + value.replace("%", "%%") + '"'


def _startup_plain_path(path):
    """Never follow a redirected startup entry or configuration directory."""
    import stat
    for candidate in (path, *path.parents):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400
                or not (stat.S_ISREG(info.st_mode) if candidate == path else stat.S_ISDIR(info.st_mode))):
            raise ValueError("A redirected or unrelated startup path was preserved. Review startup in Settings → General.")


class _POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte), ("BatteryLifePercent", ctypes.c_ubyte),
                ("SystemStatusFlag", ctypes.c_ubyte), ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]


def battery(power_supply=Path("/sys/class/power_supply")):
    """This computer's battery as {battery_level, is_charging}, or None without a battery."""
    if sys.platform == "win32":
        status = _POWER_STATUS()
        if not hasattr(ctypes, "windll") or not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            return None
        if status.BatteryFlag & 128 or status.BatteryFlag == 255 or status.BatteryLifePercent > 100:
            return None  # No system battery, or unknown.
        return {"battery_level": int(status.BatteryLifePercent), "is_charging": status.ACLineStatus == 1}
    try:
        for supply in sorted(Path(power_supply).glob("BAT*")):
            level = int((supply / "capacity").read_text().strip())
            state = (supply / "status").read_text().strip()
            return {"battery_level": max(0, min(100, level)), "is_charging": state in {"Charging", "Full"}}
    except (OSError, ValueError):
        pass
    return None


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def _windows_idle_seconds() -> float | None:
    """Return global Windows idle duration without collecting input content."""
    if not hasattr(ctypes, "windll"):
        return None
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000


def idle_seconds():
    if sys.platform == "win32":
        return _windows_idle_seconds()
    # xprintidle returns elapsed milliseconds only; unavailable on native Wayland.
    if os.environ.get("XDG_SESSION_TYPE") != "wayland" and shutil.which("xprintidle"):
        try:
            result = subprocess.run(["xprintidle"], capture_output=True, timeout=2, check=False)
            if result.returncode:
                return None
            return max(0.0, float(result.stdout.strip()) / 1000)
        except (ValueError, OSError, subprocess.TimeoutExpired):
            pass
    return None  # Unavailable must not be interpreted as permanent user activity.


# Windows publishes its Do Not Disturb (Focus Assist) profile through this WNF
# state: a DWORD where 0 is off and 1/2 are priority-only/alarms-only.
_WNF_QUIET_HOURS_PROFILE = 0x0D83063EA3BF1C75


def _windows_dnd():
    if not hasattr(ctypes, "WinDLL"):
        return None
    try:
        from ctypes import wintypes
        name, stamp = ctypes.c_uint64(_WNF_QUIET_HOURS_PROFILE), wintypes.ULONG(0)
        buffer, size = ctypes.create_string_buffer(16), wintypes.ULONG(16)
        status = ctypes.WinDLL("ntdll").NtQueryWnfStateData(ctypes.byref(name), None, None, ctypes.byref(stamp), buffer, ctypes.byref(size))
        if status != 0 or size.value < 4:
            return None
        return int.from_bytes(buffer.raw[:4], "little") != 0
    except (OSError, AttributeError, ValueError):
        return None


def system_dnd(focus):
    """The desktop's own Do Not Disturb switch, or None when it cannot be read.

    Read-only: Saiph never changes Windows Do Not Disturb. On GNOME, Do Not
    Disturb is banners off; a quiet period Saiph applied itself reads as unknown,
    and banners coming back during it mean the user ended it."""
    if sys.platform == "win32":
        return _windows_dnd()
    if sys.platform.startswith("linux") and "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper() and shutil.which("gsettings"):
        try:
            result = subprocess.run(["gsettings", "get", "org.gnome.desktop.notifications", "show-banners"], capture_output=True, timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode or result.stdout.strip() not in {b"true", b"false"}:
            return None
        banners = result.stdout.strip() == b"true"
        if focus.quiet:
            return False if banners else None
        return not banners
    return None


class FocusAdapter:
    def __init__(self, state_file=None):
        from .storage import read_json
        self.state_file = state_file
        self.quiet = False
        self.previous = None
        self.restore_pending = False
        try:
            saved = read_json(state_file, {}) if state_file else {}
        except (OSError, ValueError):
            saved = {}
        if saved.get("quiet") is True and isinstance(saved.get("previous"), bool):
            self.previous = saved["previous"]
            self.restore_pending = True

    def persist(self, quiet):
        if self.state_file:
            from .storage import write_json
            write_json(self.state_file, {"quiet": quiet, "previous": self.previous if quiet else None})

    def set(self, quiet):
        quiet = bool(quiet)
        if quiet == self.quiet and (quiet or not self.restore_pending):
            return
        if sys.platform.startswith("linux") and "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper() and shutil.which("gsettings"):
            key = ["gsettings", "get", "org.gnome.desktop.notifications", "show-banners"]
            if quiet and not self.restore_pending:
                result = subprocess.run(key, capture_output=True, timeout=3)
                if result.returncode:
                    raise ValueError("Notification focus is unavailable on this desktop.")
                self.previous = result.stdout.strip() == b"true"
            if quiet:
                # Record restoration before changing the OS, so an application
                # crash during Focus cannot permanently disable GNOME banners.
                self.persist(True)
                self.restore_pending = True
            restore = False if quiet else self.previous
            if restore is not None:
                result = subprocess.run(["gsettings", "set", "org.gnome.desktop.notifications", "show-banners", str(restore).lower()], capture_output=True, timeout=3)
                if result.returncode:
                    raise ValueError("Notification focus is unavailable on this desktop.")
            self.restore_pending = quiet
            if not quiet:
                self.persist(False)
                self.previous = None
        self.quiet = quiet
