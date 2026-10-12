# SPDX-License-Identifier: AGPL-3.0-or-later
"""Adversarial tests for the client envelope foundation, not E2EE acceptance."""
import base64
from uuid import uuid4

import pytest

pytest.importorskip("tink")
import tink
from tink import hybrid, proto_keyset_format
from tink.proto import hpke_pb2, tink_pb2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from orion_mini import hosted_crypto as crypto


@pytest.fixture
def identity():
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def recipient():
    return crypto.generate_recipient()


@pytest.fixture
def header():
    return {"protocol_version": 1, "deployment_id": str(uuid4()), "roster_version": 1,
            "roster_hash": "a" * 64, "id": str(uuid4()),
            "source": "dev_" + "1" * 32, "target": "dev_" + "2" * 32,
            "expires_at": 1_900_000_000}


def test_roundtrip_randomized_and_content_not_visible(identity, recipient, header):
    public = crypto.export_public(recipient)
    assert proto_keyset_format.serialize_without_secret(crypto.read_public(public)) == base64.b64decode(public)
    assert crypto.export_public(crypto.read_public(public)) == public
    payload = {"type": "clipboard.text", "text": "synthetic private test snowman \u2603", "details": [1, True, None]}
    first = crypto.seal(public, identity, header, payload)
    second = crypto.seal(crypto.read_public(public), identity, header, payload)
    assert first != second
    assert b"synthetic private test" not in base64.b64decode(first)
    assert crypto.open_envelope(recipient, identity.public_key(), header, first) == payload
    assert crypto.open_envelope(recipient, identity.public_key(), dict(reversed(list(header.items()))), second) == payload


def test_wrong_recipient_sender_and_tamper(identity, recipient, header):
    ciphertext = crypto.seal(crypto.export_public(recipient), identity, header, {"type": "test", "text": "private-marker"})
    failures = [
        (crypto.generate_recipient(), identity.public_key(), header, ciphertext),
        (recipient, ec.generate_private_key(ec.SECP256R1()).public_key(), header, ciphertext),
    ]
    raw = bytearray(base64.b64decode(ciphertext))
    raw[-1] ^= 1
    failures.append((recipient, identity.public_key(), header, base64.b64encode(raw).decode()))
    for name in header:
        if name == "protocol_version":
            continue  # Unsupported protocol is rejected by structural validation.
        changed = dict(header)
        changed[name] = str(uuid4()) if name in {"id", "deployment_id"} else (
            header[name] + 1 if name in {"expires_at", "roster_version"} else (
                "b" * 64 if name == "roster_hash" else "dev_" + "3" * 32))
        failures.append((recipient, identity.public_key(), changed, ciphertext))
    for args in failures:
        with pytest.raises(crypto.EnvelopeError, match="Cannot open envelope") as error:
            crypto.open_envelope(*args)
        assert "private-marker" not in str(error.value)
        assert error.value.__cause__ is None


@pytest.mark.parametrize("name,value", [
    ("roster_version", True), ("roster_version", 0), ("roster_version", 2**53),
    ("expires_at", 0), ("expires_at", False), ("expires_at", 1.5), ("expires_at", 253_402_300_800),
    ("source", "dev_" + "A" * 32), ("target", "dev_short"),
    ("id", "not-a-uuid"), ("id", "ABCDEFAB-ABCD-ABCD-ABCD-ABCDEFABCDEF"),
    ("deployment_id", None),
    ("protocol_version", True), ("protocol_version", 2), ("protocol_version", 1.0),
    ("roster_hash", "a" * 63), ("roster_hash", "G" * 64), ("roster_hash", None),
])
def test_invalid_headers(header, name, value):
    header[name] = value
    with pytest.raises(crypto.EnvelopeError, match="Invalid envelope header"):
        crypto.validate_header(header)


def test_header_fields_exact(header):
    for invalid in ({}, {**header, "type": "clipboard.text"}, {k: v for k, v in header.items() if k != "id"}, []):
        with pytest.raises(crypto.EnvelopeError):
            crypto.validate_header(invalid)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 1.25, 1.0, 2**53, -(2**53),
                                    {1: "value"}, {"value": object()}, ("tuple",), "\ud800"])
def test_canonical_rejects_non_json_and_unsafe_numbers(value):
    with pytest.raises(crypto.EnvelopeError):
        crypto.canonical(value)


def test_canonical_stable_bounded():
    assert crypto.canonical({"z": 1, "a": "\u2603"}) == b'{"a":"\\u2603","z":1}'
    for invalid in ([0] * 8_193, "a" * 49_153, "\u2603" * 9_000):
        with pytest.raises(crypto.EnvelopeError):
            crypto.canonical(invalid)
    deep = {}
    for _ in range(18):
        deep = {"inner": deep}
    with pytest.raises(crypto.EnvelopeError):
        crypto.canonical(deep)
    cycle = []
    cycle.append(cycle)
    with pytest.raises(crypto.EnvelopeError):
        crypto.canonical(cycle)


@pytest.mark.parametrize("encoded", ["", " ", "@@@@", "eA", "eA==\n", "eB==", "\u2603", None, b"eA=="])
def test_rejects_malformed_base64(identity, recipient, header, encoded):
    with pytest.raises(crypto.EnvelopeError):
        crypto.read_public(encoded)
    with pytest.raises(crypto.EnvelopeError):
        crypto.open_envelope(recipient, identity.public_key(), header, encoded)


