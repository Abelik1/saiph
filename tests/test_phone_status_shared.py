# SPDX-License-Identifier: AGPL-3.0-or-later
"""One phone status layer for the self-hosted Hub and Saiph Cloud.

Synthetic phones only. The Hub path is exercised through PhoneState and
PhoneFeatures with a fake mesh client; no Hub, phone or network is contacted.
"""
import json
from types import SimpleNamespace

import pytest

from orion_mini import phone_features as f
from orion_mini import phone_status as ps
from orion_mini.hosted_features import FeatureError, phone_command, read_phone_data
from orion_mini.phone import PhoneState
from orion_mini.storage import Store

# The body both transports carry; Cloud adds "type" inside the sealed payload.
# android/.../PhoneStatusFramesTest.kt checks the same literal for the Hub body.
LINK_STATUS_WIRE = ('{"battery":76,"bluetooth":true,"cellular":false,"charging":true,"controls":["status","ring","ringer","dnd",'
                    '"media","hotspot"],"dnd":false,"metered":false,"mobile_data":true,"paused":false,"ringer":"vibrate",'
                    '"signal":3,"wifi":true}')
BODY = json.loads(LINK_STATUS_WIRE)
SESSION = {"source": "org.example.player", "app": "Synthetic Player", "title": "Test Track", "artist": "Test Artist",
           "playing": True, "can_play": False, "can_pause": True, "can_next": True, "can_previous": False}
LINK_SESSION = {**SESSION, "can_seek": True, "position_ms": 1000, "length_ms": 60000, "volume": 40}


def test_one_codec_reads_the_status_for_both_transports():
    assert ps.read_status(BODY) == BODY
    kind, cloud = read_phone_data({"type": "phone.status", **BODY})
    assert kind == "phone.status" and cloud == ps.read_status(BODY)
    # A control name from a newer phone is dropped, not fatal.
    assert ps.read_status({**BODY, "controls": ["status", "teleport"]})["controls"] == ["status"]


@pytest.mark.parametrize("changes", [{"battery": 101}, {"signal": True}, {"ringer": "loud"}, {"controls": ["ring", "ring"]},
                                     {"extra": 1}, {"type": "phone.status"}])
def test_status_shape_is_exact_on_both_transports(changes):
    with pytest.raises(ps.ProtocolError):
        ps.read_status({**BODY, **changes})  # A Hub body never carries its type.
    if "type" not in changes:  # A Cloud payload always does.
        with pytest.raises(FeatureError):
            read_phone_data({"type": "phone.status", **{**BODY, **changes}})


def test_media_dialects_keep_the_legacy_hub_fields_only_on_the_hub():
    assert ps.read_media({"sessions": [LINK_SESSION]}, ps.LINK)["sessions"][0]["volume"] == 40
    assert ps.read_media({"sessions": [SESSION]}, ps.HOSTED) == {"sessions": [SESSION]}
    with pytest.raises(ps.ProtocolError):
        ps.read_media({"sessions": [LINK_SESSION]}, ps.HOSTED)  # Older Cloud desktops refuse these fields.
    with pytest.raises(ps.ProtocolError):
        ps.read_media({"sessions": [SESSION]}, ps.LINK)  # Older Hubs refuse a session without them.


def test_quick_action_commands_are_shared_with_dialect_differences():
    assert ps.read_command("phone.dnd", {"active": True}, ps.LINK) == {"active": True}
    assert phone_command("phone.dnd", {"active": True}) == {"type": "phone.dnd", "active": True}
    assert ps.read_command("media.command", {"source": "a", "action": "seek", "value": 5}, ps.LINK)["value"] == 5
    for body, dialect in (({"source": "a", "action": "seek", "value": 5}, ps.HOSTED), ({"source": "a", "action": "seek"}, ps.LINK),
                          ({"source": "a", "action": "play", "value": 1}, ps.LINK), ({"active": "yes"}, ps.LINK)):
        with pytest.raises(ps.ProtocolError):
            ps.read_command("media.command" if "source" in body else "phone.dnd", body, dialect)
    with pytest.raises(FeatureError):
        phone_command("media.command", {"source": "a", "action": "volume"})
    assert ps.carried("phone.hotspot", ps.LINK) and ps.carried("phone.wallpaper.request", ps.LINK)
    assert not ps.carried("phone.mobile_data", ps.LINK) and ps.carried("phone.mobile_data", ps.HOSTED)


