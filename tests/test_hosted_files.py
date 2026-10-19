# SPDX-License-Identifier: AGPL-3.0-or-later
"""Actual streaming attachment bytes, explicit destination and failure safety."""
import base64
import copy
import hashlib
import time
from uuid import uuid4

import pytest
pytest.importorskip("tink")
from cryptography.hazmat.primitives.asymmetric import ec

from orion_mini.hosted_crypto import canonical, export_public, generate_recipient
from orion_mini.hosted_session import SealedSession, public_signing_key, sign_roster
from orion_mini.hosted_files import AttachmentError, AttachmentPublicationUncertain, prepare_attachment, upload_attachment, download_attachment


@pytest.fixture
def pair(tmp_path):
    deployment = str(uuid4())
    identities = [("dev_" + uuid4().hex, ec.generate_private_key(ec.SECP256R1()), generate_recipient()) for _ in range(2)]
    members = [{"id": device, "signing_key": public_signing_key(signing.public_key()), "encryption_key": export_public(recipient)}
               for device, signing, recipient in identities]
    first = sign_roster({"deployment_id": deployment, "version": 1, "previous_hash": None,
                         "expires_at": int(time.time()) + 3600, "members": members[:1]}, identities[0][1])
    second = sign_roster({**first["roster"], "version": 2, "previous_hash": hashlib.sha256(canonical(first["roster"])).hexdigest(),
                          "members": sorted(members, key=lambda m: m["id"])}, identities[0][1])
    sessions = [SealedSession(tmp_path / (device + ".sqlite3"), deployment, members[0]["signing_key"], device, signing, recipient)
                for device, signing, recipient in identities]
    for session in sessions:
        session.accept_chain([first, second])
    return *sessions, [first, second]


class BlobRelay:
    """Test storage only; actual HTTP/auth/server semantics have separate tests."""
    def __init__(self):
        self.descriptor, self.chunks, self.envelope = None, {}, None
        self.fail_once, self.ready = None, False

    def allocate_blob(self, descriptor):
        if self.descriptor is not None:
            assert descriptor == self.descriptor
        self.descriptor = copy.deepcopy(descriptor)

    def upload_blob_chunk(self, blob_id, index, data):
        assert blob_id == self.descriptor["id"]
        if index in self.chunks:
            assert self.chunks[index] == data
        self.chunks[index] = data
        if self.fail_once == index:
            self.fail_once = None
            raise OSError("synthetic lost reply")

    def complete_blob(self, blob_id):
        assert blob_id == self.descriptor["id"]
        data = b"".join(self.chunks[i] for i in sorted(self.chunks))
        assert (len(data), hashlib.sha256(data).hexdigest()) == (self.descriptor["size"], self.descriptor["sha256"])
        self.ready = True

    def publish(self, envelope):
        assert self.ready
        if self.envelope is not None:
            assert self.envelope == envelope
        self.envelope = copy.deepcopy(envelope)
        if self.fail_once == "publish":
            self.fail_once = None
            raise OSError("synthetic lost publish reply")
        return {"accepted": True, "duplicate": False}

    def download_blob_chunk(self, blob_id, index):
        assert self.ready and blob_id == self.descriptor["id"]
        return self.chunks[index]


def prepared(pair, tmp_path, content=b"SYNTHETIC PRIVATE ATTACHMENT", **options):
    sender, receiver, _ = pair
    source = tmp_path / "private-photo-\u03bb.dat"
    source.write_bytes(content)
    folder = tmp_path / "ciphertext"
    folder.mkdir(exist_ok=True)
    result = prepare_attachment(sender, receiver.device, source.resolve(), folder.resolve(), **options)
    return result, source


def assert_no_partial(tmp_path):
    assert not list(tmp_path.glob(".orion-receive-*"))


