# SPDX-License-Identifier: AGPL-3.0-or-later
from types import SimpleNamespace

import pytest

from orion_mini import bt_lock
from orion_mini.bt_lock import BluetoothLock, validate_options

PHONE = "AA:BB:CC:DD:EE:FF"


def lock(connected, now, monkeypatch, seconds=30):
    monkeypatch.setattr(bt_lock.sys, "platform", "linux")
    monkeypatch.setattr(bt_lock.shutil, "which", lambda name: "/usr/bin/" + name)
    commands = []
    def run(command, **_):
        commands.append(command)
        if command[:2] == ["bluetoothctl", "info"]:
            return SimpleNamespace(returncode=0, stdout=f"Device {PHONE}\n\tConnected: {'yes' if connected['value'] else 'no'}\n")
        if command[:2] == ["bluetoothctl", "devices"]:
            return SimpleNamespace(returncode=0, stdout=f"Device {PHONE} Galaxy A55\nDevice 11:22:33:44:55:66 Headphones\n")
        return SimpleNamespace(returncode=0, stdout="")
    settings = {"link": {"bt_lock": {"enabled": True, "device": PHONE, "seconds": seconds}}}
    return BluetoothLock(settings, runner=run, clock=lambda: now["value"]), commands


def test_locks_once_after_the_phone_has_been_gone_long_enough(monkeypatch):
    connected, now = {"value": True}, {"value": 0.0}
    service, commands = lock(connected, now, monkeypatch)
    assert service.poll() is False
    connected["value"] = False
    assert service.poll() is False
    now["value"] = 29
    assert service.poll() is False
    now["value"] = 31
    assert service.poll() is True
    assert ["loginctl", "lock-session"] in commands
    now["value"] = 100
    assert service.poll() is False  # Not again until the phone has returned.
    assert commands.count(["loginctl", "lock-session"]) == 1


def test_never_locks_when_the_phone_was_away_at_start_or_when_off(monkeypatch):
    connected, now = {"value": False}, {"value": 0.0}
    service, commands = lock(connected, now, monkeypatch)
    for t in (0, 60, 120):
        now["value"] = t
        assert service.poll() is False
    service.settings["link"]["bt_lock"]["enabled"] = False
    connected["value"] = True; service.poll(); connected["value"] = False; now["value"] = 999
    assert service.poll() is False and ["loginctl", "lock-session"] not in commands


def test_paired_devices_are_listed(monkeypatch):
    service, _ = lock({"value": True}, {"value": 0.0}, monkeypatch)
    assert service.paired() == [{"address": PHONE, "name": "Galaxy A55"}, {"address": "11:22:33:44:55:66", "name": "Headphones"}]


def test_preferences_are_validated():
    assert validate_options({"enabled": True, "device": PHONE, "seconds": 60})["seconds"] == 60
    for options in ({"device": "phone; rm"}, {"seconds": 5}, {"enabled": "yes"}, {"command": "x"}):
        with pytest.raises(ValueError):
            validate_options(options)
