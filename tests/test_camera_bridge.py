# SPDX-License-Identifier: AGPL-3.0-or-later
"""Preview reads must not feed back into expensive full-dashboard refreshes."""
import json
from types import SimpleNamespace

from orion_mini.desktop_bridge import DesktopBridge


def fixture():
    packets, changes = [], []
    frame = {"image": "data:image/jpeg;base64,synthetic", "sequence": 7}
    workspace = SimpleNamespace(
        camera=SimpleNamespace(local=SimpleNamespace(latest=lambda: frame)),
        dispatch=lambda method, args: {"saved": True},
    )
    bridge = SimpleNamespace(
        window=SimpleNamespace(workspace=workspace, pump_jobs=lambda: None),
        response=SimpleNamespace(emit=lambda raw: packets.append(json.loads(raw))),
        changed=SimpleNamespace(emit=lambda: changes.append(True)),
    )
    return bridge, packets, changes, frame


def test_preview_reads_return_frames_without_triggering_dashboard_refresh():
    bridge, packets, changes, frame = fixture()
    for index in range(20):
        DesktopBridge.request(bridge, str(index), "camera.frame", "{}")
    assert len(packets) == 20
    assert all(packet["ok"] and packet["result"] == frame for packet in packets)
    assert not changes


def test_settings_changes_still_refresh_and_frame_arguments_are_rejected():
    bridge, packets, changes, _ = fixture()
    DesktopBridge.request(bridge, "save", "settings.save", "{}")
    assert packets[-1]["ok"] and changes == [True]
    DesktopBridge.request(bridge, "bad", "camera.frame", '{"extra":true}')
    assert packets[-1]["ok"] is False and changes == [True]


def test_screen_counting_does_not_force_a_full_dashboard_refresh():
    bridge, packets, changes, _ = fixture()
    queued, counted = [], []
    bridge.window.workspace.usage_counter = SimpleNamespace(screen_action=lambda name: lambda: counted.append(name) or {'ok':True})
    bridge.background = lambda request, action, **options: queued.append((request, action, options))
    DesktopBridge.request(bridge, 'tab', 'usage.screen', '{"screen":"photos"}')
    assert not packets and not counted and not changes
    assert len(queued) == 1 and queued[0][2] == {'changed':False}
    assert queued[0][1]() == {'ok':True} and counted == ['photos']


def test_quiet_completion_still_pumps_optional_jobs_without_refresh():
    bridge, packets, changes, _ = fixture()
    pumps = []
    bridge.window.pump_jobs = lambda: pumps.append(True)
    DesktopBridge.finish_quiet(bridge, '{"id":"tab","ok":true,"result":{"ok":true}}')
    assert packets == [{'id':'tab', 'ok':True, 'result':{'ok':True}}]
    assert pumps == [True] and not changes


def test_camera_profile_is_validated_then_sent_to_background_session():
    bridge, packets, changes, _ = fixture()
    queued, starts = [], []
    bridge.background = lambda request, action: queued.append(action)
    bridge.window.workspace.camera.start_local = lambda **args: starts.append(args)
    profile = {'preview':False, 'resolution':'1080p', 'fps':20, 'quality':'high'}
    DesktopBridge.request(bridge, 'start', 'camera.session', json.dumps(profile))
    assert not packets and not starts and len(queued) == 1
    queued.pop()()
    assert starts == [profile]
    for bad in [{**profile, 'fps':True}, {**profile, 'resolution':None}, {**profile, 'quality':'lossless'},
                {**profile, 'extra':True}, {'preview':False, 'fps':20}]:
        DesktopBridge.request(bridge, 'bad', 'camera.session', json.dumps(bad))
        assert packets[-1]['ok'] is False
    assert not queued and not changes


def test_camera_offer_names_only_a_session_and_a_phone():
    bridge, packets, changes, _ = fixture()
    queued, offers = [], []
    bridge.background = lambda request, action: queued.append(action)
    bridge.window.workspace.camera.offer_to_phone = lambda session, device: offers.append((session, device))
    DesktopBridge.request(bridge, 'offer', 'camera.offer', json.dumps({'session': 'a' * 32, 'device_id': 'dev_' + '1' * 32}))
    assert not packets and len(queued) == 1
    queued.pop()()
    assert offers == [('a' * 32, 'dev_' + '1' * 32)]
    for bad in [{'session': 'a' * 32}, {'session': 'a' * 31, 'device_id': 'dev_1'}, {'session': 'a' * 32, 'device_id': ''},
                {'session': 'a' * 32, 'device_id': 'dev_1', 'invite': 'orion-camera:1:x'}, {'session': 7, 'device_id': 'dev_1'}]:
        DesktopBridge.request(bridge, 'bad', 'camera.offer', json.dumps(bad))
        assert packets[-1]['ok'] is False
    assert not queued and not changes