@pytest.mark.parametrize('phone', [True, False])
def test_explicit_cloud_save_records_phone_history_only_after_verified_download(pair, tmp_path, monkeypatch, phone):
    from types import SimpleNamespace
    from orion_mini.hosted_runtime import HostedController
    from orion_mini.storage import Store
    sender, receiver, _ = pair
    attachment, source = prepared(pair, tmp_path)
    relay = BlobRelay()
    upload_attachment(relay, attachment)
    profile = SimpleNamespace(root=tmp_path / 'desktop', settings={'hosted': {'enabled': True}},
                              save=lambda: None, store=Store(tmp_path / 'history'))
    controller = HostedController(profile)
    controller.session, controller.transport = receiver, relay
    event = relay.envelope['header']['id']
    controller._offers[event] = relay.envelope
    controller.mailbox = SimpleNamespace(claim=lambda _: None, complete=lambda *_: None)
    monkeypatch.setattr(controller, '_token_or_error', lambda: 'synthetic-access')
    monkeypatch.setattr(controller, 'is_phone', lambda device: phone and device == sender.device)
    saved = controller.save_offer(event, tmp_path / 'downloads')
    assert __import__('pathlib').Path(saved['path']).read_bytes() == source.read_bytes()
    rows = profile.store.all('phone_file')
    if phone:
        assert len(rows) == 1
        assert {key: rows[0][key] for key in ('id', 'device_id', 'name', 'path', 'size')} == {
            'id': event, 'device_id': sender.device, 'name': source.name,
            'path': saved['path'], 'size': source.stat().st_size}
    else:
        assert rows == []
    assert event not in controller._offers


def test_gallery_original_wraps_the_existing_authenticated_streaming_manifest(pair, tmp_path):
    sender, receiver, _ = pair
    attachment, _ = prepared(pair, tmp_path, b"synthetic original", kind="photo", mime="image/jpeg")
    relay = BlobRelay()
    upload_attachment(relay, attachment)
    manifest = receiver.authenticate(relay.envelope)
    envelope = sender.encrypt(receiver.device, {"type": "photo.original", "photo_id": "41",
                                              "request": str(__import__('uuid').uuid4()), "file": manifest}, ttl_seconds=300)
    output = (tmp_path / "gallery-original.jpg").resolve()
    assert download_attachment(receiver, relay, envelope, output).read_bytes() == b"synthetic original"
    assert b"gallery-original" not in canonical(envelope)


@pytest.mark.parametrize("content,kind", [(b"", "file"), (b"synthetic photo", "photo"), (b"synthetic image", "clipboard.image"),
                                          (b"PRIVATE-STREAM-" * 170_000, "file")], ids=["empty", "photo", "image", "multi-segment"])
def test_actual_streaming_bytes_and_hidden_metadata(pair, tmp_path, content, kind):
    attachment, source = prepared(pair, tmp_path, content, kind=kind, mime="application/x-orion-private")
    sender, receiver, _ = pair
    relay = BlobRelay()
    upload_attachment(relay, attachment)
    output = tmp_path / "locally-chosen-name"
    assert download_attachment(receiver, relay, relay.envelope, output.resolve()) == output.resolve()
    assert output.read_bytes() == content
    payload = receiver.authenticate(relay.envelope)
    assert payload["name"] == source.name and payload["kind"] == kind
    opaque = attachment.ciphertext.read_bytes() + canonical(relay.descriptor) + canonical(relay.envelope)
    for secret in [source.name.encode(), b"application/x-orion-private", base64.b64decode(payload["keyset"])]:
        assert secret not in opaque
    if content:
        assert content[:min(100, len(content))] not in opaque
    assert_no_partial(tmp_path)


@pytest.mark.parametrize("failure", [0, 1, "publish"])
def test_lost_response_retries_original_ciphertext_and_event(pair, tmp_path, failure):
    attachment, _ = prepared(pair, tmp_path, b"private" * 10_000)
    relay = BlobRelay()
    relay.fail_once = failure
    before = attachment.ciphertext.read_bytes(), copy.deepcopy(attachment.envelope)
    with pytest.raises(AttachmentError):
        upload_attachment(relay, attachment)
    upload_attachment(relay, attachment)
    assert (attachment.ciphertext.read_bytes(), attachment.envelope) == before
    output = tmp_path / "received"
    download_attachment(pair[1], relay, relay.envelope, output.resolve())
    assert output.read_bytes() == b"private" * 10_000


