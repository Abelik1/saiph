# SPDX-License-Identifier: AGPL-3.0-or-later
"""Local network listeners that survive updates on Windows, and firewall checks.

Windows Firewall matches inbound connections by the full path of the listening
program. An installed Saiph runs from releases\\<version>\\app\\saiph.exe, a new
path after every update, so a rule the owner allowed once stopped matching and
the phone camera, phone screen and file transfers were blocked again (or a
missed prompt blocked them silently). The installer keeps SaiphNetwork.exe
(scripts/packaging/WindowsNetworkRelay.cs) at one fixed path next to the
releases folder; Saiph listens on 127.0.0.1 and the relay accepts the network
connections for it, so Windows asks about one program, once.

Source runs, Linux and installs without the relay listen directly, as before.
`firewall_state` only reads rules (no change, no elevation) so Saiph can say
clearly when Windows blocks the relay and how to allow it.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

RELAY = "SaiphNetwork.exe"
START_SECONDS = 5
FIREWALL_SETTINGS = ["control.exe", "/name", "Microsoft.WindowsFirewall", "/page", "pageConfigureApps"]
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def relay_path(executable=None, platform=None) -> Path | None:
    """The installed relay for this installed release, or None (source run, Linux, older install)."""
    if (platform or sys.platform) != "win32" or (executable is None and not getattr(sys, "frozen", False)):
        return None
    app = Path(executable or sys.executable).resolve().parent
    # <root>\releases\<version>\app\saiph.exe
    if app.name.lower() != "app" or app.parent.parent.name.lower() != "releases":
        return None
    relay = app.parent.parent.parent / RELAY
    return relay if relay.is_file() else None


class Relay:
    """One running relay forwarding <network port> to 127.0.0.1:<target>."""

    def __init__(self, process, port):
        self.process, self.port = process, port

    def close(self):
        process, self.process = self.process, None
        if process is None:
            return
        try:
            process.stdin.close()  # The relay exits when its input closes.
        except OSError:
            pass
        try:
            process.wait(2)
        except subprocess.TimeoutExpired:
            process.kill()
        except OSError:
            pass


def start(path: Path, target: int, *, popen=subprocess.Popen, loopback=False) -> Relay | None:
    """Start the relay for one loopback listener; None if it does not report a port in time."""
    arguments = [str(path), "--target", str(target), "--parent", str(os.getpid())]
    if loopback:
        arguments += ["--bind", "loopback"]  # Tests: Windows Firewall never asks about 127.0.0.1.
    try:
        process = popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        creationflags=_NO_WINDOW)
    except OSError:
        return None
    line = []
    reader = threading.Thread(target=lambda: line.append(process.stdout.readline()), daemon=True)
    reader.start()
    reader.join(START_SECONDS)
    match = re.fullmatch(rb"PORT ([0-9]{1,5})\r?\n", line[0]) if line else None
    if match is None or not 1024 <= int(match.group(1)) <= 65535:
        Relay(process, 0).close()
        return None
    return Relay(process, int(match.group(1)))


def listen(bind, close, *, path=None, starter=None):
    """Open a listener that devices on this network can reach.

    `bind(host)` creates the listener on `host` and returns its port; `close()`
    closes it. With the relay, the listener is loopback only and the returned
    port is the relay's; otherwise (or if the relay fails) it listens on all
    interfaces directly. Returns (network port, relay or None).
    """
    path = relay_path() if path is None else path
    if path:
        port = bind("127.0.0.1")
        relay = (starter or start)(path, port)
        if relay is not None:
            return relay.port, relay
        close()
    return bind("0.0.0.0"), None


# ------------------------------------------------------------- firewall
_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$rules = @(Get-NetFirewallApplicationFilter -Program '{program}' | Get-NetFirewallRule |
  Where-Object {{ $_.Enabled -eq 'True' -and $_.Direction -eq 'Inbound' }} |
  ForEach-Object {{ @{{ action = [int]$_.Action; profile = [int]$_.Profile }} }})
$networks = @(Get-NetConnectionProfile | ForEach-Object {{ [int]$_.NetworkCategory }})
@{{ rules = $rules; networks = $networks }} | ConvertTo-Json -Compress -Depth 3
"""
# NetSecurity enums: Action Allow=2, Block=4; Profile flags Any=0, Domain=1, Private=2, Public=4;
# NetworkCategory Public=0, Private=1, DomainAuthenticated=2.
_CATEGORY_PROFILE = {0: 4, 1: 2, 2: 1}


def evaluate(value) -> str:
    """"allowed", "blocked", "public" (allowed only on private networks while this one is public),
    "ask" (no rule yet: Windows asks the first time) or "unknown"."""
    if type(value) is not dict:
        return "unknown"
    rules, networks = value.get("rules") or [], value.get("networks") or []
    rules = [rules] if type(rules) is dict else rules
    networks = [networks] if type(networks) is int else networks
    if type(rules) is not list or type(networks) is not list or not all(type(rule) is dict for rule in rules):
        return "unknown"
    active = {_CATEGORY_PROFILE[n] for n in networks if type(n) is int and n in _CATEGORY_PROFILE} or {2}

    def applies(rule):
        profile = rule.get("profile")
        return type(profile) is int and (profile == 0 or any(profile & bit for bit in active))
    public_only = active == {4}
    allowed_private = any(rule.get("action") == 2 and type(rule.get("profile")) is int
                          and (rule["profile"] == 0 or rule["profile"] & 2) for rule in rules)
    if any(rule.get("action") == 4 and applies(rule) for rule in rules):
        # A block rule wins over any allow rule. Windows' own prompt allows Private and blocks Public.
        return "public" if public_only and allowed_private else "blocked"
    if any(rule.get("action") == 2 and applies(rule) for rule in rules):
        return "allowed"
    if public_only and allowed_private:
        return "public"
    return "ask" if not rules else "unknown"


def firewall_state(program: Path, *, run=subprocess.run) -> str:
    """Read (never change) Windows Firewall's inbound rules for `program` on the current networks."""
    if sys.platform != "win32" and run is subprocess.run:
        return "unknown"
    quoted = str(program).replace("'", "''")
    try:
        result = run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                      _SCRIPT.format(program=quoted)], capture_output=True, timeout=20, creationflags=_NO_WINDOW)
        return evaluate(json.loads(result.stdout.decode("utf-8", "replace") or "null"))
    except (OSError, subprocess.SubprocessError, ValueError):
        return "unknown"


def firewall_notice(state: str) -> str:
    """What the owner should do, or "" when nothing is needed."""
    if state == "blocked":
        return ("Windows Firewall blocks Saiph on your network, so your phone and other computers can't connect "
                "directly (phone camera, phone screen, large files). Open firewall settings, choose Change settings, "
                "tick Saiph local network for Private networks, then try again.")
    if state == "public":
        return ("Windows treats this Wi-Fi as a public network, where Saiph is not allowed. If it's your home or "
                "office network, set it to Private in Windows Settings → Network & internet, or allow Saiph local "
                "network for Public networks in firewall settings.")
    return ""


def open_firewall_settings(*, popen=subprocess.Popen):
    """Windows Security's "Allow an app through firewall" page; the owner decides there."""
    popen(FIREWALL_SETTINGS, creationflags=_NO_WINDOW)
