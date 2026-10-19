# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bounded Cloud image clipboard using the existing sealed attachment protocol."""
from __future__ import annotations

import os
import hashlib
from pathlib import Path
import tempfile

from .clipboard import PendingClipboard
from .hosted_crypto import EnvelopeError
from .hosted_files import AttachmentError, _manifest, download_attachment, prepare_attachment, upload_attachment
from .hosted_keys import _no_links, _windows_acl

MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
IMAGE_FORMATS = {"image/png": "png", "image/jpeg": "jpeg", "image/webp": "webp"}


def valid_image(mime, data, *, decode=False):
    """Check dimensions before decoding. MIME and the actual codec must agree."""
    if mime not in IMAGE_FORMATS or type(data) is not bytes or not 0 < len(data) <= MAX_IMAGE_BYTES:
        return False
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImageReader
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.ReadOnly)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    size = reader.size()
    if (not reader.canRead() or bytes(reader.format()).decode("ascii", errors="replace") != IMAGE_FORMATS[mime]
            or not size.isValid() or size.width() * size.height() > MAX_IMAGE_PIXELS):
        return False
    return not decode or not reader.read().isNull()


def private_directory(path):
    _no_links(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "nt":
        _windows_acl(path, set_private=True)
    return path


class _GuardedUpload:
    """Recheck consent, current roster and newest copy before every network call."""
    def __init__(self, transport, guard):
        self.transport, self.guard = transport, guard

    def __getattr__(self, name):
        action = getattr(self.transport, name)
        def checked(*args, **kwargs):
            if not self.guard():
                raise AttachmentError()
            return action(*args, **kwargs)
        return checked


class CloudClipboardImages:
    def __init__(self, controller):
        self.controller = controller
        self.pending = PendingClipboard()
        self.change = None
        self.uploads = {}
        self.sent = set()
        self.notice = ""

    def queue(self, mime, data):
        owner = getattr(self.controller.info, "device_id", None)
        if not owner or not valid_image(mime, data):
            self.notice = "This clipboard image is unsupported or too large. Send it as a file."
            return False
        self.notice = ""
        return self.pending.replace(owner, mime, data, max_bytes=MAX_IMAGE_BYTES)

    def clear(self):
        self.pending.clear()

    def _discard_uploads(self):
        for prepared in self.uploads.values():
            prepared.ciphertext.unlink(missing_ok=True)
        self.uploads.clear()
        self.sent.clear()

    def close(self):
        self.clear()
        self._discard_uploads()
        self.change = None

    def _allowed(self, change, target, prepared=None):
        c = self.controller
        try:
            return (self.pending.current() is change and c.enabled() and c.session is not None
                    and (c.workspace.settings.get("link") or {}).get("clipboard") is not False
                    and c.info.device_id == change.owner and target in c.session.current()
                    and (prepared is None or (prepared.descriptor["roster_version"] == c.session.roster["version"]
                         and prepared.descriptor["roster_hash"] == c.session.digest)))
        except (EnvelopeError, AttributeError):
            return False

    def sync(self):
        change = self.pending.current()
        if change is not self.change:
            self._discard_uploads()
            self.change = change
        if change is None:
            return
        c = self.controller
        targets = c._targets()
        for target in targets:
            if target in self.sent:
                continue
            if not self._allowed(change, target):
                return
            prepared = self.uploads.get(target)
            if prepared is not None and not self._allowed(change, target, prepared):
                prepared.ciphertext.unlink(missing_ok=True)
                self.uploads.pop(target)
                prepared = None
            try:
                if prepared is None:
                    folder = private_directory(c.folder / "clipboard-outgoing")
                    with tempfile.TemporaryDirectory(prefix=".clear-", dir=folder) as temporary:
                        private_directory(Path(temporary))
                        source = Path(temporary) / ("clipboard." + IMAGE_FORMATS[change.mime])
                        source.write_bytes(change.data)
                        remaining = min(30, int(change.expires - self.pending.now()))
                        if remaining < 1:
                            return
                        prepared = prepare_attachment(c.session, target, source, folder, kind="clipboard.image",
                                                      mime=change.mime, ttl_seconds=remaining)
                    self.uploads[target] = prepared
                upload_attachment(_GuardedUpload(c.transport, lambda: self._allowed(change, target, prepared)), prepared)
                self.sent.add(target)
            except (AttachmentError, OSError):
                self.notice = "Image clipboard could not finish. Copy the image again if it does not arrive."
                return  # Keep the same ciphertext/event for a bounded exact retry.
        if set(targets) <= self.sent:
            self.pending.commit(change, lambda: None)
            self._discard_uploads()
            self.change = None
            self.notice = ""

    def receive(self, envelope):
        c = self.controller
        payload, _ = _manifest(c.session, envelope)
        if (payload["kind"] != "clipboard.image" or payload["mime"] not in IMAGE_FORMATS
                or not 0 < payload["size"] <= MAX_IMAGE_BYTES):
            raise AttachmentError()
        folder = private_directory(c.folder / "clipboard-incoming")
        with tempfile.TemporaryDirectory(prefix=".image-", dir=folder) as temporary:
            private_directory(Path(temporary))
            destination = Path(temporary) / "verified"
            download_attachment(c.session, c.transport, envelope, destination)
            data = destination.read_bytes()
            if not valid_image(payload["mime"], data, decode=True):
                raise AttachmentError()
        # Authentication is rechecked after download and immediately before the
        # effect. The GUI dispatch also receives a fresh consent/roster guard.
        c.session.authenticate(envelope)
        if not c.clipboard_cache.contains_digest(payload["mime"], hashlib.sha256(data).hexdigest()):
            c._deliver_clipboard(envelope["header"]["source"], payload["mime"], data, envelope["header"]["expires_at"])
