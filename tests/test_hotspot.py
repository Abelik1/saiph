# SPDX-License-Identifier: AGPL-3.0-or-later
from types import SimpleNamespace

import pytest

from orion_mini import hotspot
from orion_mini.hotspot import Hotspot, validate_options

PROFILES = """
Profiles on interface Wi-Fi:

Group policy profiles (read only)
---------------------------------
    <None>

User profiles
-------------
    All User Profile     : Home Wi-Fi
    All User Profile     : Pixel Hotspot
"""
INTERFACES = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    State                  : connected
    SSID                   : Pixel Hotspot
    Profile                : Pixel Hotspot
"""


def windows(monkeypatch, calls, fail_connect=False):
    monkeypatch.setattr(hotspot.sys, "platform", "win32")
    def run(command, **_kwargs):
        calls.append(command)
        if command[:3] == ["netsh", "wlan", "connect"]:
            return SimpleNamespace(returncode=1 if fail_connect else 0, stdout=b"")
        output = PROFILES if command[-1] == "profiles" else INTERFACES
        return SimpleNamespace(returncode=0, stdout=output.encode())
    return run


def test_windows_profiles_and_active_network_do_not_depend_on_labels():
    assert hotspot.windows_profiles(PROFILES) == ["Home Wi-Fi", "Pixel Hotspot"]
    localised = INTERFACES.replace("Profile", "Profil").replace("State", "Status")
    assert hotspot.windows_active(localised, ["Home Wi-Fi", "Pixel Hotspot"]) == "Pixel Hotspot"
    assert hotspot.windows_active(INTERFACES, ["Home Wi-Fi"]) is None


def test_nmcli_terse_output_keeps_escaped_colons():
    assert hotspot._nmcli_fields(r"Cafe\: 5G:802-11-wireless") == ["Cafe: 5G", "802-11-wireless"]


def test_connect_uses_only_a_saved_profile_as_one_argument(monkeypatch):
    calls = []
    runner = windows(monkeypatch, calls)
    settings = {"link": {"hotspot": {"profile": "Pixel Hotspot"}}}
    assert Hotspot(settings, runner=runner).connect() == {"connecting": True, "profile": "Pixel Hotspot"}
    assert ["netsh", "wlan", "connect", "name=Pixel Hotspot"] in calls
    settings["link"]["hotspot"]["profile"] = "Pixel Hotspot\" & calc"
    with pytest.raises(ValueError):
        Hotspot(settings, runner=runner).connect()
    assert not any("calc" in " ".join(command) for command in calls)


def test_automatic_reconnection_waits_for_a_real_outage(monkeypatch):
    calls, now, route = [], {"value": 100.0}, {"value": False}
    runner = windows(monkeypatch, calls)
    settings = {"link": {"hotspot": {"profile": "Pixel Hotspot", "auto": True}}}
    supervisor = Hotspot(settings, runner=runner, clock=lambda: now["value"], route=lambda: route["value"])
    connects = lambda: sum(command[:3] == ["netsh", "wlan", "connect"] for command in calls)
    assert supervisor.poll(online=False) is False  # Outage just started.
    now["value"] += hotspot.OFFLINE_SECONDS
    route["value"] = True
    assert supervisor.poll(online=False) is False  # Another network still works.
    route["value"] = False
    assert supervisor.poll(online=False) is True and connects() == 1
    now["value"] += 10
    assert supervisor.poll(online=False) is False and connects() == 1  # Rate limited.
    assert supervisor.poll(online=True) is False
    now["value"] += hotspot.RETRY_SECONDS
    assert supervisor.poll(online=False) is False  # The outage timer restarted.
    settings["link"]["hotspot"]["auto"] = False
    now["value"] += 1000
    assert supervisor.poll(online=False) is False and connects() == 1


def test_failed_connection_reports_a_next_step(monkeypatch):
    calls = []
    supervisor = Hotspot({"link": {"hotspot": {"profile": "Pixel Hotspot"}}}, runner=windows(monkeypatch, calls, fail_connect=True))
    with pytest.raises(ValueError, match="hotspot"):
        supervisor.connect()
    assert supervisor.status()["error"] and supervisor.status()["active"] == "Pixel Hotspot"


def test_preferences_are_validated():
    assert validate_options({"profile": "Pixel", "auto": True}) == {"profile": "Pixel", "auto": True}
    for options in ({"auto": "yes"}, {"profile": 5}, {"profile": "x" * 65}, {"profile": "bad\nname"}, {"password": "x"}):
        with pytest.raises(ValueError):
            validate_options(options)
