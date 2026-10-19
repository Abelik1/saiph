# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone screen over the local network: offer format, TLS session, input and app lists.

Synthetic loopback TLS clients and the in-memory Hosted relay only; no phone, adb,
scrcpy or network service is involved (docs/PHONE_SCREEN.md).
"""
import base64
import json
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage
from websockets.exceptions import ConnectionClosed, InvalidMessage, InvalidStatus
from websockets.sync.client import connect

from orion_mini import session_offer
from orion_mini.camera_session import FRAME
from orion_mini.hosted_features import FeatureError, read_apps_list, read_screen_capabilities
from orion_mini.phone_screen import PhoneScreen
from orion_mini.screen_session import ScreenSession, input_message, read_apps, read_phone_message
from test_hosted_phone import hosted  # noqa: F401  (fixture)
from lan_tls import tls13_upgrade, websocket_client_context


def jpeg(width=540, height=1170):
    image = QImage(width, height, QImage.Format.Format_RGB888)
    image.fill(0xFF2266AA)
    output = QBuffer()
    output.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(output, 'JPEG', 60)
    return bytes(output.data())


def packet(sequence=1, width=540, height=1170, magic=b'SSF1', rotation=0):
    return FRAME.pack(magic, width, height, rotation, sequence) + jpeg(width, height)


def until(predicate):
    deadline = time.monotonic() + 4
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


def client(value, secret=None, path=None):
    # TLS 1.2 only for this threaded client; see lan_tls.py. TLS 1.3 is covered below.
    context = websocket_client_context()
    port = value.server.socket.getsockname()[1]
    return connect(f'wss://127.0.0.1:{port}' + (path or f'/screen/{value.session}'), ssl=context, proxy=None,
                   legacy=True, additional_headers={'Authorization': 'Bearer ' + (secret if secret is not None else value.secret)})


@pytest.fixture
def session():
    value = ScreenSession(addresses=lambda: ['192.168.1.7'])
    yield value
    value.stop()


def offer(**changes):
    now = int(time.time())
    return {'session': 'a' * 32, 'addresses': ['192.168.1.7'], 'port': 40000, 'certificate': 'b' * 64,
            'secret': base64.urlsafe_b64encode(bytes(32)).decode().rstrip('='), 'expires': now + 60, 'launch': '',
            'stream': {'resolution': '1080p', 'fps': 20, 'quality': 'high'}, **changes}


# ------------------------------------------------------------------ offer format
def test_screen_invitations_ride_in_the_shared_session_offer():
    code = session_offer.screen_invite_code(offer(launch='com.example.synthetic'))
    assert code.startswith('orion-screen:1:')
    now = int(time.time())
    assert session_offer.screen_invite(code, now) == offer()['expires']
    payload = session_offer.build_offer('screen', code, now)
    assert set(payload) == {'type', 'version', 'id', 'service', 'expires_at', 'invite'}
    assert payload['service'] == 'screen' and payload['invite'] == code and payload['expires_at'] == offer()['expires']
    assert session_offer.read_offer(payload, now) == payload
    with pytest.raises(ValueError):
        session_offer.read_offer({**payload, 'service': 'camera'}, now)  # A camera parser refuses screen invitations.


@pytest.mark.parametrize('changes', [
    {'addresses': ['8.8.8.8']}, {'addresses': ['127.0.0.1']}, {'addresses': []}, {'port': 80},
    {'expires': int(time.time()) + 600}, {'expires': int(time.time()) - 1}, {'launch': 'not a package'},
    {'launch': 'com.example;rm'}, {'stream': {'resolution': '4k', 'fps': 20, 'quality': 'high'}},
    {'stream': {'resolution': '1080p', 'fps': 60, 'quality': 'high'}}, {'session': 'A' * 32}, {'extra': True},
])
def test_screen_invitation_refuses_public_expired_or_unknown_values(changes):
    with pytest.raises(ValueError):
        session_offer.screen_invite_code(offer(**changes))


# ------------------------------------------------------------------ input and messages
def test_input_messages_are_exact_and_bounded():
    assert input_message({'t': 'tap', 'x': 0, 'y': 10000}) == {'t': 'tap', 'x': 0, 'y': 10000}
    assert input_message({'t': 'swipe', 'x': 1, 'y': 2, 'x2': 3, 'y2': 4, 'ms': 300})['ms'] == 300
    assert input_message({'t': 'key', 'key': 'home'}) == {'t': 'key', 'key': 'home'}
    assert input_message({'t': 'text', 'text': 'Synthetic ✓'}) == {'t': 'text', 'text': 'Synthetic ✓'}
    for event in [{'t': 'tap', 'x': -1, 'y': 0}, {'t': 'tap', 'x': 1.5, 'y': 0}, {'t': 'tap', 'x': True, 'y': 0},
                  {'t': 'tap', 'x': 1, 'y': 1, 'extra': 1}, {'t': 'swipe', 'x': 1, 'y': 2, 'x2': 3, 'y2': 4, 'ms': 10},
                  {'t': 'key', 'key': 'power'}, {'t': 'text', 'text': ''}, {'t': 'text', 'text': 'x' * 257},
                  {'t': 'text', 'text': 'line\nbreak'}, {'t': 'launch', 'package': 'com.example.app'}, 'tap']:
        with pytest.raises(ValueError):
            input_message(event)


def test_phone_messages_and_app_rows_are_exact():
    assert read_phone_message('{"t":"state","input":true}') == {'t': 'state', 'input': True}
    rows = read_apps([{'package': 'com.example.b', 'name': 'Beta'}, {'package': 'com.example.a', 'name': 'alpha'}])
    assert [row['name'] for row in rows] == ['alpha', 'Beta']
    for text in ['{"t":"state","input":1}', '{"t":"apps","apps":[{"package":"x","name":"X"}]}',
                 '{"t":"apps","apps":[{"package":"com.example.a","name":"A\\u0000"}]}', '{"t":"other"}', '[]']:
        with pytest.raises(ValueError):
            read_phone_message(text)


# ------------------------------------------------------------------ TLS session
def test_real_tls_round_trip_shows_frames_and_forwards_input_only_when_allowed(session):
    started = session.start(resolution='1080p', fps=20, quality='high')
    assert len(started['modules']) > 29 and started['delivered'] is False
    assert session.status()['state'] == 'waiting'
    with pytest.raises(ValueError):
        session.input({'t': 'tap', 'x': 1, 'y': 1})  # Not live yet.
    with client(session) as phone:
        phone.send(packet())
        until(lambda: session.status()['state'] == 'live')
        frame = session.latest()
        assert frame['image'].startswith('data:image/jpeg;base64,') and (frame['width'], frame['height']) == (540, 1170)
        with pytest.raises(ValueError):
            session.input({'t': 'tap', 'x': 5000, 'y': 5000})  # The phone has not enabled input.
        phone.send('{"t":"state","input":true}')
        until(lambda: session.status()['input'])
        assert session.input({'t': 'tap', 'x': 5000, 'y': 5000}) == {'sent': True}
        assert json.loads(phone.recv(timeout=2)) == {'t': 'tap', 'x': 5000, 'y': 5000}
        session.open_app('com.example.synthetic')
        assert json.loads(phone.recv(timeout=2)) == {'t': 'launch', 'package': 'com.example.synthetic'}
        session.request_apps()
        assert json.loads(phone.recv(timeout=2)) == {'t': 'apps'}
        phone.send(json.dumps({'t': 'apps', 'apps': [{'package': 'com.example.synthetic', 'name': 'Synthetic'}]}))
        until(lambda: session.session_apps() is not None)
        assert session.session_apps()[0]['package'] == 'com.example.synthetic'
        session.stop()
        assert session.latest()['image'] is None and session.status()['state'] == 'idle'
        with pytest.raises(ConnectionClosed):
            phone.send(packet(2))
            phone.recv(timeout=2)
    with pytest.raises(ValueError):
        session.input({'t': 'tap', 'x': 1, 'y': 1})


def test_tls13_clients_upgrade_and_bad_secrets_are_refused_without_claiming(session):
    # Sequential TLS 1.3 clients, as OkHttp behaves, never stall (see lan_tls.py).
    session.start()
    port = session.server.socket.getsockname()[1]
    for _ in range(10):
        assert tls13_upgrade(port, '/screen/' + session.session, 'synthetic-wrong-secret') == ('TLSv1.3', 'HTTP/1.1 403 Forbidden')
    assert session.status()['state'] == 'waiting'
    version, status = tls13_upgrade(port, '/screen/' + session.session, session.secret)
    assert (version, status) == ('TLSv1.3', 'HTTP/1.1 101 Switching Protocols')
    until(lambda: session.status()['state'] == 'idle')  # Upgraded, then closed: the invitation is spent.


def test_wrong_secret_or_path_does_not_consume_invite_and_second_consumer_is_refused(session):
    session.start()
    secret = session.secret
    with pytest.raises(InvalidStatus):
        client(session, 'synthetic-wrong-secret')
    with pytest.raises(InvalidStatus):
        client(session, secret, path='/camera/' + session.session)
    assert session.status()['state'] == 'waiting'
    with client(session, secret) as phone:
        with pytest.raises(InvalidStatus):
            client(session, secret)
        phone.send(packet())
        until(lambda: session.status()['state'] == 'live')
        phone.send(packet())  # Replayed sequence ends the session.
        until(lambda: session.status()['state'] == 'idle')


@pytest.mark.parametrize('bad', [
    {'magic': b'SCF1'}, {'rotation': 90}, {'width': 2000, 'height': 1000}, {'width': 1080, 'height': 2340},
], ids=['camera-magic', 'rotated', 'too-wide', 'too-tall'])
def test_camera_frames_rotations_or_oversized_screens_end_the_session(session, bad):
    session.start(resolution='1080p')
    with client(session) as phone:
        phone.send(packet(**bad))
        until(lambda: session.status()['state'] == 'idle')
    assert session.latest()['image'] is None


def test_720p_profile_bounds_the_longest_side(session):
    session.start(resolution='720p', fps=15, quality='standard')
    with client(session) as phone:
        phone.send(packet(width=886, height=1920))
        until(lambda: session.status()['state'] == 'idle')


def test_expired_invite_and_public_addresses_are_refused(session):
    session.start()
    session.deadline = session.clock() - 1
    # Refused with 403, or closed first by the expiry monitor: either way nothing connects.
    with pytest.raises((InvalidStatus, InvalidMessage)):
        client(session)
    value = ScreenSession(addresses=lambda: ['8.8.8.8'])
    with pytest.raises(ValueError):
        value.start()
    assert value.server is None


def test_idle_phone_times_out(monkeypatch, session):
    session.start()
    with client(session) as phone:
        phone.send(packet())
        until(lambda: session.status()['state'] == 'live')
        session.last_message -= 30
        until(lambda: session.status()['state'] == 'idle')


def test_cancel_invite_and_delivery_failure_falls_back_to_qr(session):
    def failing(code):
        raise ValueError('offline')
    started = session.start(deliver=failing)
    assert started['delivered'] is False and 'Scan' in session.status()['message']
    assert session.cancel_invite('0' * 32) == {'cancelled': False}
    assert session.cancel_invite(started['session']) == {'stopped': True}


# ------------------------------------------------------------------ Cloud offer and app list
def advertise(h, names=('screen', 'apps')):
    h.send({'type': 'phone.capabilities', 'capabilities': ['files']})
    h.send({'type': 'screen.capabilities', 'capabilities': list(names)})
    h.received()


def test_screen_capabilities_are_separate_and_exact():
    assert read_screen_capabilities({'type': 'screen.capabilities', 'capabilities': ['screen', 'apps']}) == ['screen', 'apps']
    for payload in [{'type': 'screen.capabilities', 'capabilities': ['sms']},
                    {'type': 'screen.capabilities', 'capabilities': ['screen', 'screen']},
                    {'type': 'phone.capabilities', 'capabilities': ['screen']}]:
        with pytest.raises(FeatureError):
            read_screen_capabilities(payload)
    # Older desktops reject unknown names in phone.capabilities; phones never put them there.
    from orion_mini.hosted_features import read_phone_data
    with pytest.raises(FeatureError):
        read_phone_data({'type': 'phone.capabilities', 'capabilities': ['screen']})


def test_cloud_delivers_the_offer_to_an_advertising_phone_without_a_qr_scan(hosted):
    h = hosted
    workspace = SimpleNamespace(_active_hosted=lambda: h.controller)
    screen = PhoneScreen(workspace, session=ScreenSession(addresses=lambda: ['192.168.1.7']))
    try:
        started = screen.start(h.device)
        assert started['delivered'] is False  # Not advertised yet: QR fallback.
        screen.stop()
        advertise(h)
        [phone] = h.controller.phones()
        assert phone['screen'] == ['screen', 'apps'] and phone['capabilities'] == ['files']
        started = screen.start(h.device)
        assert started['delivered'] is True and screen.status()['delivered']
        h.controller.step()
        [payload] = h.received()
        received = session_offer.read_offer(payload)
        assert received['service'] == 'screen'
        invite = received['invite'].split(':', 2)[2]
        decoded = json.loads(base64.urlsafe_b64decode(invite + '=' * (-len(invite) % 4)))
        assert decoded['session'] == started['session'] and decoded['secret'] == screen.session.secret
    finally:
        screen.stop()


def test_the_phone_is_told_when_a_delivered_offer_is_finished(hosted):
    """session.close clears the phone's notification and pop-up once the offer is cancelled."""
    h = hosted
    advertise(h)
    screen = PhoneScreen(SimpleNamespace(_active_hosted=lambda: h.controller), session=ScreenSession(addresses=lambda: ['192.168.1.7']))
    try:
        started = screen.start(h.device)
        assert started['delivered'] is True
        h.controller.step()
        [offer] = h.received()
        screen.session.cancel_invite(started['session'])

        def closed():
            h.controller.step()
            closed.rows = closed.rows + h.received()
            return closed.rows
        closed.rows = []
        until(closed)
        assert closed.rows == [{'type': 'session.close', 'version': 1, 'id': offer['id']}]
        assert session_offer.read_close(closed.rows[0]) == offer['id']
        for bad in [{'type': 'session.close', 'version': 1, 'id': 'x'}, {'type': 'session.close', 'version': 2, 'id': offer['id']},
                    {'type': 'session.close', 'version': 1, 'id': offer['id'], 'extra': 1}]:
            with pytest.raises(ValueError):
                session_offer.read_close(bad)
    finally:
        screen.stop()


