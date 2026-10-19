# SPDX-License-Identifier: AGPL-3.0-or-later
"""Talk on a phone call through this Linux computer's microphone and speakers.

Plan item B2 (docs/research/CALL_AUDIO_SPIKE.md, docs/CALL_AUDIO.md). The audio
travels only over Bluetooth Hands-Free (HFP) between the phone and this computer:
the phone is the audio gateway and PipeWire takes the hands-free role. Nothing
about call audio is ever sent to Saiph Cloud, a Hub or any other network service.

Saiph's phone-app events stay the source of truth for calls (who is calling,
answer and decline through the unchanged `call.command`). This module only adds
the audio route:

- while a call rings it keeps the audio on the phone (`RejectSCO`), so the phone's
  in-band ringtone does not ring here twice and a call answered on the phone stays
  there;
- "Answer" on this computer then lets the audio through and asks for the Bluetooth
  audio link (`AudioGatewayTransport1.Activate`);
- when the phone app is unreachable but Bluetooth is connected, PipeWire's
  telephony interface can answer or decline instead.

Call control and the audio switch use PipeWire's `org.pipewire.Telephony` on the
user's session bus (PipeWire 1.4 and later), through `busctl --user`. Older
PipeWire still carries the audio; Android sends it to the connected hands-free
device on its own. The optional setup step only writes or removes one per-user
WirePlumber file of Saiph's own and restarts WirePlumber as the user, after the
user asked for it. Nothing needs root."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .bt_lock import MAC
from .call_audio_probe import CallAudioProbe, text_version, verdict, wireplumber_settings

GATEWAY_UUID = "0000111f-0000-1000-8000-00805f9b34fb"   # The phone offers phone calls (Handsfree Audio Gateway).
TELEPHONY = "org.pipewire.Telephony"
ROOT_PATH = "/org/pipewire/Telephony"
AG_INTERFACE = TELEPHONY + ".AudioGateway1"
TRANSPORT_INTERFACE = TELEPHONY + ".AudioGatewayTransport1"
CALL_INTERFACE = TELEPHONY + ".Call1"
OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"
CODECS = {1: "CVSD", 2: "mSBC", 3: "LC3-SWB"}             # HFP codec IDs.
RINGING = {"incoming", "waiting"}
LIVE = {"active", "held", "dialing", "alerting", "incoming", "waiting"}
SETUP_MARKER = "Saiph: calls through this computer"
SETUP_NAME = "51-saiph-hfp-hf"
TIMEOUT = 5
REFRESH_SECONDS = 20
ROUTE_SECONDS = 10
MAX_DEVICES = 16
IDLE = {"state": "idle", "message": "", "codec": ""}
AWAY_MESSAGE = ("The call audio stayed on your phone. Choose this computer on your phone's call screen, "
                "or check that Phone calls is on for this computer in your phone's Bluetooth settings.")


def validate_options(options):
    if not isinstance(options, dict) or set(options) - {"enabled", "device"}:
        raise ValueError("Unknown call audio preference.")
    if "enabled" in options and type(options["enabled"]) is not bool:
        raise ValueError("Call audio on this computer is on or off.")
    if "device" in options and (not isinstance(options["device"], str) or not (MAC.fullmatch(options["device"]) or options["device"] == "")):
        raise ValueError("Choose a paired Bluetooth phone.")
    return dict(options)


def adapter_state(text):
    """`bluetoothctl show`: is there an adapter, and is it powered (None when unknown)?"""
    if not text or "Controller" not in text:
        return {"present": False, "powered": None}
    powered = re.search(r"^\s*Powered:\s*(yes|no)\s*$", text, re.MULTILINE)
    return {"present": True, "powered": None if powered is None else powered.group(1) == "yes"}


def device_state(text):
    """`bluetoothctl info <MAC>`: paired, connected, and does it offer phone calls (the audio gateway role)?"""
    if not text:
        return {"paired": False, "connected": False, "gateway": False}
    flag = lambda name: re.search(rf"^\s*{name}:\s*yes\s*$", text, re.MULTILINE) is not None
    return {"paired": flag("Paired"), "connected": flag("Connected"), "gateway": GATEWAY_UUID in text.lower()}


def paired_devices(text):
    devices = []
    for line in (text or "").splitlines():
        parts = line.split(" ", 2)
        if len(parts) >= 2 and parts[0] == "Device" and MAC.fullmatch(parts[1]):
            devices.append({"address": parts[1], "name": (parts[2] if len(parts) > 2 else parts[1])[:80]})
    return devices[:MAX_DEVICES]


def _value(properties, name, default=None):
    """busctl --json=short wraps each property as {"type": ..., "data": ...}."""
    item = (properties or {}).get(name)
    return item.get("data", default) if isinstance(item, dict) else default


def readiness(facts, options):
    """(state, message) for the setup card. Pure, so every combination is unit-tested.

    unsupported | checking | no-adapter | bluetooth-off | needs-setup | choose-phone |
    not-paired | no-calls-profile | phone-away | ready"""
    if facts is None:
        return "checking", "Checking Bluetooth and sound on this computer…"
    probe = facts.get("probe") or {}
    if probe.get("audio") == "unsupported":
        issues = probe.get("issues") or ["This computer cannot take calls over Bluetooth."]
        return "unsupported", issues[0]
    adapter = facts.get("adapter") or {}
    if not adapter.get("present"):
        return "no-adapter", "No Bluetooth adapter was found on this computer."
    if adapter.get("powered") is False:
        return "bluetooth-off", "Turn on Bluetooth on this computer."
    if probe.get("audio") != "ready":
        return "needs-setup", "This computer is not yet set up as a hands-free device for your phone."
    device = options.get("device") or ""
    if not device:
        return "choose-phone", "Choose the phone you paired with this computer."
    phone = (facts.get("phones") or {}).get(device)
    if not phone or not phone.get("paired"):
        return "not-paired", "That phone is no longer paired with this computer. Pair it again in Bluetooth settings."
    if not phone.get("gateway"):
        return "no-calls-profile", ("Your phone does not share phone calls with this computer. On your phone, open "
                                    "Bluetooth, tap this computer and turn on Phone calls.")
    if not phone.get("connected"):
        return "phone-away", "Your phone is paired but not connected over Bluetooth. Bring it nearby or connect it."
    return "ready", "Calls you answer here use this computer's microphone and speakers."


class Telephony:
    """PipeWire's telephony interface on the session bus, through `busctl --user`."""

    def __init__(self, run):
        self.run = run   # run(*arguments) -> stdout, or None when the command failed.

    def _objects(self, path):
        output = self.run("busctl", "--user", "--json=short", "call", TELEPHONY, path, OBJECT_MANAGER, "GetManagedObjects")
        try:
            data = json.loads(output)["data"][0] if output else None
        except (ValueError, KeyError, IndexError, TypeError):
            return None
        return data if isinstance(data, dict) else None

    def gateways(self):
        """[{path, address, transport: {state, codec, reject_sco}, calls: [...]}], or None when unavailable."""
        objects = self._objects(ROOT_PATH)
        if objects is None:
            return None
        found = []
        for path, interfaces in sorted(objects.items()):
            if not isinstance(interfaces, dict) or AG_INTERFACE not in interfaces:
                continue
            transport = interfaces.get(TRANSPORT_INTERFACE) or {}
            children = {key: value for key, value in objects.items() if key.startswith(path + "/")}
            if not children:
                children = self._objects(path) or {}
            calls = []
            for call_path, call_interfaces in sorted(children.items()):
                call = (call_interfaces or {}).get(CALL_INTERFACE) if isinstance(call_interfaces, dict) else None
                if call is not None:
                    calls.append({"path": call_path, "state": str(_value(call, "State", "")),
                                  "line": str(_value(call, "LineIdentification", "")), "name": str(_value(call, "Name", ""))})
            codec = _value(transport, "Codec")
            found.append({"path": path, "address": str(_value(interfaces[AG_INTERFACE], "Address", "")).upper(),
                          "transport": {"state": str(_value(transport, "State", "")),
                                        "codec": CODECS.get(codec, str(codec) if codec is not None else ""),
                                        "reject_sco": _value(transport, "RejectSCO")},
                          "calls": calls})
        return found

    def gateway(self, address):
        gateways = self.gateways()
        if gateways is None:
            return None
        return next((row for row in gateways if row["address"] == address.upper()), None)

    def set_reject_sco(self, path, value):
        return self.run("busctl", "--user", "set-property", TELEPHONY, path, TRANSPORT_INTERFACE,
                        "RejectSCO", "b", "true" if value else "false") is not None

    def activate(self, path):
        return self.run("busctl", "--user", "call", TELEPHONY, path, TRANSPORT_INTERFACE, "Activate") is not None

    def answer(self, path):
        return self.run("busctl", "--user", "call", TELEPHONY, path, CALL_INTERFACE, "Answer") is not None

    def hangup(self, path):
        return self.run("busctl", "--user", "call", TELEPHONY, path, CALL_INTERFACE, "Hangup") is not None


