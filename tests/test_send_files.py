# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from pathlib import Path

import pytest

from orion_mini import send_files


def test_paths_are_resolved_deduplicated_and_bounded(tmp_path):
    a = tmp_path / "a.txt"; a.write_text("a")
    b = tmp_path / "b.txt"; b.write_text("b")
    assert send_files.validate([str(a), str(b), str(a)]) == [str(a.resolve()), str(b.resolve())]
    for paths in ([], [str(tmp_path)], [str(tmp_path / "missing.txt")], [str(a)] * 21, "a.txt", [5]):
        with pytest.raises(ValueError):
            send_files.validate(paths)


def test_targets_are_online_file_capable_devices_other_than_this_computer():
    state = {"settings": {"hub": {"device_id": "desktop"}}, "phone": {"devices": [
        {"id": "desktop", "name": "Desktop", "online": True, "capabilities": ["files"]},
        {"id": "phone", "name": "Galaxy", "online": True, "capabilities": ["files"]},
        {"id": "old", "name": "Old phone", "online": False, "capabilities": ["files"]},
        {"id": "tablet", "name": "Tablet", "online": True, "capabilities": ["sms"]}]}}
    assert [d["id"] for d in send_files.targets(state)] == ["phone"]


def test_command_line_split_keeps_other_arguments(tmp_path):
    argv, paths = send_files.arguments(["saiph", "--send-files", "x.txt", "y.txt"])
    assert argv == ["saiph"] and [Path(p).name for p in paths] == ["x.txt", "y.txt"] and all(Path(p).is_absolute() for p in paths)
    assert send_files.arguments(["saiph"]) == (["saiph"], None)


def test_running_instance_receives_the_paths(tmp_path, monkeypatch):
    sent = {}
    class Response:
        status = 202
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Opener:
        def open(self, request, timeout):
            sent.update(url=request.full_url, body=json.loads(request.data), auth=request.headers["Authorization"])
            return Response()
    import urllib.request
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: Opener())
    (tmp_path / "api.json").write_text(json.dumps({"url": "http://127.0.0.1:8123", "token": "secret"}))
    assert send_files.forward(tmp_path, ["C:/a.txt"])
    assert sent == {"url": "http://127.0.0.1:8123/v1/phone/send", "body": {"paths": ["C:/a.txt"]}, "auth": "Bearer secret"}
    (tmp_path / "api.json").write_text(json.dumps({"url": "http://example.com:8123", "token": "secret"}))
    assert not send_files.forward(tmp_path, ["C:/a.txt"])


def test_api_route_requires_a_live_window_and_valid_files(tmp_path):
    from orion_mini.api import ApiServer
    import urllib.request
    received = []
    from types import SimpleNamespace
    workspace = SimpleNamespace(root=tmp_path, settings={"machine": {"name": "Test"}}, plugins=None, request_send_files=received.append)
    server = ApiServer(workspace, 0)
    info = server.start()
    try:
        token = json.loads((tmp_path / "api.json").read_text())["token"]
        file = tmp_path / "photo.jpg"; file.write_bytes(b"x")
        def post(body):
            request = urllib.request.Request(info["url"] + "/v1/phone/send", data=json.dumps(body).encode(),
                                             headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
            try:
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=5) as response:
                    return response.status
            except urllib.error.HTTPError as error:
                return error.code
        assert post({"paths": [str(file)]}) == 202
        assert received == [[str(file.resolve())]]
        assert post({"paths": [str(tmp_path)]}) == 400
        assert post({"paths": [str(file)], "device_id": "phone"}) == 400
        assert len(received) == 1
    finally:
        server.stop()
