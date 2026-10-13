# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from orion_mini.codes import verification_code
from orion_mini.phone import PhoneRuntime, PhoneState
from orion_mini.storage import Store


@pytest.mark.parametrize("text, code", [
    ("Your verification code is 482913", "482913"),
    ("G-582014 is your Google verification code", "582014"),
    ("Your code: 123-456", "123456"),
    ("Use 7731 to sign in", "7731"),
    ("Your code is 1234.", "1234"),
    ("PIN: 0042", "0042"),
])
def test_codes_are_found_next_to_a_keyword(text, code):
    assert verification_code("Messages", text) == code


@pytest.mark.parametrize("text", [
    "Meeting at 4pm, call 555-1234",           # No code keyword.
    "Your order code total is 1234.50",        # Decimal amount.
    "Payment of 4500 received",                # No keyword.
    "Your login code is 2025 for 2026",        # Years only.
    "Security update 12345-6789 installed",    # Joined to another number.
])
def test_ordinary_numbers_are_not_codes(text):
    assert verification_code("Messages", text) is None


def test_snapshot_offers_the_code_without_storing_it(tmp_path):
    store = Store(tmp_path)
    state = PhoneState(store)
    state.event({"type": "notification.upsert", "source": "phone", "created_at": 1,
                 "payload": {"key": "k", "app": "Bank", "title": "Sign-in", "text": "Your code is 918273", "actions": []}})
    assert state.snapshot()["notifications"][0]["code"] == "918273"
    assert "code" not in store.all("phone_notification")[0]


def test_copied_codes_are_digits_only_and_do_not_echo(tmp_path):
    copied = []
    runtime = PhoneRuntime.__new__(PhoneRuntime)
    from orion_mini.clipboard import RecentClipboard
    runtime.clipboard_cache, runtime.clipboard_received = RecentClipboard(), lambda mime, data: copied.append((mime, data))
    runtime.copy_code("918273")
    runtime.copy_code("rm -rf")
    assert copied == [("text/plain", b"918273")]
    assert runtime.clipboard_cache.contains_digest("text/plain", __import__("hashlib").sha256(b"918273").hexdigest())


def test_low_battery_alerts_once_until_charged():
    from types import SimpleNamespace
    import threading
    runtime = PhoneRuntime.__new__(PhoneRuntime)
    runtime.workspace = SimpleNamespace(settings={"link": {}})
    runtime.state = SimpleNamespace(lock=threading.RLock(), devices=[{"id": "phone", "name": "Galaxy A55", "capabilities": ["battery"]}])
    runtime.low_battery = set()
    notice = lambda level, charging=False: runtime.battery_notice("phone", {"battery_level": level, "is_charging": charging})
    assert notice(45) is None
    assert notice(19) == "Galaxy A55 battery is low (19%). Charge it soon."
    assert notice(15) is None  # Already told.
    assert notice(15, charging=True) is None
    assert notice(18) is not None  # Re-armed by charging.
    runtime.workspace.settings["link"]["battery_alerts"] = False
    runtime.low_battery.clear()
    assert notice(10) is None
    assert runtime.battery_notice("phone", {"battery_level": "10", "is_charging": False}) is None
