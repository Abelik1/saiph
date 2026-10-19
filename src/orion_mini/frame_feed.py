# SPDX-License-Identifier: AGPL-3.0-or-later
"""Live camera and phone-screen pictures for the dashboard, as bytes.

The bridge announces each new frame with a few bytes of metadata; the page then
loads `saiph-frame://camera/<sequence>` (or `screen`) like any image, so
Chromium decodes the JPEG off its main thread. No base64, no JSON wrapping and
no polling on the Qt GUI thread.

Only the latest frame of a live session is served, from memory. Nothing is
written to disk: Chromium's disk cache stores only http(s), and every response
also says no-store. The scheme is local, so only the dashboard's own file page
can load it, and the handler additionally refuses other initiators and methods.
"""
from __future__ import annotations

import re

SCHEME = b'saiph-frame'
SOURCES = ('camera', 'screen')
_PATH = re.compile(r'/\d{1,15}')


def register_scheme() -> None:
    """Declare the scheme. Qt requires this before QApplication is created."""
    from PySide6.QtWebEngineCore import QWebEngineUrlScheme
    if QWebEngineUrlScheme.schemeByName(SCHEME).name() == SCHEME:
        return
    scheme = QWebEngineUrlScheme(SCHEME)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    scheme.setFlags(QWebEngineUrlScheme.Flag.SecureScheme | QWebEngineUrlScheme.Flag.LocalScheme)
    QWebEngineUrlScheme.registerScheme(scheme)


def allowed(method: bytes, host: str, path: str, initiator: str) -> bool:
    """A frame request from the dashboard itself: GET, a known source, a sequence path."""
    return (method == b'GET' and host in SOURCES and bool(_PATH.fullmatch(path))
            and (initiator in ('', 'null') or initiator.startswith(('file:', 'qrc:'))))


def frame_handler(sources, parent=None):
    """A scheme handler serving `sources[name]() -> bytes | None` for each live source."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtWebEngineCore import QWebEngineUrlRequestJob, QWebEngineUrlSchemeHandler

    class FrameHandler(QWebEngineUrlSchemeHandler):
        def requestStarted(self, job):
            url, initiator = job.requestUrl(), job.initiator()
            origin = initiator.toString() if initiator.isValid() else ''
            source = sources.get(url.host()) if allowed(bytes(job.requestMethod()), url.host(), url.path(), origin) else None
            if source is None:
                job.fail(QWebEngineUrlRequestJob.Error.RequestDenied)
                return
            data = source()
            if not data:
                job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
                return
            if hasattr(job, 'setAdditionalResponseHeaders'):
                job.setAdditionalResponseHeaders({QByteArray(b'Cache-Control'): QByteArray(b'no-store')})
            buffer = QBuffer(job)
            buffer.setData(QByteArray(data))
            buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            job.reply(QByteArray(b'image/jpeg'), buffer)

    return FrameHandler(parent)
