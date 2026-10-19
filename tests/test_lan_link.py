# SPDX-License-Identifier: AGPL-3.0-or-later
"""QR-less linking on the local network: protocol, attacks and the bounded listener.

Synthetic codes and loopback sockets only (the listener allows loopback only in
tests); nothing reaches a real network, account or device.
"""
import json
import socket
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from orion_mini import lan_link as L

ROOT = "orion-root-v1:" + json.dumps({"data": {"synthetic": True}, "signature": "AAAA"})
REQUEST = "orion-approve-v1:" + json.dumps({"data": {"synthetic": True}, "signature": "BBBB"})
VECTORS = json.loads((Path(__file__).resolve().parents[1] / "android" / "app" / "src" / "test" / "resources"
                      / "lan-link-vectors.json").read_text(encoding="utf-8"))


def run(phone, computer, request=REQUEST, verify=lambda code: None):
    reveal = phone.root(computer.hello(phone.hello()[:-1])[:-1])
    computer.reveal(reveal[:-1])
    phone.received(computer.receive_request(phone.request(request)[:-1], verify)[:-1], request)


def test_both_screens_show_the_same_code_and_the_request_is_authenticated():
    phone, computer = L.PhoneHandshake("Pixel"), L.ComputerHandshake(ROOT)
    run(phone, computer)
    assert phone.code == computer.code and len(phone.code) == 7 and phone.code[3] == " "
    assert phone.root_code == ROOT and computer.request == REQUEST and computer.name == "Pixel"


def test_shared_vectors_match_the_android_phone():
    v = VECTORS
    phone = ec.derive_private_key(int(v["phone_private"], 16), ec.SECP256R1())
    pk, ck = L.unb64(v["phone_public"], 65), L.unb64(v["computer_public"], 65)
    pn, cn = L.unb64(v["phone_nonce"], 32), L.unb64(v["computer_nonce"], 32)
    assert L.b64(L.commitment(pk, pn)) == v["commit"]
    digest = L.transcript(v["root_code"], L.unb64(v["commit"], 32), pk, ck, pn, cn)
    assert digest.hex() == v["transcript"] and L.comparison_code(digest) == v["code"]
    assert L.shared_secret(phone, ck).hex() == v["shared"]
    key = L.mac_key(bytes.fromhex(v["shared"]), digest)
    assert key.hex() == v["mac_key"]
    assert L.b64(L.request_mac(key, v["request_code"])) == v["request_mac"]
    assert L.b64(L.received_mac(key, v["request_code"])) == v["received_mac"]


def test_a_relay_that_substitutes_keys_cannot_force_matching_codes():
    # Man in the middle: separate handshakes with each side. Codes depend on fresh
    # nonces committed before the other side's are seen; matching is ~1e-6.
    mismatched = 0
    for _ in range(20):
        phone, computer = L.PhoneHandshake(), L.ComputerHandshake(ROOT)
        attacker_phone, attacker_computer = L.PhoneHandshake(), L.ComputerHandshake("orion-root-v1:attacker")
        phone.root(attacker_computer.hello(phone.hello()[:-1])[:-1])
        computer.reveal(attacker_phone.root(computer.hello(attacker_phone.hello()[:-1])[:-1])[:-1])
        mismatched += phone.code != computer.code
    assert mismatched == 20


def test_a_relay_that_passes_the_comparison_through_cannot_swap_the_request():
    phone, computer = L.PhoneHandshake(), L.ComputerHandshake(ROOT)
    computer.reveal(phone.root(computer.hello(phone.hello()[:-1])[:-1])[:-1])
    forged = L.encode({"type": "link.request", "code": "orion-approve-v1:attacker", "mac": L.b64(bytes(32))})
    with pytest.raises(L.LinkError):
        computer.receive_request(forged[:-1], lambda code: None)
    assert computer.request is None


def test_the_reveal_must_match_the_commitment():
    phone, computer = L.PhoneHandshake(), L.ComputerHandshake(ROOT)
    phone.root(computer.hello(phone.hello()[:-1])[:-1])
    other = L.PhoneHandshake()
    with pytest.raises(L.LinkError):
        computer.reveal(L.encode({"type": "link.reveal", "ephemeral": L.b64(other.public), "nonce": L.b64(phone.nonce)})[:-1])


def test_root_verification_failure_refuses_the_request():
    phone, computer = L.PhoneHandshake(), L.ComputerHandshake(ROOT)
    def refuse(code):
        raise ValueError("not for this root")
    with pytest.raises(ValueError):
        run(phone, computer, verify=refuse)
    assert computer.request is None


