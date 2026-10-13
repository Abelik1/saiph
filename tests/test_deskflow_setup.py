# SPDX-License-Identifier: AGPL-3.0-or-later
import socket

from orion_mini import deskflow
from orion_mini.deskflow import Deskflow, detect, mesh_addresses


class Process:
    def __init__(self, code=None):
        self.returncode = code

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


def configured(tmp_path, monkeypatch, **options):
    executable = tmp_path / "deskflow-core.exe"
    executable.write_text("")
    monkeypatch.setattr(deskflow, "tool_path", lambda _name, _configured=None: str(executable))
    gui = tmp_path / "gui-tls"
    gui.mkdir()
    monkeypatch.setattr(deskflow, "tls_directories", lambda root: ([gui], gui))
    return {"link": {"deskflow": {"enabled": True, "role": "desktop", "local": "100.64.0.2", **options}}}, gui


def test_mesh_addresses_keep_only_this_computers_mesh_interfaces():
    entries = [(socket.AF_INET, 0, 0, "", ("192.168.1.4", 0)), (socket.AF_INET, 0, 0, "", ("100.101.2.3", 0)),
               (socket.AF_INET, 0, 0, "", ("100.101.2.3", 0)), (socket.AF_INET, 0, 0, "", ("not an address", 0))]
    assert mesh_addresses(lambda *_args: entries) == ["100.101.2.3"]
    def unavailable(*_args):
        raise OSError()
    assert mesh_addresses(unavailable) == []


def test_detect_reports_certificates_and_role_trust_without_reading_them(tmp_path, monkeypatch):
    settings, gui = configured(tmp_path, monkeypatch)
    (gui / "deskflow.pem").write_text("private test certificate")
    assert detect(tmp_path, {"role": "desktop"}, addresses=lambda: ["100.70.0.9"]) == {
        "executable": str(tmp_path / "deskflow-core.exe"), "certificates": [str(gui / "deskflow.pem")],
        "trust_file": str(gui / "trusted-clients"), "trusted": False, "mesh_addresses": ["100.70.0.9"]}
    (gui / "trusted-servers").write_text("")
    assert detect(tmp_path, {"role": "laptop"}, addresses=lambda: [])["trusted"] is True


def test_single_detected_certificate_is_used_and_crash_loops_back_off(tmp_path, monkeypatch):
    settings, gui = configured(tmp_path, monkeypatch)
    certificate = gui / "deskflow.pem"
    certificate.write_text("")
    started, now = [], {"value": 1000.0}
    supervisor = Deskflow(tmp_path, settings, popen=lambda command, **_k: started.append(command) or Process(), clock=lambda: now["value"])
    supervisor.poll()
    assert len(started) == 1 and supervisor.status()["running"] is True
    assert ("certificate=" + certificate.as_posix()) in (tmp_path / "deskflow" / "settings.ini").read_text()
    for crash in range(1, 4):
        supervisor.process.returncode = 1
        now["value"] += 5
        supervisor.poll()
        assert supervisor.crashes == crash and supervisor.status()["exit_code"] == 1
        assert len(started) == crash  # Waiting out the backoff.
        now["value"] += 15 * 2 ** crash
        supervisor.poll()
        assert len(started) == crash + 1
    assert "keeps stopping" in supervisor.error
    supervisor.restart()
    assert supervisor.crashes == 0 and supervisor.error == ""
    supervisor.poll()
    assert len(started) == 5


def test_a_long_run_resets_the_crash_count(tmp_path, monkeypatch):
    settings, gui = configured(tmp_path, monkeypatch, certificate=str(tmp_path / "chosen.pem"))
    (tmp_path / "chosen.pem").write_text("")
    now = {"value": 0.0}
    supervisor = Deskflow(tmp_path, settings, popen=lambda *_a, **_k: Process(), clock=lambda: now["value"])
    supervisor.crashes = 2
    supervisor.poll()
    now["value"] += deskflow.STABLE_SECONDS
    supervisor.process.returncode = 0
    supervisor.poll()
    assert supervisor.crashes == 0


def test_ambiguous_certificates_still_require_a_choice(tmp_path, monkeypatch):
    settings, gui = configured(tmp_path, monkeypatch)
    (gui / "one.pem").write_text("")
    (gui / "two.pem").write_text("")
    supervisor = Deskflow(tmp_path, settings, popen=lambda *_a, **_k: Process())
    supervisor.poll()
    assert supervisor.process is None and "certificate" in supervisor.error
