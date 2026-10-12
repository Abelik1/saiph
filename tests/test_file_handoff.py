# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from orion_mini.continuity import received_file_handoff, validate_handoff
from orion_mini.phone_features import PhoneFeatures
from orion_mini.storage import Store


def workspace(tmp_path):
    return SimpleNamespace(root=tmp_path, store=Store(tmp_path), settings={"cloud": {"path": str(tmp_path / "Cloud")}})


def completed(obj):
    path = Path(obj.settings["cloud"]["path"]) / "Shared" / "Lecture.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"verified synthetic file")
    event = {"id": str(uuid4()), "type": "file.offer", "source": "paired-computer", "payload": {"name": "../../Lecture.pdf", "size": path.stat().st_size, "destination": "cloud"}}
    features = PhoneFeatures(obj)
    obj.store.save("phone_transfer", {"id": event["id"], "event": event})
    features._complete_file(event, path)
    return features, event, path


def test_received_file_handoff_and_receipt_commit_together_without_resurrecting_dismissed_item(tmp_path):
    obj = workspace(tmp_path)
    features, event, path = completed(obj)
    item = obj.store.get("handoff", event["id"])
    assert item["kind"] == "file" and item["file_id"] == event["id"]
    assert item["value"] == "Lecture.pdf" and "path" not in item
    assert received_file_handoff(obj, event["id"]) == path
    assert not obj.store.all("phone_transfer")
    obj.store.delete("handoff", event["id"])
    features._complete_file(event, path)
    assert not obj.store.all("handoff") and len(obj.store.all("phone_file")) == 1


def test_remote_paths_and_incomplete_or_replaced_local_files_cannot_be_opened_as_handoff(tmp_path):
    obj = workspace(tmp_path)
    _, event, path = completed(obj)
    with pytest.raises(ValueError):
        validate_handoff({"kind": "file", "value": "/etc/passwd"})
    row = obj.store.get("phone_file", event["id"])
    outside = tmp_path / "outside.exe"
    outside.write_bytes(b"outside")
    obj.store.save("phone_file", {**row, "path": str(outside)})
    with pytest.raises(ValueError, match="unavailable"):
        received_file_handoff(obj, event["id"])
    obj.store.save("phone_file", {**row, "device_id": "different-sender"})
    with pytest.raises(ValueError):
        received_file_handoff(obj, event["id"])
    obj.store.save("phone_file", row)
    path.unlink()
    with pytest.raises(ValueError):
        received_file_handoff(obj, event["id"])


def test_native_open_is_deliberate_and_file_picker_ignores_remote_paths(tmp_path, monkeypatch):
    from orion_mini import desktop_bridge as module
    obj = workspace(tmp_path)
    _, event, path = completed(obj)
    responses, opened, deferred, sends = [], [], [], []
    obj.dispatch = lambda method, args: sends.append((method, args))
    bridge = SimpleNamespace(window=SimpleNamespace(workspace=obj, pump_jobs=lambda: None), response=SimpleNamespace(emit=lambda packet: responses.append(json.loads(packet))), changed=SimpleNamespace(emit=lambda: None), background=lambda ident, action: deferred.append(action))
    monkeypatch.setattr(module, "open_target", opened.append)
    assert not opened
    module.DesktopBridge.request(bridge, "open", "continuity.open", json.dumps({"id": event["id"], "path": str(tmp_path / "outside.exe")}))
    assert responses[-1]["ok"] and opened == [path]
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    module.DesktopBridge.request(bridge, "choose", "continuity.file.choose", json.dumps({"device_id": "laptop", "path": "/remote/untrusted"}))
    assert not sends
    deferred[-1]()
    assert sends == [("phone.file.send", {"device_id": "laptop", "path": str(path)})]


def test_file_transport_targets_an_online_computer_using_its_existing_files_capability(tmp_path):
    obj = workspace(tmp_path)
    outgoing = []
    obj.phone = SimpleNamespace(connected=True, snapshot=lambda: {"devices": [{"id": "laptop", "online": True, "capabilities": ["files", "handoff"]}]})
    obj.phone_runtime = SimpleNamespace(client=SimpleNamespace(publish=outgoing.append), loop=SimpleNamespace(call_soon_threadsafe=lambda action, event: action(event)))
    result = PhoneFeatures(obj).command("laptop", "file.offer", {"name": "file.pdf"})
    assert result["queued"] and outgoing[0]["targets"] == ["laptop"]


def test_photo_downloads_do_not_create_unsolicited_file_handoffs(tmp_path):
    obj = workspace(tmp_path)
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"photo")
    PhoneFeatures(obj)._complete_file({"id": str(uuid4()), "type": "photo.original", "source": "phone", "payload": {"size": 5}}, path)
    assert obj.store.all("phone_file") and not obj.store.all("handoff")
