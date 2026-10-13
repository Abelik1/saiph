# SPDX-License-Identifier: AGPL-3.0-or-later
from types import SimpleNamespace
from uuid import uuid4

import pytest

from orion_mini import phone_features as f
from orion_mini.storage import Store

CAPS = ["media", "contacts", "sms", "ringer", "call-dial", "call-log"]


def features(tmp_path, capabilities=CAPS):
    published = []
    runtime = SimpleNamespace(client=SimpleNamespace(publish=published.append),
                              loop=SimpleNamespace(call_soon_threadsafe=lambda fn, event: fn(event)))
    devices = [{"id": "phone", "online": True, "capabilities": list(capabilities)}]
    workspace = SimpleNamespace(root=tmp_path, store=Store(tmp_path), phone_runtime=runtime,
                                phone=SimpleNamespace(connected=True, snapshot=lambda: {"devices": devices}))
    return f.PhoneFeatures(workspace), published


def event(kind, payload, source="phone"):
    return {"id": str(uuid4()), "type": kind, "source": source, "payload": payload}


def test_media_and_ringer_state_survive_a_restore(tmp_path):
    service, _ = features(tmp_path)
    service.event(event("media.state", {"sessions": [{"source": "com.spotify.music", "title": "Song", "playing": True}]}), None)
    service.event(event("ringer.state", {"mode": "vibrate"}), None)
    snapshot = service.snapshot()
    assert snapshot["media"][0]["sessions"][0]["title"] == "Song"
    assert snapshot["ringers"][0]["mode"] == "vibrate"
    restored, _ = features(tmp_path / "other")
    restored.restore({"media": snapshot["media"], "ringers": snapshot["ringers"]})
    assert restored.snapshot()["ringers"][0]["mode"] == "vibrate"


def test_commands_are_validated_and_sent_to_the_owning_phone(tmp_path):
    service, published = features(tmp_path)
    service.dispatch("phone.media", {"device_id": "phone", "source": "com.spotify.music", "action": "next"})
    service.dispatch("phone.media", {"device_id": "phone", "source": "com.spotify.music", "action": "volume", "value": 40})
    service.dispatch("phone.contacts.search", {"device_id": "phone", "query": " Ali "})
    service.dispatch("phone.sms.compose", {"device_id": "phone", "address": "+447700900123", "text": "Hello"})
    service.dispatch("phone.ringer", {"device_id": "phone", "mode": "silent"})
    service.dispatch("phone.dial", {"device_id": "phone", "number": "+44 7700 900123"})
    service.dispatch("phone.calls.log", {"device_id": "phone"})
    assert [(e["type"], e["payload"]) for e in published] == [
        ("media.command", {"source": "com.spotify.music", "action": "next"}),
        ("media.command", {"source": "com.spotify.music", "action": "volume", "value": 40}),
        ("contacts.search", {"query": "Ali"}),
        ("sms.compose", {"addresses": ["+447700900123"], "text": "Hello"}),
        ("phone.ringer", {"mode": "silent"}),
        ("call.dial", {"number": "+44 7700 900123"}),
        ("calls.log.request", {}),
    ]
    assert all(e["targets"] == ["phone"] for e in published)


@pytest.mark.parametrize("method, args", [
    ("phone.media", {"source": "x", "action": "shell"}),
    ("phone.media", {"source": "x", "action": "volume", "value": 101}),
    ("phone.contacts.search", {"query": ""}),
    ("phone.sms.compose", {"address": "", "text": "x"}),
    ("phone.sms.compose", {"address": "1", "text": " "}),
    ("phone.ringer", {"mode": "loud"}),
    ("phone.dial", {"number": "*21*07700900123#"}),
    ("phone.dial", {"number": "()"}),
])
def test_invalid_commands_are_refused_before_sending(tmp_path, method, args):
    service, published = features(tmp_path)
    with pytest.raises(ValueError):
        service.dispatch(method, {"device_id": "phone", **args})
    assert published == []


def test_commands_need_the_phone_capability(tmp_path):
    service, published = features(tmp_path, capabilities=["sms"])
    with pytest.raises(ValueError):
        service.dispatch("phone.dial", {"device_id": "phone", "number": "123"})
    assert published == []


def test_contacts_and_call_history_stay_in_memory_and_expire(tmp_path, monkeypatch):
    service, _ = features(tmp_path)
    service.event(event("contacts.results", {"query": "Ali", "contacts": [{"name": "Alice", "numbers": ["1"]}]}), None)
    service.event(event("calls.log", {"calls": [{"number": "1", "name": "Alice", "timestamp": 1, "duration": 2, "type": "missed"}]}), None)
    snapshot = service.snapshot()
    assert snapshot["contacts"][0]["contacts"][0]["name"] == "Alice"
    assert snapshot["call_logs"][0]["calls"][0]["type"] == "missed"
    assert not any(row for kind in ("contacts.results", "calls.log") for row in service.store.all(kind))
    real = f.time.time
    monkeypatch.setattr(f.time, "time", lambda: real() + f.ANSWER_SECONDS + 1)
    assert service.snapshot()["contacts"] == [] and service.snapshot()["call_logs"] == []
