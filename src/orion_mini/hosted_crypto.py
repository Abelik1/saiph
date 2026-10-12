# SPDX-License-Identifier: AGPL-3.0-or-later
"""Client-only encrypted-envelope foundation; not a complete E2EE integration.

Tink HPKE supplies encryption, while the existing P-256 device identity signs
the routing header and payload. Keys remain in caller-owned KeysetHandles: this
module never writes keys or content. Trusted-roster verification, expiry,
replay protection and secure local key storage belong to the integration.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from uuid import UUID

import tink
from tink import hybrid, proto_keyset_format
from tink.proto import hpke_pb2, tink_pb2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

hybrid.register()

MAX_CIPHERTEXT_BYTES = 49_152
MAX_PLAINTEXT_BYTES = 24_000
MAX_PUBLIC_KEYSET_BYTES = 1_024
_MAX_SAFE_INTEGER = (1 << 53) - 1
_HEADER_KEYS = {"protocol_version", "deployment_id", "roster_version", "roster_hash", "id", "source", "target", "expires_at"}
_SIGN_DOMAIN = b"Orion/hosted-envelope/signature/v1\x00"
_CONTEXT_DOMAIN = b"Orion/hosted-envelope/context/v1\x00"
_PUBLIC_TYPE = "type.googleapis.com/google.crypto.tink.HpkePublicKey"


class EnvelopeError(ValueError):
    """Safe error without ciphertext, key material or content in its message."""


def canonical(value: object) -> bytes:
    """Bounded, deterministic ASCII JSON; reject non-JSON values and floats.

    Integer values use the interoperable exact-integer range. Floats are
    excluded to avoid inconsistent signed representations across runtimes.
    """
    remaining = 8_192
    string_budget = MAX_CIPHERTEXT_BYTES

    def check(item: object, depth: int) -> None:
        nonlocal remaining, string_budget
        remaining -= 1
        if remaining < 0 or depth > 16:
            raise EnvelopeError("Invalid envelope data.")
        if item is None or type(item) is bool:
            return
        if type(item) is int:
            if abs(item) > _MAX_SAFE_INTEGER:
                raise EnvelopeError("Invalid envelope data.")
            return
        if type(item) is str:
            string_budget -= len(item)
            if string_budget < 0 or any(0xD800 <= ord(c) <= 0xDFFF for c in item):
                raise EnvelopeError("Invalid envelope data.")
            return
        if type(item) is list:
            for child in item:
                check(child, depth + 1)
            return
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise EnvelopeError("Invalid envelope data.")
                check(key, depth + 1)
                check(child, depth + 1)
            return
        raise EnvelopeError("Invalid envelope data.")

    check(value, 0)
    result = json.dumps(value, ensure_ascii=True, allow_nan=False,
                        sort_keys=True, separators=(",", ":")).encode("ascii")
    if len(result) > MAX_CIPHERTEXT_BYTES:
        raise EnvelopeError("Invalid envelope data.")
    return result


def validate_header(header: dict) -> None:
    """Validate routing fields; deliberately does not authorize or check time."""
    if type(header) is not dict or header.keys() != _HEADER_KEYS:
        raise EnvelopeError("Invalid envelope header.")
    if type(header["protocol_version"]) is not int or header["protocol_version"] != 1:
        raise EnvelopeError("Invalid envelope header.")
    if type(header["roster_hash"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", header["roster_hash"]):
        raise EnvelopeError("Invalid envelope header.")
    for name in ("deployment_id", "id"):
        value = header[name]
        if type(value) is not str or len(value) != 36:
            raise EnvelopeError("Invalid envelope header.")
        try:
            if str(UUID(value)) != value:
                raise ValueError
        except ValueError:
            raise EnvelopeError("Invalid envelope header.") from None
    for name in ("source", "target"):
        if type(header[name]) is not str or not re.fullmatch(r"dev_[a-f0-9]{32}", header[name]):
            raise EnvelopeError("Invalid envelope header.")
    if type(header["roster_version"]) is not int or not 1 <= header["roster_version"] <= _MAX_SAFE_INTEGER:
        raise EnvelopeError("Invalid envelope header.")
    if type(header["expires_at"]) is not int or not 1 <= header["expires_at"] <= 253_402_300_799:
        raise EnvelopeError("Invalid envelope header.")


def _decode(value: str, limit: int) -> bytes:
    if type(value) is not str or not value or len(value) > 4 * ((limit + 2) // 3):
        raise EnvelopeError("Invalid encoded envelope data.")
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise EnvelopeError("Invalid encoded envelope data.") from None
    if len(result) > limit or base64.b64encode(result).decode("ascii") != value:
        raise EnvelopeError("Invalid encoded envelope data.")
    return result


def _validate_public(serialized: bytes) -> tink.KeysetHandle:
    if not serialized or len(serialized) > MAX_PUBLIC_KEYSET_BYTES:
        raise EnvelopeError("Invalid recipient key.")
    try:
        keyset = tink_pb2.Keyset.FromString(serialized)
        if len(keyset.key) != 1:
            raise ValueError
        entry = keyset.key[0]
        if (entry.status != tink_pb2.ENABLED or entry.key_id != keyset.primary_key_id
                or entry.output_prefix_type != tink_pb2.TINK
                or entry.key_data.key_material_type != tink_pb2.KeyData.ASYMMETRIC_PUBLIC
                or entry.key_data.type_url != _PUBLIC_TYPE):
            raise ValueError
        public = hpke_pb2.HpkePublicKey.FromString(entry.key_data.value)
        if (public.version != 0 or len(public.public_key) != 32
                or public.params.kem != hpke_pb2.DHKEM_X25519_HKDF_SHA256
                or public.params.kdf != hpke_pb2.HKDF_SHA256
                or public.params.aead != hpke_pb2.AES_256_GCM):
            raise ValueError
        handle = proto_keyset_format.parse_without_secret(serialized)
        handle.primitive(hybrid.HybridEncrypt)
        return handle
    except Exception:
        raise EnvelopeError("Invalid recipient key.") from None


def generate_recipient() -> tink.KeysetHandle:
    """Generate an in-memory HPKE recipient key; never use the signing key."""
    return tink.new_keyset_handle(
        hybrid.hybrid_key_templates.DHKEM_X25519_HKDF_SHA256_HKDF_SHA256_AES_256_GCM
    )


def export_public(handle: tink.KeysetHandle) -> str:
    """Export only a public keyset, accepting either private or public handles."""
    try:
        try:
            serialized = proto_keyset_format.serialize_without_secret(handle)
        except tink.TinkError:
            serialized = proto_keyset_format.serialize_without_secret(handle.public_keyset_handle())
        _validate_public(serialized)
        return base64.b64encode(serialized).decode("ascii")
    except Exception:
        raise EnvelopeError("Invalid recipient key.") from None


def read_public(value: str) -> tink.KeysetHandle:
    """Parse a bounded public-only keyset of the single supported HPKE suite."""
    return _validate_public(_decode(value, MAX_PUBLIC_KEYSET_BYTES))


def _public_handle(value: tink.KeysetHandle | str) -> tink.KeysetHandle:
    if type(value) is str:
        return read_public(value)
    try:
        return _validate_public(proto_keyset_format.serialize_without_secret(value))
    except Exception:
        raise EnvelopeError("Invalid recipient key.") from None


def _p256(key: object, private: bool) -> None:
    cls = ec.EllipticCurvePrivateKey if private else ec.EllipticCurvePublicKey
    if not isinstance(key, cls) or not isinstance(key.curve, ec.SECP256R1):
        raise EnvelopeError("Invalid signing key.")


def seal(recipient: tink.KeysetHandle | str, signing_private_key: ec.EllipticCurvePrivateKey,
         header: dict, payload: dict) -> str:
    """Sign the complete header/payload and HPKE-encrypt for one recipient."""
    validate_header(header)
    _p256(signing_private_key, True)
    if type(payload) is not dict:
        raise EnvelopeError("Invalid envelope data.")
    signed = _SIGN_DOMAIN + canonical({"header": header, "payload": payload})
    if len(canonical(payload)) > MAX_PLAINTEXT_BYTES:
        raise EnvelopeError("Envelope content is too large.")
    signature = signing_private_key.sign(signed, ec.ECDSA(hashes.SHA256()))
    plaintext = canonical({"payload": payload, "signature": base64.b64encode(signature).decode("ascii")})
    if len(plaintext) > MAX_PLAINTEXT_BYTES:
        raise EnvelopeError("Envelope content is too large.")
    try:
        ciphertext = _public_handle(recipient).primitive(hybrid.HybridEncrypt).encrypt(
            plaintext, _CONTEXT_DOMAIN + canonical(header))
    except Exception:
        raise EnvelopeError("Cannot encrypt envelope.") from None
    if len(ciphertext) > MAX_CIPHERTEXT_BYTES:
        raise EnvelopeError("Envelope content is too large.")
    return base64.b64encode(ciphertext).decode("ascii")


def _object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise EnvelopeError("Cannot open envelope.")
        result[key] = value
    return result


def open_envelope(recipient: tink.KeysetHandle, sender_public_P256: ec.EllipticCurvePublicKey,
                  header: dict, ciphertext: str) -> dict:
    """Decrypt and authenticate before returning any payload to the caller."""
    validate_header(header)
    _p256(sender_public_P256, False)
    raw = _decode(ciphertext, MAX_CIPHERTEXT_BYTES)
    try:
        plaintext = recipient.primitive(hybrid.HybridDecrypt).decrypt(
            raw, _CONTEXT_DOMAIN + canonical(header))
        if len(plaintext) > MAX_PLAINTEXT_BYTES:
            raise ValueError
        envelope = json.loads(plaintext, object_pairs_hook=_object)
        if type(envelope) is not dict or envelope.keys() != {"payload", "signature"}:
            raise ValueError
        payload = envelope["payload"]
        if type(payload) is not dict or canonical(envelope) != plaintext:
            raise ValueError
        signature = _decode(envelope["signature"], 80)
        sender_public_P256.verify(signature, _SIGN_DOMAIN + canonical({"header": header, "payload": payload}),
                                  ec.ECDSA(hashes.SHA256()))
        return payload
    except Exception:
        raise EnvelopeError("Cannot open envelope.") from None
