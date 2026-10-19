# SPDX-License-Identifier: AGPL-3.0-or-later
"""Saiph Cloud phone notifications as native desktop notifications.

Synthetic phones and a fake notifier only: nothing reaches the operating system's
notification service. The Windows toast and Linux popup themselves are physical checks.
"""
import asyncio
from copy import deepcopy
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from orion_mini import phone
from orion_mini.hosted_features import dismiss_payload
from orion_mini.phone import notification_id

from test_hosted_phone import STATUS, hosted  # noqa: F401  (hosted is a fixture)


def upsert(key="k1", title="Synthetic sender", text="Hello", app="Messages", age=0):
    return {"type": "notification.upsert", "notification": {
        "key": key, "app": app, "title": title, "text": text, "timestamp": int((time.time() - age) * 1000)}}


def remove(key="k1"):
    return {"type": "notification.remove", "key": key}


class Recorder:
    """Stands in for the desktop's phone runtime: what the hosted controller hands over."""

    def __init__(self):
        self.calls = []

    def cloud_notification(self, row):
        self.calls.append(("show", row))

    def cloud_reconcile(self, current):
        self.calls.append(("reconcile", set(current)))

    def cloud_battery(self, *args):
        self.calls.append(("battery", args))

    def of(self, kind):
        return [value for name, value in self.calls if name == kind]


class FakeNative:
    """The NativeNotifications surface the runtime uses; it must only ever run on the loop thread."""

    def __init__(self, thread):
        self.thread = thread
        self.shown, self.cleared, self.announced = [], [], []
        self.ids, self.groups = {}, {}

    async def show(self, row, command=None, group="hub"):
        assert threading.current_thread() is self.thread
        key = notification_id(row["device_id"], row["key"])
        self.shown.append(SimpleNamespace(row=row, command=command, group=group))
        self.ids[key], self.groups[key] = row, group

    async def reconcile(self, current, group="hub"):
        assert threading.current_thread() is self.thread
        for key in [key for key in self.ids if self.groups[key] == group and key not in current]:
            self.ids.pop(key)
            self.cleared.append(key)

    async def announce(self, title, message, buttons=(), clicked=None):
        assert threading.current_thread() is self.thread
        self.announced.append((title, message))


@pytest.fixture
def runtime(tmp_path):
    """The desktop phone runtime with its notifier loop on its own thread, as in the app."""
    from orion_mini.link_service import LinkWorkspace
    workspace = LinkWorkspace(tmp_path / "runtime")
    copied = []
    result = phone.PhoneRuntime(workspace, notifier_factory=lambda _: None, worker_factory=lambda: None,
                                clipboard_received=lambda mime, data: copied.append(data))
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, name="synthetic-phone-loop", daemon=True)
    thread.start()
    result.loop, result.native, result.copied = loop, FakeNative(thread), copied
    yield result
    loop.call_soon_threadsafe(loop.stop)
    thread.join(5)
    loop.close()


def drain(runtime):
    """Wait until everything already handed to the notifier loop has run."""
    asyncio.run_coroutine_threadsafe(asyncio.sleep(0), runtime.loop).result(5)


def cloud_row(key="k1", title="Synthetic sender", text="Hello", silent=False):
    device = "dev_synthetic_phone"
    return {"key": key, "app": "Messages", "title": title, "text": text, "timestamp": 1, "device_id": device,
            "id": notification_id(device, key), "silent": silent}


# ------------------------------------------------- hosted controller → hooks
def test_a_new_notification_pops_up_once_and_unchanged_updates_do_not(hosted):
    h, recorder = hosted, Recorder()
    h.profile.phone_runtime = recorder
    h.send(upsert())
    [row] = recorder.of("show")
    assert row["id"] == notification_id(h.device, "k1") and row["device_id"] == h.device
    assert (row["app"], row["title"], row["text"], row["silent"]) == ("Messages", "Synthetic sender", "Hello", False)
    h.send(upsert())  # The phone repeats it with a newer time: no second popup.
    assert len(recorder.of("show")) == 1
    h.send(upsert(text="Hello again"))  # New content pops up again, like the Hub path.
    assert [row["text"] for row in recorder.of("show")] == ["Hello", "Hello again"]
    assert len(h.profile.store.all("hosted_notification")) == 1


def test_notifications_already_on_the_phone_are_listed_but_not_announced(hosted):
    h, recorder = hosted, Recorder()
    h.profile.phone_runtime = recorder
    h.send(upsert(age=3600))  # Resent when the phone reconnected: not news.
    [row] = recorder.of("show")
    assert row["silent"] is True
    assert len(h.profile.store.all("hosted_notification")) == 1


