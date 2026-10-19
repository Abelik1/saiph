# SPDX-License-Identifier: AGPL-3.0-or-later
"""Connect a phone on the same network without scanning a QR code.

The QR code's job during linking is to give the phone the main computer's
signed root code over a channel nobody else controls: the owner's own camera.
This module replaces that channel with the local network plus a six-digit
comparison code, then hands the result to the unchanged approval path.

Only the main computer listens, only after its owner opens Add a device,
for at most five minutes and a bounded number of attempts. Protocol (JSON
lines over TCP; Android's `LanLink.kt` is the phone half):

  phone -> computer  link.hello   commit = H(phone ephemeral key, phone nonce), name
  computer -> phone  link.root    signed root code, computer ephemeral key, nonce
  phone -> computer  link.reveal  phone ephemeral key, phone nonce (checked against commit)
  both               code = six digits of H(transcript)
  phone -> computer  link.request phone's signed request code, MAC under ECDH key
  computer -> phone  link.received MAC: the request arrived intact

Security. The phone commits to its key and nonce before it sees the computer's,
and the computer's nonce is fresh, so a man in the middle on the network gets
one guess at a matching code per attempt: about one in a million. Both screens
show the code and both owners' confirmations are required: the phone confirms
before it pins the computer's keys; the computer approves only the request
authenticated under the compared transcript, with native owner verification
(Windows Hello) in `HostedController.approve`. A compromised account or relay
is not on this channel at all, and a network attacker is not the relay, so
neither alone can add a device. Codes never auto-approve.

Discovery is a UDP query answered with the computer's display name and TCP
port, only to private IPv4 senders. It carries no keys and grants nothing.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import socket
import threading
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

VERSION = 1
DISCOVERY_PORT = 47390
WINDOW_SECONDS = 300
MAX_ATTEMPTS = 8
MAX_LINE = 8192
STEP_SECONDS = 20
CONFIRM_SECONDS = 240  # The phone's owner reads the code and taps.
_B64 = re.compile(r"[A-Za-z0-9_-]+")


class LinkError(ValueError):
    def __init__(self, message="The phone could not be connected over this network. Scan the code instead."):
        super().__init__(message)


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def unb64(value, size: int) -> bytes:
    if type(value) is not str or not _B64.fullmatch(value):
        raise LinkError()
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError:
        raise LinkError() from None
    if len(raw) != size or b64(raw) != value:
        raise LinkError()
    return raw


def _framed(*parts: bytes) -> bytes:
    return b"".join(len(part).to_bytes(4, "big") + part for part in parts)


def commitment(ephemeral: bytes, nonce: bytes) -> bytes:
    return hashlib.sha256(b"saiph-link-commit-v1\0" + _framed(ephemeral, nonce)).digest()


def transcript(root_code: str, commit: bytes, phone_key: bytes, computer_key: bytes, phone_nonce: bytes,
               computer_nonce: bytes) -> bytes:
    return hashlib.sha256(b"saiph-link-transcript-v1\0" + _framed(
        root_code.encode("ascii"), commit, phone_key, computer_key, phone_nonce, computer_nonce)).digest()


def comparison_code(digest: bytes) -> str:
    value = int.from_bytes(hashlib.sha256(b"saiph-link-code-v1\0" + digest).digest()[:8], "big") % 1_000_000
    return f"{value // 1000:03d} {value % 1000:03d}"


def mac_key(shared: bytes, digest: bytes) -> bytes:
    return HKDF(hashes.SHA256(), 32, digest, b"saiph-link-mac-v1").derive(shared)


def request_mac(key: bytes, code: str) -> bytes:
    return hmac.new(key, b"saiph-link-request-v1\0" + code.encode("ascii"), hashlib.sha256).digest()


def received_mac(key: bytes, code: str) -> bytes:
    return hmac.new(key, b"saiph-link-received-v1\0" + code.encode("ascii"), hashlib.sha256).digest()


def ephemeral():
    private = ec.generate_private_key(ec.SECP256R1())
    return private, private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)


def shared_secret(private, peer: bytes) -> bytes:
    try:
        public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), peer)
    except ValueError:
        raise LinkError() from None
    return private.exchange(ec.ECDH(), public)


def clean_name(value) -> str:
    if type(value) is not str:
        raise LinkError()
    name = "".join(ch for ch in value if ch.isprintable()).strip()[:40].strip()
    return name or "Phone"


def encode(message: dict) -> bytes:
    raw = json.dumps(message, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"
    if len(raw) > MAX_LINE:
        raise LinkError()
    return raw


def decode(raw: bytes, kind: str, keys: set) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise LinkError() from None
    if type(value) is not dict or value.get("type") != kind or set(value) != {"type", *keys}:
        raise LinkError()
    return value


def private_ipv4(address: str, *, loopback=False) -> bool:
    try:
        value = ipaddress.IPv4Address(address)
    except ValueError:
        return False
    return (value.is_private and not value.is_link_local and not value.is_loopback and not value.is_unspecified
            and any(value in ipaddress.ip_network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
            ) or (loopback and value.is_loopback)


class ComputerHandshake:
    """The main computer's half, independent of sockets so tests can drive it directly."""

    def __init__(self, root_code: str):
        self.root_code = root_code
        self.private, self.public = ephemeral()
        self.nonce = secrets.token_bytes(32)
        self.commit = self.code = self.key = self.request = None
        self.name = "Phone"

    def hello(self, raw: bytes) -> bytes:
        message = decode(raw, "link.hello", {"version", "commit", "name"})
        if type(message["version"]) is not int or message["version"] != VERSION:
            raise LinkError("Update Saiph on your phone to connect without a code.")
        self.commit = unb64(message["commit"], 32)
        self.name = clean_name(message["name"])
        return encode({"type": "link.root", "root_code": self.root_code, "ephemeral": b64(self.public),
                       "nonce": b64(self.nonce)})

    def reveal(self, raw: bytes) -> str:
        message = decode(raw, "link.reveal", {"ephemeral", "nonce"})
        phone_key, phone_nonce = unb64(message["ephemeral"], 65), unb64(message["nonce"], 32)
        if not hmac.compare_digest(commitment(phone_key, phone_nonce), self.commit):
            raise LinkError()
        digest = transcript(self.root_code, self.commit, phone_key, self.public, phone_nonce, self.nonce)
        self.key = mac_key(shared_secret(self.private, phone_key), digest)
        self.code = comparison_code(digest)
        return self.code

    def receive_request(self, raw: bytes, verify) -> bytes:
        """Accept only a request authenticated under this transcript; `verify` checks it against the root."""
        message = decode(raw, "link.request", {"code", "mac"})
        code = message["code"]
        if type(code) is not str or not 0 < len(code) <= 4096 or not code.isascii():
            raise LinkError()
        if not hmac.compare_digest(request_mac(self.key, code), unb64(message["mac"], 32)):
            raise LinkError()
        verify(code)
        self.request = code
        return encode({"type": "link.received", "mac": b64(received_mac(self.key, code))})


