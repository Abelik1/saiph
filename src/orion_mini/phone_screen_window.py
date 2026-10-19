# SPDX-License-Identifier: AGPL-3.0-or-later
"""The live phone screen in its own native window (docs/PHONE_SCREEN.md).

Frames go straight from the session's receiving thread into a `QImage` and are
painted by a plain `QWidget`: no base64, no page round trip, and the dashboard
page does no work while the window is open. Only the latest decoded frame is kept;
if painting falls behind, older frames are dropped rather than queued.

The window is sized to the phone's aspect ratio, can be moved and resized, and
remembers its position and size in the profile (`phone-screen-window.json`).
A compact toolbar has Back, Home, Recents, a local view rotation and Stop, and a
red "Live" badge and outline. Mouse and keyboard become the same validated input
messages as the embedded view (`screen_session.input_message`), forwarded only
while the phone reports Control from computer on. Closing the window stops the
session. This module also gives the tray icon a red live state while the phone
screen or the phone camera is live.
"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from .screen_session import MAX_TYPED, SCALE

TOOLBAR_HEIGHT = 44
BORDER = 2
LIVE_RED = '#ef4444'
MIN_CONTENT = 240


# ------------------------------------------------------------------ pure geometry
def rotated(width, height, rotation):
    """The displayed size of a frame after the local view rotation (0, 90, 180 or 270, clockwise)."""
    return (height, width) if rotation % 180 else (width, height)


def fitted(view_width, view_height, frame_width, frame_height, rotation):
    """(x, y, width, height) of the frame shown aspect-correct and centred in the view."""
    shown_width, shown_height = rotated(frame_width, frame_height, rotation)
    if min(view_width, view_height, shown_width, shown_height) <= 0:
        return None
    scale = min(view_width / shown_width, view_height / shown_height)
    width, height = shown_width * scale, shown_height * scale
    return (view_width - width) / 2, (view_height - height) / 2, width, height


def frame_point(view_width, view_height, frame_width, frame_height, rotation, x, y):
    """A view position as integers in [0, SCALE] of the phone's own frame; None outside it."""
    box = fitted(view_width, view_height, frame_width, frame_height, rotation)
    if box is None:
        return None
    u, v = (x - box[0]) / box[2], (y - box[1]) / box[3]
    if not (0 <= u <= 1 and 0 <= v <= 1):
        return None
    # Undo the clockwise view rotation: displayed (u, v) back to the frame's (x, y).
    ox, oy = {0: (u, v), 90: (v, 1 - u), 180: (1 - u, 1 - v), 270: (1 - v, u)}[rotation % 360]
    return round(ox * SCALE), round(oy * SCALE)


def gesture(start, end):
    """A press becomes a tap, a long press (held 500 ms) or a swipe (moved over 2% of the frame).

    `start`/`end` are (x, y, seconds); the same rule as the page's PhoneScreen.tsx."""
    held = (end[2] - start[2]) * 1000
    if ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5 < SCALE * 0.02:
        return {'t': 'long' if held >= 500 else 'tap', 'x': start[0], 'y': start[1]}
    return {'t': 'swipe', 'x': start[0], 'y': start[1], 'x2': end[0], 'y2': end[1], 'ms': min(3000, max(50, round(held)))}


def wheel(point, delta_y):
    """A wheel notch becomes a short vertical swipe from the pointer, as on the page."""
    step = (1 if delta_y > 0 else -1) * 2500
    return {'t': 'swipe', 'x': point[0], 'y': point[1], 'x2': point[0], 'y2': min(SCALE, max(0, point[1] - step)), 'ms': 250}


def typed(text):
    """Printable text the phone accepts: no control characters, at most 256 characters."""
    return ''.join(c for c in text if ord(c) >= 32 and ord(c) != 127 and not 0xD800 <= ord(c) <= 0xDFFF)[:MAX_TYPED]


