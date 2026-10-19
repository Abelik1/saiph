# SPDX-License-Identifier: AGPL-3.0-or-later
"""The native phone screen window: geometry, input mapping, frames, stop on close, tray live state.

A real ScreenSession over loopback TLS with a synthetic phone client; no phone is involved."""
import json
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from orion_mini.phone_screen import PhoneScreen
from orion_mini.phone_screen_window import (GeometryStore, PhoneScreenWindowController, fitted, frame_point, gesture,
                                            typed, visible, wheel, window_size)
from orion_mini.screen_session import ScreenSession
from test_phone_screen import client, packet, until


# ------------------------------------------------------------------ pure helpers
def test_frame_points_follow_the_letterbox_and_view_rotation():
    # A 1000x2000 portrait frame in a 1000x1000 view is 500x1000, centred.
    assert fitted(1000, 1000, 1000, 2000, 0) == (250, 0, 500, 1000)
    assert frame_point(1000, 1000, 1000, 2000, 0, 250, 0) == (0, 0)
    assert frame_point(1000, 1000, 1000, 2000, 0, 750, 1000) == (10000, 10000)
    assert frame_point(1000, 1000, 1000, 2000, 0, 100, 500) is None  # In the black bar.
    # Rotated 90° clockwise, the top-left of the shown image is the frame's bottom-left.
    box = fitted(1000, 1000, 1000, 2000, 90)
    assert box == (0, 250, 1000, 500)
    assert frame_point(1000, 1000, 1000, 2000, 90, 0, 250) == (0, 10000)
    assert frame_point(1000, 1000, 1000, 2000, 90, 1000, 250) == (0, 0)
    assert frame_point(1000, 1000, 1000, 2000, 180, 250, 0) == (10000, 10000)
    assert frame_point(1000, 1000, 1000, 2000, 270, 0, 250) == (10000, 0)


def test_gestures_wheel_and_text_match_the_page_rules():
    assert gesture((10, 20, 0.0), (15, 25, 0.1)) == {'t': 'tap', 'x': 10, 'y': 20}
    assert gesture((10, 20, 0.0), (15, 25, 0.6)) == {'t': 'long', 'x': 10, 'y': 20}
    assert gesture((10, 20, 0.0), (10, 2000, 0.3)) == {'t': 'swipe', 'x': 10, 'y': 20, 'x2': 10, 'y2': 2000, 'ms': 300}
    assert gesture((0, 0, 0.0), (5000, 0, 9.0))['ms'] == 3000
    assert wheel((5000, 5000), 120) == {'t': 'swipe', 'x': 5000, 'y': 5000, 'x2': 5000, 'y2': 2500, 'ms': 250}
    assert wheel((5000, 9000), -120)['y2'] == 10000
    assert typed('a\x00b\x7fc\n') == 'abc' and len(typed('x' * 400)) == 256


def test_window_size_keeps_the_phone_aspect_on_screen():
    width, height = window_size(1080, 2340, 0, (0, 0, 1920, 1040))
    content = height - 48
    assert abs((width - 4) / content - 1080 / 2340) < 0.01 and height <= 1040
    wide, _ = window_size(1080, 2340, 90, (0, 0, 1920, 1040), height=700)
    assert wide > 700  # Rotated view: landscape window.
    narrow_screen = window_size(2340, 1080, 0, (0, 0, 800, 1000))
    assert narrow_screen[0] <= 760
    assert visible((100, 100, 400, 800), [(0, 0, 1920, 1040)])
    assert not visible((5000, 100, 400, 800), [(0, 0, 1920, 1040)])


def test_geometry_store_validates_what_it_reads(tmp_path):
    store = GeometryStore(tmp_path / 'phone-screen-window.json')
    assert store.load() is None
    store.save(10, 20, 400, 800)
    assert store.load() == {'x': 10, 'y': 20, 'width': 400, 'height': 800}
    for bad in [{'x': 1}, {'x': 'a', 'y': 0, 'width': 400, 'height': 800}, {'x': 0, 'y': 0, 'width': 10, 'height': 800}]:
        (tmp_path / 'phone-screen-window.json').write_text(json.dumps(bad))
        assert store.load() is None


# ------------------------------------------------------------------ the window with a real session
class Tray:
    def __init__(self):
        self.icon, self.tip = None, ''

    def setIcon(self, icon):
        self.icon = icon

    def setToolTip(self, text):
        self.tip = text


@pytest.fixture
def screen(tmp_path):
    session = ScreenSession(addresses=lambda: ['192.168.1.7'])
    workspace = SimpleNamespace(root=tmp_path)
    value = workspace.screen = PhoneScreen(workspace, session=session)
    yield value
    session.stop()


def connect_live(screen, qtbot, width=540, height=1170):
    started = screen.start()
    phone = client(screen.session)
    phone.send(packet(1, width, height))
    until(lambda: screen.session.status()['state'] == 'live')
    return started, phone


