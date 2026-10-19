# SPDX-License-Identifier: AGPL-3.0-or-later
"""Supervise upstream Deskflow with TLS trust and Orion-only clipboard sharing."""
from __future__ import annotations

import ipaddress
import os
import socket
import subprocess
import threading
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


MESH = ipaddress.ip_network("100.64.0.0/10")
STABLE_SECONDS = 600  # A core that ran this long is no longer crash-looping.


def tls_directories(root):
    """GUI trust folders Deskflow uses by default, then Saiph's core trust folder."""
    if os.name == "nt":
        gui = [Path(os.environ.get("ProgramData", "C:/ProgramData")) / "Deskflow" / "tls"]
    else:
        config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        gui = [config / "Deskflow" / "tls", Path("/etc/Deskflow/tls")]
    return gui, (gui[0] if os.name == "nt" else Path(root) / "deskflow" / "tls")


def mesh_addresses(lookup=None):
    """This computer's own mesh (100.64.0.0/10) addresses, without contacting anything."""
    found = set()
    try:
        entries = (lookup or socket.getaddrinfo)(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        entries = []
    for entry in entries:
        try:
            address = ipaddress.ip_address(entry[4][0])
        except (ValueError, IndexError, TypeError):
            continue
        if address in MESH:
            found.add(str(address))
    return sorted(found)


def detect(root, options=None, *, addresses=mesh_addresses):
    """Read-only setup checks. File names only: certificate contents are never opened."""
    options = options or {}
    role = options.get("role", "desktop" if os.name == "nt" else "laptop")
    executable = tool_path("deskflow-core", options.get("executable"))
    gui, core = tls_directories(root)
    certificates = []
    for directory in gui:
        try:
            certificates += sorted(str(path) for path in directory.glob("*.pem") if path.is_file())
        except OSError:
            continue
    trust = "trusted-clients" if role == "desktop" else "trusted-servers"
    try:
        trusted = (core / trust).is_file()
    except OSError:
        trusted = False
    return {"executable": executable or "", "certificates": certificates[:8], "trust_file": str(core / trust),
            "trusted": trusted, "mesh_addresses": addresses()}


class Deskflow:
    def __init__(self, root, settings, *, popen=subprocess.Popen, clock=time.monotonic, default_enabled=True):
        self.root, self.settings, self.popen, self.clock = Path(root), settings, popen, clock
        self.process = None
        self.next_attempt = 0
        self.error = ""
        self.identity = None
        self.default_enabled = default_enabled
        self.started_at = None
        self.crashes = 0
        self.exit_code = None

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
        found = None
        certificate = options.get("certificate")
        if not certificate:
            # One certificate in Deskflow's own trust folder is unambiguous.
            found = detect(self.root, options)
            certificate = found["certificates"][0] if len(found["certificates"]) == 1 else None
        if not certificate or not Path(certificate).is_file():
            self.error = "Complete Deskflow's one-time certificate trust setup on both computers."
            return
        local = options.get("local")
        if not local and role == "desktop":
            addresses = (found or detect(self.root, options))["mesh_addresses"]
            local = addresses[0] if len(addresses) == 1 else "100.64.0.2"
        identity = (executable, role, options.get("desktop", "100.64.0.2"), local or "100.64.0.2", certificate)
        if self.process and self.process.poll() is not None:
            self.exit_code = self.process.returncode
            uptime = self.clock() - (self.started_at if self.started_at is not None else self.clock())
            self.crashes = 0 if uptime >= STABLE_SECONDS else self.crashes + 1
            self.process = None
            # Back off a crash loop: 15 s, 30 s, 1 min … up to 5 minutes.
            self.next_attempt = self.clock() + min(300, 15 * 2 ** min(self.crashes, 5))
            self.error = "Deskflow stopped unexpectedly; restarting automatically." if self.crashes < 3 else "Deskflow keeps stopping. Check its trust setup, then restart sharing."
        if self.process and self.identity != identity:
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
            self.started_at = self.clock()
            if self.crashes < 3:
                self.error = ""
        except (ValueError, OSError):
            self.error = "Deskflow could not start; retrying automatically."

    def status(self):
        running = bool(self.process and self.process.poll() is None)
        return {"error": self.error, "running": running, "crashes": self.crashes, "exit_code": self.exit_code,
                "uptime": int(self.clock() - self.started_at) if running and self.started_at is not None else 0}

    def setup(self):
        """Cached setup checks for the settings page, refreshed every 30 seconds.

        The dashboard snapshot reads this on the GUI thread, and detection walks
        PATH, so a stale result is refreshed on a worker thread instead of
        blocking the snapshot. A changed role or executable is checked at once."""
        options = (self.settings.get("link") or {}).get("deskflow") or {}
        key = (options.get("role"), options.get("executable"))
        cached = getattr(self, "_setup", None)
        if cached is None or cached[0] != key:
            self._setup = cached = (key, self.clock(), detect(self.root, options))
        elif self.clock() - cached[1] >= 30 and not getattr(self, "_setup_refreshing", False):
            self._setup_refreshing = True
            def refresh():
                try:
                    found = detect(self.root, options)
                    if getattr(self, "_setup", None) is cached:
                        self._setup = (key, self.clock(), found)
                except (OSError, ValueError):
                    if getattr(self, "_setup", None) is cached:
                        self._setup = (key, self.clock(), cached[2])
                finally:
                    self._setup_refreshing = False
            threading.Thread(target=refresh, name="orion-deskflow-inspection", daemon=True).start()
        return cached[2]

    def restart(self):
        """Owner-requested restart: clears crash backoff and starts on the next poll."""
        self.stop()
        self.crashes, self.exit_code, self.next_attempt, self.error = 0, None, 0, ""
        return {"restarting": True}

    def stop(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
