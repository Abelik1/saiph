# SPDX-License-Identifier: AGPL-3.0-or-later
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("seafile_startup", Path(__file__).parents[1] / "scripts/start-seafile-client.py")
startup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(startup)


def profile(tmp_path):
    client = tmp_path / "private profile"
    binary = tmp_path / "standard client"
    (client / "ccnet").mkdir(parents=True)
    (client / "data").mkdir()
    binary.mkdir()
    (client / "ccnet/seafile.ini").write_text(str(client / "data"))
    (client / "data/repo.db").touch()
    (binary / "seafile-applet.exe").touch()
    return client, binary


def test_profile_is_in_child_environment_before_applet_creation(tmp_path, monkeypatch):
    client, binary = profile(tmp_path)
    inherited = {"CCNET_CONF_DIR": "incorrect/default", "SEAFILE_DATA_DIR": "incorrect/data", "OTHER": "retained"}
    command, environment = startup.launch_configuration(client, binary, inherited)
    assert environment["CCNET_CONF_DIR"] == (client / "ccnet").as_posix()
    assert environment["SEAFILE_DATA_DIR"] == (client / "data").as_posix()
    assert environment["OTHER"] == "retained"
    assert inherited["CCNET_CONF_DIR"] == "incorrect/default"  # No global profile mutation.
    assert command[0] == str(binary / "seafile-applet.exe")


def test_supervisor_waits_and_preserves_upstream_failure(tmp_path, monkeypatch):
    client, binary = profile(tmp_path)
    observed = {}

    class Process:
        def __init__(self, command, **options):
            observed.update(command=command, **options)
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def wait(self):
            observed["waited"] = True
            return 7

    monkeypatch.setattr(startup.subprocess, "Popen", Process)
    assert startup.run(client, binary) == 7
    assert observed["waited"]
    assert observed["env"]["CCNET_CONF_DIR"] == (client / "ccnet").as_posix()
    assert observed["stdout"] == startup.subprocess.DEVNULL
    assert observed["stderr"] == startup.subprocess.DEVNULL


def test_uninitialized_profile_never_falls_back_to_owner_defaults(tmp_path):
    client, binary = profile(tmp_path)
    (client / "data/repo.db").unlink()
    with pytest.raises(ValueError, match="not initialized"):
        startup.launch_configuration(client, binary, {})
