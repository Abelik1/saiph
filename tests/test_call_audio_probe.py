# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthetic fixtures only: no real computer, adapter, phone or configuration is read."""
import subprocess
from types import SimpleNamespace

import pytest

from orion_mini import call_audio_probe
from orion_mini.call_audio_probe import CallAudioProbe, parse_version, verdict, wireplumber_settings

ADAPTER = """Controller 00:11:22:33:44:55 (public)
\tName: test-laptop
\tPowered: yes
\tUUID: Audio Sink                (0000110b-0000-1000-8000-00805f9b34fb)
\tUUID: Handsfree Audio Gateway   (0000111f-0000-1000-8000-00805f9b34fb)
{handsfree}"""
HANDSFREE = "\tUUID: Handsfree                 (0000111e-0000-1000-8000-00805f9b34fb)"


def outputs(*, pipewire="1.6.2", wireplumber="0.5.13", bluez="5.85", server="PulseAudio (on PipeWire {pw})",
            handsfree=True, telephony=True, ofono=False):
    return {
        ("pipewire", "--version"): f"pipewire\nCompiled with libpipewire {pipewire}\nLinked with libpipewire {pipewire}\n" if pipewire else None,
        ("wireplumber", "--version"): f"wireplumber\nCompiled with libwireplumber {wireplumber}\nLinked with libwireplumber {wireplumber}\n" if wireplumber else None,
        ("bluetoothctl", "--version"): f"bluetoothctl: {bluez}\n" if bluez else None,
        ("pactl", "info"): f"Server String: /run/user/1000/pulse/native\nServer Name: {server.format(pw=pipewire)}\n",
        ("bluetoothctl", "show"): ADAPTER.format(handsfree=HANDSFREE if handsfree else ""),
        ("busctl", "--user", "--no-pager", "--no-legend", "list"):
            ":1.4 1234 wireplumber user user@1000.service - -\n" + ("org.pipewire.Telephony 1200 pipewire user - - -\n" if telephony else ""),
        ("busctl", "--system", "--no-pager", "--no-legend", "list"):
            "org.bluez 800 bluetoothd root - - -\n" + ("org.ofono 900 ofonod root - - -\n" if ofono else ""),
    }


def make(tmp_path, monkeypatch, platform="linux", **kwargs):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    table, calls = outputs(**kwargs), []
    def run(command, **options):
        calls.append(command)
        assert options["timeout"] and options["stdin"] is subprocess.DEVNULL
        out = table.get(tuple(command))
        return SimpleNamespace(returncode=0 if out is not None else 1, stdout=out or "")
    which = lambda name: None if (name == "pipewire" and kwargs.get("pipewire", "x") is None) else "/usr/bin/" + name
    probe = CallAudioProbe(runner=run, which=which, platform=platform, home=tmp_path / "home", root=tmp_path / "root")
    return probe, calls


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_versions_prefer_the_linked_library():
    assert parse_version("pipewire\nCompiled with libpipewire 1.0.4\nLinked with libpipewire 1.0.5\n") == (1, 0, 5)
    assert parse_version("bluetoothctl: 5.72\n") == (5, 72, 0)
    assert parse_version("") is None and parse_version(None) is None


def test_ubuntu_26_04_defaults_are_ready_with_hfp_call_control(tmp_path, monkeypatch):
    probe, calls = make(tmp_path, monkeypatch)
    result = probe.probe()
    assert result["audio"] == "ready" and result["call_control"] == "hfp"
    assert result["versions"] == {"pipewire": "1.6.2", "wireplumber": "0.5.13", "bluez": "5.85.0"}
    assert result["settings"]["roles"] == list(call_audio_probe.DEFAULT_ROLES_05) and result["issues"] == []
    # Read-only: only version banners, status listings and adapter information were requested.
    allowed = {"--version", "info", "show", "list"}
    assert all(command[-1] in allowed for command in calls)


def test_ubuntu_24_04_needs_the_role_and_controls_calls_through_the_app(tmp_path, monkeypatch):
    probe, _ = make(tmp_path, monkeypatch, pipewire="1.0.5", wireplumber="0.4.17", bluez="5.72", handsfree=False, telephony=False)
    write(tmp_path / "root/usr/share/wireplumber/bluetooth.lua.d/50-bluez-config.lua",
          'bluez_monitor.properties = {\n  --["bluez5.headset-roles"] = "[ hsp_hs hsp_ag hfp_hf hfp_ag ]",\n}\n')
    result = probe.probe()
    assert result["audio"] == "needs-setup" and result["call_control"] == "app"
    assert result["settings"]["roles"] == ["hsp_hs", "hfp_ag"]  # The commented line is ignored.
    assert any("hfp_hf" in issue for issue in result["issues"])


