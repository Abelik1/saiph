# SPDX-License-Identifier: AGPL-3.0-or-later
from types import SimpleNamespace

import pytest

from orion_mini import platform
from orion_mini.continuity import Continuity, validate_dnd
from orion_mini.storage import Store


class Focus:
    def __init__(self):
        self.quiet, self.previous, self.calls = False, None, []

    def set(self, quiet):
        self.calls.append(quiet)
        self.quiet = quiet


def continuity(tmp_path, *, readings=(), sync=True, now=1_800_000_000):
    workspace = SimpleNamespace(root=tmp_path, store=Store(tmp_path),
                                settings={"link": {"dnd_sync": sync}, "hub": {"device_id": "desktop"},
                                          "machine": {"features": {}}, "sleep_plan": {"hour": 23, "minute": 0}})
    published = []
    values = iter(readings)
    clock = {"now": now}
    result = Continuity(workspace, published.append, focus=Focus(), system=lambda _focus: next(values, None), clock=lambda: clock["now"])
    return result, published, clock


def frame(active, changed_at, source="phone"):
    return {"type": "focus.state", "source": source, "payload": {"active": active, "changed_at": changed_at}}


def test_remote_change_quiets_this_computer_without_echoing(tmp_path):
    sync, published, _ = continuity(tmp_path, readings=[False, False, False])
    sync.poll_dnd()
    assert sync.event(frame(True, 1_800_000_100))
    assert sync.focus.quiet is True
    sync.poll_dnd(); sync.poll_dnd()
    assert published == []
    assert sync.dnd_status() == {"enabled": True, "active": True, "source": "phone", "changed_at": 1_800_000_100, "quiet": True}


def test_owner_change_on_this_computer_is_published_once(tmp_path):
    sync, published, _ = continuity(tmp_path, readings=[False, True, True])
    assert sync.poll_dnd() is False  # First reading is only a baseline.
    assert sync.poll_dnd() is True
    assert sync.poll_dnd() is False
    assert [event["payload"] for event in published] == [{"active": True, "changed_at": 1_800_000_000}]
    assert published[0]["type"] == "focus.state" and "targets" not in published[0]


def test_older_changes_never_replace_newer_ones(tmp_path):
    sync, _, _ = continuity(tmp_path)
    sync.event(frame(True, 1_800_000_200))
    sync.event(frame(False, 1_800_000_100, source="laptop"))
    assert sync.dnd_state()["active"] is True and sync.focus.quiet is True


def test_offline_toggle_applies_locally_and_sends_when_connected(tmp_path):
    published = []
    sync, _, clock = continuity(tmp_path)
    def offline(_event):
        raise ValueError("offline")
    sync.publish = offline
    assert sync.set_dnd(True) == {"active": True, "shared": False}
    assert sync.focus.quiet is True
    sync.publish = published.append
    sync.poll_dnd()
    assert [event["payload"]["active"] for event in published] == [True]
    # Later toggles in the same second still order after the previous change.
    sync.set_dnd(False)
    assert published[-1]["payload"] == {"active": False, "changed_at": clock["now"] + 1}


def test_sync_switched_off_ignores_shared_state_and_refuses_toggles(tmp_path):
    sync, published, _ = continuity(tmp_path, readings=[False, True], sync=False)
    sync.event(frame(True, 1_800_000_100))
    assert sync.focus.quiet is False
    sync.poll_dnd(); sync.poll_dnd()
    assert published == []
    with pytest.raises(ValueError):
        sync.set_dnd(True)


def test_ending_shared_dnd_restores_notifications(tmp_path):
    sync, _, _ = continuity(tmp_path)
    sync.event(frame(True, 1_800_000_100))
    sync.focus.previous = False  # GNOME banners were already off when quiet began.
    sync.event(frame(False, 1_800_000_200))
    assert sync.focus.quiet is False and sync.focus.previous is True


def test_malformed_states_are_rejected():
    for payload in ({"active": 1, "changed_at": 5}, {"active": True}, {"active": True, "changed_at": True},
                    {"active": True, "changed_at": 5, "until": 9}, {"active": True, "changed_at": 0}):
        with pytest.raises(ValueError):
            validate_dnd(payload)


def test_gnome_reading_excludes_quiet_that_saiph_applied(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "ubuntu:GNOME")
    monkeypatch.setattr(platform.shutil, "which", lambda _name: "/usr/bin/gsettings")
    banners = {"value": b"false\n"}
    monkeypatch.setattr(platform.subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=0, stdout=banners["value"]))
    focus = Focus()
    assert platform.system_dnd(focus) is True
    focus.quiet = True
    assert platform.system_dnd(focus) is None
    banners["value"] = b"true\n"
    assert platform.system_dnd(focus) is False


def test_unknown_desktops_report_no_reading(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    assert platform.system_dnd(Focus()) is None
