# SPDX-License-Identifier: AGPL-3.0-or-later
import time

from test_acceptance import headers, pair
from test_link import client, event, hub


def test_signed_snapshot_and_transactional_bus_include_sms_and_focus(hub):
    c = client(hub)
    key, computer = pair(hub, c)
    _, phone = pair(hub, c)
    message = {"thread": 7, "recipients": ["test"], "message": {"id": 1, "addresses": ["test"],
               "body": "PRIVATE_SMS", "timestamp": 1, "direction": "incoming", "subscription": 0}}
    hub.LINK.store.publish(phone, event(type="sms.thread", payload=message))
    plan = {"enabled": True, "timezone": "Europe/London", "start_hour": 23, "start_minute": 0, "end_hour": 7, "end_minute": 0}
    hub.LINK.store.publish(computer, event(type="focus.plan", payload=plan))
    hub.LINK.store.cleanup(time.time() + 301)
    path = "/v1/link/phone"
    snapshot = c.get(path, headers=headers(key, computer, "GET", path)).json()
    assert snapshot["threads"][0]["device_id"] == phone and snapshot["messages"][0]["body"] == "PRIVATE_SMS"
    path = "/v1/link/continuity"
    assert c.get(path).status_code == 401
    response = c.get(path, headers=headers(key, computer, "GET", path))
    assert response.status_code == 200 and response.json()["focus"]["payload"] == plan