class PhoneHandshake:
    """The phone's half. Android implements the same steps; this one serves tests and vectors."""

    def __init__(self, name="Phone"):
        self.private, self.public = ephemeral()
        self.nonce = secrets.token_bytes(32)
        self.commit = commitment(self.public, self.nonce)
        self.name = name
        self.root_code = self.code = self.key = None

    def hello(self) -> bytes:
        return encode({"type": "link.hello", "version": VERSION, "commit": b64(self.commit), "name": self.name})

    def root(self, raw: bytes) -> bytes:
        message = decode(raw, "link.root", {"root_code", "ephemeral", "nonce"})
        if type(message["root_code"]) is not str or not message["root_code"].isascii() or len(message["root_code"]) > 4096:
            raise LinkError()
        computer_key, computer_nonce = unb64(message["ephemeral"], 65), unb64(message["nonce"], 32)
        self.root_code = message["root_code"]
        digest = transcript(self.root_code, self.commit, self.public, computer_key, self.nonce, computer_nonce)
        self.key = mac_key(shared_secret(self.private, computer_key), digest)
        self.code = comparison_code(digest)
        return encode({"type": "link.reveal", "ephemeral": b64(self.public), "nonce": b64(self.nonce)})

    def request(self, code: str) -> bytes:
        return encode({"type": "link.request", "code": code, "mac": b64(request_mac(self.key, code))})

    def received(self, raw: bytes, code: str) -> None:
        message = decode(raw, "link.received", {"mac"})
        if not hmac.compare_digest(received_mac(self.key, code), unb64(message["mac"], 32)):
            raise LinkError()