def test_removal_on_the_phone_and_dismissal_in_saiph_clear_the_toast(hosted):
    h, recorder = hosted, Recorder()
    h.profile.phone_runtime = recorder
    h.send(upsert("k1"))
    h.send(upsert("k2"))
    h.received()
    h.send(remove("k1"))
    assert recorder.of("reconcile")[-1] == {notification_id(h.device, "k2")}
    h.controller.dismiss_notification(notification_id(h.device, "k2"))
    assert recorder.of("reconcile")[-1] == set()
    assert dismiss_payload("k2") in h.received()  # The phone dismisses it too.


def test_notifications_turned_off_in_settings_never_pop_up(hosted):
    h, recorder = hosted, Recorder()
    h.profile.phone_runtime = recorder
    h.profile.settings["link"] = {"phone": {"features": {"notifications": False}}}
    h.send(upsert())
    assert recorder.of("show") == [] and h.profile.store.all("hosted_notification") == []
    h.profile.settings["link"] = {}
    h.send(upsert())
    assert len(recorder.of("show")) == 1


def test_without_a_desktop_runtime_notifications_are_only_listed(hosted):
    h = hosted
    h.send(upsert())  # The fixture's profile has no phone runtime (tests, headless).
    assert len(h.profile.store.all("hosted_notification")) == 1


def test_cloud_phone_status_feeds_the_low_battery_notice(hosted):
    h, recorder = hosted, Recorder()
    h.profile.phone_runtime = recorder
    h.send({"type": "phone.capabilities", "capabilities": ["files"]})
    h.received()
    h.send({**STATUS, "battery": 15, "charging": False})
    [(device, name, level, charging)] = recorder.of("battery")
    assert (device, level, charging) == (h.device, 15, False)
    assert name == "Synthetic phone"


# ------------------------------------------------- phone runtime → notifier
def test_the_runtime_shows_cloud_toasts_on_its_own_loop(runtime):
    runtime.cloud_notification(cloud_row()).result(5)
    [shown] = runtime.native.shown
    assert shown.group == "cloud" and shown.row["title"] == "Synthetic sender"
    assert shown.command == runtime.cloud_command


def test_clicking_opens_saiph_and_dismissing_dismisses_on_the_phone(runtime):
    opened, dismissed = [], threading.Event()
    runtime.workspace.request_open_phone = lambda: opened.append(True)
    runtime.workspace._hosted = SimpleNamespace(dismiss_notification=lambda ident: dismissed.set() if ident == cloud_row()["id"] else None)
    runtime.cloud_command(cloud_row(), "open")
    assert opened == [True]
    runtime.cloud_command(cloud_row(), "dismiss")
    assert dismissed.wait(5)
    runtime.workspace._hosted = SimpleNamespace(dismiss_notification=lambda ident: (_ for _ in ()).throw(ValueError("gone")))
    runtime.cloud_command(cloud_row(), "dismiss")  # Already gone or offline: nothing raises.


def test_quiet_hours_and_stale_rows_do_not_pop_up(runtime):
    runtime.continuity.focus.quiet = True
    runtime.cloud_notification(cloud_row("k1")).result(5)
    runtime.continuity.focus.quiet = False
    runtime.cloud_notification(cloud_row("k2", silent=True)).result(5)
    assert runtime.native.shown == []
    runtime.cloud_notification(cloud_row("k3")).result(5)
    assert [shown.row["key"] for shown in runtime.native.shown] == ["k3"]


def test_verification_codes_are_copied_once_when_enabled(runtime):
    row = cloud_row(title="Synthetic Bank", text="Your verification code is 482913")
    runtime.cloud_notification(row).result(5)
    assert runtime.copied == []  # Off by default.
    runtime.workspace.settings.setdefault("link", {})["auto_copy_codes"] = True
    runtime.cloud_notification(row).result(5)
    runtime.cloud_notification({**row, "text": row["text"] + "."}).result(5)  # Same code, updated text.
    assert runtime.copied == [b"482913"]
    runtime.cloud_notification(cloud_row("k9", title="Synthetic Bank", text="Old code 771100", silent=True)).result(5)
    assert runtime.copied == [b"482913"]  # Never from a notification that was already on the phone.
    runtime.continuity.focus.quiet = True
    runtime.cloud_notification(cloud_row("k8", title="Synthetic Shop", text="Login code 135790")).result(5)
    assert runtime.copied == [b"482913", b"135790"]  # Quiet hours silence the popup, not the copy.


def test_low_battery_is_announced_once_per_discharge(runtime):
    def reading(level, charging):
        runtime.cloud_battery("dev_synthetic_phone", "Synthetic phone", level, charging).result(5)
    reading(15, False)
    reading(12, False)
    assert runtime.native.announced == [("Phone battery low", "Synthetic phone battery is low (15%). Charge it soon.")]
    reading(40, True)
    runtime.continuity.focus.quiet = True
    reading(15, False)
    assert len(runtime.native.announced) == 1  # Quiet hours.
    runtime.continuity.focus.quiet = False
    reading(None, False)  # A phone hiding its battery.
    runtime.workspace.settings.setdefault("link", {})["battery_alerts"] = False
    reading(40, True)
    reading(10, False)
    assert len(runtime.native.announced) == 1