def test_live_frames_open_a_native_window_sized_to_the_phone(screen, qtbot, tmp_path):
    tray = Tray()
    icon = QIcon(QPixmap(32, 32))
    controller = PhoneScreenWindowController(screen.workspace, tray, icon)
    assert screen.status()['window'] == 'closed'
    _, phone = connect_live(screen, qtbot)
    try:
        qtbot.waitUntil(lambda: controller.window is not None and controller.window.view.image is not None, timeout=4000)
        window = controller.window
        assert screen.status()['window'] == 'open' and window.isVisible()
        assert window.view.image.width() == 540 and window.view.image.height() == 1170
        # Phone aspect, except that a very short screen cannot go below the toolbar's own width.
        expected = round((window.height() - 48) * 540 / 1170) + 4
        assert abs(window.width() - max(expected, window.minimumSizeHint().width())) <= 2
        assert window.live.isVisible() and window.frame.property('live') is True
        # Tray: red live state while the phone screen is live.
        qtbot.waitUntil(lambda: 'phone screen' in tray.tip, timeout=3000)
        assert tray.icon is not icon
        # Frames keep only the latest picture; a phone rotation refits the window.
        phone.send(packet(2, 1170, 540))
        qtbot.waitUntil(lambda: window.view.image.width() == 1170, timeout=4000)
        assert window.width() > window.height()
        # View only until the phone reports control: toolbar keys are disabled.
        assert not window.back.isEnabled()
        phone.send(json.dumps({'t': 'state', 'input': True}))
        qtbot.waitUntil(lambda: window.back.isEnabled(), timeout=4000)
    finally:
        phone.close()
        controller.shutdown()


def test_window_input_is_forwarded_to_the_phone(screen, qtbot):
    controller = PhoneScreenWindowController(screen.workspace)
    _, phone = connect_live(screen, qtbot)
    try:
        phone.send(json.dumps({'t': 'state', 'input': True}))
        qtbot.waitUntil(lambda: controller.window is not None and controller.window.back.isEnabled()
                        and controller.window.view.image is not None, timeout=4000)
        window = controller.window
        window.back.click()
        assert json.loads(phone.recv(timeout=4)) == {'t': 'key', 'key': 'back'}
        view = window.view
        centre = QPoint(view.width() // 2, view.height() // 2)
        qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=centre)
        tap = json.loads(phone.recv(timeout=4))
        assert tap['t'] == 'tap' and abs(tap['x'] - 5000) < 150 and abs(tap['y'] - 5000) < 150
        qtbot.keyClicks(view, 'hi')
        qtbot.wait(250)  # Typing is sent in one message after a short pause.
        assert json.loads(phone.recv(timeout=4)) == {'t': 'text', 'text': 'hi'}
        qtbot.keyClick(view, Qt.Key.Key_Escape)
        assert json.loads(phone.recv(timeout=4)) == {'t': 'key', 'key': 'back'}
    finally:
        phone.close()
        controller.shutdown()


def test_closing_the_window_stops_the_session_and_remembers_geometry(screen, qtbot, tmp_path):
    controller = PhoneScreenWindowController(screen.workspace)
    _, phone = connect_live(screen, qtbot)
    try:
        qtbot.waitUntil(lambda: controller.window is not None and controller.window.view.image is not None, timeout=4000)
        window = controller.window
        window.move(120, 90)
        height = window.height()
        window.close()
        until(lambda: screen.session.status()['state'] == 'idle')
        qtbot.waitUntil(lambda: controller.window is None, timeout=3000)
        assert screen.status()['window'] == 'closed'
        saved = json.loads((tmp_path / 'phone-screen-window.json').read_text())
        assert set(saved) == {'x', 'y', 'width', 'height'} and saved['height'] == height
    finally:
        phone.close()
        controller.shutdown()


def test_phone_ending_the_session_closes_the_window_without_a_second_stop(screen, qtbot):
    controller = PhoneScreenWindowController(screen.workspace)
    stops = []
    _, phone = connect_live(screen, qtbot)
    try:
        qtbot.waitUntil(lambda: controller.window is not None, timeout=4000)
        original = screen.stop
        screen.stop = lambda: stops.append(1) or original()
        phone.close()
        qtbot.waitUntil(lambda: controller.window is None, timeout=4000)
        assert stops == [] and screen.status()['window'] == 'closed'
        with pytest.raises(ValueError):
            screen.raise_window()  # Nothing to show once the session ended.
    finally:
        controller.shutdown()


def test_tray_shows_live_camera_too(screen, qtbot):
    tray = Tray()
    icon = QIcon(QPixmap(32, 32))
    screen.workspace.camera = SimpleNamespace(local=SimpleNamespace(state='live'), processes={})
    controller = PhoneScreenWindowController(screen.workspace, tray, icon)
    try:
        controller._update_tray()
        assert tray.tip == 'Saiph · Live: camera' and tray.icon is not icon
        screen.workspace.camera.local.state = 'idle'
        controller._update_tray()
        assert tray.tip == 'Saiph' and tray.icon is icon
    finally:
        controller.shutdown()