def test_app_list_pages_are_accepted_only_after_this_computers_request(hosted):
    h = hosted
    advertise(h)
    rows = [{'package': 'com.example.app%d' % i, 'name': 'App %d' % i} for i in range(3)]
    h.send({'type': 'apps.list', 'page': 0, 'pages': 1, 'apps': rows})  # Unsolicited: ignored.
    assert h.controller.phone_apps(h.device) is None
    workspace = SimpleNamespace(_active_hosted=lambda: h.controller)
    screen = PhoneScreen(workspace, session=ScreenSession(addresses=lambda: ['192.168.1.7']))
    assert screen.apps(h.device) == {'pending': True, 'source': 'cloud', 'pinned': [], 'usage': {}, 'recent': {}, 'icons': True}
    h.controller.step()
    assert h.received() == [{'type': 'apps.request'}]
    h.send({'type': 'apps.list', 'page': 1, 'pages': 2, 'apps': rows[2:]})
    assert screen.apps(h.device)['pending']
    h.send({'type': 'apps.list', 'page': 0, 'pages': 2, 'apps': rows[:2]})
    result = screen.apps(h.device)
    assert result['source'] == 'cloud' and [app['package'] for app in result['apps']] == [r['package'] for r in rows]


def test_app_list_page_shape_is_bounded():
    good = {'type': 'apps.list', 'page': 0, 'pages': 1, 'apps': [{'package': 'com.example.app', 'name': 'App'}]}
    assert read_apps_list(good)[2][0]['name'] == 'App'
    for changes in [{'page': 1}, {'pages': 11}, {'apps': [{'package': 'com.example.app', 'name': ''}]},
                    {'apps': [{'package': 'com.example.app', 'name': 'x' * 81}]}, {'extra': 1}]:
        with pytest.raises(FeatureError):
            read_apps_list({**good, **changes})


