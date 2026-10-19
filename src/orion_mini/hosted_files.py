# SPDX-License-Identifier: AGPL-3.0-or-later
"""Client-only encrypted attachment bytes and encrypted descriptive metadata.

Tink streaming AEAD encrypts a file; its one-file key and sensitive metadata
travel only inside the approved recipient's existing HPKE envelope. The relay
receives an opaque bounded blob. No key, filename, MIME or plaintext is logged.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from uuid import UUID, uuid4

import tink
from tink import proto_keyset_format, secret_key_access, streaming_aead
from tink.proto import aes_gcm_hkdf_streaming_pb2, common_pb2, tink_pb2

from .hosted_crypto import canonical
from .hosted_keys import _no_links, _windows_acl

streaming_aead.register()
CHUNK_BYTES = 32_768
MAX_CIPHERTEXT = 20 * 1024 * 1024
DOMAIN = b"Orion hosted attachment v1\0"


class AttachmentError(ValueError):
    def __init__(self):
        super().__init__("Encrypted attachment is unavailable.")


class AttachmentPublicationUncertain(AttachmentError):
    """Verified bytes already exist; callers must not blindly retry/overwrite."""
    def __init__(self):
        ValueError.__init__(self, "Attachment was verified and published; final durability is uncertain.")


@dataclass(frozen=True)
class PreparedAttachment:
    ciphertext: Path
    descriptor: dict
    envelope: dict


def _digest(path):
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as source:
        while chunk := source.read(65_536):
            size += len(chunk)
            if size > MAX_CIPHERTEXT:
                raise AttachmentError()
            digest.update(chunk)
    return size, digest.hexdigest()


def _filename(name):
    if (type(name) is not str or not name or len(name) > 255 or name in (".", "..")
            or name[-1] in " ." or any(ord(c) < 32 or c in '/\\:*?"<>|' for c in name)
            or name.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}):
        raise AttachmentError()
    return name


def _keyset(encoded):
    """Only the single maintained streaming suite used by this protocol."""
    if type(encoded) is not str or len(encoded) > 2048:
        raise AttachmentError()
    raw = base64.b64decode(encoded, validate=True)
    if not raw or len(raw) > 1024 or base64.b64encode(raw).decode() != encoded:
        raise AttachmentError()
    keyset = tink_pb2.Keyset.FromString(raw)
    if len(keyset.key) != 1:
        raise AttachmentError()
    entry = keyset.key[0]
    if (entry.key_id != keyset.primary_key_id or entry.status != tink_pb2.ENABLED
            or entry.output_prefix_type != tink_pb2.RAW or entry.key_data.key_material_type != tink_pb2.KeyData.SYMMETRIC
            or entry.key_data.type_url != "type.googleapis.com/google.crypto.tink.AesGcmHkdfStreamingKey"):
        raise AttachmentError()
    value = aes_gcm_hkdf_streaming_pb2.AesGcmHkdfStreamingKey.FromString(entry.key_data.value)
    if (value.version != 0 or len(value.key_value) != 32 or value.params.derived_key_size != 32
            or value.params.hkdf_hash_type != common_pb2.SHA256 or value.params.ciphertext_segment_size != 1_048_576):
        raise AttachmentError()
    return proto_keyset_format.parse(raw, secret_key_access.TOKEN).primitive(streaming_aead.StreamingAead)


def prepare_attachment(session, target, source: Path, ciphertext_folder: Path, *, kind="file", mime="application/octet-stream", ttl_seconds=300):
    path, created = None, False
    try:
        source, folder = Path(source), Path(ciphertext_folder)
        if (kind not in ("file", "photo", "clipboard.image") or type(mime) is not str
                or not re.fullmatch(r"[a-z0-9.+-]{1,63}/[a-z0-9.+-]{1,63}", mime)
                or type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 300
                or not source.is_absolute() or not folder.is_absolute() or not folder.is_dir()):
            raise AttachmentError()
        _no_links(source)
        _no_links(folder)
        name = _filename(source.name)
        members = session.current()
        if target not in members or target == session.device:
            raise AttachmentError()
        blob_id = str(uuid4())
        binding = {"protocol_version": 1, "deployment_id": session.deployment, "id": blob_id,
                   "roster_version": session.roster["version"], "roster_hash": session.digest,
                   "source": session.device, "target": target, "expires_at": int(time.time()) + ttl_seconds}
        key = tink.new_keyset_handle(streaming_aead.streaming_aead_key_templates.AES256_GCM_HKDF_1MB)
        primitive = key.primitive(streaming_aead.StreamingAead)
        path = folder / (blob_id + ".orion-sealed")
        digest, count = hashlib.sha256(), 0
        fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        with os.fdopen(fd, "rb") as incoming:
            before = os.fstat(incoming.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_CIPHERTEXT - 4096:
                raise AttachmentError()
            out_fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
            created = True
            with os.fdopen(out_fd, "wb") as output:
                with primitive.new_encrypting_stream(output, DOMAIN + canonical(binding)) as encrypted:
                    while chunk := incoming.read(65_536):
                        count += len(chunk)
                        if count > MAX_CIPHERTEXT - 4096:
                            raise AttachmentError()
                        digest.update(chunk)
                        encrypted.write(chunk)
            after = os.fstat(incoming.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino) or count != before.st_size:
                raise AttachmentError()
        with path.open("r+b") as finished:
            finished.flush()
            os.fsync(finished.fileno())
        size, ciphertext_hash = _digest(path)
        session.current()
        remaining = binding["expires_at"] - int(time.time())
        if (remaining <= 0 or session.roster["version"] != binding["roster_version"] or session.digest != binding["roster_hash"]):
            raise AttachmentError()
        payload = {"type": "file.encrypted", "kind": kind, "name": name, "mime": mime,
                   "size": count, "sha256": digest.hexdigest(), "blob": binding,
                   "ciphertext_size": size, "ciphertext_sha256": ciphertext_hash,
                   "keyset": base64.b64encode(proto_keyset_format.serialize(key, secret_key_access.TOKEN)).decode()}
        envelope = session.encrypt(target, payload, ttl_seconds=remaining)
        descriptor = {"id": blob_id, "target": target, "roster_version": binding["roster_version"],
                      "roster_hash": binding["roster_hash"], "expires_at": binding["expires_at"], "size": size, "sha256": ciphertext_hash}
        return PreparedAttachment(path, descriptor, envelope)
    except Exception:
        if created:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass  # At worst an opaque partial ciphertext remains locally.
        raise AttachmentError() from None


def upload_attachment(transport, prepared: PreparedAttachment):
    """Retries use the same allocation/chunks/HPKE event, including lost replies."""
    try:
        _no_links(prepared.ciphertext)
        if _digest(prepared.ciphertext) != (prepared.descriptor["size"], prepared.descriptor["sha256"]):
            raise AttachmentError()
        transport.allocate_blob(prepared.descriptor)
        with prepared.ciphertext.open("rb") as incoming:
            index = 0
            while chunk := incoming.read(CHUNK_BYTES):
                transport.upload_blob_chunk(prepared.descriptor["id"], index, chunk)
                index += 1
        transport.complete_blob(prepared.descriptor["id"])
        return transport.publish(prepared.envelope)
    except Exception:
        # Preserve prepared ciphertext and event for an exact later retry.
        raise AttachmentError() from None


def _manifest(session, envelope):
    payload = session.authenticate(envelope)
    if payload.get("type") == "photo.original":
        if (set(payload) != {"type", "photo_id", "request", "file"} or type(payload["photo_id"]) is not str
                or not re.fullmatch(r"[1-9][0-9]{0,15}", payload["photo_id"]) or int(payload["photo_id"]) > (1 << 53) - 1
                or type(payload["request"]) is not str or str(UUID(payload["request"])) != payload["request"]
                or type(payload["file"]) is not dict):
            raise AttachmentError()
        payload = payload["file"]
    elif payload.get("type") == "sms.attachment.original":
        # One MMS part this computer asked for (thread, message, part); same file manifest.
        if (set(payload) != {"type", "thread", "message", "part", "request", "file"}
                or any(type(payload[key]) is not int or not 0 <= payload[key] <= (1 << 53) - 1 for key in ("thread", "message", "part"))
                or type(payload["request"]) is not str or str(UUID(payload["request"])) != payload["request"]
                or type(payload["file"]) is not dict):
            raise AttachmentError()
        payload = payload["file"]
    expected ={"type", "kind", "name", "mime", "size", "sha256", "blob", "ciphertext_size", "ciphertext_sha256", "keyset"}
    if (set(payload) != expected or payload["type"] != "file.encrypted" or payload["kind"] not in ("file", "photo", "clipboard.image")
            or type(payload["size"]) is not int or not 0 <= payload["size"] <= MAX_CIPHERTEXT - 4096
            or type(payload["ciphertext_size"]) is not int or not 1 <= payload["ciphertext_size"] <= MAX_CIPHERTEXT
            or type(payload["mime"]) is not str or not re.fullmatch(r"[a-z0-9.+-]{1,63}/[a-z0-9.+-]{1,63}", payload["mime"])):
        raise AttachmentError()
    _filename(payload["name"])
    for name in ("sha256", "ciphertext_sha256"):
        if type(payload[name]) is not str or not re.fullmatch(r"[a-f0-9]{64}", payload[name]):
            raise AttachmentError()
    binding, header = payload["blob"], envelope["header"]
    if (type(binding) is not dict or set(binding) != {"protocol_version", "deployment_id", "id", "roster_version", "roster_hash", "source", "target", "expires_at"}
            or str(UUID(binding["id"])) != binding["id"]
            or any(binding[name] != header[name] for name in ("protocol_version", "deployment_id", "roster_version", "roster_hash", "source", "target"))
            or type(binding["expires_at"]) is not int or not int(time.time()) < binding["expires_at"] <= header["expires_at"]):
        raise AttachmentError()
    return payload, _keyset(payload["keyset"])


def download_attachment(session, transport, envelope, destination: Path):
    """Verify complete bytes before exposing a new file; never overwrite one.

    The destination is explicitly selected locally. Decrypted metadata never
    selects a filesystem path. Hard-link publication requires NTFS/ext4 or an
    equivalent local filesystem; no unsafe overwrite fallback is supplied.
    """
    published = False
    try:
        destination = Path(destination)
        if not destination.is_absolute() or not destination.parent.is_dir() or destination.exists():
            raise AttachmentError()
        _no_links(destination)
        payload, primitive = _manifest(session, envelope)
        binding = payload["blob"]
        with tempfile.TemporaryDirectory(prefix=".orion-receive-", dir=destination.parent) as temporary:
            folder = Path(temporary)
            folder.chmod(0o700)
            if os.name == "nt":
                _windows_acl(folder, set_private=True)
            ciphertext, cleartext = folder / "ciphertext", folder / "verified"
            count, digest = 0, hashlib.sha256()
            with ciphertext.open("xb") as output:
                for index in range((payload["ciphertext_size"] + CHUNK_BYTES - 1) // CHUNK_BYTES):
                    chunk = transport.download_blob_chunk(binding["id"], index)
                    expected = min(CHUNK_BYTES, payload["ciphertext_size"] - count)
                    if type(chunk) is not bytes or len(chunk) != expected:
                        raise AttachmentError()
                    count += len(chunk)
                    digest.update(chunk)
                    output.write(chunk)
            if count != payload["ciphertext_size"] or digest.hexdigest() != payload["ciphertext_sha256"]:
                raise AttachmentError()
            count, digest = 0, hashlib.sha256()
            fd = os.open(cleartext, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
            with os.fdopen(fd, "wb") as output, ciphertext.open("rb") as incoming:
                with primitive.new_decrypting_stream(incoming, DOMAIN + canonical(binding)) as decrypted:
                    while chunk := decrypted.read(65_536):
                        count += len(chunk)
                        if count > payload["size"]:
                            raise AttachmentError()
                        digest.update(chunk)
                        output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if count != payload["size"] or digest.hexdigest() != payload["sha256"]:
                raise AttachmentError()
            # No exposure after concurrent local expiry/revocation/renewal.
            _manifest(session, envelope)
            _no_links(destination)
            os.link(cleartext, destination)
            published = True
            if os.name != "nt":
                directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        return destination
    except Exception:
        if published:
            raise AttachmentPublicationUncertain() from None
        raise AttachmentError() from None