def test_the_book_gives_hub_and_cloud_phones_the_same_view(tmp_path):
    book = ps.StatusBook(Store(tmp_path), clock=lambda: 1000)
    book.apply("hub", "phone.status", BODY, 1000)
    book.apply("cloud", "phone.status", BODY, 1000)
    hub = book.view("hub", ["battery", "notifications"], True)
    cloud = book.view("cloud", ["files"], True)
    assert hub["status"] == cloud["status"] == BODY and hub["battery"] == {"battery_level": 76, "is_charging": True}
    assert hub["capabilities"] == ["battery", "notifications", *BODY["controls"]]
    assert book.view("hub", ["battery"], False)["status"] is None  # Offline hides the status.
    assert book.view("hub", ["battery"], True, now=1000 + ps.STATUS_SECONDS + 1)["status"] is None  # Too old.
    paused = {**BODY, "paused": True}
    book.apply("cloud", "phone.status", paused, 1000)
    view = book.view("cloud", ["files"], True)
    assert view["online"] is False and view["status"] == paused and view["capabilities"] == ["files"]


def test_the_book_reads_a_cloud_status_saved_before_the_shared_layer(tmp_path):
    store = Store(tmp_path)
    store.save("hosted_phone_status", {"id": "cloud", "status": BODY, "status_at": 1000, "wallpaper": "data:x"})
    book = ps.StatusBook(store, clock=lambda: 1000)
    assert book.view("cloud", [], True)["status"] == BODY
    book.save("cloud", status_at=1001)
    assert store.get("phone_status", "cloud")["wallpaper"] == "data:x" and store.all("hosted_phone_status") == []


def hub_state(tmp_path):
    state = PhoneState(Store(tmp_path))
    state.connected = True
    state.devices = [{"id": "hub-phone", "name": "Synthetic phone", "online": True, "capabilities": ["battery", "media", "ring"],
                      "battery": {"battery_level": 50, "is_charging": False}},
                     {"id": "computer", "name": "Synthetic computer", "online": True, "capabilities": ["notifications"]}]
    return state


def test_a_hub_phone_gains_the_status_header_and_quick_actions(tmp_path):
    state = hub_state(tmp_path)
    phone = state.snapshot()["devices"][0]
    # Before any status (an older phone): its own battery event and capabilities, nothing invented.
    assert phone["status"] is None and phone["battery"] == {"battery_level": 50, "is_charging": False}
    assert phone["capabilities"] == ["battery", "media", "ring"]
    assert state.status_event("hub-phone", "phone.status", ps.read_event("phone.status", BODY, ps.LINK))
    phone = state.snapshot()["devices"][0]
    assert phone["status"]["wifi"] is True and phone["status"]["signal"] == 3 and phone["battery"]["battery_level"] == 76
    assert {"status", "dnd", "ringer", "hotspot"} <= set(phone["capabilities"])
    assert phone["capabilities"].count("ring") == 1
    # Computers publish their battery only; a status from one is ignored.
    assert not state.status_event("computer", "phone.status", BODY)
    state.connected = False
    assert state.snapshot()["devices"][0]["status"] is None


