# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from types import SimpleNamespace
from pathlib import Path
from uuid import uuid4

import pytest

from orion_hub import continuity
from orion_hub.db import Database


def test_focus_retained_after_expiry_and_device_revocation(tmp_path):
    db = Database(tmp_path / "hub.sqlite")
    with db.connect() as c:
        c.executescript(continuity.SCHEMA)
        c.execute("INSERT INTO devices(id,name,public_key_der_b64,created_at) VALUES('phone','Phone','test','now')")
        plan = dict(enabled=True, timezone="Europe/London", start_hour=23, start_minute=0, end_hour=7, end_minute=0)
        event = SimpleNamespace(type="focus.plan", payload=plan, targets=None)
        continuity.apply(c, "phone", event, 100)
    assert continuity.snapshot(db)["focus"]["payload"] == plan
    restarted = Database(tmp_path / "hub.sqlite")
    assert continuity.snapshot(restarted)["focus"]["payload"] == plan
    db.execute("DELETE FROM devices WHERE id='phone'")
    assert continuity.snapshot(db)["focus"] is None


def test_wake_accepts_only_fixed_target_and_dispatches_once(tmp_path, monkeypatch):
    config = tmp_path / "targets.json"
    config.write_text(json.dumps({"desktop": {"mac": "00:11:22:33:44:55", "broadcast": "192.168.1.255"}}))
    monkeypatch.setenv("ORION_WAKE_TARGETS", str(config))
    event = SimpleNamespace(type="wake", payload={"target": "desktop"}, targets=None, id=str(uuid4()))
    continuity.validate(event)
    with pytest.raises(ValueError):
        continuity.validate(SimpleNamespace(type="wake", payload={"target": "desktop", "address": "attacker"}, targets=None))
    with pytest.raises(ValueError):
        continuity.validate(SimpleNamespace(type="wake", payload={"target": "unknown"}, targets=None))
    db = Database(tmp_path / "hub.sqlite")
    with db.connect() as c:
        c.executescript(continuity.SCHEMA)
        c.execute("INSERT INTO devices(id,name,public_key_der_b64,created_at) VALUES('phone','Phone','test','now')")
        c.execute("INSERT INTO link_events VALUES(?,?,?,?,?,?,?)", (event.id, "phone", "wake", '{}', "digest", 100, 200))
        continuity.after_insert(c, event)
    packets = []
    class FakeSocket:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def setsockopt(self, *args): pass
        def sendto(self, data, address): packets.append((data, address))
    monkeypatch.setattr(continuity.socket, "socket", lambda *_: FakeSocket())
    continuity.dispatch(db, 150); continuity.dispatch(db, 151)
    assert len(packets) == 1
    assert packets[0][0] == b'\xff' * 6 + bytes.fromhex('001122334455') * 16
    assert packets[0][1] == ("192.168.1.255", 9)


def test_handoff_shell_urls_and_focus_malformed_payload_are_rejected():
    with pytest.raises(ValueError):
        continuity.validate(SimpleNamespace(type="handoff", payload=dict(kind="link", value="file:///private"), targets=["desktop"]))
    with pytest.raises(ValueError):
        continuity.validate(SimpleNamespace(type="focus.plan", payload={}, targets=None))


def test_do_not_disturb_latest_change_is_shared_and_validated(tmp_path):
    db = Database(tmp_path / "hub.sqlite")
    with db.connect() as c:
        c.executescript(continuity.SCHEMA)
        for device in ("phone", "desktop"):
            c.execute("INSERT INTO devices(id,name,public_key_der_b64,created_at) VALUES(?,?,'test','now')", (device, device))
        continuity.apply(c, "phone", SimpleNamespace(type="focus.state", payload={"active": True, "changed_at": 1_800_000_000}, targets=None), 1_800_000_100)
        continuity.apply(c, "desktop", SimpleNamespace(type="focus.state", payload={"active": False, "changed_at": 1_800_000_060}, targets=None), 1_800_000_090)
        # A far-future time (a wrong clock) cannot pin the shared state.
        with pytest.raises(ValueError, match="future"):
            continuity.apply(c, "phone", SimpleNamespace(type="focus.state", payload={"active": True, "changed_at": 2**41 - 1}, targets=None), 1_800_000_100)
    assert continuity.snapshot(db)["dnd"] == {"source": "desktop", "active": False, "changed_at": 1_800_000_060}
    for payload, targets in (({"active": "yes", "changed_at": 1}, None), ({"active": True}, None),
                             ({"active": True, "changed_at": 1.5}, None), ({"active": True, "changed_at": 1, "app": "x"}, None),
                             ({"active": True, "changed_at": 1}, ["phone"])):
        with pytest.raises(ValueError):
            continuity.validate(SimpleNamespace(type="focus.state", payload=payload, targets=targets))
    db.execute("DELETE FROM devices WHERE id='desktop'")
    assert continuity.snapshot(db)["dnd"]["source"] == "phone"
