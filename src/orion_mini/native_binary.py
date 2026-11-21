# SPDX-License-Identifier: AGPL-3.0-or-later
"""Authenticated private binary stream for previews and clipboard, never base64."""
from __future__ import annotations
import json
import os
import socket
import struct
import threading
from collections import OrderedDict

MAX_BINARY = 64 * 1024 * 1024
MAX_HEADER = 4096


class BinaryLink:
    def __init__(self, address, token, receive):
        self.receive = receive
        self.closed = False
        self.condition = threading.Condition()
        self.pending = OrderedDict()
        if os.name == 'nt':
            self.stream = open(address, 'r+b', buffering=0)
            # Synchronous Windows pipe handles serialize a pending ReadFile with
            # WriteFile. Separate connections keep frames flowing while idle input
            # is waiting, without weakening the Chromium sandbox.
            self.incoming = open(address, 'r+b', buffering=0)
            self.socket = None
            self.incoming_socket = None
        else:
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.socket.connect(address)
            self.stream = self.socket.makefile('rwb', buffering=0)
            self.incoming_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.incoming_socket.connect(address)
            self.incoming = self.incoming_socket.makefile('rwb', buffering=0)
        self._write({'kind': 'hello', 'protocol': 1, 'token': token, 'role': 'publish'}, b'')
        self._write({'kind': 'hello', 'protocol': 1, 'token': token, 'role': 'receive'}, b'', stream=self.incoming)
        self.sender = threading.Thread(target=self._send, name='saiph-binary-send', daemon=True)
        self.reader = threading.Thread(target=self._read, name='saiph-binary-read', daemon=True)
        self.sender.start()
        self.reader.start()

    def publish(self, key, header, data):
        data = bytes(data)
        if len(data) > MAX_BINARY:
            raise ValueError('Native media exceeds its size limit.')
        with self.condition:
            if self.closed:
                return
            # Preview updates replace an older unsent frame for that source.
            if key not in self.pending and len(self.pending) >= 8:
                raise ValueError('Native media channel is busy.')
            self.pending[key] = (dict(header), data)
            self.condition.notify()

    def _write(self, header, data, *, stream=None):
        metadata = json.dumps({**header, 'bytes': len(data)}, separators=(',', ':')).encode()
        if len(metadata) > MAX_HEADER:
            raise ValueError('Invalid native media header.')
        for part in (struct.pack('!I', len(metadata)), metadata, data):
            view = memoryview(part)
            while view:
                written = (stream or self.stream).write(view)
                if not written:
                    raise EOFError()
                view = view[written:]

    def _send(self):
        try:
            while True:
                with self.condition:
                    while not self.pending and not self.closed:
                        self.condition.wait()
                    if self.closed:
                        return
                    _, (header, data) = self.pending.popitem(last=False)
                self._write(header, data)
        except (OSError, EOFError, ValueError):
            self.close()

    def _exact(self, size):
        data = bytearray()
        while len(data) < size:
            block = self.incoming.read(size - len(data))
            if not block:
                raise EOFError()
            data.extend(block)
        return bytes(data)

    def _read(self):
        try:
            while not self.closed:
                length, = struct.unpack('!I', self._exact(4))
                if not 0 < length <= MAX_HEADER:
                    raise ValueError()
                header = json.loads(self._exact(length))
                size = header.get('bytes')
                if type(size) is not int or not 0 <= size <= MAX_BINARY:
                    raise ValueError()
                self.receive(header, self._exact(size))
        except (OSError, EOFError, ValueError):
            self.close()

    def close(self):
        with self.condition:
            if self.closed:
                return
            self.closed = True
            self.pending.clear()
            self.condition.notify_all()
        for connection in (self.socket, self.incoming_socket):
            if connection:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        # Closing a synchronous Windows handle with a pending read must cancel
        # that operation first, or shutdown can wait forever on an idle pipe.
        if os.name == 'nt':
            import ctypes
            import msvcrt
            from ctypes import wintypes
            cancel = ctypes.windll.kernel32.CancelIoEx
            cancel.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
            for stream in (self.stream, self.incoming):
                if not stream.closed:
                    cancel(msvcrt.get_osfhandle(stream.fileno()), None)
        for stream in (self.stream, self.incoming):
            try:
                stream.close()
            except OSError:
                pass