class CallAudio:
    """Detection, setup and the per-call audio route. Linux only; inert elsewhere."""

    def __init__(self, settings, *, runner=subprocess.run, which=shutil.which, platform=None, home=None, root="/",
                 clock=time.monotonic, sleep=time.sleep, threaded=True):
        self.settings, self.runner, self.which = settings, runner, which
        self.platform = platform or sys.platform
        self.home, self.root = Path(home or Path.home()), root
        self.clock, self.sleep, self.threaded = clock, sleep, threaded
        self.changed = lambda: None          # The desktop app points this at its state-changed signal.
        self.telephony = Telephony(self._run)
        self.error = ""
        self.session = dict(IDLE)
        self._lock = threading.RLock()
        self._facts = None                  # (checked_at, facts)
        self._checking = False
        self._restore = None                # (gateway path, RejectSCO before Saiph held the audio on the phone)

    # Detection -------------------------------------------------------------------------
    def supported(self):
        return self.platform.startswith("linux")

    def options(self):
        return (self.settings.get("link") or {}).get("call_audio") or {}

    def _run(self, *arguments):
        if not self.which(arguments[0]):
            return None
        try:
            result = self.runner(list(arguments), capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout if result.returncode == 0 else None

    def config_home(self):
        return Path(os.environ.get("XDG_CONFIG_HOME") or self.home / ".config")

    def setup_file(self, wireplumber):
        """Saiph's own per-user WirePlumber file for this WirePlumber version."""
        if wireplumber and wireplumber[:2] < (0, 5):
            return self.config_home() / "wireplumber" / "bluetooth.lua.d" / (SETUP_NAME + ".lua")
        return self.config_home() / "wireplumber" / "wireplumber.conf.d" / (SETUP_NAME + ".conf")

    def inspect(self):
        """Read-only facts: the probe, the adapter, paired phones and PipeWire's gateways. Blocking."""
        prober = CallAudioProbe(runner=self.runner, which=self.which, platform=self.platform, home=self.home, root=self.root)
        facts = prober.facts()
        probe = {**verdict(facts), "versions": {key: text_version(facts[key]) for key in ("pipewire", "wireplumber", "bluez")},
                 "settings": facts["settings"], "handsfree_registered": facts["handsfree_registered"]}
        adapter = adapter_state(self._run("bluetoothctl", "show"))
        devices = paired_devices(self._run("bluetoothctl", "devices", "Paired") or self._run("bluetoothctl", "paired-devices"))
        phones = {}
        for device in devices:
            phones[device["address"]] = device_state(self._run("bluetoothctl", "info", device["address"]))
        chosen = self.options().get("device") or ""
        if chosen and chosen not in phones:
            phones[chosen] = device_state(self._run("bluetoothctl", "info", chosen))
        pipewire = facts.get("pipewire")
        gateways = self.telephony.gateways() if pipewire and pipewire >= (1, 4) else None
        path = self.setup_file(facts.get("wireplumber")) if facts.get("wireplumber") else None
        return {"probe": probe, "adapter": adapter, "devices": devices, "phones": phones, "gateways": gateways,
                "wireplumber": facts.get("wireplumber"), "setup_file": str(path) if path else "",
                "setup_applied": bool(path and _ours(path))}

    def refresh(self, wait=False):
        """Start a fresh check (on a worker unless wait); the page hears `changed` when it finishes."""
        if not self.supported():
            return {"supported": False}
        with self._lock:
            if self._checking:
                return {"queued": True}
            self._checking = True
        def check():
            try:
                facts = self.inspect()
                with self._lock:
                    self._facts = (self.clock(), facts)
            except Exception:
                self.error = "Saiph could not check Bluetooth on this computer."
            finally:
                with self._lock:
                    self._checking = False
                self.changed()
        if wait or not self.threaded:
            check()
        else:
            threading.Thread(target=check, name="saiph-call-audio-check", daemon=True).start()
        return {"queued": True}

    def facts(self):
        with self._lock:
            cached = self._facts
        if cached is None or self.clock() - cached[0] >= REFRESH_SECONDS:
            self.refresh()
            with self._lock:
                cached = self._facts or cached
        return cached[1] if cached else None

    def status(self, calls=()):
        options = self.options()
        base = {"supported": self.supported(), "platform": self.platform, "windows": self.platform == "win32",
                "enabled": options.get("enabled") is True, "device": options.get("device") or ""}
        if not self.supported():
            return base
        self._reconcile(calls)
        facts = self.facts()
        state, message = readiness(facts, options)
        probe = (facts or {}).get("probe") or {}
        phone = ((facts or {}).get("phones") or {}).get(base["device"]) or {}
        return {**base, "readiness": state, "message": message, "checking": self._checking,
                "devices": [{**row, **((facts or {}).get("phones") or {}).get(row["address"], {})} for row in (facts or {}).get("devices", [])],
                "phone_connected": bool(phone.get("connected") and phone.get("gateway")),
                "versions": probe.get("versions") or {}, "call_control": probe.get("call_control", "app"),
                "issues": probe.get("issues") or [],
                "setup": self._setup_status(facts, state), "session": dict(self.session), "error": self.error}

    def _setup_status(self, facts, state):
        facts = facts or {}
        probe = facts.get("probe") or {}
        settings = probe.get("settings") or {}
        configured = "hfp_hf" in settings.get("roles", ())
        if state == "needs-setup" and facts.get("wireplumber"):
            action = "restart" if configured else "write"
        else:
            action = ""
        return {"action": action, "file": facts.get("setup_file", ""), "applied": bool(facts.get("setup_applied"))}

    # Setup (only on the user's request) ------------------------------------------------
    def apply_setup(self):
        """Turn on WirePlumber's hands-free role for this user, then restart WirePlumber as the user."""
        facts = self._require_linux_facts()
        wireplumber = facts.get("wireplumber")
        if not wireplumber:
            raise ValueError("WirePlumber was not found, so Saiph cannot turn on the hands-free role.")
        settings = wireplumber_settings(wireplumber, home=self.home, root=self.root, config_home=self.config_home())
        if "hfp_hf" not in settings["roles"]:
            path = self.setup_file(wireplumber)
            if path.exists() and not _ours(path):
                raise ValueError(f"{path} already exists and was not written by Saiph. It was left unchanged.")
            roles = list(settings["roles"]) + ["hfp_hf"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(setup_text(wireplumber, roles), encoding="utf-8")
        self._spawn(self._restart_wireplumber)
        return {"queued": True}

    def remove_setup(self):
        facts = self._require_linux_facts()
        path = self.setup_file(facts.get("wireplumber"))
        if not _ours(path):
            return {"removed": False}
        path.unlink()
        self._spawn(self._restart_wireplumber)
        return {"removed": True}

    def _require_linux_facts(self):
        if not self.supported():
            raise ValueError("Calls through this computer's audio are available on Linux only for now.")
        facts = self.facts()
        if facts is None:
            self.refresh(wait=True)
            facts = self.facts()
        if facts is None:
            raise ValueError("Saiph could not check Bluetooth on this computer.")
        return facts

    def _restart_wireplumber(self):
        if self._run("systemctl", "--user", "restart", "wireplumber") is None:
            self.error = "WirePlumber could not be restarted. Sign out and back in to finish the setup."
        else:
            self.error = ""
        self.sleep(2)   # Let WirePlumber register the hands-free profile with Bluetooth again.
        with self._lock:
            self._facts = None
        self.refresh(wait=True)

    # The call -----------------------------------------------------------------------------
    def active(self):
        """On, chosen and ready: Saiph should route calls answered here."""
        if not self.supported() or self.options().get("enabled") is not True:
            return False
        facts = self.facts()
        return readiness(facts, self.options())[0] == "ready"

    def _set(self, state, message="", codec=""):
        with self._lock:
            self.session = {"state": state, "message": message, "codec": codec}
        self.changed()

    def _spawn(self, work):
        if self.threaded:
            threading.Thread(target=work, name="saiph-call-audio", daemon=True).start()
        else:
            work()

    def _gateway(self):
        device = self.options().get("device") or ""
        return self.telephony.gateway(device) if device else None

    def call_state(self, state):
        """The phone app's call state (Link and Saiph Cloud phones alike): ringing, active, missed or ended."""
        if not self.supported() or self.options().get("enabled") is not True:
            return
        if state == "ringing":
            self._spawn(self._hold_on_phone)
        elif state == "active":
            with self._lock:
                answered_elsewhere = self.session["state"] in {"idle", "ringing"}
            if answered_elsewhere:
                self._set("on-phone", "The call is on your phone.")
        elif state in {"missed", "ended"}:
            self._spawn(self._finish)

    def _hold_on_phone(self):
        """Keep a ringing call's audio on the phone until it is answered here (no second ringtone here)."""
        if not self.active():
            return
        gateway = self._gateway()
        if gateway and gateway["transport"]["reject_sco"] is False:
            if self.telephony.set_reject_sco(gateway["path"], True):
                with self._lock:
                    self._restore = (gateway["path"], False)
        self._set("ringing")

    def _finish(self):
        with self._lock:
            restore, self._restore = self._restore, None
        if restore:
            self.telephony.set_reject_sco(*restore)
        self._set("idle")

    def _reconcile(self, calls):
        """A missed end-of-call event must not leave the session stuck."""
        with self._lock:
            busy = self.session["state"] != "idle"
        if busy and calls is not None and not any(row.get("state") in {"ringing", "active"} for row in calls):
            self._spawn(self._finish)

    def answered_here(self):
        """The existing Answer on this computer was sent; bring the audio here when set up."""
        if not self.active():
            return None
        self._set("connecting", "Connecting the call audio to this computer…")
        self._spawn(self._route)
        return {"audio": "connecting"}

    def answered_on_phone(self):
        """Answer from here but keep talking on the phone: the audio stays held on the phone."""
        if self.active():
            self._set("on-phone", "The call is on your phone.")

    def move_here(self):
        if not self.supported():
            raise ValueError("Calls through this computer's audio are available on Linux only for now.")
        if not self.active():
            raise ValueError("Set up calls through this computer first.")
        self._set("connecting", "Connecting the call audio to this computer…")
        self._spawn(self._route)
        return {"audio": "connecting"}

    def fallback(self, operation):
        """The phone app could not be reached: answer or decline over Bluetooth instead. None when impossible."""
        if operation not in {"answer", "reject"} or not self.active():
            return None
        gateway = self._gateway()
        call = next((row for row in (gateway or {}).get("calls", []) if row["state"] in RINGING), None)
        if call is None:
            return None
        if operation == "reject":
            return {"queued": True, "via": "bluetooth"} if self.telephony.hangup(call["path"]) else None
        if not self.telephony.answer(call["path"]):
            return None
        self._set("connecting", "Connecting the call audio to this computer…")
        self._spawn(self._route)
        return {"queued": True, "via": "bluetooth", "audio": "connecting"}

    def _route(self):
        """Let the audio through, ask for the Bluetooth audio link once the call is live, and confirm it arrived."""
        device = self.options().get("device") or ""
        deadline = self.clock() + ROUTE_SECONDS
        gateway = self._gateway()
        if gateway is None:
            # No telephony interface (PipeWire before 1.4): Android sends the audio to the connected
            # hands-free device on its own; confirm PipeWire made the Bluetooth call streams.
            while self.clock() < deadline:
                if self.bluetooth_nodes(device):
                    self._set("here", "Talking through this computer.")
                    return
                self.sleep(0.5)
            self._set("on-phone", AWAY_MESSAGE)
            return
        # A RejectSCO held while ringing is put back when the call ends (_finish).
        if gateway["transport"]["reject_sco"] is not False and not self.telephony.set_reject_sco(gateway["path"], False):
            self._set("failed", "Saiph could not switch the call audio to this computer.")
            return
        activated = False
        while True:
            transport = gateway["transport"]
            if transport["state"] == "active":
                self._set("here", "Talking through this computer.", transport["codec"])
                return
            live = any(call["state"] in LIVE - RINGING for call in gateway["calls"])
            if live and not activated and transport["state"] in {"idle", "error", ""}:
                activated = True
                if not self.telephony.activate(gateway["path"]):
                    self._set("failed", "Saiph could not open the Bluetooth audio link. " + AWAY_MESSAGE)
                    return
            if self.clock() >= deadline:
                break
            self.sleep(0.5)
            gateway = self._gateway()
            if gateway is None:
                self._set("failed", "Your phone disconnected from this computer's Bluetooth.")
                return
        self._set("on-phone", AWAY_MESSAGE)

    def bluetooth_nodes(self, address):
        """PipeWire nodes for this phone's Bluetooth audio, as listed by pactl (PipeWire's Pulse server)."""
        token = address.replace(":", "_").lower()
        names = []
        for kind in ("sources", "sinks"):
            for line in (self._run("pactl", "list", "short", kind) or "").splitlines():
                parts = line.split("\t")
                if len(parts) > 1 and parts[1].lower().startswith("bluez") and token in parts[1].lower():
                    names.append(parts[1])
        return names


def setup_text(wireplumber, roles):
    roles = " ".join(dict.fromkeys(roles))
    if wireplumber and wireplumber[:2] < (0, 5):
        return (f"-- {SETUP_MARKER} (Bluetooth hands-free). Turn it off in Saiph or delete this file to undo.\n"
                f'bluez_monitor.properties["bluez5.headset-roles"] = "[ {roles} ]"\n')
    return (f"# {SETUP_MARKER} (Bluetooth hands-free). Turn it off in Saiph or delete this file to undo.\n"
            "monitor.bluez.properties = {\n"
            f"  bluez5.roles = [ {roles} ]\n"
            "}\n")


def _ours(path):
    try:
        with Path(path).open(encoding="utf-8", errors="replace") as handle:
            return SETUP_MARKER in handle.readline()
    except OSError:
        return False
