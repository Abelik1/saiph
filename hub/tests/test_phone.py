# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import time
from uuid import uuid4

import pytest
from test_link import hub, client, socket, until, event
from test_acceptance import pair, headers
from orion_hub import phone
from orion_hub.db import Database

def notice(**changes):
    return {"key": "private-key", "app": "Messages", "package": "test.messages", "title": "PRIVATE_TITLE",
            "text": "PRIVATE_BODY", "timestamp": 1, "actions": [{"index": 2, "label": "Archive"}], "reply_key": "reply", **changes}

def publish(hub, source, kind, payload, **extra):
    return hub.LINK.store.publish(source, event(type=kind, payload=payload, **extra))

def test_notification_state_survives_delivery_expiry_and_restart_then_reconciles(hub):
    c = client(hub); _, source = pair(hub, c); key, desktop = pair(hub, c)
    publish(hub, source, "notification.upsert", notice())
    publish(hub, source, "battery", {"battery_level": 73, "is_charging": False})
    hub.LINK.store.cleanup(time.time() + 301)
    db = Database(hub.DB.path)
    state = phone.snapshot(db, hub.LINK.presence())
    assert state["notifications"][0]["text"] == "PRIVATE_BODY"
    assert next(d for d in state["devices"] if d["id"] == source)["battery"]["battery_level"] == 73
    path = "/v1/link/phone"
    assert c.get(path).status_code == 401
    r = c.get(path, headers=headers(key, desktop, "GET", path))
    assert r.status_code == 200 and r.json()["notifications"][0]["device_id"] == source
    publish(hub, source, "notification.sync", {"keys": []})
    assert phone.snapshot(db, [])['notifications'] == []

def test_only_source_owns_state_and_commands_target_existing_actions(hub):
    c = client(hub); _, source = pair(hub, c); _, desktop = pair(hub, c); _, other = pair(hub, c)
    publish(hub, source, "notification.upsert", notice())
    publish(hub, other, "notification.remove", {"key": "private-key"})
    assert len(phone.snapshot(hub.DB, [])['notifications']) == 1
    publish(hub, desktop, "notification.command", {"key": "private-key", "operation": "action", "index": 2}, targets=[source])
    publish(hub, desktop, "notification.command", {"key": "private-key", "operation": "reply", "reply_key": "reply", "text": "PRIVATE_REPLY"}, targets=[source])
    rejected = [({}, None), ({"index": 3, "operation": "action"}, [source]),
                ({"operation": "reply", "reply_key": "wrong", "text": "x"}, [source]),
                ({"operation": "dismiss", "text": "x"}, [source]), ({}, [other]), ({}, [source, other])]
    for changes, targets in rejected:
        with pytest.raises(ValueError):
            publish(hub, desktop, "notification.command", {"key": "private-key", "operation": "dismiss", **changes}, **({"targets": targets} if targets else {}))

@pytest.mark.parametrize('kind,payload', [
    ('notification.upsert', notice(title='x'*513)), ('notification.upsert', notice(extra='PRIVATE')),
    ('notification.upsert', notice(actions=[{'index': 2,'label':'a'},{'index':2,'label':'b'}])),
    ('notification.sync', {'keys':['duplicate','duplicate']}), ('notification.sync', {'keys':['x'*513]}),
    ('battery', {'battery_level':True,'is_charging':False}), ('battery', {'battery_level':101,'is_charging':True})])
def test_invalid_feature_envelopes_leave_no_state_or_delivery(hub, kind, payload):
    c = client(hub); _, source = pair(hub,c)
    with pytest.raises(ValueError):publish(hub,source,kind,payload)
    assert not hub.DB.rows('SELECT * FROM link_events')
    assert not hub.DB.rows('SELECT * FROM phone_notifications')
    assert not hub.DB.rows('SELECT * FROM phone_state')

def test_atomic_dedup_and_revocation_delete_phone_state(hub, caplog):
    c=client(hub);_,source=pair(hub,c)
    item=event(type='notification.upsert',payload=notice())
    assert not hub.LINK.store.publish(source,item)['duplicate']
    assert hub.LINK.store.publish(source,item)['duplicate']
    assert len(hub.DB.rows('SELECT * FROM phone_notifications'))==1
    publish(hub,source,'battery',{'battery_level':80,'is_charging':True})
    hub.DB.execute('DELETE FROM devices WHERE id=?',(source,))
    assert not hub.DB.rows('SELECT * FROM phone_notifications') and not hub.DB.rows('SELECT * FROM phone_state')
    assert 'PRIVATE_BODY' not in caplog.text and 'PRIVATE_TITLE' not in caplog.text