@pytest.mark.parametrize("damage", ["changed", "short", "missing", "reordered", "wrong-type"])
def test_damaged_download_never_exposes_plaintext(pair, tmp_path, damage):
    attachment, _ = prepared(pair, tmp_path, b"private" * 10_000)
    relay = BlobRelay()
    upload_attachment(relay, attachment)
    if damage == "changed": relay.chunks[0] = bytes([relay.chunks[0][0] ^ 1]) + relay.chunks[0][1:]
    elif damage == "short": relay.chunks[0] = relay.chunks[0][:-1]
    elif damage == "missing": del relay.chunks[1]
    elif damage == "reordered": relay.chunks[0], relay.chunks[1] = relay.chunks[1], relay.chunks[0]
    else: relay.chunks[0] = bytearray(relay.chunks[0])
    output = tmp_path / "received"
    with pytest.raises(AttachmentError): download_attachment(pair[1], relay, relay.envelope, output.resolve())
    assert not output.exists()
    assert_no_partial(tmp_path)


@pytest.mark.parametrize("damage", ["key", "binding", "ciphertext", "plaintext-hash", "plaintext-size"])
def test_validly_signed_but_invalid_aead_or_hash_rejected(pair, tmp_path, damage):
    sender, receiver, _ = pair
    attachment, _ = prepared(pair, tmp_path, b"private" * 10_000)
    relay = BlobRelay()
    upload_attachment(relay, attachment)
    manifest = receiver.authenticate(relay.envelope)
    if damage == "key":
        other, _ = prepared(pair, tmp_path, b"other")
        manifest["keyset"] = receiver.authenticate(other.envelope)["keyset"]
    elif damage == "binding": manifest["blob"]["id"] = str(uuid4()); relay.descriptor["id"] = manifest["blob"]["id"]
    elif damage == "ciphertext":
        relay.chunks[0] = relay.chunks[0][:100] + bytes([relay.chunks[0][100] ^ 1]) + relay.chunks[0][101:]
        manifest["ciphertext_sha256"] = hashlib.sha256(b"".join(relay.chunks.values())).hexdigest()
    elif damage == "plaintext-hash": manifest["sha256"] = "0" * 64
    else: manifest["size"] -= 1
    event = sender.encrypt(receiver.device, manifest)
    output = tmp_path / "received"
    with pytest.raises(AttachmentError): download_attachment(receiver, relay, event, output.resolve())
    assert not output.exists()
    assert_no_partial(tmp_path)


@pytest.mark.parametrize("name,value", [("name", "../outside"), ("name", "CON.txt"), ("name", "private."),
    ("name", "file\n.txt"), ("mime", "text/plain\r\nOther:x"), ("keyset", "invalid"), ("size", True),
    ("ciphertext_size", 20 * 1024 * 1024 + 1), ("sha256", "X" * 64), ("kind", "execute"), ("unexpected", "x")])
def test_malicious_metadata_is_not_a_path_or_algorithm_request(pair, tmp_path, name, value):
    sender, receiver, _ = pair
    attachment, _ = prepared(pair, tmp_path)
    relay = BlobRelay()
    upload_attachment(relay, attachment)
    manifest = receiver.authenticate(relay.envelope)
    manifest[name] = value
    event = sender.encrypt(receiver.device, manifest)
    with pytest.raises(AttachmentError): download_attachment(receiver, relay, event, (tmp_path / "received").resolve())
    assert not (tmp_path / "received").exists()
    assert_no_partial(tmp_path)


def test_no_overwrite_even_when_destination_appears_mid_download(pair, tmp_path):
    attachment, _ = prepared(pair, tmp_path)
    relay = BlobRelay()
    upload_attachment(relay, attachment)
    output = tmp_path / "received"
    real_download = relay.download_blob_chunk
    def racing_download(blob_id, index):
        output.write_bytes(b"existing user's file")
        return real_download(blob_id, index)
    relay.download_blob_chunk = racing_download
    with pytest.raises(AttachmentError): download_attachment(pair[1], relay, relay.envelope, output.resolve())
    assert output.read_bytes() == b"existing user's file"
    assert_no_partial(tmp_path)


