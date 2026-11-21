# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone remote over the local network (remote_lan.py), through the real pinned-TLS server."""
import json
import time

import pytest
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from lan_tls import websocket_client_context
from orion_mini.remote_lan import RemoteLan
from test_remote import Pointer, command, setup


def lan_remote(addresses=("192.168.1.7",), **options):
    controls = Pointer()
    service, published, now = setup({"adapters": {"touchpad": True, "media": True}, **options}, controls)
    service.lan = RemoteLan(service, addresses=lambda: list(addresses))
    return service, controls, published


def open_socket(invite, secret=None, session=None):
    return connect(f"wss://127.0.0.1:{invite['port']}/remote/{session or invite['session']}", ssl=websocket_client_context(),
                   proxy=None, additional_headers={"Authorization": "Bearer " + (secret or invite["secret"])})


def wait_for(check, seconds=3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.01)
    return check()


@pytest.fixture
def lan():
    service, controls, published = lan_remote()
    yield service, controls, published
    service.lan.close()


def test_an_allowed_phone_gets_a_one_use_pinned_invitation(lan):
    service, controls, _ = lan
    invite = service.lan.offer("phone")
    assert set(invite) == {"session", "addresses", "port", "certificate", "secret", "expires"}
    assert invite["addresses"] == ["192.168.1.7"] and len(invite["certificate"]) == 64 and len(invite["secret"]) == 43
    with open_socket(invite) as socket:
        socket.send(json.dumps({"t": "cmd", "c": {"app": "touchpad", "control": "move", "dx": 40, "dy": -7}}))
        assert wait_for(lambda: controls.calls == [("pointer", "move", 40, -7)])
        socket.send('{"t":"hb"}')
        socket.send(json.dumps({"t": "cmd", "c": {"app": "touchpad", "control": "click"}}))
        assert wait_for(lambda: len(controls.calls) == 2)
        assert controls.calls[-1] == ("pointer", "click", 0, 0)
        assert service.lan.live("phone")
    assert service.last["device_id"] == "phone"
    # The invitation worked once: the same secret now opens nothing.
    with pytest.raises((InvalidStatus, OSError)):
        open_socket(invite)


def test_a_refused_command_is_answered_and_movement_is_not(lan):
    service, controls, _ = lan
    invite = service.lan.offer("phone")
    with open_socket(invite) as socket:
        socket.send(json.dumps({"t": "cmd", "c": {"app": "touchpad", "control": "move", "dx": 3, "dy": 3}}))
        socket.send(json.dumps({"t": "cmd", "c": {"app": "nothing", "control": "x"}}))
        answer = json.loads(socket.recv(timeout=3))
        assert answer["t"] == "result" and answer["ok"] is False and answer["app"] == "nothing"
    assert controls.calls == [("pointer", "move", 3, 3)]


def test_wrong_secret_wrong_session_and_unallowed_phones_get_nothing(lan):
    service, controls, _ = lan
    assert service.lan.offer("stranger") is None
    invite = service.lan.offer("phone")
    for bad in ({"secret": "x" * 43}, {"session": "0" * 32}):
        with pytest.raises((InvalidStatus, OSError)):
            open_socket(invite, **bad)
    with open_socket(invite) as socket:  # The real invitation still works after the failed guesses.
        socket.send('{"t":"hb"}')
    assert controls.calls == []


def test_no_private_network_means_no_invitation():
    service, _, _ = lan_remote(addresses=())
    assert service.lan.offer("phone") is None
    service, _, _ = lan_remote(addresses=("8.8.8.8",))
    assert service.lan.offer("phone") is None


def test_malformed_messages_end_the_channel_and_a_new_offer_replaces_the_old(lan):
    service, controls, _ = lan
    invite = service.lan.offer("phone")
    with open_socket(invite) as socket:
        socket.send("not json")
        assert wait_for(lambda: not service.lan.live("phone"))
    first = service.lan.offer("phone")
    second = service.lan.offer("phone")
    assert first["session"] != second["session"]
    with pytest.raises((InvalidStatus, OSError)):
        open_socket(first)
    with open_socket(second) as socket:
        socket.send(json.dumps({"t": "cmd", "c": {"app": "touchpad", "control": "move", "dx": 1, "dy": 1}}))
        assert wait_for(lambda: len(controls.calls) == 1)


def test_turning_a_phone_off_stops_its_commands_at_once(lan):
    service, controls, _ = lan
    invite = service.lan.offer("phone")
    with open_socket(invite) as socket:
        socket.send(json.dumps({"t": "cmd", "c": {"app": "touchpad", "control": "move", "dx": 1, "dy": 1}}))
        assert wait_for(lambda: len(controls.calls) == 1)
        service.workspace.settings["link"]["remote"]["devices"] = []
        socket.send(json.dumps({"t": "cmd", "c": {"app": "touchpad", "control": "move", "dx": 1, "dy": 1}}))
        answer = json.loads(socket.recv(timeout=3))
        assert answer["ok"] is False
    assert len(controls.calls) == 1
