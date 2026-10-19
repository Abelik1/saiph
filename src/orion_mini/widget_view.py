# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dashboard in a QWebEngineView widget, as before the native child window.

Selected with {"host": "widget"} in rendering.json (rendering.py) to compare
presentation paths. It offers the same surface as dashboard_view.DashboardView:
`widget`, load/setHtml/add_script/runJavaScript, profile(), set_shown(),
window_moved() and the loadFinished/files_dropped/drag_changed signals.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView

from .dashboard_view import local_files, local_url


class LocalPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        return local_url(url)


class DashboardWidget(QWebEngineView):
    """A web page cannot see a Windows file path, and Chromium answers a dropped
    file by navigating away from the dashboard. So Qt takes the drop first and
    hands the real paths to the page over the same channel everything else uses."""
    files_dropped = Signal(list)
    drag_changed = Signal(bool)
    DRAG_EVENTS = {QEvent.DragEnter, QEvent.DragMove, QEvent.DragLeave, QEvent.Drop}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.render_widget = None
        self.dragging = False
        self.loadFinished.connect(lambda _ok: self.watch_render_widget())

    def watch_render_widget(self):
        """Chromium renders into a child widget that owns its own drop handling,
        and replaces it across loads, so re-attach whenever it changes."""
        widget = self.focusProxy()
        if widget is not None and widget is not self.render_widget:
            self.render_widget = widget
            widget.installEventFilter(self)

    def event(self, event):
        if event.type() in {QEvent.ChildAdded, QEvent.ChildPolished}:
            self.watch_render_widget()
        return super().event(event)

    def set_dragging(self, active: bool) -> None:
        if active != self.dragging:
            self.dragging = active
            self.drag_changed.emit(active)

    def handle_drag(self, event) -> bool:
        """Answer one drag event; True means Chromium never sees it."""
        if event.type() == QEvent.DragLeave:
            self.set_dragging(False)
            return False
        files = local_files(event.mimeData())
        if not files:
            return False
        event.setDropAction(Qt.CopyAction)
        event.accept()
        dropping = event.type() == QEvent.Drop
        self.set_dragging(not dropping)
        if dropping:
            self.files_dropped.emit(files)
        return True

    def eventFilter(self, watched, event):
        if watched is self.render_widget and event.type() in self.DRAG_EVENTS and self.handle_drag(event):
            return True
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event):
        self.handle_drag(event)

    def dragMoveEvent(self, event):
        self.handle_drag(event)

    def dragLeaveEvent(self, event):
        self.handle_drag(event)

    def dropEvent(self, event):
        self.handle_drag(event)


class WidgetDashboardView:
    def __init__(self, bridge, ground: str, parent):
        self.widget = DashboardWidget(parent)
        self.widget.setPage(LocalPage(self.widget))
        self.widget.page().setBackgroundColor(QColor(ground))
        self.channel = QWebChannel(self.widget.page())
        self.channel.registerObject('orionMini', bridge)
        self.widget.page().setWebChannel(self.channel)
        self.loadFinished, self.files_dropped, self.drag_changed = (
            self.widget.loadFinished, self.widget.files_dropped, self.widget.drag_changed)

    def profile(self):
        return self.widget.page().profile()

    def load(self, url: QUrl) -> None:
        self.widget.load(url)

    def setHtml(self, html: str, base: QUrl = QUrl()) -> None:
        self.widget.setHtml(html, base)

    def add_script(self, name: str, source: str) -> None:
        script = QWebEngineScript()
        script.setName(name)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setSourceCode(source)
        self.widget.page().scripts().insert(script)

    def runJavaScript(self, code: str, callback=None) -> None:
        if callback is None:
            self.widget.page().runJavaScript(code)
        else:
            self.widget.page().runJavaScript(code, 0, callback)

    def set_shown(self, shown: bool) -> None:
        """Tell Chromium whether anyone can see the page (timers stop while hidden)."""
        page = self.widget.page()
        if hasattr(page, "setVisible") and page.isVisible() != shown:
            page.setVisible(shown)

    def window_moved(self) -> None:
        """A widget's web view follows the window's screen position on its own."""
