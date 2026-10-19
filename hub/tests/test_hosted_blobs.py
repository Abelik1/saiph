# SPDX-License-Identifier: AGPL-3.0-or-later
"""Opaque attachment HTTP boundary and transaction fences, synthetic data only."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import sqlite3
import time
from uuid import uuid4

import pytest
pytest.importorskip("tink")
pytest.importorskip("jwt")
from fastapi import HTTPException

from test_hosted import setup as hosted_setup, headers
from orion_hub import hosted_blobs
from orion_hub.hosted import stable
from orion_hub.hosted_blobs import attach, CHUNK_SIZE, MAX_BLOB


@pytest.fixture
def setup(hosted_setup):
    if not hasattr(hosted_setup["app"].state, "blobs"):
        attach(hosted_setup["app"], hosted_setup["app"].state.mailbox)
    return hosted_setup


def descriptor(setup, data=b"opaque ciphertext", **changes):
    latest = setup["entries"][-1]["roster"]
    value = {"id": str(uuid4()), "target": setup["receiver"]["id"],
             "roster_version": latest["version"], "roster_hash": hashlib.sha256(stable(latest)).hexdigest(),
             "expires_at": int(time.time()) + 240, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    value.update(changes)
    return value


def request(setup, method, path, value=None, device=None):
    raw = stable(value) if value is not None else b""
    return setup["client"].request(method, path, content=raw,
        headers=headers(device or setup["root"], path, method, raw))


def allocate(setup, value):
    return request(setup, "POST", "/v1/sealed/blobs", value)


def chunk_path(value, index=0):
    return f'/v1/sealed/blobs/{value["id"]}/chunks/{index}'


def put(setup, value, raw, index=0, **kwargs):
    return request(setup, "POST", chunk_path(value, index), {"data": base64.b64encode(raw).decode()}, **kwargs)


def complete(setup, value):
    return request(setup, "POST", f'/v1/sealed/blobs/{value["id"]}/complete', {})


def rows(setup, table):
    with sqlite3.connect(setup["database"]) as db:
        return db.execute("SELECT count(*) FROM " + table).fetchone()[0]


def test_chunked_roundtrip_idempotent_retries_and_ciphertext_only_state(setup):
    data = bytes(range(256)) * 260
    value = descriptor(setup, data)
    assert allocate(setup, value).json() == {"accepted": True, "duplicate": False}
    assert allocate(setup, value).json() == {"accepted": True, "duplicate": True}
    assert request(setup, "GET", chunk_path(value), device=setup["receiver"]).status_code == 409
    assert complete(setup, value).status_code == 409
    chunks = [data[offset:offset + CHUNK_SIZE] for offset in range(0, len(data), CHUNK_SIZE)]
    for index, raw in enumerate(chunks):
        assert put(setup, value, raw, index).json() == {"accepted": True, "duplicate": False}
        assert put(setup, value, raw, index).json() == {"accepted": True, "duplicate": True}
    assert complete(setup, value).json() == {"ready": True}
    assert complete(setup, value).json() == {"ready": True}
    recovered = b"".join(base64.b64decode(request(setup, "GET", chunk_path(value, index), device=setup["receiver"]).json()["data"]) for index in range(len(chunks)))
    assert recovered == data
    assert put(setup, value, chunks[0]).json()["duplicate"] is True
    with sqlite3.connect(setup["database"]) as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(hosted_blobs)")]
        assert not {"filename", "mime", "plaintext", "key"} & set(columns)


@pytest.mark.parametrize("change", [
    {"id": "invalid"}, {"id": 3}, {"id": "00000000000000000000000000000000"},
    {"target": "bad"}, {"target": None}, {"roster_version": True}, {"roster_version": 1.0},
    {"roster_hash": "z" * 64}, {"roster_hash": "a" * 63}, {"size": 0}, {"size": -1},
    {"size": True}, {"size": 1.5}, {"size": MAX_BLOB + 1}, {"sha256": "A" * 64},
    {"sha256": None}, {"expires_at": True}, {"expires_at": 1.2}, {"filename": "not permitted"},
])
def test_descriptor_bounds_exact_types_and_no_sensitive_metadata(setup, change):
    assert allocate(setup, descriptor(setup, **change)).status_code == 400
    assert rows(setup, "hosted_blobs") == 0


def test_descriptor_context_and_target_membership(setup):
    assert allocate(setup, descriptor(setup, roster_hash="a" * 64)).status_code == 409
    assert allocate(setup, descriptor(setup, target=setup["root"]["id"])).status_code == 400
    assert allocate(setup, descriptor(setup, target=setup["outsider"]["id"])).status_code == 403
    assert allocate(setup, descriptor(setup, expires_at=int(time.time()))).status_code == 400
    # int() truncation plus a second boundary before the server's float clock
    # made +301 fall inside the 300 s bound; +302 still exceeds it.
    assert allocate(setup, descriptor(setup, expires_at=int(time.time()) + 302)).status_code == 400


def test_account_token_and_unsigned_and_replayed_requests_rejected(setup):
    value = descriptor(setup)
    assert setup["client"].post("/v1/sealed/blobs", json=value, headers=setup["account"]).status_code == 403
    assert setup["client"].post("/v1/sealed/blobs", json=value).status_code == 401
    raw = stable(value)
    signed = headers(setup["root"], "/v1/sealed/blobs", "POST", raw)
    assert setup["client"].post("/v1/sealed/blobs", content=raw, headers=signed).status_code == 200
    assert setup["client"].post("/v1/sealed/blobs", content=raw, headers=signed).status_code == 409
    altered = stable({**value, "size": value["size"] + 1})
    assert setup["client"].post("/v1/sealed/blobs", content=altered,
        headers=headers(setup["root"], "/v1/sealed/blobs", "POST", raw)).status_code == 403


def test_existing_uuid_descriptor_and_source_cannot_change(setup):
    value = descriptor(setup)
    assert allocate(setup, value).status_code == 200
    for change in ({"size": value["size"] + 1}, {"sha256": "a" * 64}, {"expires_at": value["expires_at"] + 1}):
        assert allocate(setup, {**value, **change}).status_code == 409
    reverse = {**value, "target": setup["root"]["id"]}
    assert request(setup, "POST", "/v1/sealed/blobs", reverse, setup["receiver"]).status_code == 409


def test_sequential_chunks_exact_lengths_duplicate_conflict_and_incomplete_gate(setup):
    data = b"x" * (CHUNK_SIZE + 3)
    value = descriptor(setup, data)
    assert allocate(setup, value).status_code == 200
    assert put(setup, value, data[-3:], 1).status_code == 409
    assert put(setup, value, b"x").status_code == 400
    assert put(setup, value, b"x" * CHUNK_SIZE).status_code == 200
    assert put(setup, value, b"y" * CHUNK_SIZE).status_code == 409
    assert complete(setup, value).status_code == 409
    assert put(setup, value, b"x" * 4, 1).status_code == 400
    assert put(setup, value, b"x" * 3, 1).status_code == 200
    assert complete(setup, value).status_code == 200
    for index in (-1, 2, 99999999999999999999):
        assert put(setup, value, b"x", index).status_code == 400
    assert request(setup, "GET", chunk_path(value, -1), device=setup["receiver"]).status_code == 400


@pytest.mark.parametrize("data", ["", "%%%", "eA", "eA==\n", "eB==", 4, None])
def test_chunk_base64_is_canonical_and_nonempty(setup, data):
    value = descriptor(setup, b"x")
    assert allocate(setup, value).status_code == 200
    assert request(setup, "POST", chunk_path(value), {"data": data}).status_code == 400


def test_hash_mismatch_and_database_chunk_corruption_fail_complete(setup):
    value = descriptor(setup, b"original")
    assert allocate(setup, value).status_code == 200
    assert put(setup, value, b"tampered").status_code == 200
    assert complete(setup, value).status_code == 409
    with sqlite3.connect(setup["database"]) as db:
        db.execute("UPDATE hosted_blob_chunks SET ciphertext=? WHERE blob=?", (b"original", value["id"]))
    assert complete(setup, value).status_code == 200
    with sqlite3.connect(setup["database"]) as db:
        db.execute("UPDATE hosted_blob_chunks SET ciphertext=? WHERE blob=?", (b"bad", value["id"]))
    assert complete(setup, value).status_code == 409
    assert request(setup, "GET", chunk_path(value), device=setup["receiver"]).status_code == 409


def test_source_upload_recipient_download_and_no_other_device_delete(setup):
    outsider = setup["invite"](setup["outsider"])
    setup["roster"]([*setup["entries"][-1]["roster"]["members"], outsider])
    value = descriptor(setup, b"x")
    assert allocate(setup, value).status_code == 200
    assert put(setup, value, b"x", device=setup["receiver"]).status_code == 403
    assert put(setup, value, b"x").status_code == 200
    assert complete(setup, value).status_code == 200
    assert request(setup, "GET", chunk_path(value)).status_code == 403
    assert request(setup, "GET", chunk_path(value), device=setup["outsider"]).status_code == 403
    path = f'/v1/sealed/blobs/{value["id"]}'
    assert request(setup, "DELETE", path, device=setup["outsider"]).status_code == 403
    assert request(setup, "DELETE", path, device=setup["receiver"]).json() == {"ok": True}
    assert request(setup, "DELETE", path).json() == {"ok": True}
    assert rows(setup, "hosted_blob_chunks") == rows(setup, "hosted_blobs") == 0


def test_recipient_and_reserved_byte_quota_and_cleanup(setup, monkeypatch):
    for _ in range(4):
        assert allocate(setup, descriptor(setup, size=MAX_BLOB)).status_code == 200
    assert allocate(setup, descriptor(setup)).status_code == 429
    # Reservation rather than uploaded bytes prevents partial-upload bypass.
    assert rows(setup, "hosted_blob_chunks") == 0
    with sqlite3.connect(setup["database"]) as db:
        db.execute("UPDATE hosted_blobs SET expires_at=0")
    monkeypatch.setattr(hosted_blobs, "DEPLOYMENT_QUOTA", 10)
    assert allocate(setup, descriptor(setup, b"123456")).status_code == 200
    assert allocate(setup, descriptor(setup, b"123456")).status_code == 429
    assert rows(setup, "hosted_blobs") == 1


def test_expiry_removes_chunks_before_download(setup, monkeypatch):
    # Frozen clock: a one-second lifetime must not race the upload on a slow machine.
    now = int(time.time())
    monkeypatch.setattr(hosted_blobs.time, "time", lambda: now)
    value = descriptor(setup, b"x", expires_at=now + 1)
    assert allocate(setup, value).status_code == 200
    assert put(setup, value, b"x").status_code == 200
    assert complete(setup, value).status_code == 200
    monkeypatch.setattr(hosted_blobs.time, "time", lambda: value["expires_at"])
    assert request(setup, "GET", chunk_path(value), device=setup["receiver"]).status_code == 404
    # Cleanup commits on a successful authorized operation, not a failed read.
    assert allocate(setup, descriptor(setup, b"new")).status_code == 200
    assert rows(setup, "hosted_blob_chunks") == 0
    assert rows(setup, "hosted_blobs") == 1


def test_roster_change_purges_atomically_and_stale_authorization_cannot_write(setup):
    value = descriptor(setup, b"x")
    assert allocate(setup, value).status_code == 200
    assert put(setup, value, b"x").status_code == 200
    old_version = value["roster_version"]
    root_member = next(item for item in setup["entries"][-1]["roster"]["members"] if item["id"] == setup["root"]["id"])
    setup["roster"]([root_member])
    assert rows(setup, "hosted_blob_chunks") == rows(setup, "hosted_blobs") == 0
    with pytest.raises(HTTPException) as error:
        setup["app"].state.blobs.chunk(setup["root"]["id"], old_version, value["id"], 0, {"data": "eA=="})
    assert error.value.status_code == 409
    assert request(setup, "GET", chunk_path(value), device=setup["receiver"]).status_code == 403
    assert rows(setup, "hosted_blob_chunks") == rows(setup, "hosted_blobs") == 0


def test_roster_trigger_and_blob_clear_rollback_together(setup):
    value = descriptor(setup, b"x")
    assert allocate(setup, value).status_code == 200
    assert put(setup, value, b"x").status_code == 200
    with sqlite3.connect(setup["database"]) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO rosters VALUES(999,?,?,?)", ("test-rollback", "{}", "unused"))
        assert db.execute("SELECT count(*) FROM hosted_blobs").fetchone()[0] == 0
        db.rollback()
    assert rows(setup, "hosted_blobs") == rows(setup, "hosted_blob_chunks") == 1


def test_concurrent_exact_allocation_and_chunk_are_idempotent(setup):
    value = descriptor(setup, b"x")
    store = setup["app"].state.blobs
    args = (setup["root"]["id"], value["roster_version"])
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: store.allocate(*args, value), range(4)))
    assert sum(not item["duplicate"] for item in results) == 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: store.chunk(*args, value["id"], 0, {"data": "eA=="}), range(4)))
    assert sum(not item["duplicate"] for item in results) == 1
    assert rows(setup, "hosted_blobs") == rows(setup, "hosted_blob_chunks") == 1


def test_duplicate_json_and_oversized_body_rejected_before_storage(setup):
    path = "/v1/sealed/blobs"
    for raw, expected in ((b'{"id":1,"id":2}', 400), (b" " * 65537, 413)):
        response = setup["client"].post(path, content=raw, headers=headers(setup["root"], path, "POST", raw))
        assert response.status_code == expected
    assert rows(setup, "hosted_blobs") == 0


def test_invalid_blob_uuid_index_and_complete_body_are_generic_errors(setup):
    value = descriptor(setup, b"x")
    assert allocate(setup, value).status_code == 200
    assert request(setup, "GET", "/v1/sealed/blobs/invalid/chunks/0", device=setup["receiver"]).status_code == 400
    assert request(setup, "GET", chunk_path(value, "bad"), device=setup["receiver"]).status_code == 400
    assert request(setup, "POST", f'/v1/sealed/blobs/{value["id"]}/complete', {"name": "forbidden"}).status_code == 400


def test_separate_deployment_cannot_access_same_blob_uuid(setup, tmp_path):
    other = hosted_setup.__wrapped__(tmp_path / "other-deployment")
    if not hasattr(other["app"].state, "blobs"):
        attach(other["app"], other["app"].state.mailbox)
    value = descriptor(setup, b"x")
    assert allocate(setup, value).status_code == 200
    assert put(setup, value, b"x").status_code == 200
    assert complete(setup, value).status_code == 200
    path = chunk_path(value)
    assert request(other, "GET", path, device=setup["receiver"]).status_code == 403
    assert request(other, "GET", path, device=other["receiver"]).status_code == 404
    assert rows(other, "hosted_blobs") == rows(other, "hosted_blob_chunks") == 0
    assert rows(setup, "hosted_blobs") == rows(setup, "hosted_blob_chunks") == 1


def test_roster_change_between_verified_signature_and_blob_write_is_fenced(setup, monkeypatch):
    value = descriptor(setup, b"x")
    assert allocate(setup, value).status_code == 200
    mailbox = setup["app"].state.mailbox
    original = mailbox.device
    root_member = next(item for item in setup["entries"][-1]["roster"]["members"] if item["id"] == setup["root"]["id"])
    changed = False

    def authorize_then_revoke(request, raw):
        nonlocal changed
        result = original(request, raw)
        if not changed:
            changed = True
            setup["roster"]([root_member])
        return result

    monkeypatch.setattr(mailbox, "device", authorize_then_revoke)
    assert put(setup, value, b"x").status_code == 409
    assert changed
    assert rows(setup, "hosted_blobs") == rows(setup, "hosted_blob_chunks") == 0


def test_chunk_cannot_exceed_fixed_size_or_accept_extra_metadata(setup):
    value = descriptor(setup, size=CHUNK_SIZE + 1)
    assert allocate(setup, value).status_code == 200
    assert put(setup, value, b"x" * (CHUNK_SIZE + 1)).status_code == 400
    assert request(setup, "POST", chunk_path(value), {"data": "eA==", "filename": "private"}).status_code == 400


def test_expired_roster_denies_all_blob_operations(setup, monkeypatch):
    value = descriptor(setup, b"x")
    assert allocate(setup, value).status_code == 200
    assert put(setup, value, b"x").status_code == 200
    assert complete(setup, value).status_code == 200
    expiry = setup["entries"][-1]["roster"]["expires_at"]
    monkeypatch.setattr(hosted_blobs.time, "time", lambda: expiry)
    assert request(setup, "GET", chunk_path(value), device=setup["receiver"]).status_code == 403
    assert request(setup, "DELETE", f'/v1/sealed/blobs/{value["id"]}').status_code == 403
