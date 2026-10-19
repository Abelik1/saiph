# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cloud bitmap bytes use real sealed streaming crypto and fresh delivery guards."""
import hashlib
import struct
import threading
import time
import zlib
from types import SimpleNamespace

import pytest

from test_hosted_files import pair, BlobRelay
from orion_mini.clipboard import RecentClipboard, GuardedClipboardDelivery, QtClipboard
from orion_mini.hosted_clipboard import CloudClipboardImages, valid_image, MAX_IMAGE_BYTES
from orion_mini.hosted_crypto import canonical
from orion_mini.hosted_runtime import HostedController


def png(width=4, height=3):
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\0' + b'\x21\x42\x63\x80' * min(width, 4)) * min(height, 3)))
            + chunk(b'IEND', b''))


def controller(session, relay, folder):
    c = SimpleNamespace(session=session, transport=relay, folder=folder,
                        workspace=SimpleNamespace(settings={'link': {'clipboard': True}}),
                        enabled=lambda: True, info=SimpleNamespace(device_id=session.device),
                        clipboard_cache=RecentClipboard(), status='active', clipboard_dispatch=None,
                        clock=time.time,
                        _outgoing_clipboard=None, _wake=threading.Event())
    c._targets = lambda: [target for target in session.current() if target != session.device]
    c.clear_local_clipboard = lambda: HostedController.clear_local_clipboard(c)
    c._deliver_clipboard = lambda *args: HostedController._deliver_clipboard(c, *args)
    c.clipboard_images = CloudClipboardImages(c)
    return c


@pytest.mark.parametrize('mime,data', [('image/jpeg', png()), ('image/png', b'invalid'),
    ('image/gif', png()), ('image/png', png(4001, 4000)),
    ('image/png', b'x' * (MAX_IMAGE_BYTES + 1)), ('image/png', b'')],
    ids=['wrong-codec', 'malformed', 'unsupported', 'pixel-limit', 'byte-limit', 'empty'])
def test_invalid_codec_dimensions_and_bytes_are_rejected(mime, data):
    assert not valid_image(mime, data, decode=True)


def test_valid_rgba_png_has_transparency_and_exact_pixels():
    assert valid_image('image/png', png(), decode=True)


@pytest.mark.parametrize('lost_reply', [None, 0, 'publish'])
def test_encrypted_image_round_trip_and_exact_retry(pair, tmp_path, lost_reply):
    sender, receiver, _ = pair
    relay = BlobRelay()
    relay.fail_once = lost_reply
    c = controller(sender, relay, tmp_path / 'sender')
    assert c.clipboard_images.queue('image/png', png())
    c.clipboard_images.sync()
    if lost_reply is not None:
        prepared = next(iter(c.clipboard_images.uploads.values()))
        before = prepared.ciphertext.read_bytes(), canonical(prepared.envelope)
        c.clipboard_images.sync()
        assert b''.join(relay.chunks.values()) == before[0]
        assert canonical(relay.envelope) == before[1]
    assert c.clipboard_images.pending.current() is None
    assert not list((c.folder / 'clipboard-outgoing').iterdir())
    payload = receiver.authenticate(relay.envelope)
    assert payload['kind'] == 'clipboard.image' and payload['mime'] == 'image/png'
    opaque = canonical(relay.envelope) + canonical(relay.descriptor) + b''.join(relay.chunks.values())
    assert png() not in opaque and b'clipboard.png' not in opaque and b'image/png' not in opaque
    dest = controller(receiver, relay, tmp_path / 'receiver')
    effects = []
    dest.clipboard_sink = lambda mime, data: effects.append((mime, data))
    dest.clipboard_images.receive(relay.envelope)
    assert effects == [('image/png', png())]
    dest.clipboard_images.receive(relay.envelope)
    assert len(effects) == 1
    assert not list((dest.folder / 'clipboard-incoming').iterdir())


