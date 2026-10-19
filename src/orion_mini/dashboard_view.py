# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dashboard's Chromium view, in its own natively composited child window.

A `QWebEngineView` widget draws through a hidden Qt Quick window that follows
the widget's position on screen. Every pixel a window moves therefore changes
the web view's window position, which Qt WebEngine forwards to Chromium as new
visual properties; Chromium answers with a full new frame that Qt composites
into the widget window. Dragging the window cost 60-80 % of a core on the GUI
thread and the window lagged behind the pointer (docs/DESKTOP_PERFORMANCE.md).

Here Chromium lives in a `QQuickView` (a QML `WebEngineView`) embedded with
`QWidget.createWindowContainer`. That native child window keeps the same
position relative to its parent while the main window moves, so a drag needs
no new web frame, and each web frame goes straight to the child window's GPU
swap chain without any widget composition.

The QML engine only hosts this one view: navigation stays limited to local
files, dropped files are taken by Qt before Chromium can navigate to them, and
the web channel exposes the same single bridge object.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Property, QEvent, QMetaObject, QObject, QPointF, QUrl, Q_ARG, Qt, Signal, Slot
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import QMenu, QToolTip, QWidget

QML = """
import QtQuick
import QtWebEngine
import QtWebChannel

WebEngineView {
    id: view
    anchors.fill: parent
    focus: true
    backgroundColor: host ? host.ground : "transparent"
    webChannel: WebChannel { id: channel }
    Component.onCompleted: channel.registerObject("orionMini", host.bridge)
    onNavigationRequested: function (request) {
        if (host.allowed(request.url)) request.accept(); else request.reject();
    }
    onNewWindowRequested: function (request) { }
    // Menus and tooltips are native Qt widgets, as they were with QWebEngineView, so
    // no Qt Quick Controls are needed. The dashboard uses no web dialogs at all.
    onContextMenuRequested: function (request) {
        request.accepted = true;
        var flags = request.editFlags, at = view.mapToGlobal(request.position.x, request.position.y);
        host.contextMenu(at, request.isContentEditable, (flags & ContextMenuRequest.CanCut) !== 0,
                         (flags & ContextMenuRequest.CanCopy) !== 0, (flags & ContextMenuRequest.CanPaste) !== 0,
                         (flags & ContextMenuRequest.CanSelectAll) !== 0);
    }
    onTooltipRequested: function (request) {
        request.accepted = true;
        host.tooltip(request.type === TooltipRequest.Show ? request.text : "");
    }
    onJavaScriptDialogRequested: function (request) { request.accepted = true; request.dialogReject(); }
    onFileDialogRequested: function (request) { request.accepted = true; request.dialogReject(); }
    onColorDialogRequested: function (request) { request.accepted = true; request.dialogReject(); }
    onAuthenticationDialogRequested: function (request) { request.accepted = true; request.dialogReject(); }
    function act(name) { view.triggerWebAction(WebEngineView[name]); }
    onLoadingChanged: function (loading) {
        if (loading.status === WebEngineView.LoadSucceededStatus) host.loaded(true);
        else if (loading.status === WebEngineView.LoadFailedStatus) host.loaded(false);
    }
    function evaluate(token, code) {
        view.runJavaScript(code, function (value) { host.report(token, JSON.stringify(value === undefined ? null : value)); });
    }
    function addScript(name, source) {
        var script = WebEngine.script();
        script.name = name;
        script.sourceCode = source;
        script.worldId = WebEngineScript.MainWorld;
        script.injectionPoint = WebEngineScript.DocumentCreation;
        view.userScripts.insert(script);
    }
}
"""


def prepare_web_engine(profile=None) -> dict:
    """Everything Qt needs before QApplication exists: the presentation choice in
    the profile's rendering.json (rendering.py), the frame feed scheme and Qt
    Quick WebEngine. Returns the presentation choice in effect."""
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWebEngineQuick import QtWebEngineQuick
    from . import rendering
    from .frame_feed import register_scheme
    choice = rendering.apply(rendering.load(profile) if profile is not None else rendering.DEFAULT)
    register_scheme()
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    QtWebEngineQuick.initialize()
    return choice


def dashboard_view(bridge, ground: str, parent):
    """The dashboard host the presentation choice asks for (native unless rendering.json says widget)."""
    from . import rendering
    if rendering.active().get("host") == "widget":
        from .widget_view import WidgetDashboardView
        return WidgetDashboardView(bridge, ground, parent)
    return DashboardView(bridge, ground, parent)


def local_url(url: QUrl) -> bool:
    return url.isLocalFile() or url.scheme() in {'qrc', 'about'}


def local_files(mime) -> list[str]:
    return [url.toLocalFile() for url in mime.urls() if url.isLocalFile()] if mime.hasUrls() else []


