# SPDX-License-Identifier: AGPL-3.0-or-later
"""Finite request/response boundary for the local dashboard."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot, QMimeData, QMimeDatabase, QUrl, QTimer, Qt
from PySide6.QtGui import QDrag, QImageIOHandler, QImageReader
from PySide6.QtWidgets import QFileDialog, QApplication

from .platform import set_startup, open_target


class DesktopBridge(QObject):
    response = Signal(str)
    # Everything that changes app state announces `changed`; the page hears
    # `refresh`, which is held while nobody can see the window.
    changed = Signal()
    refresh = Signal()
    # Windows drops arrive at Qt, never at the page, so they travel back down this way.
    dropped = Signal(str)
    dragging = Signal(bool)
    completed = Signal(str)
    quiet_completed = Signal(str)
    update_ready = Signal()
    photo_prepared = Signal(str, object)
    # A new live camera or phone-screen picture: metadata only, the bytes are
    # loaded from the frame feed (frame_feed.py).
    frame = Signal(str)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.completed.connect(self.finish)
        self.quiet_completed.connect(self.finish_quiet)
        self.photo_prepared.connect(self.finish_photo)
        self.update_ready.connect(lambda: QTimer.singleShot(700, self.window.quit_app))
        # One update state for the footer button, Settings → Updates and the tray.
        from .update_schedule import DesktopUpdates
        self.updates = DesktopUpdates(window.workspace, changed=self.changed.emit, restart=self.update_ready.emit)
        self.held = False
        self.changed.connect(self.forward)
        self.feeds = {}
        workspace = window.workspace
        for name, session in (('camera', getattr(getattr(workspace, 'camera', None), 'local', None)),
                              ('screen', getattr(getattr(workspace, 'screen', None), 'session', None))):
            if session is not None and hasattr(session, 'jpeg'):
                session.notify = self.announcer(name, session)
                self.feeds[name] = session.jpeg

    @Slot()
    def forward(self):
        """Pass a change to the page, or hold it while the window is hidden or
        minimised: a hidden page needs no snapshot, and building one costs the
        GUI thread tens of milliseconds every time a phone or Cloud event arrives."""
        visible = getattr(self.window, 'dashboard_visible', None)
        if visible is None or visible():
            self.refresh.emit()
        else:
            self.held = True

    def resume(self):
        """The window is visible again: one refresh for everything held meanwhile."""
        if self.held:
            self.held = False
            self.refresh.emit()

    def announcer(self, name, session):
        """Session threads report frames and state here; Qt queues both to the page."""
        def announce(kind):
            if kind == 'frame':
                self.frame.emit(json.dumps({'source': name, **session.describe()}))
            else:
                self.changed.emit()
        return announce

    @Slot(str)
    def finish(self, packet):
        self.response.emit(packet)
        self.changed.emit()
        self.window.pump_jobs()

    @Slot(str)
    def finish_quiet(self, packet):
        self.response.emit(packet)
        self.window.pump_jobs()

    def background(self, request_id, action, *, changed=True):
        completed = self.completed if changed else self.quiet_completed
        def run():
            try: packet={"id":request_id,"ok":True,"result":action()}
            except Exception as error: packet={"id":request_id,"ok":False,"error":str(error)}
            completed.emit(json.dumps(packet))
        threading.Thread(target=run,name="orion-phone-action",daemon=True).start()

    def photo_original(self, request_id, method, args):
        if set(args) != {"device_id", "photo_id"} or not all(isinstance(value, str) and value for value in args.values()):
            raise ValueError("Choose a photo from a paired phone.")
        def prepare():
            try:
                features = self.window.workspace.phone_features
                with features.lock:
                    features.photo_request(args["device_id"], args["photo_id"], "prefetch")
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    row = features.photo_cached(args["device_id"], args["photo_id"])
                    if row:
                        result, clipboard = self.prepare_photo(row, method == "phone.photo.copy")
                        self.photo_prepared.emit(json.dumps({"id": request_id, "result": result}), clipboard)
                        return
                    time.sleep(0.1)
                raise ValueError("Your phone has not sent the original yet. Try again when it is connected.")
            except Exception as error:
                self.completed.emit(json.dumps({"id": request_id, "ok": False, "error": str(error)}))
        threading.Thread(target=prepare, name="orion-photo-original", daemon=True).start()

    @staticmethod
    def prepare_photo(row, copying):
        # Decode and read bytes away from the GUI thread. Only clipboard ownership
        # crosses back to Qt's GUI thread, including for large phone originals.
        path = Path(row["path"])
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        if not reader.canRead():
            raise ValueError("This image format cannot be opened here. Save the original to open it in another app.")
        size = reader.size()
        if reader.transformation() & QImageIOHandler.Transformation.TransformationRotate90:
            size.transpose()
        result = {"url": QUrl.fromLocalFile(str(path)).toString(), "width": size.width(), "height": size.height(), "size": path.stat().st_size}
        if not copying:
            return result, None
        image = reader.read()
        if image.isNull():
            raise ValueError("The original image could not be copied. Try saving it instead.")
        mime = QMimeDatabase().mimeTypeForFile(str(path)).name()
        encoded = path.read_bytes() if mime.startswith("image/") else None
        return {"copied": True, "width": image.width(), "height": image.height()}, (image, mime, encoded)

    @Slot(str, object)
    def finish_photo(self, raw, clipboard):
        packet = json.loads(raw)
        try:
            if clipboard is not None:
                image, mime, encoded = clipboard
                data = QMimeData()
                data.setImageData(image)
                if encoded is not None:
                    data.setData(mime, encoded)
                QApplication.clipboard().setMimeData(data)
            self.finish(json.dumps({"id": packet["id"], "ok": True, "result": packet["result"]}))
        except Exception as error:
            self.finish(json.dumps({"id": packet["id"], "ok": False, "error": str(error)}))

    def photo_drag(self, request_id, args):
        workspace = self.window.workspace
        workspace.dispatch("phone.photo.prefetch", args)
        timer = QTimer(self)
        timer.setInterval(100)
        deadline = time.monotonic() + 30
        def poll():
            try:
                row = workspace.phone_features.photo_cached(args["device_id"],args["photo_id"])
                held = bool(QApplication.mouseButtons() & Qt.MouseButton.LeftButton)
                if row and held:
                    timer.stop(); timer.deleteLater()
                    data=QMimeData();data.setUrls([QUrl.fromLocalFile(row["path"])])
                    drag=QDrag(self.window);drag.setMimeData(data);drag.exec()
                    result={"dragged":True}
                elif not held or time.monotonic() >= deadline:
                    timer.stop(); timer.deleteLater(); result={"preparing":not bool(row),"ready":bool(row)}
                else:return
                self.finish(json.dumps({"id":request_id,"ok":True,"result":result}))
            except Exception as error:
                timer.stop(); timer.deleteLater()
                self.finish(json.dumps({"id":request_id,"ok":False,"error":str(error)}))
        timer.timeout.connect(poll)
        timer.start()

    @Slot(str, str, str)
    def request(self, request_id: str, method: str, arguments: str):
        from .desktop_actions import DesktopActions
        return DesktopActions.request(_QtActions(self), request_id, method, arguments)


class _QtActions:
    """Preserve the Qt adapter and its existing test/extension boundary."""
    def __init__(self, bridge):
        self.bridge = bridge
    def __getattr__(self, name):
        return getattr(self.bridge, name)
    @property
    def dialogs(self):
        return QFileDialog
    @property
    def clipboard(self):
        return QApplication.clipboard()
    def open_target(self, value):
        return open_target(value)
    def set_startup(self, enabled):
        return set_startup(enabled)
