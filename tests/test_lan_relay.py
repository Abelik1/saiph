# SPDX-License-Identifier: AGPL-3.0-or-later
"""Listeners that keep one firewall answer across updates, and read-only firewall checks.

No firewall rule or system setting is read or changed: PowerShell and process
starts are mocked. The real relay, where compiled, binds 127.0.0.1 only
("--bind loopback"), which Windows Firewall never asks about.
"""
import functools
import hashlib
import json
import struct
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from orion_mini import lan_relay
from orion_mini.lan_relay import Relay, evaluate, firewall_notice, firewall_state, listen, relay_path, start

ROOT = Path(__file__).resolve().parents[1]
COMPILER = Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe")


def installed(tmp_path, relay=True):
    app = tmp_path / "OrionMini" / "releases" / "0.1.0-beta.40" / "app"
    app.mkdir(parents=True)
    (app / "saiph.exe").write_bytes(b"MZ synthetic")
    if relay:
        (tmp_path / "OrionMini" / "SaiphNetwork.exe").write_bytes(b"MZ synthetic relay")
    return app / "saiph.exe"


def test_relay_is_found_only_beside_an_installed_windows_release(tmp_path):
    exe = installed(tmp_path)
    assert relay_path(exe, "win32") == tmp_path / "OrionMini" / "SaiphNetwork.exe"
    assert relay_path(exe, "linux") is None
    assert relay_path(installed(tmp_path / "older", relay=False), "win32") is None  # An install from before this change.
    source = tmp_path / "checkout" / "saiph.exe"
    source.parent.mkdir()
    source.write_bytes(b"MZ")
    assert relay_path(source, "win32") is None
    assert relay_path() is None  # This test run is a source run.


class FakeProcess:
    def __init__(self, output):
        import io
        self.stdout, self.stdin = io.BytesIO(output), io.BytesIO()
        self.waited = self.killed = False
        self.arguments = None

    def wait(self, timeout=None):
        self.waited = True

    def kill(self):
        self.killed = True


def test_relay_start_reads_its_port_and_closes_by_closing_input():
    made = []

    def popen(arguments, **options):
        made.append(FakeProcess(b"PORT 50123\r\n"))
        made[-1].arguments, made[-1].options = arguments, options
        return made[-1]
    relay = start(Path("C:/Saiph/SaiphNetwork.exe"), 41000, popen=popen)
    assert relay.port == 50123
    assert made[0].arguments[1:5] == ["--target", "41000", "--parent", made[0].arguments[4]]
    assert made[0].options["creationflags"] == lan_relay._NO_WINDOW
    relay.close()
    assert made[0].stdin.closed and made[0].waited
    relay.close()  # Idempotent.


@pytest.mark.parametrize("output", [b"", b"PORT 80\n", b"listening\n", b"PORT 99999\n"])
def test_relay_without_a_valid_port_is_stopped(output):
    process = FakeProcess(output)
    assert start(Path("C:/Saiph/SaiphNetwork.exe"), 41000, popen=lambda *a, **k: process) is None
    assert process.stdin.closed


def test_listen_uses_loopback_behind_the_relay_and_falls_back_to_a_direct_listener():
    calls = []

    def bind(host):
        calls.append(("bind", host))
        return 41000

    def close():
        calls.append(("close",))
    relay = Relay(None, 50123)
    assert listen(bind, close, path=Path("C:/r.exe"), starter=lambda path, port: relay) == (50123, relay)
    assert calls == [("bind", "127.0.0.1")]
    calls.clear()
    assert listen(bind, close, path=Path("C:/r.exe"), starter=lambda path, port: None) == (41000, None)
    assert calls == [("bind", "127.0.0.1"), ("close",), ("bind", "0.0.0.0")]
    calls.clear()
    assert listen(bind, close, path=False) == (41000, None)  # No relay installed: as before.
    assert calls == [("bind", "0.0.0.0")]


