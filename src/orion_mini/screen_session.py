# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone screen on this computer: one-use, pinned TLS on a private local network.

The same design as the phone camera (`camera_session.py`): an ephemeral P-256
certificate, a 256-bit bearer secret and a one-connection, two-minute invitation
for literal private IPv4 addresses. The phone captures its screen with Android
MediaProjection after owner verification and Android's own consent, and sends
bounded JPEG frames. This computer may send back pointer, key, text, launch and
app-list requests over the same socket, but only while that one session is live;
the phone injects them only if its owner turned on Saiph's accessibility input.

Nothing is recorded: only the latest frame is kept in memory. No audio exists on
this channel. Frames and invitations are excluded from status and diagnostics.

The native phone screen window (`phone_screen_window.py`) subscribes to raw frames
and state changes; the page's base64 preview is built only when the page asks.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hmac
import json
import secrets
import threading
import time

from websockets.sync.server import serve

from .camera_session import FRAME, lan_addresses, local_address, read_frame, tls_context
from . import session_offer
from .lan_relay import listen

MAGIC = b'SSF1'
MAX_FRAME = 1_500_000
# Longest side of the phone's (portrait or landscape) screen for each profile.
BOUNDS = {'720p': (1280, 1280 * 720), '1080p': (1920, 1920 * 1080)}
INVITE_SECONDS = session_offer.MAX_LIFETIME
SESSION_SECONDS = 3600
IDLE_SECONDS = 8  # The phone repeats its last frame at least every two seconds.
MAX_PREVIEW = 750_000  # JPEG bytes handed to the page per frame (1 MB as base64).
PREVIEW_PREFIX = 'data:image/jpeg;base64,'
MAX_TEXT_MESSAGE = 65_536
SCALE = 10_000  # Pointer positions are integers in [0, SCALE] of the shown frame.
KEYS = ('back', 'home', 'recents', 'backspace', 'enter')
MAX_TYPED = 256
INPUT_PER_SECOND = 60


def input_message(event) -> dict:
    """Exact pointer/key/text shape forwarded to the phone; anything else is refused."""
    def point(value):
        if type(value) is not int or not 0 <= value <= SCALE:
            raise ValueError('Unsupported phone screen input.')
        return value
    if type(event) is not dict or type(event.get('t')) is not str:
        raise ValueError('Unsupported phone screen input.')
    kind = event['t']
    if kind in ('tap', 'long') and set(event) == {'t', 'x', 'y'}:
        return {'t': kind, 'x': point(event['x']), 'y': point(event['y'])}
    if kind == 'swipe' and set(event) == {'t', 'x', 'y', 'x2', 'y2', 'ms'}:
        if type(event['ms']) is not int or not 50 <= event['ms'] <= 3000:
            raise ValueError('Unsupported phone screen input.')
        return {'t': kind, 'x': point(event['x']), 'y': point(event['y']), 'x2': point(event['x2']),
                'y2': point(event['y2']), 'ms': event['ms']}
    if kind == 'key' and set(event) == {'t', 'key'} and event['key'] in KEYS:
        return {'t': kind, 'key': event['key']}
    if kind == 'text' and set(event) == {'t', 'text'} and type(event['text']) is str and 1 <= len(event['text']) <= MAX_TYPED:
        text = event['text']
        if any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in text):
            raise ValueError('Unsupported phone screen input.')
        return {'t': kind, 'text': text}
    raise ValueError('Unsupported phone screen input.')


def read_apps(rows) -> list[dict]:
    """A phone's launchable apps: package names and short display names only."""
    if type(rows) is not list or len(rows) > 1000:
        raise ValueError('Invalid phone app list.')
    apps = {}
    for row in rows:
        if (type(row) is not dict or set(row) != {'package', 'name'} or not session_offer.valid_package(row['package'])
                or type(row['name']) is not str or not 1 <= len(row['name']) <= 80
                or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in row['name'])):
            raise ValueError('Invalid phone app list.')
        apps[row['package']] = {'package': row['package'], 'name': row['name'], 'system': False}
    return sorted(apps.values(), key=lambda app: app['name'].lower())


def read_phone_message(text) -> dict:
    """Exact phone -> computer control messages on the screen socket."""
    if type(text) is not str or len(text) > MAX_TEXT_MESSAGE:
        raise ValueError('Invalid phone screen message.')
    value = json.loads(text)
    if type(value) is not dict or type(value.get('t')) is not str:
        raise ValueError('Invalid phone screen message.')
    if value['t'] == 'state' and set(value) == {'t', 'input'} and type(value['input']) is bool:
        return value
    if value['t'] == 'apps' and set(value) == {'t', 'apps'}:
        return {'t': 'apps', 'apps': read_apps(value['apps'])}
    if value['t'] == 'launched' and set(value) == {'t', 'package', 'ok'} and session_offer.valid_package(value['package']) \
            and type(value['ok']) is bool:
        return value
    raise ValueError('Invalid phone screen message.')


