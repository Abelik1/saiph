# SPDX-License-Identifier: AGPL-3.0-or-later
import time
import base64
import json
import threading

import pytest
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage
from websockets.sync.client import connect
from websockets.exceptions import InvalidStatus, ConnectionClosed

from orion_mini.camera_session import CameraSession, FRAME, local_address, read_frame
from lan_tls import tls13_upgrade, websocket_client_context


class Sink:
    def __init__(self):
        self.frames = []
        self.writes = 0
        self.closed = False

    def write(self, value, width=1280, height=720):
        self.frames[:] = [value]
        self.writes += 1
        self.dimensions = (width, height)

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
    # TLS 1.2 only for this threaded client; see lan_tls.py. TLS 1.3 is covered below.
    context = websocket_client_context()
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
        assert value.latest()['rotation'] == 90
        assert value.cancel_invite(value.session) == {'cancelled': False}
        value.stop()
        assert sink.closed and value.latest()['image'] is None
        with pytest.raises(ConnectionClosed):
            phone.send(packet(2))


def test_tls13_clients_upgrade_and_bad_secrets_are_refused_without_claiming(session):
    # Sequential TLS 1.3 clients, as OkHttp behaves, never stall (see lan_tls.py).
    value, sink = session
    port = value.server.socket.getsockname()[1]
    for _ in range(10):
        assert tls13_upgrade(port, '/camera/' + value.session, 'synthetic-wrong-secret') == ('TLSv1.3', 'HTTP/1.1 403 Forbidden')
    assert value.status()['state'] == 'waiting'
    assert tls13_upgrade(port, '/camera/' + value.session, value.secret) == ('TLSv1.3', 'HTTP/1.1 101 Switching Protocols')
    until(lambda: value.status()['state'] == 'idle')
    assert not sink.frames


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


@pytest.mark.parametrize('resolution,dimensions', [('720p', (1280, 720)), ('1080p', (1920, 1080))])
def test_profile_is_encoded_and_delivers_real_selected_pixel_size(resolution, dimensions, monkeypatch):
    import qrcode
    codes = []
    add = qrcode.QRCode.add_data
    monkeypatch.setattr(qrcode.QRCode, 'add_data', lambda self, code: (codes.append(code), add(self, code))[-1])
    sink = Sink()
    value = CameraSession(lambda: sink, addresses=lambda: ['192.168.1.7'])
    try:
        value.start(resolution=resolution, fps=20, quality='high')
        prefix = 'orion-camera:2:'
        assert codes[0].startswith(prefix)
        encoded = codes[0][len(prefix):]
        offer = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
        assert offer['stream'] == {'resolution': resolution, 'fps': 20, 'quality': 'high'}
        with client(value) as phone:
            phone.send(packet(width=dimensions[0], height=dimensions[1]))
            until(lambda: value.status()['running'])
            assert sink.dimensions == dimensions
            assert len(sink.frames[0]) == dimensions[0] * dimensions[1] * 4
            frame = value.latest()
            assert (frame['source_width'], frame['source_height']) == dimensions
            assert frame['output_width'] == dimensions[0]
    finally:
        value.stop()


@pytest.mark.parametrize('options', [{'fps': True}, {'fps': 120}, {'fps': '20'}, {'resolution': '4k'},
                                    {'quality': 'lossless'}, {'resolution': ''}, {'quality': ''}])
def test_invalid_profile_rejected_before_any_listener_or_sink(options):
    value = CameraSession(lambda: pytest.fail('must not register'), addresses=lambda: ['192.168.1.7'])
    with pytest.raises(ValueError):
        value.start(**options)
    assert value.server is None and value.sink is None


