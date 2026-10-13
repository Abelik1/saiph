# SPDX-License-Identifier: AGPL-3.0-or-later
"""Your week: computed and kept on this computer only, independent of sharing."""
import json

import pytest

from orion_mini.link_service import LinkWorkspace

NOW = 1_800_000_000  # Friday 2027-01-15 08:00 UTC


@pytest.fixture
def workspace(tmp_path):
    workspace = LinkWorkspace(tmp_path)
    workspace.insights.clock = workspace.usage_counter.clock = lambda: NOW
    return workspace


def message(thread, offset_days, direction, number):
    return {"id": f"m{thread}-{number}", "device_id": "phone", "thread": thread, "body": "synthetic",
            "timestamp": int((NOW - offset_days * 86400) * 1000), "direction": direction}


def test_week_summarises_features_and_people_without_sharing(workspace):
    sent = []
    workspace.usage_counter.endpoint = "https://service.example.test/v1/usage"
    workspace.usage_counter.post = lambda url, batch: sent.append(batch)
    for _ in range(3):
        workspace.usage_counter.count("sms_send")
    workspace.usage_counter.count("clipboard_sent")
    workspace.usage_counter.screen("messages")
    workspace.store.save("phone_thread", {"id": "t1", "device_id": "phone", "thread": 1, "recipients": ["Synthetic Ana"], "message": {}})
    workspace.store.save("phone_thread", {"id": "t2", "device_id": "phone", "thread": 2, "recipients": ["Synthetic Ben"], "message": {}})
    for number in range(4):
        workspace.store.save("phone_message", message(1, 1, "outgoing" if number % 2 else "incoming", number))
    workspace.store.save("phone_message", message(2, 2, "outgoing", 9))
    workspace.store.save("phone_message", message(2, 30, "outgoing", 10))  # Older than a week.
    week = workspace.dispatch("insights.week", {})
    assert week["actions"] == 4 and week["screen"] == "messages" and week["busiest_day"] == "Friday"
    assert week["top"][0] == {"feature": "sms_send", "label": "Text message sent through the phone", "count": 3}
    assert week["people"] == [{"name": "Synthetic Ana", "sent": 2, "received": 2, "total": 4},
                              {"name": "Synthetic Ben", "sent": 1, "received": 0, "total": 1}]
    # Sharing was never agreed: nothing was counted for, or sent to, the service.
    assert workspace.store.all("usage_day") == [] and workspace.usage_counter.flush() == 0 and sent == []


def test_shared_batches_never_contain_the_personal_summary(workspace):
    workspace.usage_counter.endpoint = "https://service.example.test/v1/usage"
    workspace.dispatch("usage.consent", {"granted": True})
    workspace.store.save("phone_thread", {"id": "t1", "device_id": "phone", "thread": 1, "recipients": ["Synthetic Ana"], "message": {}})
    workspace.store.save("phone_message", message(1, 0, "outgoing", 1))
    workspace.usage_counter.count("sms_send")
    workspace.usage_counter.clock = lambda: NOW + 86400
    [batch] = workspace.usage_counter.pending()
    assert "Synthetic Ana" not in json.dumps(batch) and batch["features"] == {"sms_send": "1"}


def test_turning_off_deletes_counts_and_stops_counting(workspace):
    workspace.usage_counter.count("call")
    assert workspace.store.all("insight_day")
    workspace.dispatch("insights.enable", {"enabled": False})
    assert workspace.store.all("insight_day") == [] and workspace.state()["insights"] == {"enabled": False}
    workspace.usage_counter.count("call")
    assert workspace.store.all("insight_day") == [] and workspace.dispatch("insights.week", {}) == {"enabled": False}
    workspace.dispatch("insights.enable", {"enabled": True})
    workspace.usage_counter.count("call")
    workspace.dispatch("insights.clear", {})
    assert workspace.store.all("insight_day") == []
    with pytest.raises(ValueError):
        workspace.dispatch("insights.enable", {"enabled": "no"})


def test_counts_older_than_two_weeks_are_removed(workspace):
    workspace.usage_counter.count("call")
    workspace.insights.clock = lambda: NOW + 15 * 86400
    workspace.usage_counter.count("photo_save")
    assert [row["id"] for row in workspace.store.all("insight_day")] == ["2027-01-30"]
