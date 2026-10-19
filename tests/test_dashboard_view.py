# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dashboard's native web view host: navigation, drops and screen position."""
from PySide6.QtCore import QEvent, QMimeData, QPointF, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent

from orion_mini.dashboard_view import DashboardHost, local_url


def test_only_local_pages_may_load():
    assert local_url(QUrl.fromLocalFile('C:/Saiph/frontend/dist/index.html'))
    assert local_url(QUrl('qrc:///qtwebchannel/qwebchannel.js')) and local_url(QUrl('about:blank'))
    assert not local_url(QUrl('https://example.com/'))
    assert not local_url(QUrl('saiph-frame://camera/1'))  # Frames load as images, never as a page.


KEEP = []  # A Qt event only borrows its mime data; keep it alive for the test.


def drop(kind, urls):
    data = QMimeData()
    data.setUrls(urls)
    KEEP.append(data)
    if kind == QEvent.Drop:
        return QDropEvent(QPointF(10, 10), Qt.CopyAction, data, Qt.LeftButton, Qt.NoModifier)
    return QDragEnterEvent(QPointF(10, 10).toPoint(), Qt.CopyAction, data, Qt.LeftButton, Qt.NoModifier)


def test_dropped_files_reach_qt_never_the_page(qapp, tmp_path):
    host = DashboardHost(None, '#040916')
    dropped, dragging = [], []
    host.files_dropped.connect(dropped.append)
    host.drag_changed.connect(dragging.append)
    local = QUrl.fromLocalFile(str(tmp_path / 'a.txt'))  # A platform path: 'C:/…' is not local on Linux.
    assert host.eventFilter(None, drop(QEvent.DragEnter, [local]))
    assert host.eventFilter(None, drop(QEvent.Drop, [local]))
    assert dropped == [[local.toLocalFile()]] and dragging == [True, False]
    # A web link drag is the page's own business.
    assert not host.eventFilter(None, drop(QEvent.DragEnter, [QUrl('https://example.com/')]))