def test_slow_decode_does_not_block_preview_reads_and_cannot_publish_after_stop(monkeypatch):
    value = CameraSession(Sink, addresses=lambda: ['192.168.1.7'])
    entered, release = threading.Event(), threading.Event()
    real_decode = QImage.fromData
    def slow_decode(*args):
        entered.set()
        assert release.wait(3)
        return real_decode(*args)
    image = packet()
    monkeypatch.setattr(QImage, 'fromData', slow_decode)
    value.start(preview=True, resolution='1080p', fps=20, quality='high')
    try:
        with client(value) as phone:
            phone.send(image)
            assert entered.wait(2)
            started = time.monotonic()
            assert value.latest()['image'] is None
            assert value.status()['state'] == 'connecting'
            assert time.monotonic() - started < 0.2
            # Invalidate under the same public stop path before decode finishes.
            done = threading.Event()
            stopper = threading.Thread(target=lambda: (value.stop(), done.set()))
            stopper.start()
            until(lambda: value.status()['state'] == 'idle')
            replacement = value.start(preview=True)
            release.set()
            assert done.wait(3)
            stopper.join(3)
            assert value.status()['state'] == 'waiting'
            assert value.latest()['image'] is None
            assert value.session == replacement['session']
    finally:
        release.set()
        value.stop()


def test_preview_is_the_phones_validated_jpeg_untouched_and_every_frame_is_announced(session):
    value, sink = session
    announced = []
    value.notify = announced.append
    image = jpeg()
    with client(value) as phone:
        phone.send(packet(1, rotation=90, image=image))
        until(lambda: value.status()['state'] == 'live')
        phone.send(packet(2, rotation=90, image=image))
        until(lambda: sink.writes == 2 and value.describe()['sequence'] == 2)
        # Never scaled, re-encoded or base64-wrapped for the dashboard; it rotates it.
        assert value.jpeg() == image
        assert value.describe()['rotation'] == 90
        assert value.latest()['image'] == 'data:image/jpeg;base64,' + base64.b64encode(image).decode()
        # The webcam still receives upright pixels at its fixed size.
        assert sink.dimensions == (1280, 720) and len(sink.frames[0]) == 1280 * 720 * 4
        until(lambda: announced.count('frame') == 2)
        assert announced[:2] == ['state', 'state']  # Claimed, then live.
        value.stop()
    assert value.jpeg() is None and announced[-1] == 'state'


def test_stopping_an_idle_session_announces_nothing():
    # Camera.status() stops idle sessions while the dashboard builds its state;
    # announcing that would make every snapshot request the next one.
    from orion_mini.screen_session import ScreenSession
    for value in (CameraSession(lambda: None, addresses=lambda: ['192.168.1.7']), ScreenSession(addresses=lambda: ['192.168.1.7'])):
        announced = []
        value.notify = announced.append
        value.stop()
        value.stop()
        assert announced == []


def test_undecodable_preview_ends_the_session_before_the_dashboard_sees_it(session):
    value, sink = session
    with client(value) as phone:
        broken = b'\xff\xd8\xff\xc0\x00\x11\x08\x02\xd0\x05\x00' + b'\x00' * 64 + b'\xff\xd9'
        try:
            phone.send(packet(1, image=broken))
        except ConnectionClosed:
            pass
        until(lambda: value.status()['state'] == 'idle')
    assert value.jpeg() is None and value.latest()['image'] is None


def test_frame_feed_serves_only_dashboard_gets_for_known_sources():
    from orion_mini.frame_feed import allowed
    assert allowed(b'GET', 'camera', '/12', '')
    assert allowed(b'GET', 'screen', '/0', 'file://')
    assert allowed(b'GET', 'camera', '/3', 'null')
    assert not allowed(b'POST', 'camera', '/12', '')
    assert not allowed(b'GET', 'microphone', '/12', '')
    assert not allowed(b'GET', 'camera', '/12/../x', '')
    assert not allowed(b'GET', 'camera', '/latest', '')
    assert not allowed(b'GET', 'camera', '/12', 'https://example.com')


def test_invitation_for_a_sealed_offer_is_the_qr_content_until_claimed(session):
    from orion_mini.session_offer import build_offer
    value, sink = session
    invite = value.invitation(value.session)
    assert invite.startswith('orion-camera:1:')
    assert build_offer('camera', invite)['invite'] == invite  # Same strict checks the phone applies.
    with pytest.raises(ValueError):
        value.invitation('0' * 32)
    with client(value) as phone:
        phone.send(packet())
        until(lambda: value.status()['state'] == 'live')
        with pytest.raises(ValueError):
            value.invitation(value.session)  # Claimed: the bearer secret is gone.
    value.stop()
    with pytest.raises(ValueError):
        value.invitation(value.session)