def _readline(stream, deadline: float) -> bytes:
    stream.settimeout(max(0.1, deadline - time.monotonic()))
    data = bytearray()
    while not data.endswith(b"\n"):
        chunk = stream.recv(1)
        if not chunk:
            raise LinkError()
        data += chunk
        if len(data) > MAX_LINE:
            raise LinkError()
    return bytes(data[:-1])


class LinkListener:
    """Answers discovery and runs one handshake at a time while the owner's window is open."""

    def __init__(self, *, root_code, label, verify, changed=lambda: None, discovery_port=DISCOVERY_PORT,
                 allow_loopback=False, clock=time.monotonic):
        self.root_code, self.label, self.verify, self.changed = root_code, label, verify, changed
        self.discovery_port, self.allow_loopback, self.clock = discovery_port, allow_loopback, clock
        self.lock = threading.RLock()
        self.udp = self.tcp = None
        self.deadline = 0.0
        self.attempts = 0
        self.peer = None  # {"name", "code", "state", "request"}; request never leaves this process.
        self.error = ""
        self.generation = 0

    # --------------------------------------------------------------- control
    def start(self) -> dict:
        with self.lock:
            if self.tcp is not None:
                self.deadline = self.clock() + WINDOW_SECONDS
                return self.status()
            udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    udp.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                udp.bind(("0.0.0.0", self.discovery_port))
                tcp.bind(("0.0.0.0", 0))
                tcp.listen(2)
            except OSError:
                udp.close(); tcp.close()
                raise LinkError("Another Saiph window is already looking for phones on this network. Scan the code instead.") from None
            udp.settimeout(0.5); tcp.settimeout(0.5)
            self.udp, self.tcp = udp, tcp
            self.generation += 1
            self.deadline = self.clock() + WINDOW_SECONDS
            self.attempts, self.peer, self.error = 0, None, ""
            epoch = self.generation
            threading.Thread(target=self._discovery, args=(epoch,), name="saiph-link-discovery", daemon=True).start()
            threading.Thread(target=self._accept, args=(epoch,), name="saiph-link-accept", daemon=True).start()
            return self.status()

    def stop(self) -> dict:
        with self.lock:
            udp, tcp = self.udp, self.tcp
            self.udp = self.tcp = None
            self.peer, self.generation = None, self.generation + 1
        for value in (udp, tcp):
            if value is not None:
                value.close()
        return {"listening": False}

    def status(self) -> dict:
        with self.lock:
            if self.tcp is not None and self.clock() >= self.deadline:
                threading.Thread(target=self.stop, daemon=True).start()
            listening = self.tcp is not None and self.clock() < self.deadline
            peer = None
            if self.peer and self.peer["state"] in ("comparing", "requested"):
                peer = {"name": self.peer["name"], "code": self.peer["code"], "state": self.peer["state"]}
            return {"listening": listening, "expires_in": max(0, int(self.deadline - self.clock())) if listening else 0,
                    "peer": peer, "error": self.error}

    def take_request(self, code: str):
        """The authenticated request for the comparison code the owner approved, once."""
        with self.lock:
            peer = self.peer
            if (peer is None or peer["state"] != "requested" or type(code) is not str
                    or not hmac.compare_digest(peer["code"].encode(), code.encode())):
                raise LinkError("This phone's request changed. Compare the code on both screens again.")
            peer["state"] = "approving"
            return peer["request"], peer["name"]

    def finish(self, approved: bool):
        """After approval the window closes (one phone per window); otherwise the owner may retry."""
        with self.lock:
            if approved:
                self.peer = None
                self.deadline = self.clock()
            elif self.peer is not None and self.peer["state"] == "approving":
                self.peer["state"] = "requested"

    # --------------------------------------------------------------- network
    def _live(self, epoch) -> bool:
        with self.lock:
            return self.generation == epoch and self.tcp is not None and self.clock() < self.deadline

    def _discovery(self, epoch):
        udp = self.udp
        while self._live(epoch):
            try:
                raw, (address, port) = udp.recvfrom(512)
            except socket.timeout:
                continue
            except OSError:
                return
            if not private_ipv4(address, loopback=self.allow_loopback):
                continue
            try:
                query = decode(raw, "link.discover", {"version", "nonce"})
                if query["version"] != VERSION or type(query["version"]) is not int:
                    continue
                unb64(query["nonce"], 16)
                with self.lock:
                    tcp_port = self.tcp.getsockname()[1] if self.tcp is not None else None
                if tcp_port is None:
                    return
                udp.sendto(encode({"type": "link.here", "version": VERSION, "nonce": query["nonce"],
                                   "name": clean_name(self.label()), "port": tcp_port}), (address, port))
            except (LinkError, OSError):
                continue

    def _accept(self, epoch):
        tcp = self.tcp
        while self._live(epoch):
            try:
                connection, (address, _) = tcp.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self.lock:
                busy = self.peer is not None and self.peer["state"] in ("connecting", "comparing", "requested", "approving")
                allowed = private_ipv4(address, loopback=self.allow_loopback) and not busy and self.attempts < MAX_ATTEMPTS
                if allowed:
                    self.attempts += 1
                    self.peer = {"name": "Phone", "code": "", "state": "connecting", "request": None}
            if not allowed:
                connection.close()
                continue
            threading.Thread(target=self._handshake, args=(epoch, connection), name="saiph-link-handshake", daemon=True).start()

    def _handshake(self, epoch, connection):
        peer = self.peer
        try:
            with connection:
                computer = ComputerHandshake(self.root_code())
                connection.sendall(computer.hello(_readline(connection, self.clock() + STEP_SECONDS)))
                code = computer.reveal(_readline(connection, self.clock() + STEP_SECONDS))
                with self.lock:
                    if not self._live(epoch) or self.peer is not peer:
                        return
                    peer.update(name=computer.name, code=code, state="comparing")
                self.changed()
                reply = computer.receive_request(_readline(connection, self.clock() + CONFIRM_SECONDS), self.verify)
                with self.lock:
                    if not self._live(epoch) or self.peer is not peer:
                        return
                    peer.update(state="requested", request=computer.request)
                connection.sendall(reply)
                self.changed()
        except (LinkError, OSError, ValueError):
            with self.lock:
                if self.peer is peer and peer["state"] in ("connecting", "comparing"):
                    self.peer = None
                    self.error = "The phone stopped connecting. Try again on the phone, or scan the code."
            self.changed()


def discover(port=DISCOVERY_PORT, *, targets=("255.255.255.255",), timeout=1.5, allow_loopback=False) -> list[dict]:
    """The phone's discovery query; Android implements the same. Returns [{"name","address","port"}]."""
    nonce = b64(secrets.token_bytes(16))
    found = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp.settimeout(0.2)
        for target in targets:
            udp.sendto(encode({"type": "link.discover", "version": VERSION, "nonce": nonce}), (target, port))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw, (address, _) = udp.recvfrom(1024)
            except socket.timeout:
                continue
            try:
                answer = decode(raw, "link.here", {"version", "nonce", "name", "port"})
            except LinkError:
                continue
            if (answer["nonce"] == nonce and private_ipv4(address, loopback=allow_loopback)
                    and type(answer["port"]) is int and 1024 <= answer["port"] <= 65535):
                found[(address, answer["port"])] = {"name": clean_name(answer["name"]), "address": address, "port": answer["port"]}
    return list(found.values())