@pytest.mark.parametrize('change', ['disable', 'replace', 'expire'])
def test_each_upload_call_rechecks_consent_and_latest_copy(pair, tmp_path, change):
    sender, _, _ = pair
    relay = BlobRelay()
    c = controller(sender, relay, tmp_path / 'sender')
    clock = [100.0]
    c.clipboard_images.pending.now = lambda: clock[0]
    assert c.clipboard_images.queue('image/png', png())
    original = relay.allocate_blob
    def allocate(value):
        original(value)
        if change == 'disable': c.workspace.settings['link']['clipboard'] = False
        elif change == 'replace': c.clipboard_images.queue('image/png', png(3, 3))
        else: clock[0] += 31
    relay.allocate_blob = allocate
    c.clipboard_images.sync()
    assert relay.envelope is None and not relay.chunks
    c.clipboard_images.close()
    assert not list((c.folder / 'clipboard-outgoing').iterdir())


@pytest.mark.parametrize('change', ['disable', 'session', 'expired-roster', 'expired-event'])
def test_gui_dispatch_rechecks_authority_after_worker_completed(pair, tmp_path, change):
    sender, receiver, _ = pair
    relay = BlobRelay()
    c = controller(sender, relay, tmp_path / 'sender')
    c.clipboard_images.queue('image/png', png()); c.clipboard_images.sync()
    dest = controller(receiver, relay, tmp_path / 'receiver')
    queued = []
    dest.clipboard_dispatch = lambda *args: queued.append(args)
    dest.clipboard_images.receive(relay.envelope)
    assert len(queued) == 1 and queued[0][2]()
    if change == 'disable': dest.workspace.settings['link']['clipboard'] = False
    elif change == 'session': dest.session = None
    elif change == 'expired-roster': receiver.roster['expires_at'] = 0
    else: dest.clock = lambda: relay.envelope['header']['expires_at'] + 1
    assert not queued[0][2]()
    assert not dest.clipboard_cache.contains_digest('image/png', hashlib.sha256(png()).hexdigest())


def test_native_writer_preserves_rgba_pixels_and_refuses_stale_delivery():
    effects = []
    writer = object.__new__(QtClipboard)
    writer.runtime = SimpleNamespace(workspace=SimpleNamespace(settings={}), clipboard_cache=RecentClipboard())
    writer.clipboard = SimpleNamespace(setImage=effects.append)
    writer.write('image/png', GuardedClipboardDelivery(png(), lambda: False))
    assert not effects
    writer.write('image/png', GuardedClipboardDelivery(png(), lambda: True))
    assert len(effects) == 1
    image = effects[0]
    assert (image.width(), image.height()) == (4, 3)
    assert image.pixelColor(1, 1).getRgb() == (33, 66, 99, 128)


def rotated_jpeg(width=4, height=2, orientation=6):
    """A synthetic JPEG whose EXIF says: rotate 90° clockwise to display."""
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor(200, 30, 30))
    buffer = QBuffer(); buffer.open(QIODevice.WriteOnly); image.save(buffer, 'JPEG', 95)
    plain = bytes(buffer.data())
    tiff = (b'MM\x00\x2a\x00\x00\x00\x08' + b'\x00\x01'
            + b'\x01\x12\x00\x03\x00\x00\x00\x01' + struct.pack('!H', orientation) + b'\x00\x00' + b'\x00\x00\x00\x00')
    app1 = b'Exif\x00\x00' + tiff
    return plain[:2] + b'\xff\xe1' + struct.pack('!H', len(app1) + 2) + app1 + plain[2:]


def test_copied_jpeg_keeps_its_exif_orientation():
    from PySide6.QtGui import QImage
    from orion_mini.clipboard import oriented_png
    data = oriented_png(rotated_jpeg())
    image = QImage.fromData(data, 'PNG')
    assert (image.width(), image.height()) == (2, 4)  # Upright, as the phone showed it.
    assert oriented_png(b'not an image') is None

    sent = []
    reader = object.__new__(QtClipboard)
    reader.runtime = SimpleNamespace(workspace=SimpleNamespace(settings={}), local_clipboard=lambda kind, value: sent.append((kind, value)))
    mime = SimpleNamespace(hasImage=lambda: True, hasText=lambda: False,
                           hasFormat=lambda name: name == 'image/jpeg', data=lambda name: rotated_jpeg())
    reader.clipboard = SimpleNamespace(mimeData=lambda: mime, image=lambda: QImage.fromData(rotated_jpeg()))
    reader.changed()
    [(kind, value)] = sent
    shared = QImage.fromData(value, 'PNG')
    assert kind == 'image/png' and (shared.width(), shared.height()) == (2, 4)