class ScreenSession:
    def __init__(self, *, addresses=lan_addresses, clock=time.monotonic):
        self.addresses, self.clock = addresses, clock
        self.lock = threading.RLock()
        self.server = self.connection = None
        self.state = 'idle'
        self.message = ''
        self.frame = None
        self.serial = 0
        self.session = ''
        self.secret = ''
        self.deadline = self.last_message = 0
        self.resolution, self.fps, self.quality = '1080p', 20, 'high'
        self.launch = ''
        self.device_id = None
        self.delivered = False
        self.input_enabled = False
        self.dimensions = None
        self.apps = None
        self.notice = ''
        self.samples = []
        self._sent = []
        # Called with 'frame' or 'state' from session threads, outside the lock.
        self.notify = None
        self._frame_listeners = []
        self._state_listeners = []
        self._invite = None  # The waiting session's code for the page; never the invitation text itself.

    def _announce(self, kind):
        notify = self.notify
        if notify is not None:
            try:
                notify(kind)
            except Exception:
                pass  # The dashboard's next refresh still shows the session.

    def subscribe(self, *, frame=None, state=None):
        """Call `frame(jpeg, width, height, sequence)` for each accepted frame (on the
        receiving thread) and `state(status)` after each state change. Returns an unsubscribe."""
        with self.lock:
            if frame is not None:
                self._frame_listeners.append(frame)
            if state is not None:
                self._state_listeners.append(state)

        def unsubscribe():
            with self.lock:
                for rows, item in ((self._frame_listeners, frame), (self._state_listeners, state)):
                    if item in rows:
                        rows.remove(item)
        return unsubscribe

    def _changed(self):
        """Tell state listeners; never under the lock, and never let one break the session."""
        with self.lock:
            listeners, status = list(self._state_listeners), self.status()
        for listener in listeners:
            try:
                listener(status)
            except Exception:
                pass
        self._announce('state')  # The page's frame feed hears state changes too.

    def start(self, *, resolution='1080p', fps=20, quality='high', launch='', device_id=None, deliver=None):
        if (type(resolution) is not str or resolution not in BOUNDS or type(fps) is not int or fps not in (15, 20, 30)
                or type(quality) is not str or quality not in ('standard', 'high')):
            raise ValueError('Choose a supported screen resolution, frame rate and image quality.')
        if launch != '' and not session_offer.valid_package(launch):
            raise ValueError('Choose an app from the list.')
        with self.lock:
            if self.server is not None:
                raise ValueError('Stop the current phone screen session first.')
            addresses = self.addresses()
            if not addresses or any(not local_address(x) for x in addresses):
                raise ValueError('Connect this computer and your phone to the same private Wi-Fi or LAN.')
            self.resolution, self.fps, self.quality, self.launch = resolution, fps, quality, launch
            self.device_id, self.delivered, self.input_enabled = device_id, False, False
            self.dimensions, self.frame, self.samples, self._sent, self.notice = None, None, [], [], ''
            try:
                tls, fingerprint = tls_context(addresses, 'Saiph Phone Screen')
                self.secret = secrets.token_urlsafe(32)
                self.session = secrets.token_hex(16)
                self.deadline = self.clock() + INVITE_SECONDS
                self.state, self.message = 'waiting', 'Waiting for your phone.'
                made = []

                def bind(host):
                    made.append(serve(self._receive, host, 0, ssl=tls, max_size=MAX_FRAME, max_queue=1,
                                      open_timeout=5, close_timeout=1, compression=None, process_request=self._authorize))
                    return made[-1].socket.getsockname()[1]
                # Installed on Windows: loopback plus the fixed-path relay the firewall knows (lan_relay.py).
                port, self.relay = listen(bind, lambda: made.pop().socket.close())
                self.server = made[-1]
                expires = int(time.time()) + INVITE_SECONDS
                offer = {'session': self.session, 'addresses': addresses, 'port': port, 'certificate': fingerprint,
                         'secret': self.secret, 'expires': expires, 'launch': launch,
                         'stream': {'resolution': resolution, 'fps': fps, 'quality': quality}}
                code = session_offer.screen_invite_code(offer)
                import qrcode
                qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
                qr.add_data(code); qr.make(fit=True)
                modules = [''.join('1' if cell else '0' for cell in row) for row in qr.get_matrix()]
                server, epoch = self.server, self.session
                threading.Thread(target=server.serve_forever, name='orion-screen-tls', daemon=True).start()
                threading.Thread(target=self._monitor, args=(epoch,), name='orion-screen-expiry', daemon=True).start()
            except Exception:
                self.stop()
                raise
        self._changed()
        # Delivery is a network call; never hold the session lock across it.
        delivered = False
        if deliver is not None:
            try:
                delivered = bool(deliver(code))
            except (ValueError, OSError):
                delivered = False
        with self.lock:
            if self.session == epoch and self.server is not None:
                self.delivered = delivered
                self.message = ('On your phone, tap the Saiph notification to show your screen.' if delivered
                                else 'On your phone: Saiph → Show phone screen → Scan computer\'s code.')
        self._changed()
        result = {'session': epoch, 'modules': modules, 'delivered': delivered, 'expires_in': INVITE_SECONDS,
                  'expires_at': datetime.fromtimestamp(expires, timezone.utc).isoformat()}
        with self.lock:
            if self.session == epoch and self.server is not None:
                self._invite = dict(result)
        return result

    def current_invite(self):
        """The waiting session's QR (the same answer `start` gave), for a page that did not start it."""
        with self.lock:
            if self._invite is None or self.state != 'waiting' or self._invite['session'] != self.session:
                return {}
            return {**self._invite, 'expires_in': max(0, int(self.deadline - self.clock()))}

    def _authorize(self, connection, request):
        with self.lock:
            if (self.state != 'waiting' or self.clock() >= self.deadline
                    or request.path != '/screen/' + self.session
                    or len(request.headers.get_all('Authorization')) != 1
                    or not hmac.compare_digest(request.headers['Authorization'].encode('utf-8'),
                                               ('Bearer ' + self.secret).encode('ascii'))):
                return connection.respond(403, 'Screen invitation is unavailable.\n')
            # Claim before upgrade: simultaneous clients cannot both acquire it.
            self.state, self.connection, self.secret = 'connecting', connection, ''
            self.last_message = self.clock()
        self._changed()
        return None

    def _current(self, connection, epoch):
        return connection is self.connection and self.server is not None and self.session == epoch

    def _receive(self, connection):
        sequence = 0
        epoch = None
        try:
            with self.lock:
                if connection is not self.connection or self.server is None:
                    return
                epoch = self.session
                self.last_message = self.clock()
                self.deadline = self.last_message + SESSION_SECONDS
                bound, pixels = BOUNDS[self.resolution]
            for value in connection:
                if type(value) is str:
                    message = read_phone_message(value)
                    with self.lock:
                        if not self._current(connection, epoch):
                            break
                        self.last_message = self.clock()
                        changed = message['t'] == 'state' and self.input_enabled != message['input']
                        if message['t'] == 'state':
                            self.input_enabled = message['input']
                        elif message['t'] == 'apps':
                            self.apps = {'apps': message['apps'], 'at': self.clock()}
                        else:
                            self.notice = '' if message['ok'] else ('Android kept the app closed. Tap the Saiph notification on your phone to open it, '
                                                                     'or turn on Control from computer there.')
                            changed = True
                    if changed:
                        self._changed()
                    continue
                image, _, sequence = read_frame(value, sequence, max_pixels=pixels, max_dimension=bound,
                                                magic_value=MAGIC, rotations=(0,))
                width, height = FRAME.unpack_from(value)[1:3]
                if len(image) > MAX_PREVIEW:
                    raise ValueError('Phone screen frame is too large.')
                image = bytes(image)
                with self.lock:
                    # Stop/replace may run meanwhile; never publish into another session.
                    if not self._current(connection, epoch):
                        break
                    went_live = self.state != 'live'
                    # Kept as the phone's JPEG bytes; the page loads them through the
                    # frame feed (frame_feed.py) and a separate window through listeners.
                    self.frame = image
                    self.serial += 1
                    serial = self.serial
                    self.last_message, self.state, self.message = self.clock(), 'live', ''
                    self.samples = [s for s in self.samples if s >= self.last_message - 3][-119:] + [self.last_message]
                    self.dimensions = {'width': width, 'height': height}
                    listeners = list(self._frame_listeners)
                for listener in listeners:
                    try:
                        listener(image, width, height, serial)
                    except Exception:
                        pass
                if went_live:
                    self._changed()
                self._announce('frame')
        except Exception:
            # Deliberately omit URLs, headers, credentials and image content.
            pass
        finally:
            with self.lock:
                current = connection is self.connection
            if current:
                self.stop('Phone screen disconnected. Start again when you are ready.', expected_session=epoch)

    def _monitor(self, epoch):
        while True:
            time.sleep(0.5)
            with self.lock:
                if self.server is None or self.session != epoch:
                    return
                expired = self.clock() >= self.deadline
                stalled = self.state in ('connecting', 'live') and self.clock() - self.last_message > IDLE_SECONDS
            if expired or stalled:
                self.stop('Phone screen session ended. Start again when you are ready.', expected_session=epoch)
                return

    def send(self, message) -> dict:
        """Forward one validated request to the live phone; refused at any other time."""
        with self.lock:
            connection = self.connection
            if self.state != 'live' or connection is None:
                raise ValueError('Start the phone screen first.')
            if message['t'] in ('tap', 'long', 'swipe', 'key', 'text') and not self.input_enabled:
                raise ValueError('Control from this computer is off on your phone. Turn on Saiph input in the phone\'s Phone screen page.')
            now = self.clock()
            self._sent = [s for s in self._sent if s > now - 1]
            if len(self._sent) >= INPUT_PER_SECOND:
                return {'sent': False}
            self._sent.append(now)
        try:
            connection.send(json.dumps(message, separators=(',', ':')))
        except Exception:
            raise ValueError('Phone screen disconnected.') from None
        return {'sent': True}

    def input(self, event) -> dict:
        return self.send(input_message(event))

    def open_app(self, package) -> dict:
        if not session_offer.valid_package(package):
            raise ValueError('Choose an app from the list.')
        with self.lock:
            self.notice = ''
        return self.send({'t': 'launch', 'package': package})

    def request_apps(self) -> dict:
        return self.send({'t': 'apps'})

    def status(self):
        with self.lock:
            return {'state': self.state, 'running': self.state == 'live',
                    'waiting': self.state in ('waiting', 'connecting'), 'message': self.notice or self.message,
                    'resolution': self.resolution, 'fps': self.fps, 'quality': self.quality,
                    'input': self.state == 'live' and self.input_enabled, 'delivered': self.delivered,
                    'device_id': self.device_id if self.state != 'idle' else None,
                    'launch': self.launch if self.state != 'idle' else ''}

    def describe(self):
        """The newest frame's metadata, without its picture."""
        with self.lock:
            samples = self.samples
            measured = ((len(samples) - 1) / (samples[-1] - samples[0])
                        if len(samples) > 1 and samples[-1] > samples[0] and self.clock() - samples[-1] < 1 else 0)
            return {'sequence': self.serial, 'fps': round(measured, 1), **(self.dimensions or {})}

    def jpeg(self):
        """The newest picture while live, for the dashboard's frame feed."""
        with self.lock:
            return self.frame if self.state == 'live' else None

    def latest(self):
        """Polling form of the picture, for dashboards without the frame feed."""
        with self.lock:
            image, info = self.frame, self.describe()
        return {'image': None if image is None else 'data:image/jpeg;base64,' + base64.b64encode(image).decode(), **info}

    def measured_fps(self):
        with self.lock:
            samples = self.samples
            if len(samples) > 1 and samples[-1] > samples[0] and self.clock() - samples[-1] < 1:
                return round((len(samples) - 1) / (samples[-1] - samples[0]), 1)
            return 0

    def session_apps(self, max_age=300):
        with self.lock:
            if self.apps is None or self.clock() - self.apps['at'] > max_age:
                return None
            return list(self.apps['apps'])

    def cancel_invite(self, session):
        with self.lock:
            if self.server is not None and self.session == session and self.state in ('waiting', 'connecting'):
                return self.stop()
        return {'cancelled': False}

    def stop(self, message='', *, expected_session=None):
        with self.lock:
            if expected_session is not None and self.session != expected_session:
                return {'stopped': False}
            server, connection = self.server, self.connection
            relay, self.relay = getattr(self, 'relay', None), None
            # Only a real change is announced; stopping an idle session is a no-op.
            ended = self.state != 'idle'
            self.server = self.connection = None
            self.state, self.message, self.frame, self.secret, self._invite = 'idle', message, None, '', None
            self.samples, self.dimensions, self.input_enabled, self._sent = [], None, False, []
        if server or connection:
            self._changed()  # Before shutdown, which may wait while called from the handler thread.
        if connection:
            connection.close()
        if server:
            server.shutdown()
        if relay:
            relay.close()
        return {'stopped': True}