def test_hub_status_ringer_and_media_feed_the_shared_phone_page(tmp_path):
    state = hub_state(tmp_path)
    features = f.PhoneFeatures(SimpleNamespace(root=tmp_path, store=state.store))
    state.status_event("hub-phone", "phone.status", BODY, features)
    assert features.snapshot()["ringers"][0]["mode"] == "vibrate"
    assert state.status_event("hub-phone", "media.state", ps.read_media({"sessions": [LINK_SESSION]}, ps.LINK), features)
    assert features.snapshot()["media"][0]["sessions"][0]["title"] == "Test Track"
    # No "ringer" control (Do Not Disturb access withdrawn): the stale ringer row goes.
    state.status_event("hub-phone", "phone.status", {**BODY, "controls": ["status", "ring"]}, features)
    assert features.snapshot()["ringers"] == []


def test_a_current_hub_snapshot_restores_each_phones_status(tmp_path):
    state = hub_state(tmp_path)
    devices = state.devices
    state.restore({"devices": devices, "notifications": [], "statuses": [
        {**BODY, "device_id": "hub-phone", "updated_at": 1e12}, {"battery": 5, "device_id": "hub-phone", "updated_at": 1}]})
    assert ps.StatusBook(state.store).saved("hub-phone")["status"] == BODY


def hub_features(tmp_path, capabilities):
    published = []
    runtime = SimpleNamespace(client=SimpleNamespace(publish=published.append), loop=SimpleNamespace(call_soon_threadsafe=lambda fn, event: fn(event)))
    state = PhoneState(Store(tmp_path))
    state.connected = True
    state.devices = [{"id": "hub-phone", "name": "Synthetic phone", "online": True, "capabilities": capabilities}]
    workspace = SimpleNamespace(root=tmp_path, store=state.store, phone_runtime=runtime, phone=state, settings={"link": {"phone": {}}})
    return f.PhoneFeatures(workspace), state, published


def test_hub_quick_actions_need_the_phone_to_list_them(tmp_path):
    features, state, published = hub_features(tmp_path, ["battery"])
    with pytest.raises(ValueError):
        features.dispatch("phone.dnd", {"device_id": "hub-phone", "active": True})
    state.status_event("hub-phone", "phone.status", BODY)
    assert features.dispatch("phone.dnd", {"device_id": "hub-phone", "active": True})["queued"]
    assert features.dispatch("phone.hotspot", {"device_id": "hub-phone"})["queued"]
    assert [(e["type"], e["targets"], e["payload"]) for e in published] == [
        ("phone.dnd", ["hub-phone"], {"active": True}), ("phone.hotspot", ["hub-phone"], {})]
    # Sync over mobile data stays a Saiph Cloud setting, even if a phone lists it.
    state.status_event("hub-phone", "phone.status", {**BODY, "controls": [*BODY["controls"], "mobile_data"]})
    with pytest.raises(ValueError):
        features.dispatch("phone.mobile_data", {"device_id": "hub-phone", "allowed": False})


def test_hub_refresh_is_rate_limited_like_cloud(tmp_path):
    features, state, published = hub_features(tmp_path, ["battery"])
    state.status_event("hub-phone", "phone.status", BODY)
    assert features.dispatch("phone.refresh", {"device_id": "hub-phone"})["queued"]
    assert features.dispatch("phone.refresh", {"device_id": "hub-phone"}) == {"queued": True}
    assert [e["type"] for e in published] == ["phone.status.request"]


def test_hub_media_seek_and_volume_still_reach_older_hub_phones(tmp_path):
    features, _, published = hub_features(tmp_path, ["battery", "media"])
    features.dispatch("phone.media", {"device_id": "hub-phone", "source": "org.example.player", "action": "volume", "value": 30})
    assert published[0]["payload"] == {"source": "org.example.player", "action": "volume", "value": 30}


JPEG = "data:image/jpeg;base64,/9j/wAAICAAQABAD/9k="  # A synthetic 16x16 frame header, no pixels.