ALLOW_PRIVATE, BLOCK_PUBLIC = {"action": 2, "profile": 2}, {"action": 4, "profile": 4}


@pytest.mark.parametrize("value, expected", [
    ({"rules": [ALLOW_PRIVATE, BLOCK_PUBLIC], "networks": [1]}, "allowed"),  # Windows' prompt, home Wi-Fi.
    ({"rules": [ALLOW_PRIVATE, BLOCK_PUBLIC], "networks": [0]}, "public"),  # Same rules, Wi-Fi marked public.
    ({"rules": [{"action": 4, "profile": 2}, BLOCK_PUBLIC], "networks": [1]}, "blocked"),  # Prompt cancelled.
    ({"rules": [{"action": 2, "profile": 0}, {"action": 4, "profile": 0}], "networks": [1]}, "blocked"),  # Block wins.
    ({"rules": [{"action": 2, "profile": 0}], "networks": [0]}, "allowed"),
    ({"rules": {"action": 2, "profile": 2}, "networks": 1}, "allowed"),  # ConvertTo-Json unwraps single items.
    ({"rules": [], "networks": [1]}, "ask"),  # Never asked: Windows asks the first time.
    ({"rules": None, "networks": None}, "ask"),
    ({"rules": [{"action": 4, "profile": 1}], "networks": [1]}, "unknown"),
    ("garbage", "unknown"),
    ({"rules": ["x"], "networks": [1]}, "unknown"),
])
def test_firewall_rules_are_read_into_one_answer(value, expected):
    assert evaluate(value) == expected


def test_firewall_state_only_reads_rules_for_that_program(tmp_path):
    seen = []

    def run(arguments, **options):
        seen.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, json.dumps({"rules": [ALLOW_PRIVATE], "networks": [1]}).encode(), b"")
    program = Path("C:/Users/O'Brien/AppData/Local/Programs/OrionMini/SaiphNetwork.exe")
    assert firewall_state(program, run=run) == "allowed"
    script = seen[0][-1]
    assert "-Program 'C:\\Users\\O''Brien\\AppData\\Local\\Programs\\OrionMini\\SaiphNetwork.exe'" in script \
        or "-Program 'C:/Users/O''Brien/AppData/Local/Programs/OrionMini/SaiphNetwork.exe'" in script
    assert seen[0][0] == "powershell.exe" and "-NonInteractive" in seen[0]
    for verb in ("New-NetFirewallRule", "Set-NetFirewall", "Remove-NetFirewall", "netsh", "Enable-", "Disable-"):
        assert verb not in script

    def broken(arguments, **options):
        raise subprocess.TimeoutExpired(arguments, 20)
    assert firewall_state(program, run=broken) == "unknown"
    assert firewall_state(program, run=lambda a, **k: subprocess.CompletedProcess(a, 1, b"", b"")) == "unknown"


def test_firewall_notice_says_what_to_do():
    assert "tick Saiph local network for Private networks" in firewall_notice("blocked")
    assert "set it to Private" in firewall_notice("public")
    assert firewall_notice("allowed") == firewall_notice("ask") == firewall_notice("unknown") == ""


def test_open_firewall_settings_opens_the_allowed_apps_page_only():
    opened = []
    lan_relay.open_firewall_settings(popen=lambda arguments, **options: opened.append(arguments))
    assert opened == [["control.exe", "/name", "Microsoft.WindowsFirewall", "/page", "pageConfigureApps"]]