def test_without_cloud_or_session_the_list_explains_what_is_needed():
    screen = PhoneScreen(SimpleNamespace(), session=ScreenSession(addresses=lambda: ['192.168.1.7']))
    assert screen.apps('dev_synthetic')['unavailable']
    with pytest.raises(ValueError):
        screen.open_app('dev_synthetic', 'not a package')


# ------------------------------------------------------------------ no scrcpy in normal use
def test_a_waiting_session_shares_its_code_with_the_page_until_it_ends(session):
    started = session.start()
    invite = session.current_invite()
    assert invite['session'] == started['session'] and invite['modules'] == started['modules']
    assert 'secret' not in json.dumps(invite) and session.secret not in json.dumps(invite)
    session.stop()
    assert session.current_invite() == {}


def test_scrcpy_routes_need_the_usb_debugging_opt_in(tmp_path, qtbot):
    from PySide6.QtCore import QObject
    from orion_mini.desktop_bridge import DesktopBridge
    from orion_mini.link_service import LinkWorkspace
    from orion_mini.phone_settings import preferences, validate

    class Window(QObject):
        def __init__(self):
            super().__init__()
            self.workspace = LinkWorkspace(tmp_path)

        def pump_jobs(self):
            pass

    window = Window()
    bridge = DesktopBridge(window)
    answers = []
    bridge.response.connect(lambda raw: answers.append(json.loads(raw)))
    assert preferences(window.workspace.settings)['usb_debugging'] is False
    for method in ('phone.mirror', 'phone.apps.legacy', 'phone.app.open.legacy'):
        bridge.request(method, method, json.dumps({'device_id': 'phone', 'package': 'com.example.app'}
                                                  if method == 'phone.app.open.legacy' else {'device_id': 'phone'}))
    assert [a['ok'] for a in answers] == [False, False, False]
    assert all('scrcpy' not in a['error'].lower() or 'Settings → Advanced' in a['error'] for a in answers)
    assert not any('Install' in a['error'] for a in answers)
    assert validate({'usb_debugging': True})['usb_debugging'] is True
    with pytest.raises(ValueError):
        validate({'usb_debugging': 'yes'})
    bridge.request('invite', 'screen.invite', '{}')
    assert answers[-1] == {'id': 'invite', 'ok': True, 'result': {}}
