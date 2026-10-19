# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from types import SimpleNamespace

from orion_mini.desktop_bridge import DesktopBridge


def test_snapshot_omits_only_identical_bytes_and_always_rechecks_live_state():
    value = {'phone': {'online': True}, 'photos': ['synthetic-thumbnail' * 10000]}
    reads, packets, changes = [], [], []
    workspace = SimpleNamespace(dispatch=lambda method, args: reads.append((method, args)) or value)
    obj = SimpleNamespace(window=SimpleNamespace(workspace=workspace, pump_jobs=lambda: None),
        response=SimpleNamespace(emit=packets.append), changed=SimpleNamespace(emit=lambda: changes.append(True)))
    DesktopBridge.request(obj, 'first', 'state', '{}')
    first = json.loads(packets[-1])
    assert first['result'] == value
    DesktopBridge.request(obj, 'same', 'state', json.dumps({'revision': first['revision']}))
    unchanged = json.loads(packets[-1])
    assert unchanged['unchanged'] and 'result' not in unchanged
    assert len(packets[-1]) < 200
    value['phone']['online'] = False
    DesktopBridge.request(obj, 'fresh', 'state', json.dumps({'revision': first['revision']}))
    changed = json.loads(packets[-1])
    assert changed['result']['phone']['online'] is False
    assert changed['revision'] != first['revision']
    # A caller without a revision always receives full state, even after caching.
    DesktopBridge.request(obj, 'legacy', 'state', '{}')
    assert json.loads(packets[-1])['result'] == value
    assert reads == [('state', {})] * 4 and not changes


def test_invalid_revision_rejected_without_snapshot_or_pending_request():
    packets = []
    def forbidden(*args):
        raise AssertionError('Snapshot must not run')
    obj = SimpleNamespace(window=SimpleNamespace(workspace=SimpleNamespace(dispatch=forbidden)),
        response=SimpleNamespace(emit=lambda raw: packets.append(json.loads(raw))))
    for args in [{'revision': True}, {'revision': 'x' * 64}, {'revision': 'a' * 65}, {'path': 'private'}]:
        DesktopBridge.request(obj, 'bad', 'state', json.dumps(args))
    assert len(packets) == 4 and all(not p['ok'] for p in packets)
