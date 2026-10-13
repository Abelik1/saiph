# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone remote for desktop apps: a fixed catalog of adapters with fixed controls.

A paired phone chooses an app and presses a control. Each control maps to one
predefined key press or system action on this computer. There is no shell, no
arbitrary key or command, and no screen sharing. Remote control is off by
default; the owner enables it, chooses which phones may use it and which
adapters are offered. Typing text into the focused app is a separate opt-in."""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import threading
import time
from uuid import uuid4

MAX_TEXT = 500
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
BROWSERS = {"chrome", "msedge", "firefox", "brave", "opera", "vivaldi", "chromium", "chromium-browser", "google-chrome", "firefox-esr"}
PRESENTERS = {"powerpnt", "soffice", "soffice.bin", "acrord32", "acrobat", "sumatrapdf", "okular", "evince", "libreoffice", *BROWSERS}

# Windows virtual-key codes for the fixed controls.
VK = {"media_play_pause": 0xB3, "media_prev": 0xB1, "media_next": 0xB0, "volume_down": 0xAE, "volume_up": 0xAF,
      "volume_mute": 0xAD, "right": 0x27, "left": 0x25, "f5": 0x74, "escape": 0x1B, "b": 0x42, "k": 0x4B,
      "j": 0x4A, "l": 0x4C, "f": 0x46, "c": 0x43, "m": 0x4D, "return": 0x0D, "tab": 0x09, "backspace": 0x08}
XDOTOOL = {"right": "Right", "left": "Left", "f5": "F5", "escape": "Escape", "b": "b", "k": "k", "j": "j", "l": "l",
           "f": "f", "c": "c", "m": "m", "return": "Return", "tab": "Tab", "backspace": "BackSpace"}


def button(ident, label, key=None, action=None):
    return {"id": ident, "label": label, "kind": "button", "key": key, "action": action}


ADAPTERS = {
    "media": {"name": "Media", "default": True, "scope": None, "controls": [
        button("play_pause", "Play / pause", "media_play_pause", "play-pause"), button("previous", "Previous", "media_prev", "previous"),
        button("next", "Next", "media_next", "next"), button("volume_down", "Volume −", "volume_down", "volume-down"),
        button("volume_up", "Volume +", "volume_up", "volume-up"), button("mute", "Mute", "volume_mute", "mute")]},
    "presentation": {"name": "Presentation", "default": True, "scope": PRESENTERS, "controls": [
        button("previous", "Previous slide", "left"), button("next", "Next slide", "right"),
        button("start", "Start slideshow", "f5"), button("black", "Black screen", "b"), button("end", "End slideshow", "escape")]},
    "video": {"name": "Web video", "default": True, "scope": BROWSERS, "controls": [
        button("play_pause", "Play / pause", "k"), button("back", "Back 10 s", "j"), button("forward", "Forward 10 s", "l"),
        button("fullscreen", "Full screen", "f"), button("captions", "Captions", "c"), button("mute", "Mute", "m")]},
    "system": {"name": "This computer", "default": False, "scope": None, "controls": [
        button("lock", "Lock computer", action="lock")]},
    "keyboard": {"name": "Type into the focused app", "default": False, "scope": None, "controls": [
        {"id": "type", "label": "Text to type", "kind": "text", "max": MAX_TEXT, "key": None, "action": "type"},
        button("enter", "Enter", "return"), button("tab", "Tab", "tab"), button("backspace", "Backspace", "backspace"),
        button("escape", "Escape", "escape")]},
}


def validate_options(options, current=None):
    if not isinstance(options, dict) or set(options) - {"enabled", "adapters", "devices"}:
        raise ValueError("Unknown remote control preference.")
    if "enabled" in options and type(options["enabled"]) is not bool:
        raise ValueError("Remote control is on or off.")
    adapters = options.get("adapters", {})
    if not isinstance(adapters, dict) or set(adapters) - set(ADAPTERS) or any(type(v) is not bool for v in adapters.values()):
        raise ValueError("Choose which apps the phone may control.")
    devices = options.get("devices", [])
    if not isinstance(devices, list) or len(devices) > 32 or any(not isinstance(d, str) or not 0 < len(d) <= 128 for d in devices):
        raise ValueError("Choose which phones may control this computer.")
    merged = {**(current or {}), **options}
    if "adapters" in options:
        merged["adapters"] = {**((current or {}).get("adapters") or {}), **adapters}
    return merged


def _foreground_windows():
    """Executable name of the foreground window's process, lower case without .exe."""
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    window = user32.GetForegroundWindow()
    if not window:
        return None
    pid = ctypes.c_ulong(0)
    user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        size = ctypes.c_ulong(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return os.path.basename(buffer.value).lower().removesuffix(".exe")
    finally:
        kernel32.CloseHandle(handle)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _Union(ctypes.Union):
        # MOUSEINPUT is the largest member, so cbSize matches Windows on 32 and 64 bit.
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]
    _anonymous_ = ("union",)
    _fields_ = [("type", ctypes.c_ulong), ("union", _Union)]


