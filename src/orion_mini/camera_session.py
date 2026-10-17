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

PREFIX = 'orion-camera:1:'
FRAME = struct.Struct('!4sHHHQ')
MAX_FRAME = 512_000
MAX_PIXELS = 1280 * 720
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


def tls_context(addresses):
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Saiph Camera')])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
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


def read_frame(value, previous):
    if type(value) is not bytes or not FRAME.size + 4 <= len(value) <= MAX_FRAME:
        raise ValueError('Invalid camera frame.')
    magic, width, height, rotation, sequence = FRAME.unpack_from(value)
    if (magic != b'SCF1' or not 1 <= width <= 1280 or not 1 <= height <= 1280
            or width * height > MAX_PIXELS or rotation not in (0, 90, 180, 270)
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
        self.serial = 0
        self.deadline = self.last_frame = 0

    def start(self, preview=False):
        with self.lock:
            if self.server is not None:
                raise ValueError('Stop the current camera session first.')
            addresses = self.addresses()
            if not addresses or any(not local_address(x) for x in addresses):
                raise ValueError('Connect this computer and your phone to the same private Wi-Fi or LAN.')
            self.sink = None if preview else self.sink_factory()
            self.preview = preview
            try:
                tls, fingerprint = tls_context(addresses)
                self.secret = secrets.token_urlsafe(32)
                self.session = secrets.token_hex(16)
                self.deadline = self.clock() + INVITE_SECONDS
                self.state, self.message, self.frame = 'waiting', 'Scan the camera code in Saiph on your phone.', None
                self.server = serve(self._receive, '0.0.0.0', 0, ssl=tls, max_size=MAX_FRAME,
                                    max_queue=1, open_timeout=5, close_timeout=1, compression=None,
                                    process_request=self._authorize)
                port = self.server.socket.getsockname()[1]
                offer = {'session': self.session, 'addresses': addresses, 'port': port,
                         'certificate': fingerprint, 'secret': self.secret, 'expires': int(time.time()) + INVITE_SECONDS}
                code = PREFIX + base64.urlsafe_b64encode(json.dumps(offer, separators=(',', ':')).encode()).decode().rstrip('=')
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
            self.secret = ''
        return None

    def _receive(self, connection):
        sequence = 0
        try:
            with self.lock:
                if connection is not self.connection or self.server is None:
                    return
                self.last_frame = self.clock()
                self.deadline = self.last_frame + SESSION_SECONDS
                epoch = self.session
            for value in connection:
                image, rotation, sequence = read_frame(value, sequence)
                with self.lock:
                    if connection is not self.connection or self.server is None:
                        break
                    if self.state == 'live' and self.clock() - self.last_frame < 0.05:
                        continue
                    from PySide6.QtCore import Qt
                    from PySide6.QtGui import QImage, QTransform
                    decoded = QImage.fromData(image, 'JPEG')
                    if decoded.isNull():
                        raise ValueError('Camera image could not be decoded.')
                    if rotation:
                        decoded = decoded.transformed(QTransform().rotate(rotation))
                    canvas = QImage(1280, 720, QImage.Format.Format_RGBA8888)
                    canvas.fill(Qt.GlobalColor.black)
                    from PySide6.QtGui import QPainter
                    fitted = decoded.scaled(1280, 720, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    painter = QPainter(canvas)
                    painter.drawImage((1280 - fitted.width()) // 2, (720 - fitted.height()) // 2, fitted)
                    painter.end()
                    if self.sink:
                        self.sink.write(bytes(canvas.constBits()))
                    # Only the latest bounded preview is kept; nothing is persisted.
                    from PySide6.QtCore import QBuffer, QIODevice
                    output = QBuffer()
                    output.open(QIODevice.OpenModeFlag.WriteOnly)
                    canvas.scaledToWidth(640).save(output, 'JPEG', 65)
                    if output.size() > 100_000:
                        output.close(); output.setData(b''); output.open(QIODevice.OpenModeFlag.WriteOnly)
                        canvas.scaledToWidth(480).save(output, 'JPEG', 55)
                    self.frame = 'data:image/jpeg;base64,' + base64.b64encode(bytes(output.data())).decode()
                    self.serial += 1
                    self.last_frame, self.state, self.message = self.clock(), 'live', 'Choose Saiph Camera in your meeting app.'
        except Exception:
            # Deliberately omit URLs, headers, credentials and image content.
            pass
        finally:
            with self.lock:
                current = connection is self.connection
            if current:
                self.stop('Phone camera disconnected. Start a new session when you are ready.', expected_session=epoch)

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
                    'message': self.message, 'preview': getattr(self, 'preview', False)}

    def latest(self):
        with self.lock:
            return {'image': self.frame, 'sequence': self.serial}

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
            self.server = self.connection = self.sink = None
            # Blank the webcam before publishing idle or waiting for a network
            # close handshake. Another session cannot race this producer close.
            if sink:
                try:
                    sink.close()
                except Exception:
                    message = 'Camera stopped. Restart Saiph before using the webcam again.'
            self.state, self.message, self.frame, self.secret = 'idle', message, None, ''
        if connection:
            connection.close()
        if server:
            server.shutdown()
        return {'stopped': True}