def test_wallpaper_shape_is_shared():
    assert ps.read_wallpaper({"preview": JPEG}) == {"preview": JPEG}
    assert ps.read_wallpaper({"preview": ""}) == {"preview": ""}
    for preview in ("data:image/png;base64,AAAA", "data:image/jpeg;base64,!!", "x" * 16_024):
        with pytest.raises(ps.ProtocolError):
            ps.read_wallpaper({"preview": preview})
    assert read_phone_data({"type": "phone.wallpaper", "preview": JPEG}) == ("phone.wallpaper", {"preview": JPEG})


def test_a_hub_phone_sends_its_wallpaper_only_when_asked_and_opted_in(tmp_path):
    features, state, published = hub_features(tmp_path, ["battery"])
    state.status_event("hub-phone", "phone.status", {**BODY, "controls": [*BODY["controls"], "wallpaper"]})
    with pytest.raises(ValueError, match="Use phone wallpaper"):
        features.dispatch("phone.wallpaper", {"device_id": "hub-phone"})
    # An unasked answer is dropped.
    assert not state.status_event("hub-phone", "phone.wallpaper", {"preview": JPEG})
    features.workspace.settings = {"link": {"phone": {"wallpaper": True}}}
    assert state.status_book.wallpaper_due("hub-phone", True)
    assert features.dispatch("phone.wallpaper", {"device_id": "hub-phone"})["queued"]
    assert published[-1]["type"] == "phone.wallpaper.request" and published[-1]["targets"] == ["hub-phone"]
    assert not state.status_book.wallpaper_due("hub-phone", True)  # Not twice within a minute.
    assert state.status_event("hub-phone", "phone.wallpaper", {"preview": JPEG})
    assert not state.status_event("hub-phone", "phone.wallpaper", {"preview": JPEG})  # One answer per request.
    assert state.snapshot(wallpaper=True)["devices"][0]["wallpaper"] == JPEG
    assert state.snapshot()["devices"][0]["wallpaper"] is None  # Setting off: no picture leaves the store.
    assert not state.status_book.wallpaper_due("hub-phone", True)  # Fresh for six hours.


# ----------------------------------------------- phone.signal: Wi-Fi and mobile bars
# android/.../PhoneStatusFramesTest.kt checks the same literals.
SIGNAL_WIRE = '{"cellular_level":3,"type":"phone.signal","wifi_level":2}'
LINK_SIGNAL_WIRE = '{"cellular_level":null,"wifi_level":null}'
SIGNAL = {"wifi_level": 2, "cellular_level": 3}


def test_signal_bars_have_their_own_exact_shape_on_both_transports():
    from orion_mini.hosted_crypto import canonical
    assert canonical(json.loads(SIGNAL_WIRE)) == SIGNAL_WIRE.encode()
    assert read_phone_data(json.loads(SIGNAL_WIRE)) == ("phone.signal", SIGNAL)
    assert ps.read_event("phone.signal", json.loads(LINK_SIGNAL_WIRE), ps.LINK) == {"wifi_level": None, "cellular_level": None}
    for bad in ({**SIGNAL, "wifi_level": 5}, {**SIGNAL, "cellular_level": -1}, {**SIGNAL, "wifi_level": True},
                {**SIGNAL, "wifi_level": 2.0}, {"wifi_level": 2}, {**SIGNAL, "rssi": -73}):
        with pytest.raises(ps.ProtocolError):
            ps.read_signal(bad)
        with pytest.raises(FeatureError):
            read_phone_data({"type": "phone.signal", **bad})
    # phone.status itself is unchanged, so older desktops and Hubs keep accepting it.
    with pytest.raises(ps.ProtocolError):
        ps.read_status({**BODY, "wifi_level": 2})


def test_the_book_shows_signal_bars_only_beside_a_fresh_status(tmp_path):
    book = ps.StatusBook(Store(tmp_path), clock=lambda: 1000)
    book.apply("cloud", "phone.signal", SIGNAL, 1000)
    assert book.view("cloud", [], True)["signal"] is None  # No status yet: nothing to show beside.
    book.apply("cloud", "phone.status", BODY, 1000)
    assert book.view("cloud", [], True)["signal"] == SIGNAL
    assert book.view("cloud", [], False)["signal"] is None
    assert book.view("cloud", [], True, now=1000 + ps.STATUS_SECONDS + 1)["signal"] is None
    book.apply("cloud", "phone.status", {**BODY, "paused": True}, 1000)
    assert book.view("cloud", [], True)["signal"] is None