def window_size(frame_width, frame_height, rotation, available, height=None):
    """Outer (width, height) for the phone's aspect within `available` (x, y, width, height).

    Keeps a remembered window height when there is one, otherwise 82% of the screen."""
    shown_width, shown_height = rotated(frame_width, frame_height, rotation)
    _, _, max_width, max_height = available
    chrome = TOOLBAR_HEIGHT + 2 * BORDER
    outer = height if height else int(max_height * 0.82)
    content = max(MIN_CONTENT, min(outer, max_height - 16) - chrome)
    width = round(content * shown_width / shown_height) + 2 * BORDER
    if width > max_width * 0.95:
        width = int(max_width * 0.95)
        content = max(MIN_CONTENT // 2, round((width - 2 * BORDER) * shown_height / shown_width))
    return max(width, 300), content + chrome


def visible(rect, screens, margin=80):
    """True when at least `margin` x `margin` pixels of `rect` (x, y, w, h) lie on one screen."""
    x, y, w, h = rect
    for sx, sy, sw, sh in screens:
        if min(x + w, sx + sw) - max(x, sx) >= margin and min(y + h, sy + sh) - max(y, sy) >= margin:
            return True
    return False


class GeometryStore:
    """The window's last position and size; validated on load, never trusted blindly."""

    def __init__(self, path):
        self.path = Path(path) if path is not None else None

    def load(self):
        if self.path is None:
            return None
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        if (type(value) is not dict or set(value) != {'x', 'y', 'width', 'height'}
                or any(type(value[key]) is not int for key in value)
                or not all(-100_000 <= value[key] <= 100_000 for key in ('x', 'y'))
                or not 200 <= value['width'] <= 20_000 or not 200 <= value['height'] <= 20_000):
            return None
        return value

    def save(self, x, y, width, height):
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps({'x': int(x), 'y': int(y), 'width': int(width), 'height': int(height)}),
                                 encoding='utf-8')
            os.replace(temporary, self.path)
        except OSError:
            pass


def live_icon(base: QIcon, size=64) -> QIcon:
    """The app icon with a red live dot, for the tray while the camera or phone screen is live."""
    pixmap = base.pixmap(size, size) if not base.isNull() else QPixmap(size, size)
    if base.isNull():
        pixmap.fill(QColor('#081430'))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    diameter = size * 0.46
    painter.setPen(QPen(QColor('#ffffff'), size * 0.06))
    painter.setBrush(QColor(LIVE_RED))
    painter.drawEllipse(QRectF(size - diameter - 1, size - diameter - 1, diameter, diameter))
    painter.end()
    return QIcon(pixmap)


def toolbar_icon(kind, color='#e7ebf4', size=40) -> QIcon:
    """Back, Home, Recents and Rotate as small vector icons, so they look the same on every system."""
    icon = QIcon()
    for mode, tint in ((QIcon.Mode.Normal, color), (QIcon.Mode.Disabled, '#4b5a7c')):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(tint), size * 0.08)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        unit = size / 40
        if kind == 'back':
            path = QPainterPath()
            path.moveTo(25 * unit, 11 * unit); path.lineTo(15 * unit, 20 * unit); path.lineTo(25 * unit, 29 * unit)
            painter.drawPath(path)
        elif kind == 'home':
            painter.drawEllipse(QRectF(12 * unit, 12 * unit, 16 * unit, 16 * unit))
        elif kind == 'recents':
            painter.drawRoundedRect(QRectF(13 * unit, 12 * unit, 14 * unit, 16 * unit), 3 * unit, 3 * unit)
        elif kind == 'rotate':
            painter.drawArc(QRectF(11 * unit, 11 * unit, 18 * unit, 18 * unit), 40 * 16, 280 * 16)
            path = QPainterPath()
            path.moveTo(27 * unit, 8 * unit); path.lineTo(27.5 * unit, 14.5 * unit); path.lineTo(21 * unit, 14 * unit)
            painter.drawPath(path)
        painter.end()
        icon.addPixmap(pixmap, mode)
    return icon


