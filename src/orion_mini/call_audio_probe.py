# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read-only check: can this Linux computer act as a Bluetooth hands-free unit for a phone?

Research spike B2 (docs/research/CALL_AUDIO_SPIKE.md). Phone calls can reach the
computer's speakers and microphone only over Bluetooth Hands-Free (HFP), with the
computer in the hands-free ("HF") role. On Linux that role comes from PipeWire's
native Bluetooth backend (WirePlumber's ``hfp_hf`` role); PipeWire 1.4 and later
also offer call control on the session bus as ``org.pipewire.Telephony``.

This module only *reads* state: version banners, WirePlumber configuration files
and the adapter's registered profiles. It never writes configuration, restarts a
service, pairs a device or opens an audio connection. It is not wired into the
app yet; the prototype plan in the spike document decides whether it will be."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HANDSFREE_UUID = "0000111e-0000-1000-8000-00805f9b34fb"     # Our adapter offers the HF role.
TELEPHONY_SERVICE = "org.pipewire.Telephony"
VERSION = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")
TIMEOUT = 5

# WirePlumber defaults, from its Bluetooth configuration documentation.
DEFAULT_ROLES_04 = ("hsp_hs", "hfp_ag")                                       # bluez5.headset-roles, 0.4
DEFAULT_ROLES_05 = ("a2dp_sink", "a2dp_source", "bap_sink", "bap_source", "hfp_hf", "hfp_ag")  # bluez5.roles, 0.5


def parse_version(text):
    """First dotted version in a banner such as 'Linked with libpipewire 1.0.5' or 'bluetoothctl: 5.72'."""
    if not text:
        return None
    for line in text.splitlines():
        if "linked with" in line.lower():   # The running library beats the compile-time one.
            match = VERSION.search(line)
            if match:
                return tuple(int(part or 0) for part in match.groups())
    match = VERSION.search(text)
    return tuple(int(part or 0) for part in match.groups()) if match else None


def text_version(version):
    return ".".join(map(str, version)) if version else ""


def _strip_comments(text, marker):
    return "\n".join(line.split(marker, 1)[0] for line in text.splitlines())


def _roles(value):
    return tuple(role for role in re.split(r"[\s,]+", value.strip()) if role)


def wireplumber_settings(wireplumber, *, home, root="/", config_home=None):
    """Effective HF-related settings from WirePlumber configuration files.

    Returns {roles, backend, telephony, files}; roles and backend fall back to the
    documented defaults. Later files override earlier ones: packaged defaults, then
    /etc, then the user's own directory. A hint only: the adapter's registered
    profiles (see probe) are what really count."""
    root, home = Path(root), Path(home)
    config_home = Path(config_home or os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    major_minor = wireplumber[:2] if wireplumber else None
    lua = major_minor is not None and major_minor < (0, 5)
    if lua:
        subdir, pattern, marker = "bluetooth.lua.d", "*.lua", "--"
        roles_re = re.compile(r'\[\s*"bluez5\.headset-roles"\s*\]\s*=\s*"\[([^\]]*)\]"')
        backend_re = re.compile(r'\[\s*"bluez5\.hfphsp-backend"\s*\]\s*=\s*"(\w+)"')
        telephony_re = None
        roles = DEFAULT_ROLES_04
    else:
        subdir, pattern, marker = "wireplumber.conf.d", "*.conf", "#"
        roles_re = re.compile(r'"?bluez5\.roles"?\s*[=:]\s*\[([^\]]*)\]')
        backend_re = re.compile(r'"?bluez5\.hfphsp-backend"?\s*[=:]\s*"?(\w+)"?')
        telephony_re = re.compile(r'"?bluez5\.telephony-dbus-service"?\s*[=:]\s*"?(true|false)"?')
        roles = DEFAULT_ROLES_05
    files = []
    for base in (root / "usr/share/wireplumber", root / "etc/wireplumber", config_home / "wireplumber"):
        if not lua and (base / "wireplumber.conf").is_file():
            files.append(base / "wireplumber.conf")
        directory = base / subdir
        if directory.is_dir():
            files.extend(sorted(directory.glob(pattern)))
    backend, telephony, used = "native", True, []
    for path in files:
        try:
            text = _strip_comments(path.read_text(encoding="utf-8", errors="replace"), marker)
        except OSError:
            continue
        found = False
        for match in roles_re.finditer(text):
            roles, found = _roles(match.group(1)), True
        for match in backend_re.finditer(text):
            backend, found = match.group(1), True
        for match in (telephony_re.finditer(text) if telephony_re else ()):
            telephony, found = match.group(1) == "true", True
        if found:
            used.append(str(path))
    return {"roles": list(roles), "backend": backend, "telephony": telephony, "files": used}


class CallAudioProbe:
    """Collects read-only facts and turns them into a short, user-facing verdict."""

    def __init__(self, *, runner=subprocess.run, which=shutil.which, platform=None, home=None, root="/"):
        self.runner, self.which = runner, which
        self.platform = platform or sys.platform
        self.home = home or Path.home()
        self.root = root

    def _run(self, *arguments):
        if not self.which(arguments[0]):
            return None
        try:
            result = self.runner(list(arguments), capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout if result.returncode == 0 else None

    def facts(self):
        pipewire = parse_version(self._run("pipewire", "--version"))
        wireplumber = parse_version(self._run("wireplumber", "--version"))
        bluez = parse_version(self._run("bluetoothctl", "--version"))
        info = self._run("pactl", "info") or ""
        server = re.search(r"^Server Name:\s*(.+)$", info, re.MULTILINE)
        server = server.group(1).strip() if server else ""
        adapter = self._run("bluetoothctl", "show")
        handsfree = None if adapter is None or "Controller" not in adapter else HANDSFREE_UUID in adapter.lower()
        names = self._run("busctl", "--user", "--no-pager", "--no-legend", "list")
        telephony_bus = None if names is None else any(line.split(" ", 1)[0] == TELEPHONY_SERVICE for line in names.splitlines())
        ofono_names = self._run("busctl", "--system", "--no-pager", "--no-legend", "list")
        ofono = None if ofono_names is None else any(line.split(" ", 1)[0] == "org.ofono" for line in ofono_names.splitlines())
        settings = wireplumber_settings(wireplumber, home=self.home, root=self.root) if wireplumber else None
        return {"pipewire": pipewire, "wireplumber": wireplumber, "bluez": bluez, "server": server,
                "handsfree_registered": handsfree, "telephony_on_bus": telephony_bus, "ofono_running": ofono,
                "settings": settings}

    def probe(self):
        if not self.platform.startswith("linux"):
            return {"platform": self.platform, "audio": "unsupported", "call_control": "app", "issues": [
                "Calls through this computer's audio are being researched for Windows; see the call audio spike."]}
        facts = self.facts()
        return {"platform": "linux", **verdict(facts),
                "versions": {key: text_version(facts[key]) for key in ("pipewire", "wireplumber", "bluez")},
                "server": facts["server"], "handsfree_registered": facts["handsfree_registered"],
                "settings": facts["settings"]}


def verdict(facts):
    """Decide from collected facts. audio: ready | needs-setup | unsupported | unknown.
    call_control: 'hfp' when PipeWire's telephony interface can answer and dial,
    otherwise 'app' (Saiph's existing phone-app commands)."""
    issues = []
    pipewire, wireplumber, settings = facts.get("pipewire"), facts.get("wireplumber"), facts.get("settings") or {}
    server = (facts.get("server") or "").lower()
    if facts.get("bluez") is None:
        issues.append("BlueZ (bluetoothctl) was not found.")
        return {"audio": "unsupported", "call_control": "app", "issues": issues}
    if pipewire is None or (server and "pipewire" not in server):
        issues.append("The sound server is not PipeWire. PulseAudio needs oFono for the hands-free role; "
                      "Saiph supports PipeWire only.")
        return {"audio": "unsupported", "call_control": "app", "issues": issues}
    if wireplumber is None:
        issues.append("WirePlumber was not found; another PipeWire session manager is not supported.")
        return {"audio": "unsupported", "call_control": "app", "issues": issues}
    if facts.get("ofono_running"):
        issues.append("oFono is running and may claim the hands-free role instead of PipeWire.")
    configured = "hfp_hf" in settings.get("roles", ()) and settings.get("backend", "native") in {"native", "any"}
    if not configured:
        issues.append("WirePlumber's hands-free role (hfp_hf) is off; a per-user configuration file can turn it on.")
    registered = facts.get("handsfree_registered")
    if registered is True:
        audio = "ready"
    elif registered is False:
        audio = "needs-setup"
        if configured:
            issues.append("The hands-free role is configured but not registered with Bluetooth; restart WirePlumber.")
    else:
        audio = "needs-setup" if not configured else "unknown"
        issues.append("Bluetooth is off or unavailable, so the hands-free role could not be confirmed.")
    # Saiph's own phone-app commands always work; HFP call control is an extra only when proven present.
    call_control = "app"
    if pipewire < (1, 4):
        pass  # The telephony interface arrived in PipeWire 1.4.0 (March 2025).
    elif not settings.get("telephony", True):
        issues.append("PipeWire's telephony interface is turned off in WirePlumber's configuration.")
    elif facts.get("telephony_on_bus"):
        call_control = "hfp"
    else:
        issues.append("PipeWire's telephony interface was not on the session bus; it may appear only once a phone connects.")
    return {"audio": audio, "call_control": call_control, "issues": issues}


def probe(**kwargs):
    return CallAudioProbe(**kwargs).probe()