class DashboardHost(QObject):
    """What QML reads (`host`) and what the shell drives: load, scripts, drops."""
    loadFinished = Signal(bool)
    evaluated = Signal(int, str)
    web_action = Signal(str)
    files_dropped = Signal(list)
    drag_changed = Signal(bool)
    DRAG_EVENTS = {QEvent.DragEnter, QEvent.DragMove, QEvent.DragLeave, QEvent.Drop}

    def __init__(self, bridge, ground: str, parent=None):
        super().__init__(parent)
        self._bridge, self._ground = bridge, QColor(ground)
        self.dragging = False

    def get_bridge(self):
        return self._bridge

    def get_ground(self):
        return self._ground

    bridge = Property(QObject, get_bridge, constant=True)
    ground = Property(QColor, get_ground, constant=True)

    @Slot(QUrl, result=bool)
    def allowed(self, url):
        return local_url(url)

    @Slot(int, str)
    def report(self, token, value):
        self.evaluated.emit(token, value)

    @Slot(QPointF, bool, bool, bool, bool, bool)
    def contextMenu(self, at, editable, cut, copy, paste, select_all):
        """Copy for selected text; Cut, Copy, Paste and Select all in text fields."""
        choices = [('Cut', 'Cut', editable and cut), ('Copy', 'Copy', copy),
                   ('Paste', 'Paste', editable and paste), ('Select all', 'SelectAll', editable and select_all)]
        if not any(enabled for *_, enabled in choices):
            return
        menu = QMenu()
        for label, action, enabled in choices:
            if editable or enabled:
                item = menu.addAction(label)
                item.setEnabled(enabled)
                item.triggered.connect(lambda _checked=False, action=action: self.web_action.emit(action))
        menu.exec(at.toPoint())

    @Slot(str)
    def tooltip(self, text):
        if text:
            QToolTip.showText(QCursor.pos(), text)
        else:
            QToolTip.hideText()

    @Slot(bool)
    def loaded(self, ok):
        self.loadFinished.emit(ok)

    def set_dragging(self, active: bool) -> None:
        """Hovering repeats a move event many times a second; the page only needs
        to hear when the answer actually changes."""
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
        if event.type() in self.DRAG_EVENTS and self.handle_drag(event):
            return True
        return super().eventFilter(watched, event)


class DashboardView:
    """The dashboard view: `widget` goes into the main window; the rest mirrors
    the parts of QWebEngineView the shell and its test harness use."""

    def __init__(self, bridge, ground: str, parent: QWidget):
        from PySide6.QtQuick import QQuickView
        self.host = DashboardHost(bridge, ground, parent)
        self.loadFinished, self.files_dropped, self.drag_changed = (
            self.host.loadFinished, self.host.files_dropped, self.host.drag_changed)
        self.quick = QQuickView()
        self.quick.setColor(QColor(ground))
        self.quick.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        self.quick.rootContext().setContextProperty('host', self.host)
        # Dropped files reach Qt here, before the web view could navigate to them.
        self.quick.installEventFilter(self.host)
        from PySide6.QtQml import QQmlComponent
        component = QQmlComponent(self.quick.engine(), self.quick)  # Owned by the view, not Python.
        # Inline, so packaging carries no separate .qml file; the base URL only names it.
        component.setData(QML.encode(), QUrl.fromLocalFile(str(Path(__file__).with_name('dashboard_view.qml'))))
        root = component.create(self.quick.rootContext())
        if root is None:
            raise RuntimeError('The dashboard view could not start: ' + '; '.join(e.toString() for e in component.errors()))
        self.quick.setContent(QUrl(), component, root)
        self._component = component
        self.view = root
        self.host.web_action.connect(lambda action: QMetaObject.invokeMethod(self.view, 'act', Q_ARG('QVariant', action)))
        self.widget = QWidget.createWindowContainer(self.quick, parent)
        self.widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.widget.setMinimumSize(1, 1)

    def set_shown(self, shown: bool) -> None:
        """Tell Chromium whether anyone can see the page. A hidden or minimised
        window otherwise leaves the page "visible", so its timers keep running."""
        if self.view.property('visible') != shown:
            self.view.setProperty('visible', shown)

    def window_moved(self) -> None:
        """Tell Chromium where the view now is on screen, once a move has settled.

        The child window keeps its position relative to the main window, so Qt
        WebEngine never hears that the main window moved; Chromium would place
        popups (a <select>'s list) and screen coordinates at the old spot. Re-announcing
        the position makes it read the view's real screen geometry again: one update
        per drag instead of one full frame per pixel moved."""
        self.quick.xChanged.emit(self.quick.x())
        self.quick.yChanged.emit(self.quick.y())

    def profile(self):
        from PySide6.QtWebEngineQuick import QQuickWebEngineProfile
        return QQuickWebEngineProfile.defaultProfile()

    def load(self, url: QUrl) -> None:
        self.view.setProperty('url', url)

    def setHtml(self, html: str, base: QUrl = QUrl()) -> None:
        QMetaObject.invokeMethod(self.view, 'loadHtml', Q_ARG(str, html), Q_ARG(QUrl, base))

    def add_script(self, name: str, source: str) -> None:
        """A script run at document creation in the page's main world (test harness)."""
        QMetaObject.invokeMethod(self.view, 'addScript', Q_ARG('QVariant', name), Q_ARG('QVariant', source))

    def runJavaScript(self, code: str, callback=None) -> None:
        """Runs `code` in the page; `callback` receives its JSON-compatible result."""
        if callback is None:
            QMetaObject.invokeMethod(self.view, 'runJavaScript', Q_ARG(str, code))
            return
        import json
        self._token = getattr(self, '_token', 0) + 1
        token = self._token
        def answer(done, value):
            if done == token:
                self.host.evaluated.disconnect(answer)
                callback(json.loads(value))
        self.host.evaluated.connect(answer)
        QMetaObject.invokeMethod(self.view, 'evaluate', Q_ARG('QVariant', token), Q_ARG('QVariant', code))