# ------------------------------------------------------------------ widgets
class FrameView(QWidget):
    """Paints the latest frame and turns mouse and keyboard into phone input."""
    phone_input = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = None
        self.rotation = 0
        self.control = False
        self.press = None
        self.wheel_at = 0.0
        self.buffer = ''
        self.flush = QTimer(self)
        self.flush.setSingleShot(True)
        self.flush.setInterval(80)
        self.flush.timeout.connect(self._flush)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(QSize(MIN_CONTENT // 2, MIN_CONTENT // 2))
        self.setAccessibleName("Your phone's screen")

    def set_image(self, image):
        self.image = image
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#000000'))
        image = self.image
        if image is None or image.isNull():
            painter.setPen(QColor('#909fc1'))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'Waiting for the first picture…')
            return
        box = fitted(self.width(), self.height(), image.width(), image.height(), self.rotation)
        if box is None:
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        x, y, width, height = box
        painter.translate(x + width / 2, y + height / 2)
        painter.rotate(self.rotation)
        drawn_width, drawn_height = (height, width) if self.rotation % 180 else (width, height)
        painter.drawImage(QRectF(-drawn_width / 2, -drawn_height / 2, drawn_width, drawn_height), image)

    def point(self, position):
        image = self.image
        if image is None or image.isNull():
            return None
        return frame_point(self.width(), self.height(), image.width(), image.height(), self.rotation,
                           position.x(), position.y())

    def mousePressEvent(self, event):
        self.setFocus()
        if not self.control:
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.phone_input.emit({'t': 'key', 'key': 'back'})
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.phone_input.emit({'t': 'key', 'key': 'home'})
        elif event.button() == Qt.MouseButton.LeftButton:
            point = self.point(event.position())
            self.press = (*point, time.monotonic()) if point else None

    def mouseReleaseEvent(self, event):
        start, self.press = self.press, None
        if event.button() != Qt.MouseButton.LeftButton or start is None or not self.control:
            return
        point = self.point(event.position()) or start[:2]
        self.phone_input.emit(gesture(start, (*point, time.monotonic())))

    def wheelEvent(self, event):
        if not self.control or time.monotonic() - self.wheel_at < 0.25 or event.angleDelta().y() == 0:
            return
        point = self.point(event.position())
        if point is None:
            return
        self.wheel_at = time.monotonic()
        self.phone_input.emit(wheel(point, -event.angleDelta().y()))

    def keyPressEvent(self, event):
        if not self.control:
            return super().keyPressEvent(event)
        key, modifiers = event.key(), event.modifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_V:
            self.queue(QApplication.clipboard().text())
        elif modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier):
            return super().keyPressEvent(event)
        elif key == Qt.Key.Key_Escape:
            self.phone_input.emit({'t': 'key', 'key': 'back'})
        elif key == Qt.Key.Key_Backspace:
            self._flush()
            self.phone_input.emit({'t': 'key', 'key': 'backspace'})
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._flush()
            self.phone_input.emit({'t': 'key', 'key': 'enter'})
        elif event.text():
            self.queue(event.text())
        else:
            return super().keyPressEvent(event)

    def queue(self, text):
        clean = typed(text)
        if clean:
            self.buffer = typed(self.buffer + clean)
            self.flush.start()

    def _flush(self):
        value, self.buffer = self.buffer, ''
        self.flush.stop()
        if value:
            self.phone_input.emit({'t': 'text', 'text': value})


