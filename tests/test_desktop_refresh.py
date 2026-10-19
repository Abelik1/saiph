# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dashboard refreshes on announced changes, with a slow visible-only safety net."""
import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject

from orion_mini.app import REFRESH_TICKS, MainWindow
from orion_mini.desktop_bridge import DesktopBridge


def window(visible=True, settling=False):
    emitted = []
    return emitted, SimpleNamespace(
        workspace=SimpleNamespace(show_enrollment=False), ticks=0,
        bridge=SimpleNamespace(changed=SimpleNamespace(emit=lambda: emitted.append(True))),
        settling=SimpleNamespace(isActive=lambda: settling), dashboard_visible=lambda: visible)


def test_visible_dashboard_gets_a_slow_safety_net_refresh(monkeypatch):
    monkeypatch.setenv('ORION_MINI_TEST', '1')
    emitted, fake = window()
    for _ in range(REFRESH_TICKS * 4):
        MainWindow.on_tick(fake)
    assert REFRESH_TICKS >= 3 and len(emitted) == 4


@pytest.mark.parametrize('visible,settling', [(False, False), (True, True)])
def test_hidden_or_moving_window_builds_no_periodic_snapshot(monkeypatch, visible, settling):
    monkeypatch.setenv('ORION_MINI_TEST', '1')
    emitted, fake = window(visible, settling)
    for _ in range(REFRESH_TICKS * 4):
        MainWindow.on_tick(fake)
    assert emitted == []


class Session:
    def __init__(self):
        self.notify = None

    def jpeg(self):
        return b'\xff\xd8synthetic\xff\xd9'

    def describe(self):
        return {'sequence': 7, 'rotation': 90, 'fps': 19.5}


class Window(QObject):
    def __init__(self, workspace):
        super().__init__()
        self.workspace = workspace


def test_sessions_announce_frames_as_metadata_and_state_as_a_change(qapp):
    camera, screen = Session(), Session()
    bridge = DesktopBridge(Window(SimpleNamespace(camera=SimpleNamespace(local=camera), screen=SimpleNamespace(session=screen))))
    frames, changes = [], []
    bridge.frame.connect(frames.append)
    bridge.changed.connect(lambda: changes.append(True))
    assert set(bridge.feeds) == {'camera', 'screen'} and bridge.feeds['camera']() == camera.jpeg()
    camera.notify('frame')
    screen.notify('state')
    assert [json.loads(value) for value in frames] == [{'source': 'camera', 'sequence': 7, 'rotation': 90, 'fps': 19.5}]
    assert changes == [True]


class HiddenWindow(Window):
    def __init__(self, workspace):
        super().__init__(workspace)
        self.visible = False

    def dashboard_visible(self):
        return self.visible


def test_a_hidden_window_holds_page_refreshes_and_catches_up_once(qapp):
    window = HiddenWindow(SimpleNamespace())
    bridge = DesktopBridge(window)
    refreshes = []
    bridge.refresh.connect(lambda: refreshes.append(True))
    for _ in range(5):
        bridge.changed.emit()  # Phone and Cloud events while the window sits in the tray.
    assert refreshes == []
    window.visible = True
    bridge.resume()
    bridge.resume()
    assert refreshes == [True]
    bridge.changed.emit()
    assert refreshes == [True, True]


def test_read_only_cloud_questions_do_not_trigger_a_snapshot(qapp):
    import time as clock
    from PySide6.QtCore import QCoreApplication
    asked = []
    window = Window(SimpleNamespace(dispatch=lambda method, args: asked.append(method) or {'requests': []}))
    window.pump_jobs = lambda: None
    bridge = DesktopBridge(window)
    changes, answers = [], []
    bridge.changed.connect(lambda: changes.append(True))
    bridge.response.connect(answers.append)
    for method in ('hosted.approvals', 'hosted.requests', 'hosted.link.status'):
        bridge.request(method, method, '{}')
    deadline = clock.monotonic() + 3
    while len(answers) < 3 and clock.monotonic() < deadline:
        QCoreApplication.processEvents()
    assert sorted(asked) == ['hosted.approvals', 'hosted.link.status', 'hosted.requests'] and len(answers) == 3
    assert changes == []
