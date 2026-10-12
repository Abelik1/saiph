# SPDX-License-Identifier: AGPL-3.0-or-later
"""Supervise upstream Deskflow with TLS trust and Orion-only clipboard sharing."""
from __future__ import annotations

import ipaddress
import os
import subprocess
import time
from pathlib import Path

from .storage import write_text
from .companion_tools import tool_path

SERVER_CONFIG = """section: screens
    desktop:
    laptop:
end
section: links
    desktop:
        right = laptop
    laptop:
        left = desktop
end
section: options
    enableClipboard = false
end
"""


def configuration(root, *, role="desktop", desktop="100.64.0.2", local=None, certificate=None):
    if role not in {"desktop", "laptop"} or ipaddress.ip_address(desktop) not in ipaddress.ip_network("100.64.0.0/10"):
        raise ValueError("Deskflow needs a mesh server and a known computer role.")
    if role == "desktop" and (local is None or ipaddress.ip_address(local) not in ipaddress.ip_network("100.64.0.0/10")):
        raise ValueError("Deskflow must listen only on this computer's mesh address.")
    if certificate and any(character in str(certificate) for character in '\r\n\0'):
        raise ValueError("Deskflow certificate path is invalid.")
    directory = Path(root) / "deskflow"
    directory.mkdir(parents=True, exist_ok=True)
    config = directory / "server.conf"
    write_text(config, SERVER_CONFIG)
    # Deskflow >=1.25 uses QSettings INI plus --settings, not old -c CLI flags.
    settings = f"[core]\ncomputerName={role}\nport=24800\ninterface={local or ''}\nprocessMode=1\nenableEnterCommand=false\nenableExitCommand=false\n"
    settings += f"[server]\nexternalConfig=true\nexternalConfigFile={config.as_posix()}\nenableClipboard=false\n"
    settings += f"[client]\nremoteHost={desktop}\ndynamicConnectionInterval=true\n"
    settings += "[security]\ntlsEnabled=true\ncheckPeerFingerprints=true\n"
    if certificate:
        settings += "certificate=" + Path(certificate).as_posix() + "\n"
    settings += "[log]\nlevel=ERROR\ntoFile=false\n"
    path = directory / "settings.ini"
    write_text(path, settings)
    return path


class Deskflow:
    def __init__(self, root, settings, *, popen=subprocess.Popen, clock=time.monotonic, default_enabled=True):
        self.root, self.settings, self.popen, self.clock = Path(root), settings, popen, clock
        self.process = None
        self.next_attempt = 0
        self.error = ""
        self.identity = None
        self.default_enabled = default_enabled

    def poll(self):
        options = (self.settings.get("link") or {}).get("deskflow") or {}
        if options.get("enabled", self.default_enabled) is False:
            self.stop()
            return
        role = options.get("role", "desktop" if os.name == "nt" else "laptop")
        executable = tool_path("deskflow-core", options.get("executable"))
        installed = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Deskflow" / "deskflow-core.exe"
        if not executable and installed.is_file():
            executable = str(installed)
        if not executable:
            self.error = "Deskflow is not installed on this computer."
            return
        certificate = options.get("certificate")
        if not certificate or not Path(certificate).is_file():
            self.error = "Complete Deskflow's one-time certificate trust setup on both computers."
            return
        identity = (executable, role, options.get("desktop", "100.64.0.2"), options.get("local", "100.64.0.2"), certificate)
        if self.process and (self.identity != identity or self.process.poll() is not None):
            self.stop()
        if self.process or self.clock() < self.next_attempt:
            return
        self.next_attempt = self.clock() + 15
        try:
            path = configuration(self.root, role=role, desktop=identity[2], local=identity[3] if role == "desktop" else None, certificate=certificate)
            self.process = self.popen([str(executable), "server" if role == "desktop" else "client", "--settings", str(path)],
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
            self.identity = identity
            self.error = ""
        except (ValueError, OSError):
            self.error = "Deskflow could not start; retrying automatically."

    def stop(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