@pytest.mark.parametrize("raw", [
    b'{"type":"link.hello","version":1,"commit":"' + L.b64(bytes(32)).encode() + b'","name":"P","extra":1}',
    b'{"type":"link.hello","version":true,"commit":"' + L.b64(bytes(32)).encode() + b'","name":"P"}',
    b'{"type":"link.hello","version":2,"commit":"' + L.b64(bytes(32)).encode() + b'","name":"P"}',
    b'{"type":"link.hello","version":1,"commit":"' + L.b64(bytes(31)).encode() + b'","name":"P"}',
    b'{"type":"link.hello","version":1,"commit":"' + L.b64(bytes(32)).encode() + b'=","name":"P"}',
    b'{"type":"link.hello","version":1,"commit":"' + L.b64(bytes(32)).encode() + b'","name":7}',
    b'{"type":"link.root","version":1}',
    b'not json',
    '{"type":"link.hello","version":1,"commit":"x","name":"é"}'.encode(),
])
def test_messages_are_exact(raw):
    with pytest.raises(L.LinkError):
        L.ComputerHandshake(ROOT).hello(raw)


def test_invalid_curve_points_are_refused():
    phone, computer = L.PhoneHandshake(), L.ComputerHandshake(ROOT)
    root = json.loads(computer.hello(phone.hello()[:-1]))
    root["ephemeral"] = L.b64(b"\x04" + bytes(64))
    with pytest.raises(L.LinkError):
        phone.root(L.encode(root)[:-1])


def test_names_are_one_short_printable_line():
    assert L.clean_name("Pixel\n\x00 9 Pro" + "x" * 80) == ("Pixel 9 Pro" + "x" * 80)[:40]
    assert L.clean_name("   ") == "Phone"


@pytest.mark.parametrize("address, allowed", [
    ("192.168.1.7", True), ("10.0.0.2", True), ("172.20.1.1", True), ("8.8.8.8", False),
    ("127.0.0.1", False), ("169.254.1.1", False), ("100.64.0.1", False), ("::1", False), ("0.0.0.0", False)])
def test_only_private_ipv4_peers(address, allowed):
    assert L.private_ipv4(address) is allowed


# ---------------------------------------------------------------- listener
class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def listener():
    verified, changes = [], []
    value = L.LinkListener(root_code=lambda: ROOT, label=lambda: "Synthetic desk", verify=verified.append,
                           changed=lambda: changes.append(True), discovery_port=0, allow_loopback=True)
    value.start()
    value.verified = verified
    yield value
    value.stop()


def until(predicate, seconds=4):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert predicate()


def connect(listener):
    found = L.discover(listener.udp.getsockname()[1], targets=("127.0.0.1",), timeout=0.4, allow_loopback=True)
    assert [(row["name"], row["address"]) for row in found] == [("Synthetic desk", "127.0.0.1")]
    stream = socket.create_connection(("127.0.0.1", found[0]["port"]), timeout=4)
    return stream, stream.makefile("rb")


def test_discovery_handshake_and_approval_over_loopback(listener):
    stream, lines = connect(listener)
    phone = L.PhoneHandshake("Pixel")
    with stream:
        stream.sendall(phone.hello())
        stream.sendall(phone.root(lines.readline().rstrip(b"\n")))
        until(lambda: listener.status()["peer"] is not None)
        assert listener.status()["peer"] == {"name": "Pixel", "code": phone.code, "state": "comparing"}
        with pytest.raises(L.LinkError):
            listener.take_request(phone.code)  # Nothing to approve before the phone confirmed.
        stream.sendall(phone.request(REQUEST))
        phone.received(lines.readline().rstrip(b"\n"), REQUEST)
    until(lambda: (listener.status()["peer"] or {}).get("state") == "requested")
    assert listener.verified == [REQUEST]
    with pytest.raises(L.LinkError):
        listener.take_request("000 000")
    assert listener.take_request(phone.code) == (REQUEST, "Pixel")
    with pytest.raises(L.LinkError):
        listener.take_request(phone.code)  # Once.
    listener.finish(True)
    assert listener.status()["listening"] is False  # One phone per window.


def test_an_abandoned_handshake_frees_the_listener(listener):
    stream, lines = connect(listener)
    with stream:
        stream.sendall(b'{"type":"link.hello","version":9}\n')
        assert lines.readline() == b""
    until(lambda: listener.status()["error"] != "")
    assert listener.status()["peer"] is None


def test_attempts_are_bounded_per_window(listener):
    for _ in range(L.MAX_ATTEMPTS):
        stream, lines = connect(listener)
        with stream:
            stream.sendall(b"garbage\n")
            lines.readline()
        until(lambda: listener.peer is None)
    stream, lines = connect(listener)
    with stream:
        assert lines.readline() == b""  # Closed at once: the owner must open a new window.
    assert listener.attempts == L.MAX_ATTEMPTS


def test_window_closes_after_five_minutes():
    clock = Clock()
    value = L.LinkListener(root_code=lambda: ROOT, label=lambda: "Desk", verify=lambda code: None, discovery_port=0,
                           allow_loopback=True, clock=clock)
    try:
        assert value.start()["listening"] is True
        clock.now += L.WINDOW_SECONDS
        assert value.status()["listening"] is False
    finally:
        value.stop()


def test_a_second_listener_on_the_same_port_reports_a_clear_error(listener):
    other = L.LinkListener(root_code=lambda: ROOT, label=lambda: "Desk", verify=lambda code: None,
                           discovery_port=listener.udp.getsockname()[1], allow_loopback=True)
    with pytest.raises(L.LinkError, match="already looking"):
        other.start()
