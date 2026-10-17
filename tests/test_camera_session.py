# SPDX-License-Identifier: AGPL-3.0-or-later
import ssl
import time

import pytest
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage
from websockets.sync.client import connect
from websockets.exceptions import InvalidStatus, ConnectionClosed

from orion_mini.camera_session import CameraSession, FRAME, local_address, read_frame


class Sink:
    def __init__(self):
        self.frames = []
        self.closed = False

    def write(self, value):
        self.frames[:] = [value]

    def close(self):
        self.closed = True


def jpeg(width=1280, height=720):
    image = QImage(width, height, QImage.Format.Format_RGB888)
    image.fill(0xFF1177AA)
    output = QBuffer()
    output.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(output, 'JPEG', 65)
    return bytes(output.data())


def packet(sequence=1, rotation=0, width=1280, height=720, image=None):
    return FRAME.pack(b'SCF1', width, height, rotation, sequence) + (jpeg(width, height) if image is None else image)


def until(predicate):
    deadline = time.monotonic() + 4
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


@pytest.fixture
def session():
    sink = Sink()
    value = CameraSession(lambda: sink, addresses=lambda: ['192.168.1.7'])
    value.start()
    yield value, sink
    value.stop()


def client(session, secret=None):
    # Synthetic loopback connection only. The Android client performs exact
    # certificate pinning; this fixture tests the actual TLS/auth server path.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    port = session.server.socket.getsockname()[1]
    return connect(f'wss://127.0.0.1:{port}/camera/{session.session}', ssl=context, proxy=None, legacy=True,
                   additional_headers={'Authorization': 'Bearer ' + (secret if secret is not None else session.secret)})


def test_real_tls_round_trip_fits_rotated_preview_and_blanks_on_stop(session):
    value, sink = session
    with client(value) as phone:
        phone.send(packet(rotation=90))
        until(lambda: value.status()['state'] == 'live')
        assert len(sink.frames[0]) == 1280 * 720 * 4
        assert value.latest()['image'].startswith('data:image/jpeg;base64,')
        assert value.cancel_invite(value.session) == {'cancelled': False}
        value.stop()
        assert sink.closed and value.latest()['image'] is None
        with pytest.raises(ConnectionClosed):
            phone.send(packet(2))


def test_wrong_secret_does_not_consume_invite_and_replay_is_rejected(session):
    value, sink = session
    secret = value.secret
    with pytest.raises(InvalidStatus):
        client(value, 'synthetic-wrong-secret')
    assert value.status()['state'] == 'waiting'
    with client(value, secret) as phone:
        with pytest.raises(InvalidStatus):
            client(value, secret)
        phone.send(packet())
        until(lambda: value.status()['state'] == 'live')
        phone.send(packet())  # Duplicate sequence ends the session.
        until(lambda: value.status()['state'] == 'idle')
        assert sink.closed


def test_bad_dimensions_or_replayed_sequence_never_decode():
    good = jpeg()
    for value, previous in [(packet(image=good, width=1279), 0), (packet(), 1),
                            (packet(rotation=45), 0), (FRAME.pack(b'SCF1', 65535, 65535, 0, 1) + good, 0),
                            (b'x' * 512001, 0), ('text', 0)]:
        with pytest.raises(ValueError):
            read_frame(value, previous)


def test_expired_invite_refused_before_connection(session):
    value, sink = session
    value.deadline = value.clock() - 1
    with pytest.raises(InvalidStatus):
        client(value)
    assert not sink.frames


def test_no_public_dns_link_local_or_ipv6_offers():
    for address in ['127.0.0.1', '8.8.8.8', '169.254.169.254', 'localhost', '192.168.01.7', '::1']:
        assert not local_address(address)
    for address in ['10.1.2.3', '172.16.1.1', '192.168.1.7']:
        assert local_address(address)
    value = CameraSession(Sink, addresses=lambda: ['8.8.8.8'])
    with pytest.raises(ValueError):
        value.start()
    assert value.server is None


def test_preview_never_initializes_virtual_camera():
    def forbidden():
        raise AssertionError('Preview must not register a webcam')
    value = CameraSession(forbidden, addresses=lambda: ['192.168.1.7'])
    try:
        qr = value.start(preview=True)
        assert qr['expires_in'] == 120 and len(qr['modules']) > 29
        assert value.cancel_invite('wrong-session') == {'cancelled': False}
        assert value.cancel_invite(qr['session']) == {'stopped': True}
    finally:
        value.stop()


def test_old_session_cleanup_cannot_stop_a_replacement(session):
    value, sink = session
    old = value.session
    value.stop()
    replacement = value.start(preview=True)
    assert replacement['session'] != old
    assert value.stop('Old connection ended.', expected_session=old) == {'stopped': False}
    assert value.status()['state'] == 'waiting'
    assert value.session == replacement['session']