def _send_windows(events):
    inputs = (INPUT * len(events))()
    for index, (vk, scan, flags) in enumerate(events):
        inputs[index].type = 1  # INPUT_KEYBOARD
        inputs[index].ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    if ctypes.windll.user32.SendInput(len(events), inputs, ctypes.sizeof(INPUT)) != len(events):
        raise ValueError("This computer did not accept the input. Elevated windows cannot be controlled.")


class SystemControls:
    """Platform side effects, kept apart so the policy can be tested without them."""

    def __init__(self, runner=subprocess.run):
        self.runner = runner
        self.wayland = sys.platform.startswith("linux") and os.environ.get("XDG_SESSION_TYPE") == "wayland"

    def _run(self, command):
        try:
            result = self.runner(command, capture_output=True, timeout=10, check=False, stdin=subprocess.DEVNULL, **NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError("This computer could not perform that control.") from None
        if result.returncode:
            raise ValueError("This computer could not perform that control.")
        return result.stdout.decode("utf-8", "replace") if isinstance(result.stdout, bytes) else (result.stdout or "")

    def keys_available(self):
        return sys.platform == "win32" or (sys.platform.startswith("linux") and not self.wayland and bool(shutil.which("xdotool")))

    def available(self, adapter):
        if adapter == "media":
            return sys.platform == "win32" or bool(shutil.which("playerctl") or shutil.which("pactl"))
        if adapter == "system":
            return sys.platform == "win32" or bool(shutil.which("loginctl"))
        return self.keys_available()

    def foreground(self):
        if sys.platform == "win32":
            try:
                return _foreground_windows()
            except (OSError, AttributeError):
                return None
        if self.keys_available():
            try:
                pid = int(self._run(["xdotool", "getactivewindow", "getwindowpid"]).strip())
                with open(f"/proc/{pid}/comm", encoding="utf-8") as comm:
                    return comm.read().strip().lower()
            except (ValueError, OSError):
                return None
        return None

    def key(self, name):
        if sys.platform == "win32":
            vk = VK[name]
            extended = 0x0001 if vk in {0x25, 0x27} else 0  # KEYEVENTF_EXTENDEDKEY for arrows.
            _send_windows([(vk, 0, extended), (vk, 0, extended | 0x0002)])
        else:
            self._run(["xdotool", "key", "--clearmodifiers", XDOTOOL[name]])

    def media(self, action):
        if shutil.which("playerctl") and action in {"play-pause", "previous", "next"}:
            self._run(["playerctl", action])
        elif shutil.which("pactl") and action in {"volume-down", "volume-up", "mute"}:
            command = {"volume-down": ["set-sink-volume", "@DEFAULT_SINK@", "-5%"], "volume-up": ["set-sink-volume", "@DEFAULT_SINK@", "+5%"],
                       "mute": ["set-sink-mute", "@DEFAULT_SINK@", "toggle"]}[action]
            self._run(["pactl", *command])
        else:
            raise ValueError("Install playerctl and PulseAudio/PipeWire tools to use media controls.")

    def lock(self):
        if sys.platform == "win32":
            if not ctypes.windll.user32.LockWorkStation():
                raise ValueError("This computer could not be locked.")
        else:
            self._run(["loginctl", "lock-session"])

    def type(self, text):
        if sys.platform == "win32":
            data, events = text.encode("utf-16-le"), []
            for index in range(0, len(data), 2):
                code = int.from_bytes(data[index:index + 2], "little")  # Surrogate pairs are sent unit by unit.
                events += [(0, code, 0x0004), (0, code, 0x0004 | 0x0002)]  # KEYEVENTF_UNICODE
            _send_windows(events)
        else:
            self._run(["xdotool", "type", "--clearmodifiers", "--delay", "8", "--", text])


class Remote:
    def __init__(self, workspace, publish, controls=None, clock=time.monotonic):
        self.workspace, self.publish = workspace, publish
        self.controls = controls or SystemControls()
        self.clock = clock
        self.lock = threading.Lock()
        self.recent = {}  # (device, typing) -> recent command times, for rate limiting.
        self.last = None  # Most recent command, shown on the settings page.

    def options(self):
        return (self.workspace.settings.get("link") or {}).get("remote") or {}

    def enabled(self):
        return self.options().get("enabled") is True

    def adapter_enabled(self, ident):
        return (self.options().get("adapters") or {}).get(ident, ADAPTERS[ident]["default"]) is True

    def allowed(self, device):
        return self.enabled() and device in (self.options().get("devices") or [])

    def catalog(self):
        apps = []
        for ident, adapter in ADAPTERS.items():
            if not self.adapter_enabled(ident):
                continue
            available = self.controls.available(ident)
            apps.append({"id": ident, "name": adapter["name"], "available": available,
                         "controls": [{key: control[key] for key in ("id", "label", "kind", "max") if key in control} for control in adapter["controls"]]})
        return {"apps": apps}

    def event(self, frame):
        kind = frame["type"]
        if kind not in {"remote.catalog.request", "remote.command"}:
            return False
        source = frame["source"]
        if not self.allowed(source):
            # Not an approved controller: no catalog and no side effect, only a refusal.
            self._reply(source, "remote.result", {"app": "", "control": "", "ok": False,
                                                  "message": "Allow this phone in Saiph's remote control settings on the computer."})
            return True
        if kind == "remote.catalog.request":
            if frame["payload"] != {}:
                raise ValueError("Invalid remote request.")
            self._reply(source, "remote.catalog", self.catalog())
            return True
        payload = frame["payload"] if isinstance(frame["payload"], dict) else {}  # Older Hubs do not validate it.
        app, control = payload.get("app"), payload.get("control")
        try:
            self.command(source, payload)
            result = {"app": app, "control": control, "ok": True, "message": ""}
        except ValueError as error:
            result = {"app": str(app)[:32], "control": str(control)[:32], "ok": False, "message": str(error)[:200]}
        self._reply(source, "remote.result", result)
        return True

    def command(self, source, payload):
        if not isinstance(payload, dict) or set(payload) - {"app", "control", "text"} or not {"app", "control"} <= set(payload):
            raise ValueError("Invalid remote command.")
        app, control = payload["app"], payload["control"]
        adapter = ADAPTERS.get(app) if isinstance(app, str) else None
        if adapter is None or not self.adapter_enabled(app):
            raise ValueError("That app is not offered by this computer.")
        spec = next((c for c in adapter["controls"] if c["id"] == control), None)
        if spec is None:
            raise ValueError("Unknown control.")
        text = payload.get("text")
        if spec["kind"] == "text":
            if not isinstance(text, str) or not 0 < len(text) <= MAX_TEXT or any(ord(c) < 32 or 0x7F <= ord(c) < 0xA0 for c in text):
                raise ValueError(f"Type up to {MAX_TEXT} characters on one line.")
        elif "text" in payload:
            raise ValueError("Invalid remote command.")
        self._rate_limit(source, spec["kind"] == "text")
        if not self.controls.available(app):
            raise ValueError("This control is unavailable on this computer." + (" Wayland does not allow apps to send keys." if self.controls.wayland else ""))
        scope = adapter["scope"]
        if scope is not None:
            current = self.controls.foreground()
            if current not in scope:
                raise ValueError("Bring the " + adapter["name"].lower() + " window to the front on the computer first.")
        if spec["action"] == "lock":
            self.controls.lock()
        elif spec["action"] == "type":
            self.controls.type(text)
        elif app == "media" and sys.platform != "win32":
            self.controls.media(spec["action"])
        else:
            self.controls.key(spec["key"])
        self.last = {"device_id": source, "app": app, "control": control, "at": time.time()}

    def _rate_limit(self, source, typing):
        now = self.clock()
        with self.lock:
            key = (source, typing)  # Button presses and typed text have separate budgets.
            times = [t for t in self.recent.get(key, []) if now - t < 1]
            if len(times) >= (2 if typing else 10):
                raise ValueError("Too many controls at once. Try again in a moment.")
            self.recent[key] = times + [now]

    def _reply(self, target, kind, payload):
        try:
            self.publish({"id": str(uuid4()), "type": kind, "ttl_seconds": 30, "targets": [target], "payload": payload})
        except ValueError:
            pass  # Offline: the phone shows that no answer arrived.

    def status(self):
        options = self.options()
        return {"enabled": self.enabled(), "devices": list(options.get("devices") or []),
                "adapters": {ident: {"name": adapter["name"], "enabled": self.adapter_enabled(ident), "available": self.controls.available(ident)}
                             for ident, adapter in ADAPTERS.items()},
                "wayland": self.controls.wayland, "last": self.last}