def test_a_user_override_turns_the_role_on_for_wireplumber_0_4(tmp_path, monkeypatch):
    probe, _ = make(tmp_path, monkeypatch, pipewire="1.0.5", wireplumber="0.4.17", bluez="5.72", telephony=False)
    write(tmp_path / "home/.config/wireplumber/bluetooth.lua.d/51-saiph-hfp-hf.lua",
          'bluez_monitor.properties["bluez5.headset-roles"] = "[ hsp_hs hfp_hf hfp_ag ]"\n')
    result = probe.probe()
    assert result["audio"] == "ready" and "hfp_hf" in result["settings"]["roles"]
    assert result["settings"]["files"][-1].endswith("51-saiph-hfp-hf.lua")


def test_wireplumber_0_5_overrides_apply_in_order(tmp_path):
    root, home = tmp_path / "root", tmp_path / "home"
    write(root / "etc/wireplumber/wireplumber.conf.d/50-site.conf",
          "monitor.bluez.properties = {\n  bluez5.roles = [ a2dp_sink a2dp_source ]\n}\n")
    settings = wireplumber_settings((0, 5, 13), home=home, root=root, config_home=home / ".config")
    assert settings["roles"] == ["a2dp_sink", "a2dp_source"]
    write(home / ".config/wireplumber/wireplumber.conf.d/51-user.conf",
          "monitor.bluez.properties = {\n  # bluez5.roles = [ a2dp_sink ]\n  bluez5.roles = [ a2dp_sink hfp_hf ]\n"
          "  bluez5.telephony-dbus-service = false\n}\n")
    settings = wireplumber_settings((0, 5, 13), home=home, root=root, config_home=home / ".config")
    assert settings["roles"] == ["a2dp_sink", "hfp_hf"] and settings["telephony"] is False
    assert len(settings["files"]) == 2


def test_configured_but_not_registered_suggests_a_restart(tmp_path, monkeypatch):
    probe, _ = make(tmp_path, monkeypatch, handsfree=False)
    result = probe.probe()
    assert result["audio"] == "needs-setup"
    assert any("restart WirePlumber" in issue for issue in result["issues"])


def test_pipewire_1_4_without_the_service_on_the_bus_falls_back_to_app_control(tmp_path, monkeypatch):
    probe, _ = make(tmp_path, monkeypatch, pipewire="1.4.7", wireplumber="0.5.10", telephony=False)
    result = probe.probe()
    assert result["audio"] == "ready" and result["call_control"] == "app"
    assert any("session bus" in issue for issue in result["issues"])


def test_pulseaudio_and_missing_bluez_are_unsupported(tmp_path, monkeypatch):
    probe, _ = make(tmp_path, monkeypatch, pipewire="0.3.48", wireplumber="0.4.8", bluez="5.64", server="pulseaudio")
    assert probe.probe()["audio"] == "unsupported"
    probe, _ = make(tmp_path, monkeypatch, bluez=None)
    assert probe.probe()["audio"] == "unsupported"


def test_ofono_is_reported_and_bluetooth_off_is_unknown(tmp_path, monkeypatch):
    probe, _ = make(tmp_path, monkeypatch, ofono=True)
    assert any("oFono" in issue for issue in probe.probe()["issues"])
    facts = {"pipewire": (1, 6, 2), "wireplumber": (0, 5, 13), "bluez": (5, 85, 0), "server": "",
             "handsfree_registered": None, "telephony_on_bus": None, "ofono_running": None,
             "settings": {"roles": ["hfp_hf"], "backend": "native", "telephony": True}}
    assert verdict(facts)["audio"] == "unknown"
    facts["settings"]["backend"] = "ofono"
    assert verdict(facts)["audio"] == "needs-setup"


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_other_platforms_run_nothing(tmp_path, monkeypatch, platform):
    probe, calls = make(tmp_path, monkeypatch, platform=platform)
    result = probe.probe()
    assert result["audio"] == "unsupported" and result["call_control"] == "app" and calls == []


def test_command_failures_are_tolerated(tmp_path, monkeypatch):
    def broken(command, **_):
        raise subprocess.TimeoutExpired(command, 5)
    probe = CallAudioProbe(runner=broken, which=lambda name: "/usr/bin/" + name, platform="linux",
                           home=tmp_path, root=tmp_path)
    assert probe.probe()["audio"] == "unsupported"
