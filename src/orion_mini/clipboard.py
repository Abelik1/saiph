# SPDX-License-Identifier: AGPL-3.0-or-later
"""Clipboard metadata and bounded loop prevention; content is never logged."""
from __future__ import annotations
import hashlib
import threading
import time
from dataclasses import dataclass, field
from .peer import MAX_CLIPBOARD

ECHO_SECONDS = 10


class RecentClipboard:
    """The value most recently synced, suppressed only as an echo.

    A remote write or local publish records its (mime, digest); the OS change
    callback that follows within ECHO_SECONDS is not rebroadcast. Content seen
    earlier is not blocked: copying A, B, then A again must deliver A again.
    """
    def __init__(self, now=time.monotonic):
        self.now = now; self.keys = set(); self.at = float('-inf'); self.lock = threading.RLock()
    def _current(self, now):
        return self.keys if now - self.at < ECHO_SECONDS else set()
    def claim(self, mime, data):
        digest = hashlib.sha256(data).hexdigest()
        with self.lock:
            now = self.now()
            key = (mime, digest)
            if key in self._current(now): return None
            self.keys = {key}; self.at = now
        return digest
    def received(self, mime, data, *, alias=False):
        # Each native write replaces the previous value. Only an explicit
        # re-encoding of this same write may add a second digest (JPEG -> PNG).
        key = (mime, hashlib.sha256(data).hexdigest())
        with self.lock:
            now = self.now()
            current = self._current(now)
            self.keys = (current | {key}) if alias and len(current) < 8 else {key}; self.at = now
    def contains_digest(self, mime, digest):
        with self.lock:
            return (mime, digest) in self._current(self.now())


@dataclass(frozen=True)
class ClipboardChange:
    owner: str
    mime: str
    data: bytes = field(repr=False)
    digest: str = field(repr=False)
    expires: float


@dataclass(frozen=True)
class GuardedClipboardDelivery:
    data: bytes = field(repr=False)
    authorized: object = field(repr=False)


class PendingClipboard:
    """One recent local change, held in memory for at most 30 seconds."""
    MAX_BYTES = 16 * 1024 * 1024

    def __init__(self, now=time.monotonic):
        self.now = now
        self.lock = threading.Lock()
        self.value = None

    def replace(self, owner, mime, data, *, max_bytes=None):
        with self.lock:
            self.value = None
            if len(data) > (self.MAX_BYTES if max_bytes is None else max_bytes):
                return False
            self.value = ClipboardChange(owner, mime, data, hashlib.sha256(data).hexdigest(), self.now() + 30)
            return True

    def current(self):
        with self.lock:
            if self.value and self.now() >= self.value.expires:
                self.value = None
            return self.value

    def clear(self):
        with self.lock:
            self.value = None

    def commit(self, change, action):
        # Publish and removal are atomic relative to a newer GUI-thread copy.
        # A refused publish leaves the latest value available for automatic retry.
        with self.lock:
            if self.value is not change or self.now() >= change.expires:
                return False
            action()
            self.value = None
            return True

def envelope(mime, data, digest, peer=None):
    if mime not in {'text/plain','image/png','image/jpeg','image/webp'}: raise ValueError('Unsupported clipboard type')
    if len(data) > MAX_CLIPBOARD: raise ValueError('Clipboard content needs a file send')
    payload = {'mime':mime,'sha256':digest,'size':len(data)}
    text = data.decode('utf-8') if mime == 'text/plain' else None
    if text is not None and len(text) <= 4096: payload['text'] = text
    else:
        if peer is None: raise ValueError('Direct clipboard transfer is unavailable')
        payload['blob'] = peer.offer(data)
    return payload

def oriented_png(data, mime='image/jpeg'):
    """PNG bytes of an encoded image with its EXIF orientation applied, or None.

    Qt's default clipboard decode ignores EXIF, so a portrait phone photo copied
    on Linux would arrive sideways. Size is checked before decoding."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImageReader
    buffer=QBuffer();buffer.setData(QByteArray(bytes(data)));buffer.open(QIODevice.ReadOnly)
    reader=QImageReader(buffer,mime.split('/',1)[1].encode());reader.setAutoTransform(True);size=reader.size()
    if not size.isValid() or size.width()*size.height()>40_000_000: return None
    image=reader.read()
    if image.isNull(): return None
    out=QBuffer();out.open(QIODevice.WriteOnly);image.save(out,'PNG')
    return bytes(out.data())

class QtClipboard:
    """Created and invoked only on Qt's GUI thread, including received writes."""
    def __init__(self, runtime):
        from PySide6.QtWidgets import QApplication
        self.runtime = runtime; self.clipboard = QApplication.clipboard()
        self.clipboard.dataChanged.connect(self.changed)
    def image_bytes(self, image):
        from PySide6.QtCore import QBuffer, QIODevice
        buffer=QBuffer();buffer.open(QIODevice.WriteOnly);image.save(buffer,'PNG')
        return bytes(buffer.data())
    def changed(self):
        try:
            mime = self.clipboard.mimeData()
            hosted = getattr(self.runtime.workspace, '_hosted', None)
            if mime is None:
                if hosted is not None: hosted.clear_local_clipboard()
                return
            if mime.hasImage():
                # A copied JPEG keeps its orientation; other formats use Qt's own decode.
                data = oriented_png(mime.data('image/jpeg')) if mime.hasFormat('image/jpeg') else None
                data = data or self.image_bytes(self.clipboard.image()); kind='image/png'
            elif mime.hasText():data=mime.text().encode();kind='text/plain'
            else:
                if hosted is not None: hosted.clear_local_clipboard()
                return
            self.runtime.local_clipboard(kind,data)
            # Opt-in hosted preview; absent unless its setting was turned on.
            if hosted is not None: hosted.local_clipboard(kind,data)
        except Exception: self.runtime.state.error = 'Clipboard sharing is temporarily unavailable.'
    def write(self, mime, data):
        guarded = isinstance(data, GuardedClipboardDelivery)
        guard = data.authorized if isinstance(data, GuardedClipboardDelivery) else lambda: True
        if isinstance(data, GuardedClipboardDelivery): data = data.data
        if (self.runtime.workspace.settings.get('link') or {}).get('clipboard') is False or not guard(): return
        if mime == 'text/plain':
            hosted = getattr(self.runtime.workspace, '_hosted', None)
            if guarded and hosted is not None: hosted.clipboard_cache.received(mime,data)
            self.runtime.clipboard_cache.received(mime,data)
            self.clipboard.setText(data.decode('utf-8'))
        else:
            from PySide6.QtGui import QImageReader
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice
            buffer=QBuffer();buffer.setData(QByteArray(data));buffer.open(QIODevice.ReadOnly)
            reader=QImageReader(buffer);reader.setAutoTransform(True);size=reader.size()
            if not size.isValid() or size.width()*size.height()>40_000_000: raise ValueError('Invalid clipboard image')
            image=reader.read()
            if image.isNull(): raise ValueError('Invalid clipboard image')
            if not guard(): return
            hosted = getattr(self.runtime.workspace, '_hosted', None)
            if guarded and hosted is not None:
                hosted.clipboard_cache.received(mime,data)
                hosted.clipboard_cache.received('image/png',self.image_bytes(image),alias=True)
            # OS image formats may re-encode JPEG as PNG. Suppress that echo too.
            self.runtime.clipboard_cache.received(mime,data)
            self.runtime.clipboard_cache.received('image/png',self.image_bytes(image),alias=True)
            self.clipboard.setImage(image)