def test_size_bounds(identity, recipient, header):
    with pytest.raises(crypto.EnvelopeError):
        crypto.read_public(base64.b64encode(b"x" * 1_025).decode())
    with pytest.raises(crypto.EnvelopeError):
        crypto.open_envelope(recipient, identity.public_key(), header, base64.b64encode(b"x" * 49_153).decode())
    with pytest.raises(crypto.EnvelopeError):
        crypto.seal(crypto.export_public(recipient), identity, header, {"text": "x" * 24_000})
    allowed = {"text": "x" * 23_700}
    ciphertext = crypto.seal(crypto.export_public(recipient), identity, header, allowed)
    assert crypto.open_envelope(recipient, identity.public_key(), header, ciphertext) == allowed


def test_private_keysets_not_accepted_as_public(recipient, identity, header):
    from tink import secret_key_access
    serialized = proto_keyset_format.serialize(recipient, secret_key_access.TOKEN)
    with pytest.raises(crypto.EnvelopeError):
        crypto.read_public(base64.b64encode(serialized).decode())
    with pytest.raises(crypto.EnvelopeError):
        crypto.seal(recipient, identity, header, {})


@pytest.mark.parametrize("mutation", ["algorithm", "disabled", "primary", "prefix", "extra", "length", "material", "type", "version"])
def test_public_keyset_restrictions(recipient, mutation):
    keyset = tink_pb2.Keyset.FromString(base64.b64decode(crypto.export_public(recipient)))
    entry = keyset.key[0]
    public = hpke_pb2.HpkePublicKey.FromString(entry.key_data.value)
    if mutation == "algorithm":
        public.params.aead = hpke_pb2.AES_128_GCM
    elif mutation == "disabled":
        entry.status = tink_pb2.DISABLED
    elif mutation == "primary":
        keyset.primary_key_id ^= 1
    elif mutation == "prefix":
        entry.output_prefix_type = tink_pb2.RAW
    elif mutation == "extra":
        keyset.key.add().CopyFrom(entry)
    elif mutation == "length":
        public.public_key = b"x" * 31
    elif mutation == "material":
        entry.key_data.key_material_type = tink_pb2.KeyData.ASYMMETRIC_PRIVATE
    elif mutation == "type":
        entry.key_data.type_url = "invalid"
    else:
        public.version = 1
    entry.key_data.value = public.SerializeToString()
    with pytest.raises(crypto.EnvelopeError):
        crypto.read_public(base64.b64encode(keyset.SerializeToString()).decode())


@pytest.mark.parametrize("badkey", [None, "key", ec.generate_private_key(ec.SECP384R1())])
def test_only_p256_signatures(identity, recipient, header, badkey):
    with pytest.raises(crypto.EnvelopeError):
        crypto.seal(crypto.export_public(recipient), badkey, header, {})
    ciphertext = crypto.seal(crypto.export_public(recipient), identity, header, {})
    with pytest.raises(crypto.EnvelopeError):
        crypto.open_envelope(recipient, badkey, header, ciphertext)


@pytest.mark.parametrize("plaintext", [
    b'{"payload":{},"payload":{},"signature":"eA=="}',
    b'{"payload":{"x":NaN},"signature":"eA=="}',
    b'{"payload":{},"signature":"eA==","unexpected":1}',
    b'{"payload":[],"signature":"eA=="}',
    b'not-json', b'\xff', b"x" * 24_001,
])
def test_malicious_public_sender_plaintexts_rejected(identity, recipient, header, plaintext):
    encryptor = crypto.read_public(crypto.export_public(recipient)).primitive(hybrid.HybridEncrypt)
    ciphertext = encryptor.encrypt(plaintext, crypto._CONTEXT_DOMAIN + crypto.canonical(header))
    with pytest.raises(crypto.EnvelopeError, match="Cannot open envelope"):
        crypto.open_envelope(recipient, identity.public_key(), header, base64.b64encode(ciphertext).decode())


def test_public_encryption_does_not_authenticate_sender(identity, recipient, header):
    # An operator with the public HPKE key can encrypt arbitrary content, but
    # cannot forge the trusted device's signature inside that ciphertext.
    attacker = ec.generate_private_key(ec.SECP256R1())
    payload = {"type": "call.answer"}
    signed = crypto._SIGN_DOMAIN + crypto.canonical({"header": header, "payload": payload})
    signature = attacker.sign(signed, ec.ECDSA(hashes.SHA256()))
    plaintext = crypto.canonical({"payload": payload, "signature": base64.b64encode(signature).decode()})
    encrypted = crypto.read_public(crypto.export_public(recipient)).primitive(hybrid.HybridEncrypt).encrypt(
        plaintext, crypto._CONTEXT_DOMAIN + crypto.canonical(header))
    with pytest.raises(crypto.EnvelopeError, match="Cannot open envelope"):
        crypto.open_envelope(recipient, identity.public_key(), header, base64.b64encode(encrypted).decode())


def test_expiry_and_replay_are_explicitly_callers_responsibility(identity, recipient, header):
    header["expires_at"] = 1
    ciphertext = crypto.seal(crypto.export_public(recipient), identity, header, {})
    assert crypto.open_envelope(recipient, identity.public_key(), header, ciphertext) == {}
    assert crypto.open_envelope(recipient, identity.public_key(), header, ciphertext) == {}