def test_large_send_failure_names_the_firewall_when_it_blocks_this_computer():
    from orion_mini.hosted_transfers import HostedTransfers, MAX_PLAINTEXT, Transfer

    class Controller:
        folder = Path(".")
        lock = None
        changes = 0

        def lan_notice(self, refresh=False):
            return firewall_notice("blocked")

        def device_name(self, device):
            return "Synthetic laptop"

        def changed(self):
            self.changes += 1

        def transfer_alert(self, message):
            pass

        def session_close(self, target, offer):
            pass
    transfers = HostedTransfers.__new__(HostedTransfers)
    transfers.c, transfers.monotonic, transfers.jobs = Controller(), time.monotonic, {}
    import threading
    transfers.lock, transfers._wake, transfers._thread, transfers.background = threading.RLock(), threading.Event(), None, False
    job = Transfer("t1", Path("synthetic.bin"), "dev_laptop", "synthetic.bin", MAX_PLAINTEXT + 1)
    job.state, job.route = "connecting", "lan"
    transfers.jobs[job.id] = job
    transfers._fallback(job, "silent")
    assert job.state == "failed" and job.error.startswith("Windows Firewall blocks Saiph on your network")
    assert job.error.endswith("Nothing was sent.")


# ---------------------------------------------------------- the real relay
@pytest.fixture(scope="module")
def relay_exe(tmp_path_factory):
    if sys.platform != "win32" or not COMPILER.is_file():
        pytest.skip("Windows Framework compiler absent")
    out = tmp_path_factory.mktemp("relay") / "SaiphNetwork.exe"
    subprocess.run([str(COMPILER), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(out),
                    str(ROOT / "scripts/packaging/WindowsNetworkRelay.cs")], check=True, capture_output=True)
    return out


def test_file_transfer_through_the_real_relay_is_exact_and_the_relay_exits(relay_exe, tmp_path, monkeypatch):
    from orion_mini import lan_files
    from orion_mini.session_offer import read_file_invite
    started = []

    def loopback_start(path, target, **options):
        relay = start(path, target, loopback=True)
        started.append(relay)
        return relay
    monkeypatch.setattr(lan_relay, "relay_path", lambda: relay_exe)
    monkeypatch.setattr(lan_relay, "start", loopback_start)
    source = tmp_path / "Synthetic.bin"
    source.write_bytes(hashlib.sha256(b"seed").digest() * 100_000)  # 3.2 MB
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    server = lan_files.LanFileServer("get", source, name=source.name, size=source.stat().st_size, sha256=digest,
                                     addresses=lambda: ["10.9.9.9"])
    invite = read_file_invite(server.start(), int(time.time()))
    relay = started[0]
    assert relay is not None and invite["port"] == relay.port != server.server.server_address[1]
    assert server.server.server_address[0] == "127.0.0.1"  # The app itself listens on loopback only.
    out = lan_files.fetch(invite, tmp_path / "received.part", dial=lambda address: "127.0.0.1")
    assert hashlib.sha256(out.read_bytes()).hexdigest() == digest
    process = relay.process
    deadline = time.monotonic() + 10
    while server.status()["state"] != "done" and time.monotonic() < deadline:
        time.sleep(0.05)
    deadline = time.monotonic() + 10
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert process.poll() is not None  # Closed with the transfer.


def test_relay_refuses_unexpected_arguments(relay_exe):
    for arguments in ([], ["--target", "0", "--parent", "1"], ["--target", "80", "--parent", "x"],
                      ["--target", "80", "--parent", "1", "--bind", "0.0.0.0"]):
        assert subprocess.run([str(relay_exe), *arguments], capture_output=True, timeout=10).returncode == 2


