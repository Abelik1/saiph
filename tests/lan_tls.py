# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthetic loopback TLS clients for the phone camera and phone screen servers.

The phone's OkHttp client pins the exact certificate; these clients skip that to
exercise the real server TLS, authorisation and upgrade path.

Why `websocket_client_context` caps TLS at 1.2: CPython's `ssl` sockets are not safe
for a concurrent recv() and send() from two threads under TLS 1.3. The
websockets sync client has its reader thread inside recv() (receiving the server's
post-handshake session tickets) while it writes the upgrade request, and on Windows
about one in three such writes never reached the server, which then timed out after
5 s. A plain sequential client never stalled, nor did TLS 1.2 (no post-handshake
tickets). OkHttp, the Android client, completed 30 of 30 full-duplex TLS 1.3 sessions
against ScreenSession in a probe. The servers keep TLS 1.3; `tls13_upgrade` checks it.
"""
from __future__ import annotations

import socket
import ssl


def _unverified():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def websocket_client_context():
    """For websockets.sync.client.connect, whose reader thread overlaps its writes."""
    context = _unverified()
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    return context


def tls13_upgrade(port, path, secret, *, timeout=5):
    """One sequential TLS 1.3 WebSocket upgrade; returns (TLS version, HTTP status line)."""
    context = _unverified()
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    request = (f'GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
               'Sec-WebSocket-Key: c3ludGhldGljLWtleS0xMg==\r\nSec-WebSocket-Version: 13\r\n'
               f'Authorization: Bearer {secret}\r\n\r\n').encode()
    with socket.create_connection(('127.0.0.1', port), timeout=timeout) as plain:
        with context.wrap_socket(plain) as tls:
            tls.sendall(request)
            response = b''
            while b'\r\n' not in response:
                chunk = tls.recv(4096)
                if not chunk:
                    break
                response += chunk
            return tls.version(), response.split(b'\r\n', 1)[0].decode('latin-1')