def test_revocation_during_download_blocks_file_publication(pair, tmp_path):
    sender, receiver, chain = pair
    attachment, _ = prepared(pair, tmp_path)
    relay = BlobRelay()
    upload_attachment(relay, attachment)
    real_download = relay.download_blob_chunk
    def revoke(blob_id, index):
        third = sign_roster({**chain[-1]["roster"], "version": 3,
            "previous_hash": hashlib.sha256(canonical(chain[-1]["roster"])).hexdigest(),
            "members": chain[0]["roster"]["members"]}, sender.signing)
        with pytest.raises(ValueError): receiver.accept_chain([*chain, third])
        return real_download(blob_id, index)
    relay.download_blob_chunk = revoke
    output = tmp_path / "received"
    with pytest.raises(AttachmentError): download_attachment(receiver, relay, relay.envelope, output.resolve())
    assert not output.exists()
    assert_no_partial(tmp_path)


def test_source_mutation_and_local_ciphertext_tamper_fail_closed(pair, tmp_path, monkeypatch):
    import orion_mini.hosted_files as files
    source, folder = tmp_path / "source", tmp_path / "ciphertext"
    source.write_bytes(b"synthetic bytes")
    folder.mkdir()
    real_fstat, calls = files.os.fstat, 0
    identity = source.stat()
    def mutated(fd):
        nonlocal calls
        current = real_fstat(fd)
        if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
            calls += 1
            if calls == 2: source.write_bytes(b"source changed during encryption")
        return real_fstat(fd)
    with monkeypatch.context() as context:
        context.setattr(files.os, "fstat", mutated)
        with pytest.raises(AttachmentError): prepare_attachment(pair[0], pair[1].device, source.resolve(), folder.resolve())
    assert list(folder.iterdir()) == []
    attachment, _ = prepared(pair, tmp_path)
    attachment.ciphertext.write_bytes(b"tampered")
    relay = BlobRelay()
    with pytest.raises(AttachmentError): upload_attachment(relay, attachment)
    assert relay.descriptor is None


def test_expired_manifest_and_source_size_bound(pair, tmp_path, monkeypatch):
    import orion_mini.hosted_files as files
    attachment, source = prepared(pair, tmp_path)
    relay = BlobRelay()
    upload_attachment(relay, attachment)
    with monkeypatch.context() as context:
        context.setattr(files.time, "time", lambda: attachment.descriptor["expires_at"] + 1)
        with pytest.raises(AttachmentError): download_attachment(pair[1], relay, relay.envelope, (tmp_path / "received").resolve())
    assert not (tmp_path / "received").exists()
    source.write_bytes(b"x" * 4097)
    monkeypatch.setattr(files, "MAX_CIPHERTEXT", 8192)
    with pytest.raises(AttachmentError): prepare_attachment(pair[0], pair[1].device, source.resolve(), source.parent.resolve())


def test_failed_exclusive_create_never_deletes_existing_ciphertext(pair, tmp_path, monkeypatch):
    import orion_mini.hosted_files as files
    source, folder = tmp_path / "source", tmp_path / "ciphertext"
    source.write_bytes(b"synthetic bytes")
    folder.mkdir()
    collision = uuid4()
    existing = folder / (str(collision) + ".orion-sealed")
    existing.write_bytes(b"previous verified ciphertext")
    monkeypatch.setattr(files, "uuid4", lambda: collision)
    with pytest.raises(AttachmentError): prepare_attachment(pair[0], pair[1].device, source.resolve(), folder.resolve())
    assert existing.read_bytes() == b"previous verified ciphertext"


def test_failure_after_publication_has_distinct_uncertain_outcome(pair, tmp_path, monkeypatch):
    import orion_mini.hosted_files as files
    attachment, _ = prepared(pair, tmp_path)
    relay = BlobRelay()
    upload_attachment(relay, attachment)
    real_temporary = files.tempfile.TemporaryDirectory
    class FailingCleanup:
        def __init__(self, **kwargs): self.inner = real_temporary(**kwargs)
        def __enter__(self): return self.inner.__enter__()
        def __exit__(self, *args):
            self.inner.__exit__(*args)
            raise OSError("synthetic final cleanup failure")
    monkeypatch.setattr(files.tempfile, "TemporaryDirectory", FailingCleanup)
    output = tmp_path / "received"
    with pytest.raises(AttachmentPublicationUncertain): download_attachment(pair[1], relay, relay.envelope, output.resolve())
    assert output.read_bytes() == b"SYNTHETIC PRIVATE ATTACHMENT"
    assert_no_partial(tmp_path)