def test_nothing_is_scheduled_before_the_notifier_loop_exists(tmp_path):
    from orion_mini.link_service import LinkWorkspace
    idle = phone.PhoneRuntime(LinkWorkspace(tmp_path), notifier_factory=lambda _: None, worker_factory=lambda: None)
    assert idle.cloud_notification(cloud_row()) is None and idle.cloud_reconcile(set()) is None


def test_hub_and_cloud_toasts_reconcile_separately():
    pytest.importorskip("desktop_notifier")
    sent, cleared = [], []

    class Notifier:
        async def send(self, **options):
            sent.append(options)
            return len(sent)

        async def clear(self, ident):
            cleared.append(ident)

    native = object.__new__(phone.NativeNotifications)
    native.notifier, native.copy, native.ids, native.groups, native.suppressed = Notifier(), None, {}, {}, set()
    hub_commands, cloud_commands = [], []
    native.command = lambda row, operation, **extra: hub_commands.append(operation)
    hub = {"device_id": "hub-phone", "key": "h", "app": "Mail", "title": "Synthetic", "text": "", "actions": []}

    async def scenario():
        await native.show(hub)
        await native.show(cloud_row(), command=lambda row, operation, **extra: cloud_commands.append(operation), group="cloud")
        sent[1]["on_clicked"]()
        sent[1]["on_dismissed"]()
        assert cloud_commands == ["open", "dismiss"] and hub_commands == []
        await native.reconcile(set(), group="cloud")  # Cloud reconcile leaves the Hub toast alone.
        assert cleared == [2]
        await native.reconcile(set())
        assert cleared == [2, 1]
    asyncio.run(scenario())


# ------------------------------------------------- end to end, root and member
def test_cloud_notifications_reach_the_notifier_end_to_end(hosted, runtime):
    h = hosted
    h.profile.phone_runtime = runtime
    runtime.workspace._hosted = h.controller
    h.send(upsert())
    drain(runtime)
    h.send(upsert())
    drain(runtime)
    [shown] = runtime.native.shown
    assert shown.group == "cloud" and shown.row["device_id"] == h.device
    h.send(remove())
    drain(runtime)
    assert runtime.native.cleared == [notification_id(h.device, "k1")]
    h.received()
    # Dismissing the toast on the desktop dismisses the notification on the phone.
    h.send(upsert("k2"))
    drain(runtime)
    runtime.native.shown[-1].command(runtime.native.shown[-1].row, "dismiss")
    deadline = time.monotonic() + 5
    while h.profile.store.all("hosted_notification") and time.monotonic() < deadline:
        time.sleep(.02)
    assert h.profile.store.all("hosted_notification") == []
    assert dismiss_payload("k2") in h.received()


def test_a_joined_computer_shows_cloud_notifications_too(tmp_path, monkeypatch):
    import requests
    from cryptography.hazmat.primitives.asymmetric import ec
    from orion_mini.hosted_approval import make_request_code, trust_root_code
    from orion_mini.hosted_crypto import generate_recipient
    from orion_mini.hosted_session import SealedSession
    from test_hosted_second_computer import SyntheticService, computer

    monkeypatch.setattr(requests.sessions.Session, "request",
                        lambda *a, **k: pytest.fail("Synthetic Hosted test attempted a real HTTP request"))
    service = SyntheticService()
    main = computer(tmp_path, "main", service, monkeypatch, [])
    code = main.setup_root()
    root = trust_root_code(code["code"], trusted_out_of_band=True)
    laptop = computer(tmp_path, "laptop", service, monkeypatch, [])
    request = laptop.join(code["code"], True)
    main.approve(request["code"], "Synthetic laptop", True)
    device = "dev_" + uuid4().hex
    signing, encryption = ec.generate_private_key(ec.SECP256R1()), generate_recipient()
    main.approve(make_request_code(root, device, signing, encryption), "Synthetic phone", True)
    laptop.step()
    assert laptop.status == "active" and not laptop.is_root()
    handset = SealedSession(tmp_path / "phone.sqlite3", service.deployment, root.signing_key, device, signing, encryption)
    handset.accept_chain(deepcopy(service.chain))
    recorder = Recorder()
    laptop.workspace.phone_runtime = recorder

    def deliver(payload):
        service.inboxes.setdefault(laptop.info.device_id, []).append(handset.encrypt(laptop.info.device_id, payload))
        laptop.step()
    deliver(upsert())
    deliver(upsert())
    [row] = recorder.of("show")
    assert row["device_id"] == device and row["silent"] is False
    laptop.dismiss_notification(row["id"])
    laptop.step()
    assert recorder.of("reconcile")[-1] == set()
    assert dismiss_payload("k1") in [handset.authenticate(envelope) for envelope in service.inboxes.get(device, [])]