# ------------------------------------------------------------ installer
@pytest.mark.skipif(sys.platform != "win32", reason="Windows native installer")
def test_installer_keeps_the_relay_at_one_path_across_updates_and_removes_its_own(tmp_path):
    if not COMPILER.is_file():
        pytest.skip("Windows Framework compiler absent")
    target = ROOT / "test-artifacts"
    target.mkdir(exist_ok=True)
    import tempfile
    with tempfile.TemporaryDirectory(prefix="installer-relay-", dir=target) as directory:
        work = Path(directory)
        stub = work / "stub.exe"
        subprocess.run([str(COMPILER), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(stub),
                        "/reference:System.Windows.Forms.dll", "/reference:System.Drawing.dll",
                        "/reference:System.IO.Compression.dll", "/reference:System.IO.Compression.FileSystem.dll",
                        "/reference:System.Web.Extensions.dll", str(ROOT / "scripts/packaging/WindowsSetup.cs")],
                       check=True, capture_output=True)

        def installer(version, relay):
            files = {"app/Saiph.exe": b"MZ synthetic", "app/OrionMini.exe": b"MZ synthetic", "licenses/inventory.json": b"{}"}
            if relay is not None:
                files["SaiphNetwork.exe"] = relay  # Synthetic bytes: the installer copies it, never runs it.
            items = [{"path": p, "bytes": len(c), "sha256": hashlib.sha256(c).hexdigest()} for p, c in files.items()]
            manifest = {"format": "orion-desktop-package", "schema": 1, "version": version, "platform": "windows-x86_64",
                        "profile": "link", "build": 7, "entrypoint": "app/Saiph.exe", "files": items,
                        "release_state": "internal-preview", "license_inventory": "licenses/inventory.json"}
            archive = work / (version + ".zip")
            with zipfile.ZipFile(archive, "w") as output:
                for path, content in files.items():
                    output.writestr(path, content)
                output.writestr("package-manifest.json", json.dumps(manifest))
            executable = work / (version + ".exe")
            executable.write_bytes(stub.read_bytes() + archive.read_bytes() + struct.pack("<Q", archive.stat().st_size) + b"ORIONZIP")
            return executable

        install = work / "installed"

        def run(executable, *extra):
            return subprocess.run([str(executable), "--silent", "--isolated", "--no-launch", "--destination", str(install), *extra],
                                  capture_output=True, timeout=30).returncode
        relay = install / "SaiphNetwork.exe"
        assert run(installer("0.1.0-beta.39", None)) == 0
        assert not relay.exists()  # Packages from before the relay leave nothing.
        assert run(installer("0.1.0-beta.40", b"MZ relay one")) == 0
        assert relay.read_bytes() == b"MZ relay one"
        assert run(installer("0.1.0-beta.41", b"MZ relay two")) == 0
        assert relay.read_bytes() == b"MZ relay two"  # Same path, new bytes: the firewall rule still applies.
        assert not (install / "SaiphNetwork.exe.new").exists()
        assert run(install / "Uninstall.exe", "--uninstall") == 0
        assert not relay.exists()
        # A file at that path which no release shipped is not Saiph's to delete.
        assert run(installer("0.1.0-beta.42", b"MZ relay two")) == 0
        relay.write_bytes(b"MZ owner's own file")
        assert run(install / "Uninstall.exe", "--uninstall") == 0
        assert relay.read_bytes() == b"MZ owner's own file"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Framework compiler")
def test_distribution_adds_the_relay_to_the_signed_payload_manifest(tmp_path):
    if not COMPILER.is_file():
        pytest.skip("Windows Framework compiler absent")
    import importlib.util
    spec = importlib.util.spec_from_file_location("packaging", ROOT / "scripts/packaging/build-desktop-distribution.py")
    packaging = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "scripts/packaging"))
    spec.loader.exec_module(packaging)
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "package-manifest.json").write_text(json.dumps({"files": [{"path": "app/Saiph.exe", "bytes": 2, "sha256": "0" * 64}]}))
    manifest = packaging.add_network_relay(staging, COMPILER)
    relay = staging / "SaiphNetwork.exe"
    entry = next(item for item in manifest["files"] if item["path"] == "SaiphNetwork.exe")
    assert entry == {"path": "SaiphNetwork.exe", "bytes": relay.stat().st_size, "sha256": hashlib.sha256(relay.read_bytes()).hexdigest()}
    assert json.loads((staging / "package-manifest.json").read_text()) == manifest
    with pytest.raises(ValueError):
        packaging.add_network_relay(staging, COMPILER)
