# SPDX-License-Identifier: AGPL-3.0-or-later
import threading
from types import SimpleNamespace

from orion_mini import platform
from orion_mini.phone import PhoneRuntime, capabilities


def test_linux_battery_is_read_from_power_supply(tmp_path, monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "linux")
    assert platform.battery(tmp_path) is None  # Desktops without a battery publish nothing.
    supply = tmp_path / "BAT0"; supply.mkdir()
    (supply / "capacity").write_text("57\n"); (supply / "status").write_text("Discharging\n")
    assert platform.battery(tmp_path) == {"battery_level": 57, "is_charging": False}
    (supply / "status").write_text("Charging\n")
    assert platform.battery(tmp_path)["is_charging"] is True


def runtime(connected=True):
    published = []
    value = PhoneRuntime.__new__(PhoneRuntime)
    value.state = SimpleNamespace(connected=connected, lock=threading.RLock(), devices=[
        {"id": "phone", "name": "Galaxy", "capabilities": ["battery"]}, {"id": "laptop", "name": "Laptop", "capabilities": ["files"]}])
    value.workspace = SimpleNamespace(settings={"link": {}})
    value.publish, value.battery_sent, value.low_battery = published.append, (None, 0), set()
    return value, published


def test_computer_battery_is_shared_on_change_or_every_ten_minutes():
    service, published = runtime()
    reading = {"battery_level": 80, "is_charging": True}
    assert service.share_battery(reading, 1000)
    assert not service.share_battery(reading, 1100)
    assert service.share_battery({**reading, "battery_level": 79}, 1150)
    assert service.share_battery({**reading, "battery_level": 79}, 1800)
    assert [e["type"] for e in published] == ["battery"] * 3 and "targets" not in published[0]
    assert not service.share_battery(None, 5000)
    offline, nothing = runtime(connected=False)
    assert not offline.share_battery(reading, 1000) and nothing == []


def test_low_battery_alerts_only_for_phones():
    service, _ = runtime()
    assert service.battery_notice("laptop", {"battery_level": 5, "is_charging": False}) is None
    assert service.battery_notice("phone", {"battery_level": 5, "is_charging": False}).startswith("Galaxy battery is low")


def test_ringing_this_computer_follows_the_setting():
    assert "ring" in capabilities({"link": {}})
    assert "ring" not in capabilities({"link": {"ring_computer": False}})
