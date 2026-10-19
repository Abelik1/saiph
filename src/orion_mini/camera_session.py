# SPDX-License-Identifier: AGPL-3.0-or-later
"""Foreground phone camera: one-use, pinned TLS on a private local network.

This channel is independent of account tokens and never changes device pairing.
The QR is an ephemeral capability, shown only after a local desktop action. The
phone additionally verifies its owner and asks for Android camera access. No
audio, background capture, persistent video, public listener URLs or remote relay.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import ssl
import struct
import tempfile
import threading
import time
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from websockets.sync.server import serve

from .lan_relay import listen

PREFIX = 'orion-camera:1:'
PROFILE_PREFIX = 'orion-camera:2:'
FRAME = struct.Struct('!4sHHHQ')
MAX_FRAME = 1_500_000
MAX_PIXELS = 1920 * 1080
RESOLUTIONS = {'720p': (1280, 720), '1080p': (1920, 1080)}
JPEG_QUALITY = {'standard': 75, 'high': 90}
INVITE_SECONDS = 120
SESSION_SECONDS = 1800


def local_address(value):
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        return False
    return any(address in network for network in (
        ipaddress.ip_network('10.0.0.0/8'), ipaddress.ip_network('172.16.0.0/12'),
        ipaddress.ip_network('192.168.0.0/16'),
    )) and value not in {'10.0.0.0', '172.16.0.0', '192.168.0.0'}


def lan_addresses():
    from PySide6.QtNetwork import QNetworkAddressEntry, QNetworkInterface
    values = []
    for interface in QNetworkInterface.allInterfaces():
        flags = interface.flags()
        if not flags & QNetworkInterface.InterfaceFlag.IsUp or flags & QNetworkInterface.InterfaceFlag.IsLoopBack:
            continue
        for entry in interface.addressEntries():
            value = entry.ip().toString()
            if local_address(value) and value not in values:
                values.append(value)
    return values[:8]


def tls_context(addresses, name='Saiph Camera', hours=1):
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=hours))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(x)) for x in addresses]), False)
            .sign(key, hashes.SHA256()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    # load_cert_chain has a path-only API. Files live only in a private random
    # temporary directory and are removed immediately after OpenSSL loads them.
    with tempfile.TemporaryDirectory(prefix='orion-camera-tls-') as directory:
        root = Path(directory)
        private = root / 'key.pem'
        private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption()))
        private.chmod(0o600)
        public = root / 'cert.pem'
        public.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        context.load_cert_chain(public, private)
    return context, cert.fingerprint(hashes.SHA256()).hex()


def read_frame(value, previous, *, max_pixels=MAX_PIXELS, max_dimension=1920, magic_value=b'SCF1', rotations=(0, 90, 180, 270)):
    if type(value) is not bytes or not FRAME.size + 4 <= len(value) <= MAX_FRAME:
        raise ValueError('Invalid camera frame.')
    magic, width, height, rotation, sequence = FRAME.unpack_from(value)
    if (magic != magic_value or not 1 <= width <= max_dimension or not 1 <= height <= max_dimension
            or width * height > max_pixels or rotation not in rotations
            or sequence <= previous):
        raise ValueError('Invalid camera frame.')
    image = value[FRAME.size:]
    if not image.startswith(b'\xff\xd8') or not image.endswith(b'\xff\xd9'):
        raise ValueError('Invalid camera image.')
    # Inspect bounded JPEG dimensions before asking Qt to allocate pixels.
    offset = 2
    while offset + 4 <= len(image):
        if image[offset] != 255:
            break
        marker = image[offset + 1]
        length = int.from_bytes(image[offset + 2:offset + 4], 'big')
        if length < 2 or offset + 2 + length > len(image):
            break
        if marker in (0xC0, 0xC1, 0xC2):
            if length >= 8 and (int.from_bytes(image[offset + 7:offset + 9], 'big'),
                               int.from_bytes(image[offset + 5:offset + 7], 'big')) == (width, height):
                return image, rotation, sequence
            break
        offset += 2 + length
    raise ValueError('Camera image dimensions do not match.')


class CameraSession:
    def __init__(self, sink_factory, *, addresses=lan_addresses, clock=time.monotonic):
        self.sink_factory, self.addresses, self.clock = sink_factory, addresses, clock
        self.lock = threading.RLock()
        self.server = self.connection = self.sink = None
        self.state = 'idle'
        self.message = ''
        self.frame = None
        self.rotation = 0
        self.serial = 0
        self.deadline = self.last_frame = 0
        # Called with 'frame' or 'state' from session threads, outside the lock.
        self.notify = None

    def _announce(self, kind):
        notify = self.notify
        if notify is not None:
            try:
                notify(kind)
            except Exception:
                pass  # The dashboard's next refresh still shows the session.

    def start(self, preview=False, *, resolution=None, fps=None, quality=None):
        profiled = any(value is not None for value in (resolution, fps, quality))
        resolution = '720p' if resolution is None else resolution
        fps = 15 if fps is None else fps
        quality = 'standard' if quality is None else quality
        if (type(resolution) is not str or resolution not in RESOLUTIONS
                or type(fps) is not int or fps not in (15, 20, 30)
                or type(quality) is not str or quality not in JPEG_QUALITY):
            raise ValueError('Choose a supported camera resolution, frame rate and image quality.')
        with self.lock:
            if self.server is not None:
                raise ValueError('Stop the current camera session first.')
            addresses = self.addresses()
            if not addresses or any(not local_address(x) for x in addresses):
                raise ValueError('Connect this computer and your phone to the same private Wi-Fi or LAN.')
            self.sink = None if preview else self.sink_factory()
            self.preview = preview
            self.resolution, self.fps, self.quality = resolution, fps, quality
            self.samples = []
            self.dimensions = None
            try:
                tls, fingerprint = tls_context(addresses)
                self.secret = secrets.token_urlsafe(32)
                self.session = secrets.token_hex(16)
                self.deadline = self.clock() + INVITE_SECONDS
                self.state, self.message, self.frame = 'waiting', 'Scan the camera code in Saiph on your phone.', None
                made = []

                def bind(host):
                    made.append(serve(self._receive, host, 0, ssl=tls, max_size=MAX_FRAME,
                                      max_queue=1, open_timeout=5, close_timeout=1, compression=None,
                                      process_request=self._authorize))
                    return made[-1].socket.getsockname()[1]
                # Installed on Windows: loopback plus the fixed-path relay the firewall knows (lan_relay.py).
                port, self.relay = listen(bind, lambda: made.pop().socket.close())
                self.server = made[-1]
                offer = {'session': self.session, 'addresses': addresses, 'port': port,
                         'certificate': fingerprint, 'secret': self.secret, 'expires': int(time.time()) + INVITE_SECONDS}
                if profiled:
                    offer['stream'] = {'resolution': resolution, 'fps': fps, 'quality': quality}
                code = (PROFILE_PREFIX if profiled else PREFIX) + base64.urlsafe_b64encode(json.dumps(offer, separators=(',', ':')).encode()).decode().rstrip('=')
                # Kept only while waiting, for a sealed session offer to an approved phone.
                self.invite = code
                import qrcode
                qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
                qr.add_data(code); qr.make(fit=True)
                modules = [''.join('1' if cell else '0' for cell in row) for row in qr.get_matrix()]
                server = self.server
                threading.Thread(target=server.serve_forever, name='orion-camera-tls', daemon=True).start()
                epoch = self.session
                threading.Thread(target=self._monitor, args=(epoch,), name='orion-camera-expiry', daemon=True).start()
                return {'session': self.session, 'modules': modules, 'expires_in': INVITE_SECONDS,
                        'expires_at': datetime.fromtimestamp(offer['expires'], timezone.utc).isoformat()}
            except Exception:
                self.stop()
                raise

    def _authorize(self, connection, request):
        with self.lock:
            if (self.state != 'waiting' or self.clock() >= self.deadline
                    or request.path != '/camera/' + self.session
                    or len(request.headers.get_all('Authorization')) != 1
                    or not hmac.compare_digest(request.headers['Authorization'].encode('utf-8'), ('Bearer ' + self.secret).encode('ascii'))):
                return connection.respond(403, 'Camera invitation is unavailable.\n')
            # Claim before upgrade: simultaneous clients cannot both acquire it.
            self.state = 'connecting'
            self.connection = connection
            self.last_frame = self.clock()
            self.secret = self.invite = ''
        self._announce('state')
        return None

    def _receive(self, connection):
        sequence = 0
        epoch = None
        # The socket reader never waits for image work: a slow decode would
        # otherwise back up TLS and make the phone drop frames in bursts.
        # Only the newest validated frame is kept for the processing thread.
        pending = threading.Condition()
        slot = {'frame': None, 'done': False, 'dropped': 0}
        worker = None
        try:
            with self.lock:
                if connection is not self.connection or self.server is None:
                    return
                self.last_frame = self.clock()
                self.deadline = self.last_frame + SESSION_SECONDS
                epoch = self.session
                width, height = RESOLUTIONS[self.resolution]
            worker = threading.Thread(target=self._process, args=(connection, epoch, width, height, pending, slot),
                                      name='orion-camera-frames', daemon=True)
            worker.start()
            for value in connection:
                image, rotation, sequence = read_frame(value, sequence, max_pixels=width * height, max_dimension=width)
                with pending:
                    if slot['done']:
                        break
                    if slot['frame'] is not None:
                        slot['dropped'] += 1
                    slot['frame'] = (image, rotation)
                    pending.notify()
                with self.lock:
                    if connection is not self.connection or self.server is None:
                        break
        except Exception:
            # Deliberately omit URLs, headers, credentials and image content.
            pass
        finally:
            with pending:
                slot['done'] = True
                pending.notify()
            # Never leave image work running after the session it belongs to.
            if worker is not None:
                worker.join(5)
            with self.lock:
                current = epoch is not None and connection is self.connection
            if current:
                self.stop('Phone camera disconnected. Start a new session when you are ready.', expected_session=epoch)

    def _process(self, connection, epoch, width, height, pending, slot):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage, QTransform, QPainter
        try:
            while True:
                with pending:
                    while slot['frame'] is None and not slot['done']:
                        pending.wait(1)
                    if slot['done']:
                        return
                    image, rotation = slot['frame']
                    slot['frame'] = None
                with self.lock:
                    if connection is not self.connection or self.server is None or self.session != epoch:
                        return
                    sink = self.sink
                # Decoding also proves the phone's JPEG is a whole, valid image
                # before the dashboard is offered it.
                decoded = QImage.fromData(image, 'JPEG')
                if decoded.isNull():
                    raise ValueError('Camera image could not be decoded.')
                source_dimensions = (decoded.width(), decoded.height())
                rgba = None
                if sink:
                    # Only the virtual webcam needs upright pixels at its fixed output size.
                    if rotation:
                        decoded = decoded.transformed(QTransform().rotate(rotation))
                    if decoded.width() == width and decoded.height() == height:
                        canvas = decoded.convertToFormat(QImage.Format.Format_RGBA8888)
                    else:
                        canvas = QImage(width, height, QImage.Format.Format_RGBA8888)
                        canvas.fill(Qt.GlobalColor.black)
                        fitted = decoded.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        painter = QPainter(canvas)
                        painter.drawImage((width - fitted.width()) // 2, (height - fitted.height()) // 2, fitted)
                        painter.end()
                    rgba = bytes(canvas.constBits())
                with self.lock:
                    # Stop/replace may run while a frame decodes. Never publish
                    # or write that old frame into a replacement session.
                    if connection is not self.connection or self.server is None or self.session != epoch:
                        return
                    if self.sink:
                        self.sink.write(rgba, width, height)
                    # The preview is the phone's own validated JPEG, untouched:
                    # the dashboard decodes and rotates it, so no frame is ever
                    # scaled, re-encoded or base64-wrapped here.
                    self.frame, self.rotation = image, rotation
                    self.serial += 1
                    went_live = self.state != 'live'
                    self.last_frame, self.state, self.message = self.clock(), 'live', 'Choose Saiph Camera in your meeting app.'
                    self.samples = [sample for sample in self.samples if sample >= self.last_frame - 3][-119:] + [self.last_frame]
                    self.dimensions = {'source_width': source_dimensions[0], 'source_height': source_dimensions[1],
                                       'output_width': width, 'output_height': height, 'dropped_frames': slot['dropped']}
                if went_live:
                    self._announce('state')
                self._announce('frame')
        except Exception:
            # A frame that cannot be decoded ends the session, as before.
            connection.close()

    def _monitor(self, epoch):
        while True:
            time.sleep(0.5)
            with self.lock:
                if self.server is None or self.session != epoch:
                    return
                expired = self.clock() >= self.deadline
                stalled = self.state in ('connecting', 'live') and self.clock() - self.last_frame > 8
            if expired or stalled:
                self.stop('Camera session ended. Start again when you are ready.', expected_session=epoch)
                return

    def status(self):
        with self.lock:
            return {'state': self.state, 'running': self.state == 'live', 'waiting': self.state in ('waiting', 'connecting'),
                    'message': self.message, 'preview': getattr(self, 'preview', False),
                    'resolution': getattr(self, 'resolution', '720p'), 'fps': getattr(self, 'fps', 15),
                    'quality': getattr(self, 'quality', 'standard')}

    def describe(self):
        """The newest frame's metadata, without its picture."""
        with self.lock:
            samples = getattr(self, 'samples', [])
            measured = ((len(samples) - 1) / (samples[-1] - samples[0])
                        if len(samples) > 1 and samples[-1] > samples[0] and self.clock() - samples[-1] < 1 else 0)
            return {'sequence': self.serial, 'rotation': self.rotation if self.frame else 0, 'fps': round(measured, 1),
                    **(getattr(self, 'dimensions', None) or {})}

    def jpeg(self):
        """The newest preview JPEG while live, for the dashboard's frame feed."""
        with self.lock:
            return self.frame if self.state == 'live' else None

    def latest(self):
        """Polling form of the preview, for dashboards without the frame feed."""
        with self.lock:
            image, info = self.frame, self.describe()
        return {'image': None if image is None else 'data:image/jpeg;base64,' + base64.b64encode(image).decode(), **info}

    def invitation(self, session):
        """The unclaimed invitation for this session, for a sealed offer; never logged or shown."""
        with self.lock:
            if (self.server is None or getattr(self, 'session', None) != session or self.state != 'waiting'
                    or self.clock() >= self.deadline or not getattr(self, 'invite', '')):
                raise ValueError('This camera code has expired. Start a new session.')
            return self.invite

    def cancel_invite(self, session):
        with self.lock:
            if self.server is not None and self.session == session and self.state in ('waiting', 'connecting'):
                return self.stop()
        return {'cancelled': False}

    def stop(self, message='', *, expected_session=None):
        with self.lock:
            if expected_session is not None and getattr(self, 'session', None) != expected_session:
                return {'stopped': False}
            server, connection, sink = self.server, self.connection, self.sink
            relay, self.relay = getattr(self, 'relay', None), None
            # Status reads call stop() on an idle session; only a real change is announced.
            ended = self.state != 'idle'
            self.server = self.connection = self.sink = None
            # Blank the webcam before publishing idle or waiting for a network
            # close handshake. Another session cannot race this producer close.
            if sink:
                try:
                    sink.close()
                except Exception:
                    message = 'Camera stopped. Restart Saiph before using the webcam again.'
            self.state, self.message, self.frame, self.secret, self.invite = 'idle', message, None, '', ''
            self.samples, self.dimensions = [], None
        if connection:
            connection.close()
        if server:
            server.shutdown()
        if relay:
            relay.close()
        if ended:
            self._announce('state')
        return {'stopped': True}