def test_a_hub_phone_and_a_hub_snapshot_carry_signal_bars(tmp_path):
    state = hub_state(tmp_path)
    assert state.status_event("hub-phone", "phone.status", BODY)
    assert state.status_event("hub-phone", "phone.signal", ps.read_event("phone.signal", SIGNAL, ps.LINK))
    assert state.snapshot()["devices"][0]["signal"] == SIGNAL
    assert not state.status_event("computer", "phone.signal", SIGNAL)
    restored = hub_state(tmp_path / "restored")
    restored.restore({"devices": restored.devices, "notifications": [], "statuses": [{**BODY, "device_id": "hub-phone", "updated_at": 1e12}],
                      "signals": [{**SIGNAL, "device_id": "hub-phone", "updated_at": 1e12}, {"wifi_level": 9, "device_id": "hub-phone", "updated_at": 1}]})
    assert ps.StatusBook(restored.store).saved("hub-phone")["signal"] == SIGNAL


def test_find_phone_state_is_shared_and_bounded(tmp_path):
    from orion_mini.hosted_crypto import canonical
    # android/.../PhoneStatusFramesTest.kt checks the same literals.
    ringing = '{"ringing":true,"seconds":30,"type":"phone.ring.state"}'
    stopped = '{"ringing":false,"seconds":0,"type":"phone.ring.state"}'
    for wire in (ringing, stopped):
        assert canonical(json.loads(wire)) == wire.encode()
        kind, body = read_phone_data(json.loads(wire))
        assert kind == "phone.ring.state" and ps.read_event(kind, {k: v for k, v in json.loads(wire).items() if k != "type"}, ps.LINK) == body
    book = ps.StatusBook(Store(tmp_path), clock=lambda: 1000)
    # Only a phone that offers Find phone.
    assert not book.apply("phone", ps.PHONE_RING_STATE, {"ringing": True, "seconds": 30}, 1000, capabilities=["files"])
    assert book.apply("phone", ps.PHONE_RING_STATE, {"ringing": True, "seconds": 30}, 1000, capabilities=["ring"])
    assert book.view("phone", ["ring"], True)["ringing"] is True
    assert book.view("phone", ["ring"], False)["ringing"] is False  # Offline: not shown as ringing.
    assert book.view("phone", ["ring"], True, now=1030)["ringing"] is False  # Ends by itself if "stopped" is lost.
    book.apply("phone", ps.PHONE_RING_STATE, {"ringing": False, "seconds": 0}, 1001, capabilities=["ring"])
    assert book.view("phone", ["ring"], True)["ringing"] is False


def test_a_hub_phone_reports_ringing_and_a_computer_stops_it(tmp_path):
    features, state, published = hub_features(tmp_path, ["battery", "ring"])
    assert state.snapshot()["devices"][0]["ringing"] is False
    assert state.status_event("hub-phone", "phone.ring.state", ps.read_event("phone.ring.state", {"ringing": True, "seconds": 30}, ps.LINK))
    assert state.snapshot()["devices"][0]["ringing"] is True
    assert features.dispatch("phone.ring.stop", {"device_id": "hub-phone"})["queued"]
    assert [(e["type"], e["targets"], e["payload"]) for e in published] == [("phone.ring.stop", ["hub-phone"], {})]
    state.status_event("hub-phone", "phone.ring.state", {"ringing": False, "seconds": 0})
    assert state.snapshot()["devices"][0]["ringing"] is False
    with pytest.raises(ps.ProtocolError):
        ps.read_event("phone.ring.state", {"ringing": True, "seconds": 30, "type": "phone.ring.state"}, ps.LINK)
