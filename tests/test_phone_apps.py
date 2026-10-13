# SPDX-License-Identifier: AGPL-3.0-or-later
from types import SimpleNamespace

import pytest

from orion_mini import phone_apps

LIST = """INFO: scrcpy 3.3.4 <https://github.com/Genymobile/scrcpy>
[server] INFO: List of apps:
 * Settings                    com.android.settings
 - Spotify                     com.spotify.music
 - Bad entry                   ; rm -rf
 - Spotify                     com.spotify.music
"""


def test_list_is_parsed_and_user_apps_come_first(monkeypatch):
    monkeypatch.setattr(phone_apps, "_scrcpy", lambda: "scrcpy")
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs["env"]["ADB"]))
        return SimpleNamespace(stdout=LIST, stderr="")
    result = phone_apps.list_apps("/sdk/adb", "R58M1", runner=run)
    assert result == {"apps": [{"package": "com.spotify.music", "name": "Spotify", "system": False},
                               {"package": "com.android.settings", "name": "Settings", "system": True}]}
    assert calls == [(["scrcpy", "--serial", "R58M1", "--list-apps"], "/sdk/adb")]


def test_open_passes_only_a_validated_package_as_one_argument(monkeypatch):
    monkeypatch.setattr(phone_apps, "_scrcpy", lambda: "scrcpy")
    started = []
    phone_apps.open_app("/sdk/adb", "R58M1", "com.spotify.music", "Spotify", runner=lambda command, **_: started.append(command))
    assert started == [["scrcpy", "--serial", "R58M1", "--new-display", "--start-app=com.spotify.music", "--no-audio", "--window-title", "Spotify · Phone"]]
    for package in ("--shell", "com.spotify.music; calc", "spotify", "+com.app"):
        with pytest.raises(ValueError):
            phone_apps.open_app("/sdk/adb", "R58M1", package, runner=lambda *_a, **_k: None)
    with pytest.raises(ValueError):
        phone_apps.open_app("/sdk/adb", "R58 M1", "com.spotify.music", runner=lambda *_a, **_k: None)


def test_linux_pin_writes_an_owned_menu_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(phone_apps.sys, "platform", "linux")
    result = phone_apps.pin("com.spotify.music", "Spotify\nExec=evil", home=tmp_path)
    text = (tmp_path / "applications" / "saiph-phone-com.spotify.music.desktop").read_text()
    assert result["pinned"] and "# ORION_OWNED=1" in text and "--open-phone-app com.spotify.music" in text
    assert not any(line.startswith("Exec=evil") for line in text.splitlines())  # The newline cannot start a new key.
    with pytest.raises(ValueError):
        phone_apps.pin("not a package", "x", home=tmp_path)


def test_api_route_opens_only_valid_packages(tmp_path):
    import json, urllib.request
    from orion_mini.api import ApiServer
    opened = []
    workspace = SimpleNamespace(root=tmp_path, settings={"machine": {"name": "Test"}}, plugins=None, request_open_phone_app=opened.append)
    server = ApiServer(workspace, 0)
    info = server.start()
    try:
        token = json.loads((tmp_path / "api.json").read_text())["token"]
        def post(body):
            request = urllib.request.Request(info["url"] + "/v1/phone/app", data=json.dumps(body).encode(),
                                             headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
            try:
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=5) as response:
                    return response.status
            except urllib.error.HTTPError as error:
                return error.code
        assert post({"package": "com.spotify.music"}) == 202
        assert post({"package": "com.spotify.music; calc"}) == 400
        assert opened == ["com.spotify.music"]
    finally:
        server.stop()
