# SPDX-License-Identifier: AGPL-3.0-or-later
"""Files of any size directly between the owner's devices on one private network.

The computer always listens; phones only connect, as for the phone camera and
phone screen. One transfer is one listener with a fresh certificate pinned by
the invitation, which travels inside a sealed Saiph Cloud envelope to exactly
one approved device ("file" in session_offer.py, docs/LAN_FILES.md).

  POST /file/<session>/claim     Authorization: Bearer <secret>  -> {"resume": token}
  GET  /file/<session>           Authorization: Resume <token>, Range: bytes=N-   ("get")
  POST /file/<session>/done      {"size": n, "sha256": hex}  the receiver's own result ("get")
  GET  /file/<session>/received  -> {"received": n}                                ("put")
  PUT  /file/<session>?offset=N  the rest of the file; answered after verification ("put")

The bearer secret works once; the resume token it returns is known only to the
device that claimed it, over the pinned TLS connection, and lets that device
continue after a dropped connection for `RESUME_SECONDS`. Both sides check the
exact size and SHA-256 from the sealed offer before a file counts as received.
A received file stays in a private folder until the owner saves it. File names,
paths, secrets and contents are never logged.
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
import re
import secrets
import shutil
import socket
import socketserver
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from .session_offer import (MAX_FILE_BYTES, OfferError, file_invite_code, read_file_invite, valid_filename)

CHUNK = 1 << 20
INVITE_SECONDS = 100  # Under the offer maximum (120 s), so a receiver whose clock is a little behind accepts it.
RESUME_SECONDS = 90  # A dropped connection may come back for this long.
IO_TIMEOUT = 15  # Seconds without a byte before a connection counts as dropped.
CONNECT_TIMEOUT = 4
RETRY_SECONDS = 2
READY_SECONDS = 1800  # A received file waits this long for Save, then is removed.
SPACE_MARGIN = 64 * 1024 * 1024
PART = ".saiph-part"


class LanUnreachable(Exception):
    """No address answered with the pinned certificate, or the invitation was refused."""


class LanFailed(Exception):
    def __init__(self, text):
        super().__init__(text)
        self.text = text


def sha256_file(path: Path, *, limit=MAX_FILE_BYTES) -> tuple[int, str]:
    digest, size = hashlib.sha256(), 0
    with Path(path).open("rb") as source:
        while chunk := source.read(CHUNK):
            size += len(chunk)
            if size > limit:
                raise ValueError("File is too large.")
            digest.update(chunk)
    return size, digest.hexdigest()


def free_space(folder: Path) -> int:
    try:
        return shutil.disk_usage(folder).free
    except OSError:
        return 0


def remove_parts(folder: Path):
    """Partial and unsaved files a closed or crashed app left behind."""
    try:
        entries = [path for path in Path(folder).iterdir() if path.name.endswith(PART)]
    except OSError:
        return
    for path in entries:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


# ------------------------------------------------------------------ server
class _Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = False
    request_queue_size = 8

    def __init__(self, owner, context, host="0.0.0.0"):
        self.owner, self.context = owner, context
        super().__init__((host, 0), _Handler)

    def get_request(self):
        sock, address = self.socket.accept()
        sock.settimeout(IO_TIMEOUT)
        return self.context.wrap_socket(sock, server_side=True, do_handshake_on_connect=False), address

    def handle_error(self, request, client_address):
        pass  # Never print request details; a broken connection is ordinary here.


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Saiph"
    sys_version = ""

    def setup(self):
        self.request.settimeout(IO_TIMEOUT)
        self.request.do_handshake()
        super().setup()

    def log_message(self, *args):
        pass

    def _reply(self, status, body=None, headers=()):
        raw = b"" if body is None else json.dumps(body, separators=(",", ":")).encode()
        self.send_response(status)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        if raw:
            self.wfile.write(raw)
        self.close_connection = True

    def _route(self, method):
        owner = self.server.owner
        path, _, query = self.path.partition("?")
        match = re.fullmatch(r"/file/([a-f0-9]{32})(/claim|/done|/received)?", path)
        if match is None or not hmac.compare_digest(match.group(1), owner.session):
            return self._reply(404)
        action = (match.group(2) or "")[1:]
        auth = self.headers.get_all("Authorization") or []
        if len(auth) != 1:
            return self._reply(403)
        try:
            if method == "POST" and action == "claim":
                return owner._claim(self, auth[0])
            if not owner._resumed(auth[0]):
                return self._reply(403)
            if method == "GET" and action == "" and owner.mode == "get":
                return owner._serve(self)
            if method == "POST" and action == "done" and owner.mode == "get":
                return owner._done(self)
            if method == "GET" and action == "received" and owner.mode == "put":
                return self._reply(200, {"received": owner.received})
            if method == "PUT" and action == "" and owner.mode == "put":
                return owner._accept(self, query)
            return self._reply(405)
        except (OSError, ValueError):
            self.close_connection = True

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")


class LanFileServer:
    """One file transfer on a private network: one listener, one claim, resumable.

    mode "get": this computer serves `path` to the device that claims.
    mode "put": a phone uploads into `path` (created here, private).
    """

    def __init__(self, mode, path: Path, *, name, size, sha256, request="", addresses=None,
                 clock=time.monotonic, invite_seconds=INVITE_SECONDS):
        if mode not in ("get", "put") or not valid_filename(name) or type(size) is not int or not 0 <= size <= MAX_FILE_BYTES:
            raise ValueError("This file cannot be sent over your network.")
        self.mode, self.path, self.name, self.size, self.sha256, self.request = mode, Path(path), name, size, sha256, request
        self.addresses = addresses
        self.clock, self.invite_seconds = clock, invite_seconds
        self.lock = threading.RLock()
        self.session = secrets.token_hex(16)
        self.secret = secrets.token_urlsafe(32)
        self.resume = ""
        self.state = "idle"  # waiting -> claimed -> done | failed; expired/closed end it early.
        self.error = ""
        self.received = 0  # put: bytes written and hashed; get: the receiver's confirmed offset.
        self.sent = 0  # get: furthest byte handed to the network.
        self._digest = hashlib.sha256()
        self._generation = 0
        self._stream = None
        self.server = self.relay = None
        self.deadline = self.touched = 0.0

    # ------------------------------------------------------------ lifecycle
    def start(self) -> str:
        from .camera_session import lan_addresses, local_address, tls_context
        from .lan_relay import listen
        addresses = (self.addresses or lan_addresses)()
        if not addresses or any(not local_address(address) for address in addresses):
            raise LanUnreachable()
        if self.mode == "put":
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
            os.close(fd)
        try:
            context, fingerprint = tls_context(addresses[:8], "Saiph Files", hours=24)
            made = []

            def bind(host):
                made.append(_Server(self, context, host))
                return made[-1].server_address[1]
            # Installed on Windows: loopback plus the fixed-path relay the firewall knows (lan_relay.py).
            port, relay = listen(bind, lambda: made.pop().server_close())
            with self.lock:
                self.server, self.relay = made[-1], relay
                self.state = "waiting"
                self.deadline = self.clock() + self.invite_seconds
                self.touched = self.clock()
            invite = file_invite_code({"session": self.session, "addresses": addresses[:8], "port": port,
                                       "certificate": fingerprint, "secret": self.secret,
                                       "expires": int(time.time()) + self.invite_seconds, "mode": self.mode,
                                       "name": self.name, "size": self.size, "sha256": self.sha256, "request": self.request})
            threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.25},
                             name="orion-lan-file", daemon=True).start()
            threading.Thread(target=self._monitor, name="orion-lan-file-watch", daemon=True).start()
            return invite
        except Exception:
            self.close()
            raise

    def _monitor(self):
        while True:
            time.sleep(0.5)
            with self.lock:
                if self.state == "waiting" and self.clock() >= self.deadline:
                    self._end("expired", "")
                elif self.state == "claimed" and self.clock() - self.touched > RESUME_SECONDS:
                    self._end("failed", "lost")
                if self.state not in ("waiting", "claimed"):
                    break
        self._shutdown()

    def _end(self, state, error):
        """Caller holds the lock."""
        self.state, self.error, self.secret, self.resume = state, error, "", ""
        self._generation += 1
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if state != "done" and self.mode == "put":
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass

    def _shutdown(self):
        with self.lock:
            server, self.server = self.server, None
            relay, self.relay = self.relay, None
        if relay is not None:
            relay.close()
        if server is not None:
            threading.Thread(target=lambda: (server.shutdown(), server.server_close()), daemon=True).start()

    def close(self, state="closed"):
        """The sender gave up (fallback, cancel, exit). A finished transfer keeps its result."""
        with self.lock:
            if self.state in ("idle", "waiting", "claimed"):
                self._end(state, "")
        self._shutdown()

    def status(self) -> dict:
        with self.lock:
            done = self.received if self.mode == "put" else max(self.received, min(self.sent, self.size))
            return {"state": self.state, "error": self.error, "bytes": done, "size": self.size}

    # -------------------------------------------------------------- requests
    def _claim(self, handler, authorization):
        with self.lock:
            if (self.state != "waiting" or self.clock() >= self.deadline or not self.secret
                    or not hmac.compare_digest(authorization.encode("utf-8", "replace"), ("Bearer " + self.secret).encode())):
                return handler._reply(403)
            # Claimed before answering: a replayed or second claim gets nothing.
            self.state, self.secret, self.resume = "claimed", "", secrets.token_urlsafe(32)
            self.touched = self.clock()
            resume = self.resume
        handler._reply(200, {"resume": resume})

    def _resumed(self, authorization) -> bool:
        with self.lock:
            if self.state != "claimed" or not self.resume:
                return False
            if not hmac.compare_digest(authorization.encode("utf-8", "replace"), ("Resume " + self.resume).encode()):
                return False
            self.touched = self.clock()
            return True

    def _take_stream(self, handler):
        """A newer connection replaces an older one, which stops at its next chunk."""
        with self.lock:
            self._generation += 1
            old, self._stream = self._stream, handler.request
            generation = self._generation
        if old is not None:
            try:
                old.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        return generation

    def _current(self, generation) -> bool:
        with self.lock:
            if generation == self._generation and self.state == "claimed":
                self.touched = self.clock()
                return True
            return False

    def _serve(self, handler):
        offset = 0
        ranged = handler.headers.get("Range")
        if ranged is not None:
            match = re.fullmatch(r"bytes=([0-9]{1,15})-", ranged.strip())
            if match is None or int(match.group(1)) > self.size:
                return handler._reply(416)
            offset = int(match.group(1))
        try:
            fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        except OSError:
            with self.lock:
                self._end("failed", "missing")
            return handler._reply(410)
        generation = self._take_stream(handler)
        with self.lock:
            self.received = max(self.received, offset)
        with os.fdopen(fd, "rb") as source:
            if os.fstat(source.fileno()).st_size != self.size:
                with self.lock:
                    self._end("failed", "changed")
                return handler._reply(410)
            source.seek(offset)
            handler.send_response(206 if ranged is not None else 200)
            handler.send_header("Content-Type", "application/octet-stream")
            handler.send_header("Content-Length", str(self.size - offset))
            if ranged is not None:
                handler.send_header("Content-Range", f"bytes {offset}-{max(offset, self.size - 1)}/{self.size}")
            handler.send_header("Connection", "close")
            handler.end_headers()
            handler.close_connection = True
            position = offset
            while position < self.size:
                if not self._current(generation):
                    return
                chunk = source.read(min(CHUNK, self.size - position))
                if not chunk:
                    return
                handler.wfile.write(chunk)
                position += len(chunk)
                with self.lock:
                    if generation == self._generation:
                        self.sent = max(self.sent, position)
            handler.wfile.flush()

    def _body(self, handler, limit=512):
        length = handler.headers.get("Content-Length")
        if length is None or not length.isdigit() or int(length) > limit:
            raise ValueError("Invalid body.")
        return json.loads(handler.rfile.read(int(length)) or b"null")

    def _done(self, handler):
        try:
            body = self._body(handler)
        except ValueError:
            return handler._reply(400)
        if type(body) is not dict or set(body) != {"size", "sha256"}:
            return handler._reply(400)
        with self.lock:
            matched = body["size"] == self.size and type(body["sha256"]) is str and hmac.compare_digest(body["sha256"], self.sha256)
            self.received = self.size if matched else self.received
            self._end("done" if matched else "failed", "" if matched else "mismatch")
        handler._reply(200, {"ok": matched})

    def _accept(self, handler, query):
        match = re.fullmatch(r"offset=([0-9]{1,15})", query)
        length = handler.headers.get("Content-Length")
        with self.lock:
            received = self.received
        if match is None or int(match.group(1)) != received:
            return handler._reply(409, {"received": received})
        if length is None or not length.isdigit() or int(length) != self.size - received:
            return handler._reply(400)
        generation = self._take_stream(handler)
        remaining = self.size - received
        with self.path.open("r+b") as output:
            output.seek(received)
            output.truncate()
            while remaining:
                if not self._current(generation):
                    return
                chunk = handler.rfile.read(min(CHUNK, remaining))
                if not chunk:
                    return
                output.write(chunk)
                with self.lock:
                    if generation != self._generation:
                        return
                    self._digest.update(chunk)
                    self.received += len(chunk)
                remaining -= len(chunk)
            output.flush()
            os.fsync(output.fileno())
        with self.lock:
            matched = self.received == self.size and hmac.compare_digest(self._digest.hexdigest(), self.sha256)
            if self._stream is handler.request:
                self._stream = None  # This connection still carries the answer.
            self._end("done" if matched else "failed", "" if matched else "mismatch")
        handler._reply(200 if matched else 422, {"ok": matched})


# ------------------------------------------------------------------ client
def _connect(address, port, fingerprint, *, timeout, dial=None):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # Trust is the pinned certificate below, not a CA.
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = http.client.HTTPSConnection(dial(address) if dial else address, port, timeout=timeout, context=context)
    connection.connect()
    der = connection.sock.getpeercert(binary_form=True)
    if not der or not hmac.compare_digest(hashlib.sha256(der).hexdigest(), fingerprint):
        connection.close()
        raise ssl.SSLError("Unexpected certificate.")
    connection.sock.settimeout(IO_TIMEOUT)
    return connection


def _json(response, limit=512):
    raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Invalid reply.")
    return json.loads(raw)


def fetch(invite: dict, destination: Path, *, progress=None, cancelled=lambda: False, clock=time.monotonic,
          sleep=time.sleep, dial=None) -> Path:
    """Download a "get" invitation into `destination` (a new private file) and verify it.

    Raises LanUnreachable when the claim never succeeded (the sender may fall back),
    or LanFailed after it did. `destination` is removed unless verified.
    """
    destination = Path(destination)
    session, port, fingerprint = invite["session"], invite["port"], invite["certificate"]
    addresses = list(invite["addresses"])
    resume = None
    for address in addresses:
        if cancelled():
            raise LanUnreachable()
        try:
            connection = _connect(address, port, fingerprint, timeout=CONNECT_TIMEOUT, dial=dial)
            try:
                connection.request("POST", f"/file/{session}/claim", body=b"",
                                   headers={"Authorization": "Bearer " + invite["secret"], "Content-Length": "0"})
                response = connection.getresponse()
                if response.status == 200:
                    value = _json(response)
                    if type(value) is dict and type(value.get("resume")) is str and re.fullmatch(r"[A-Za-z0-9_-]{43}", value["resume"]):
                        resume = value["resume"]
                        addresses.remove(address)
                        addresses.insert(0, address)
                        break
                raise LanUnreachable()
            finally:
                connection.close()
        except (OSError, ssl.SSLError, http.client.HTTPException, ValueError):
            continue
        except LanUnreachable:
            raise
    if resume is None:
        raise LanUnreachable()
    size, digest, received = invite["size"], hashlib.sha256(), 0
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
    verified = False
    try:
        if progress is not None:
            progress(0)  # Connected and claimed: the transfer is now visible.
        with os.fdopen(fd, "wb") as output:
            last = clock()
            while received < size:
                if cancelled():
                    raise LanFailed("cancelled")
                if clock() - last > RESUME_SECONDS:
                    raise LanFailed("lost")
                try:
                    connection = _connect(addresses[0], port, fingerprint, timeout=CONNECT_TIMEOUT, dial=dial)
                except (OSError, ssl.SSLError, http.client.HTTPException):
                    addresses.append(addresses.pop(0))
                    sleep(RETRY_SECONDS)
                    continue
                try:
                    connection.request("GET", f"/file/{session}",
                                       headers={"Authorization": "Resume " + resume, "Range": f"bytes={received}-"})
                    response = connection.getresponse()
                    if response.status in (403, 410, 416):
                        raise LanFailed("refused")
                    if response.status != 206:
                        raise http.client.HTTPException()
                    while received < size:
                        if cancelled():
                            raise LanFailed("cancelled")
                        chunk = response.read(min(CHUNK, size - received))
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
                        received += len(chunk)
                        last = clock()
                        if progress is not None:
                            progress(received)
                except (OSError, http.client.HTTPException, ssl.SSLError):
                    sleep(RETRY_SECONDS if received < size else 0)
                finally:
                    connection.close()
            output.flush()
            os.fsync(output.fileno())
        matched = hmac.compare_digest(digest.hexdigest(), invite["sha256"])
        # Tell the sender the receiver's own result; it reports "Sent" only on a match.
        for _ in range(5):
            try:
                connection = _connect(addresses[0], port, fingerprint, timeout=CONNECT_TIMEOUT, dial=dial)
                try:
                    body = json.dumps({"size": received, "sha256": digest.hexdigest()}).encode()
                    connection.request("POST", f"/file/{session}/done", body=body,
                                       headers={"Authorization": "Resume " + resume, "Content-Type": "application/json",
                                                "Content-Length": str(len(body))})
                    connection.getresponse().read(512)
                    break
                finally:
                    connection.close()
            except (OSError, http.client.HTTPException, ssl.SSLError):
                sleep(1)
        if not matched:
            raise LanFailed("mismatch")
        verified = True
        return destination
    finally:
        if not verified:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass


# ------------------------------------------------------------------- inbox
FAILURES = {
    "lost": "The connection to {device} was lost. Ask to send it again when both are on the same network.",
    "mismatch": "{name} arrived damaged and was deleted. Ask to send it again.",
    "refused": "{device} stopped sending {name}.",
    "storage": "Not enough free space for {name} ({size}). Free some space and ask to send it again.",
    "changed": "{name} changed on {device} while it was sending. Ask to send it again.",
    "missing": "{name} is no longer on {device}.",
    "cancelled": "Receiving {name} was cancelled.",
}


def failure_text(code, *, name, device, size=0):
    from .hosted_transfers import megabytes
    template = FAILURES.get(code, "{name} could not be received from {device}. Ask to send it again.")
    return template.format(name=name, device=device, size=f"{megabytes(size, up=True)} MB")


class Incoming:
    __slots__ = ("id", "source", "name", "size", "mode", "state", "received", "error", "path", "ready_at",
                 "server", "cancel", "saved", "offer")

    def __init__(self, offer_id, source, name, size, mode, path):
        self.id, self.source, self.name, self.size, self.mode, self.path = offer_id, source, name, size, mode, path
        self.state, self.received, self.error, self.ready_at = "waiting", 0, "", 0.0
        self.server, self.cancel, self.saved = None, threading.Event(), ""
        self.offer = ""  # "put": the ID of the sealed offer carrying our upload invitation.


class LanInbox:
    """Files arriving over the local network, until the owner saves or dismisses them.

    A computer's "get" offer is fetched at once; a phone's request gets a "put"
    invitation. A row is shown only once the sender actually connected, so a
    refused or unreachable offer never leaves a dead row: the sender falls back.
    """

    LIMIT = 8

    def __init__(self, controller, *, monotonic=time.monotonic, dial=None):
        self.c, self.monotonic, self.dial = controller, monotonic, dial
        self.lock = threading.RLock()
        self.items: dict[str, Incoming] = {}
        self._reported = 0.0
        remove_parts(self.folder)

    @property
    def folder(self) -> Path:
        return self.c.folder / "incoming"

    def _space(self, size) -> bool:
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        return free_space(self.folder) >= size + SPACE_MARGIN

    def _admit(self, offer_id, source, name, size, mode) -> Incoming | None:
        with self.lock:
            self._prune()
            if offer_id in self.items:
                return None
            busy = sum(item.state in ("waiting", "receiving") for item in self.items.values())
            if busy >= self.LIMIT:
                self.c.file_refuse(source, offer_id, "busy")
                return None
            if not self._space(size):
                self.c.file_refuse(source, offer_id, "storage")
                item = Incoming(offer_id, source, name, size, mode, None)
                item.state, item.error = "failed", failure_text("storage", name=name, device=self.c.device_name(source), size=size)
                self.items[offer_id] = item
                self.c.changed()
                return None
            item = Incoming(offer_id, source, name, size, mode, self.folder / (secrets.token_hex(16) + PART))
            self.items[offer_id] = item
            return item

    def offer(self, source, offer_id, invite: dict):
        """A computer offers a file ("get"): fetch it now into the private folder."""
        item = self._admit(offer_id, source, invite["name"], invite["size"], "get")
        if item is None:
            return
        threading.Thread(target=self._fetch, args=(item, invite), name="orion-lan-receive", daemon=True).start()

    def _fetch(self, item, invite):
        def progress(count):
            first = item.state == "waiting"
            item.state, item.received = "receiving", count
            if first:
                self.c.changed()
            self._tick()
        try:
            fetch(invite, item.path, progress=progress, cancelled=item.cancel.is_set, dial=self.dial,
                  clock=self.monotonic)
        except LanUnreachable:
            with self.lock:
                self.items.pop(item.id, None)
            if not item.cancel.is_set():
                self.c.file_refuse(item.source, item.id, "unreachable")
            return
        except LanFailed as failure:
            self._failed(item, failure.text)
            return
        except Exception:
            self._failed(item, "")
            return
        self._ready(item)

    def request(self, source, request: dict):
        """A phone asks to upload ("put"): open a listener and invite it."""
        item = self._admit(request["id"], source, request["name"], request["size"], "put")
        if item is None:
            return
        try:
            server = LanFileServer("put", item.path, name=request["name"], size=request["size"], sha256=request["sha256"],
                                   request=request["id"], addresses=getattr(self.c, "lan_addresses", None))
            invite = server.start()
            item.server = server
            item.offer = self.c.file_offer(source, invite)
        except Exception:
            with self.lock:
                self.items.pop(item.id, None)
            if item.server is not None:
                item.server.close()
            self.c.file_refuse(source, request["id"], "unreachable")
            return
        threading.Thread(target=self._watch, args=(item,), name="orion-lan-upload", daemon=True).start()

    def _watch(self, item):
        while True:
            time.sleep(0.25)
            status = item.server.status()
            if status["state"] == "claimed":
                first = item.state == "waiting"
                item.state, item.received = "receiving", status["bytes"]
                if first:
                    self.c.changed()
                self._tick()
            elif status["state"] == "done":
                return self._ready(item)
            elif status["state"] == "failed":
                return self._failed(item, status["error"])
            elif status["state"] in ("expired", "closed"):
                with self.lock:
                    self.items.pop(item.id, None)
                self.c.changed()
                return

    def _tick(self):
        """Progress reaches the window at most twice a second."""
        now = self.monotonic()
        if now - self._reported >= 0.5:
            self._reported = now
            self.c.changed()

    def _ready(self, item):
        with self.lock:
            item.state, item.received, item.ready_at = "ready", item.size, self.monotonic()
        self.c.lan_received(item)
        self.c.changed()

    def _failed(self, item, code):
        with self.lock:
            item.state = "failed"
            item.error = failure_text(code, name=item.name, device=self.c.device_name(item.source), size=item.size)
            if item.path is not None:
                try:
                    item.path.unlink(missing_ok=True)
                except OSError:
                    pass
        self.c.changed()

    def closed(self, source, offer_id):
        """The other side withdrew before connecting: a computer that fell back, or a phone
        that could not reach our upload listener (it names the listener's offer ID)."""
        with self.lock:
            item = next((item for item in self.items.values() if item.source == source and item.state == "waiting"
                         and offer_id in (item.id, item.offer)), None)
            if item is None:
                return
            item.cancel.set()
            self.items.pop(item.id, None)
        if item.server is not None:
            item.server.close()

    def has(self, offer_id) -> bool:
        with self.lock:
            return offer_id in self.items

    def save(self, offer_id, folder: Path) -> tuple[Path, Incoming]:
        """Move a verified file into `folder` under a fresh name; never overwrite."""
        with self.lock:
            item = self.items.get(offer_id)
            if item is None or item.state != "ready":
                raise ValueError("This file is no longer available.")
            item.state = "saving"
        try:
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            stem, suffix = os.path.splitext(item.name)
            destination, index = folder / item.name, 1
            while destination.exists():
                destination, index = folder / f"{stem} ({index}){suffix}", index + 1
            try:
                os.link(item.path, destination)
            except OSError:
                # Another volume (a moved Downloads folder): copy, then publish without overwriting.
                temporary = folder / ("." + secrets.token_hex(8) + PART)
                with item.path.open("rb") as source, temporary.open("xb") as output:
                    shutil.copyfileobj(source, output, CHUNK)
                    output.flush()
                    os.fsync(output.fileno())
                try:
                    os.link(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
            item.path.unlink(missing_ok=True)
        except Exception:
            with self.lock:
                item.state = "ready"
            raise
        with self.lock:
            self.items.pop(offer_id, None)
        return destination, item

    def dismiss(self, offer_id):
        with self.lock:
            item = self.items.get(offer_id)
            if item is None:
                raise ValueError("This file is no longer available.")
            if item.state in ("waiting", "receiving"):
                item.cancel.set()
                if item.server is not None:
                    item.server.close()
            self.items.pop(offer_id, None)
        if item.path is not None:
            try:
                item.path.unlink(missing_ok=True)
            except OSError:
                pass

    def _prune(self):
        now = self.monotonic()
        for key, item in list(self.items.items()):
            if item.state == "ready" and now - item.ready_at > READY_SECONDS:
                self.items.pop(key, None)
                if item.path is not None:
                    try:
                        item.path.unlink(missing_ok=True)
                    except OSError:
                        pass

    def active(self) -> bool:
        with self.lock:
            return any(item.state in ("waiting", "receiving") for item in self.items.values())

    def close(self):
        with self.lock:
            items, self.items = list(self.items.values()), {}
        for item in items:
            item.cancel.set()
            if item.server is not None:
                item.server.close()
            if item.path is not None:
                try:
                    item.path.unlink(missing_ok=True)
                except OSError:
                    pass

    def snapshot(self) -> list:
        now, wall = self.monotonic(), time.time()
        with self.lock:
            self._prune()
            items = [item for item in self.items.values() if item.state != "waiting"]
        rows = []
        for item in items:
            row = {"id": item.id, "name": item.name, "size": item.size, "source": item.source, "route": "lan",
                   "mime": "application/octet-stream", "state": "ready" if item.state == "saving" else item.state,
                   "progress": round(item.received / item.size, 3) if item.size else 1.0, "error": item.error,
                   "source_name": self.c.device_name(item.source)}
            if item.state in ("ready", "saving"):
                row["expires_at"] = int(wall + READY_SECONDS - (now - item.ready_at))
            rows.append(row)
        return rows