STYLE = f"""
#phoneScreen {{ background: #040916; }}
#phoneFrame {{ border: {BORDER}px solid #1a2847; border-radius: 0; background: #000; }}
#phoneFrame[live="true"] {{ border-color: {LIVE_RED}; }}
#toolbar {{ background: #081430; }}
#toolbar QToolButton {{ color: #e7ebf4; background: transparent; border: 0; border-radius: 8px;
    min-width: 32px; min-height: 32px; font-size: 16px; padding: 0 6px; }}
#toolbar QToolButton:hover {{ background: #121d36; }}
#toolbar QToolButton:pressed {{ background: #1a2847; }}
#toolbar QToolButton:disabled {{ color: #4b5a7c; }}
#toolbar QToolButton#stop {{ color: #fecaca; font-size: 13px; font-weight: 600; }}
#toolbar QToolButton#stop:hover {{ background: #3b1a22; }}
#live {{ color: #ffffff; background: {LIVE_RED}; border-radius: 9px; padding: 1px 8px; font-size: 11px; font-weight: 700; }}
"""


class PhoneScreenWindow(QWidget):
    """Top-level window: compact toolbar over the frame view, with a red live outline."""
    stop_requested = Signal()
    phone_input = Signal(dict)
    geometry_changed = Signal()

    def __init__(self, icon=None):
        super().__init__(None, Qt.WindowType.Window)
        self.setObjectName('phoneScreen')
        self.setWindowTitle('Phone screen · Saiph')
        if icon is not None:
            self.setWindowIcon(icon)
        self.setStyleSheet(STYLE)
        self.quiet = False
        self.frame = QFrame(self)
        self.frame.setObjectName('phoneFrame')
        self.frame.setProperty('live', True)
        toolbar = QWidget(self.frame)
        toolbar.setObjectName('toolbar')
        toolbar.setFixedHeight(TOOLBAR_HEIGHT)
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(2)

        def button(text, tip, run, name=None):
            item = QToolButton(toolbar)
            if text in ('back', 'home', 'recents', 'rotate'):
                item.setIcon(toolbar_icon(text))
                item.setIconSize(QSize(22, 22))
            else:
                item.setText(text)
            item.setToolTip(tip)
            item.setAccessibleName(tip.split(' (')[0])
            item.setCursor(Qt.CursorShape.PointingHandCursor)
            if name:
                item.setObjectName(name)
            item.clicked.connect(run)
            row.addWidget(item)
            return item
        self.back = button('back', 'Back (Esc or right-click)', lambda: self.phone_input.emit({'t': 'key', 'key': 'back'}))
        self.home = button('home', 'Home (middle-click)', lambda: self.phone_input.emit({'t': 'key', 'key': 'home'}))
        self.recents = button('recents', 'Recent apps', lambda: self.phone_input.emit({'t': 'key', 'key': 'recents'}))
        self.rotate = button('rotate', 'Rotate view', self.rotate_view)
        row.addSpacing(6)
        self.live = QLabel('● LIVE', toolbar)
        self.live.setObjectName('live')
        self.live.setAccessibleName('Live: your phone screen is being shared')
        row.addWidget(self.live)
        row.addStretch(1)
        # A portrait phone window is narrow: control state, fps and notices go in the title bar.
        self.status = ''
        self.stop = button('■ Stop', 'Stop sharing your phone screen', self.stop_requested.emit, 'stop')
        self.view = FrameView(self.frame)
        self.view.phone_input.connect(self.phone_input)
        column = QVBoxLayout(self.frame)
        column.setContentsMargins(BORDER, BORDER, BORDER, BORDER)
        column.setSpacing(0)
        column.addWidget(toolbar)
        column.addWidget(self.view, 1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.frame)
        self.set_control(False)

    def set_control(self, enabled):
        self.view.control = enabled
        for item in (self.back, self.home, self.recents):
            item.setEnabled(enabled)
        self.view.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)

    def set_status(self, text):
        if text != self.status:
            self.status = text
            self.setWindowTitle('Phone screen · ' + text if text else 'Phone screen · Saiph')
            self.live.setToolTip(text)

    def rotate_view(self):
        self.view.rotation = (self.view.rotation + 90) % 360
        image = self.view.image
        if image is not None and not image.isNull():
            self.fit(image.width(), image.height())
        self.view.update()
        self.geometry_changed.emit()

    def fit(self, frame_width, frame_height):
        """Resize to the phone's aspect, keeping the current height and the window on its screen."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 800)
        width, height = window_size(frame_width, frame_height, self.view.rotation,
                                    (area.x(), area.y(), area.width(), area.height()), self.height() if self.isVisible() else None)
        self.resize(width, height)
        x = min(max(self.x(), area.x()), area.x() + area.width() - width)
        y = min(max(self.y(), area.y()), area.y() + area.height() - height)
        self.move(x, y)

    def moveEvent(self, event):
        super().moveEvent(event)
        self.geometry_changed.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.geometry_changed.emit()

    def close_quietly(self):
        """Close because the session already ended; do not ask to stop it again."""
        self.quiet = True
        self.close()

    def closeEvent(self, event):
        if not self.quiet:
            self.stop_requested.emit()
        self.geometry_changed.emit()
        super().closeEvent(event)


# ------------------------------------------------------------------ controller
class PhoneScreenWindowController(QObject):
    """Opens the window when the phone screen goes live, feeds it frames and stops the session on close."""
    frame_arrived = Signal()
    state_arrived = Signal(object)

    def __init__(self, workspace, tray=None, icon=None, parent=None, geometry_path=None):
        super().__init__(parent)
        self.workspace = workspace
        self.screen = workspace.screen
        self.session = self.screen.session
        self.tray = tray
        self.icon = icon if icon is not None else QIcon()
        self.live_tray_icon = None
        self.tray_live = False
        root = getattr(workspace, 'root', None)
        self.geometry = GeometryStore(geometry_path if geometry_path is not None
                                      else (Path(root) / 'phone-screen-window.json' if root is not None else None))
        self.window = None
        self.latest = None
        self.latest_lock = threading.Lock()
        self.signal_pending = False
        self.status = self.session.status()
        self.notice = ''
        self.sender = ThreadPoolExecutor(max_workers=1, thread_name_prefix='orion-screen-input')
        self.closed = False
        self.frame_arrived.connect(self._show_frame, Qt.ConnectionType.QueuedConnection)
        self.state_arrived.connect(self._apply_state, Qt.ConnectionType.QueuedConnection)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(400)
        self.save_timer.timeout.connect(self._save_geometry)
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(1000)
        self.status_timer.timeout.connect(self._refresh)
        self.status_timer.start()
        self.screen.window = 'closed'
        self.screen.show_window = self.raise_window
        self.unsubscribe = self.session.subscribe(frame=self._frame, state=self._state)

    # Receiving thread: decode here so the GUI thread only paints.
    def _frame(self, jpeg, _width, _height, _sequence):
        image = QImage.fromData(jpeg, 'JPEG')
        if image.isNull():
            return
        with self.latest_lock:
            self.latest = image
            pending, self.signal_pending = self.signal_pending, True
        if not pending:
            self.frame_arrived.emit()

    def _state(self, status):
        self.state_arrived.emit(status)

    def _show_frame(self):
        with self.latest_lock:
            image, self.signal_pending = self.latest, False
        if image is None or self.session.status()['state'] != 'live':
            return
        if self.window is None:
            self._open()
        first = self.window.view.image is None
        rotated_before = (self.window.view.image.width() > self.window.view.image.height()) if not first else None
        self.window.view.set_image(image)
        if first or rotated_before != (image.width() > image.height()):
            # First picture or the phone turned: match the window to the new aspect.
            self.window.fit(image.width(), image.height())

    def _apply_state(self, status):
        self.status = status
        if status.get('state') == 'live':
            if self.window is None:
                self._open()
            self.window.set_control(bool(status.get('input')))
            self._refresh()
        elif status.get('state') == 'idle' and self.window is not None:
            self._close()
        self._update_tray()

    def _open(self):
        window = self.window = PhoneScreenWindow(self.icon)
        window.stop_requested.connect(self.stop_session)
        window.phone_input.connect(self.send)
        window.geometry_changed.connect(self.save_timer.start)
        saved = self.geometry.load()
        screens = [(s.availableGeometry().x(), s.availableGeometry().y(), s.availableGeometry().width(),
                    s.availableGeometry().height()) for s in QGuiApplication.screens()]
        if saved is not None:
            window.resize(saved['width'], saved['height'])
            if visible((saved['x'], saved['y'], saved['width'], saved['height']), screens):
                window.move(saved['x'], saved['y'])
        else:
            area = QGuiApplication.primaryScreen().availableGeometry() if QGuiApplication.primaryScreen() else QRect(0, 0, 1280, 800)
            width, height = window_size(9, 19.5, 0, (area.x(), area.y(), area.width(), area.height()))
            window.resize(width, height)
            window.move(area.x() + area.width() - width - 48, area.y() + max(16, (area.height() - height) // 2))
        window.set_control(bool(self.status.get('input')))
        self.screen.window = 'open'
        window.show()
        window.raise_()
        window.activateWindow()
        window.view.setFocus()
        window.destroyed.connect(self._destroyed)

    def _destroyed(self, *_):
        self.window = None

    def _close(self):
        window, self.window = self.window, None
        self.screen.window = 'closed'
        if window is not None:
            self._save_geometry(window)
            window.close_quietly()
            window.deleteLater()

    def _save_geometry(self, window=None):
        window = window or self.window
        if window is None:
            return
        position, size = window.pos(), window.size()
        self.geometry.save(position.x(), position.y(), size.width(), size.height())

    def _refresh(self):
        window = self.window
        if window is None:
            self._update_tray()
            return
        status = self.status
        fps = self.session.measured_fps()
        parts = ['Control on' if status.get('input') else 'View only', f'{fps:.0f} fps' if fps else '']
        window.set_status(self.notice or ' · '.join(p for p in parts if p))
        self._update_tray()

    def raise_window(self):
        """Bring the window forward (page button); reopen it if it was closed while live."""
        if self.window is None:
            if self.session.status()['state'] != 'live':
                raise ValueError('Start the phone screen first.')
            self._open()
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()
        return {'shown': True}

    def send(self, event):
        if self.closed:
            return

        def run():
            try:
                self.session.input(event)
                self.notice = ''
            except ValueError as error:
                self.notice = str(error)[:120]
        self.sender.submit(run)

    def stop_session(self):
        """The window was closed or Stop pressed: end sharing (network shutdown off the GUI thread)."""
        self.screen.window = 'closed'
        threading.Thread(target=self.screen.stop, name='orion-screen-stop', daemon=True).start()
        if self.window is not None:
            self._save_geometry()
            self.window.quiet = True
            QTimer.singleShot(0, self._close)

    def live_sources(self):
        """What is live now, for the tray: the phone screen and/or the phone camera."""
        sources = []
        if self.session.status()['state'] == 'live':
            sources.append('phone screen')
        camera = getattr(self.workspace, 'camera', None)
        local = getattr(camera, 'local', None)
        if getattr(local, 'state', None) == 'live' or getattr(camera, 'processes', None):
            sources.append('camera')
        return sources

    def _update_tray(self):
        if self.tray is None:
            return
        sources = self.live_sources()
        live = bool(sources)
        if live != self.tray_live:
            self.tray_live = live
            if live and self.live_tray_icon is None:
                self.live_tray_icon = live_icon(self.icon)
            self.tray.setIcon(self.live_tray_icon if live else self.icon)
        self.tray.setToolTip('Saiph · Live: ' + ' and '.join(sources) if live else 'Saiph')

    def shutdown(self):
        self.closed = True
        self.status_timer.stop()
        self.unsubscribe()
        self._close()
        self.sender.shutdown(wait=False)
