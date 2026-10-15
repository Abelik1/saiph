# SPDX-License-Identifier: AGPL-3.0-or-later
"""Real JWT, device signature, pinned roster and Tink mailbox round trips."""
import base64
import copy
import hashlib
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
pytest.importorskip("tink")
pytest.importorskip("jwt")
import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient

from orion_hub.hosted import HostedConfig, Mailbox, create_app, stable
from orion_hub.hosted_auth import AccessTokens, Auth0Config
from orion_hub.security import canonical as signed_request
from orion_mini.hosted_crypto import EnvelopeError, export_public, generate_recipient
from orion_mini.hosted_session import SealedSession, enrollment, public_signing_key, sign_roster


@pytest.fixture
def setup(tmp_path):
    config = Auth0Config("https://synthetic.eu.auth0.com/", "https://api.orion.example", ("native-client",), "auth0|synthetic")
    authority = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tokens = AccessTokens(config, key_resolver=lambda kid: authority.public_key())
    deployment = str(uuid4())
    database = tmp_path / "hosted.sqlite3"
    app = create_app(HostedConfig(deployment, database, config), tokens=tokens)
    client = TestClient(app)
    claims = {"iss": config.issuer, "aud": config.audience, "azp": config.client_ids[0],
              "sub": config.owner_subject, "iat": int(time.time()), "exp": int(time.time()) + 300}
    token = jwt.encode(claims, authority, algorithm="RS256", headers={"kid": "synthetic"})
    account = {"Authorization": "Bearer " + token}
    devices = []
    for _ in range(3):
        devices.append({"id": "dev_" + uuid4().hex, "sign": ec.generate_private_key(ec.SECP256R1()), "enc": generate_recipient()})
    root, receiver, outsider = devices
    entries = []

    def invite(device):
        value = enrollment(deployment, device["id"], device["sign"], device["enc"])
        response = client.post("/v1/devices/requests", json=value, headers=account)
        assert response.status_code == 200
        return value["device"]

    def roster(members):
        previous = hashlib.sha256(stable(entries[-1]["roster"])).hexdigest() if entries else None
        value = {"deployment_id": deployment, "version": len(entries) + 1, "previous_hash": previous,
                 "expires_at": int(time.time()) + 3600, "members": sorted(members, key=lambda item: item["id"])}
        entry = sign_roster(value, root["sign"])
        response = client.post("/v1/devices/rosters", json=entry, headers=account)
        assert response.status_code == 200, response.status_code
        entries.append(entry)
        return entry

    root_public = invite(root)
    roster([root_public])
    receiver_public = invite(receiver)
    roster([root_public, receiver_public])
    pin = public_signing_key(root["sign"].public_key())
    for device in devices[:2]:
        session = SealedSession(tmp_path / (device["id"] + ".sqlite3"), deployment, pin, device["id"], device["sign"], device["enc"])
        session.accept_chain(entries)
        device["session"] = session
    return {"client": client, "app": app, "account": account, "deployment": deployment, "database": database,
            "root": root, "receiver": receiver, "outsider": outsider, "entries": entries, "invite": invite, "roster": roster}


def headers(device, path, method="GET", raw=b"", nonce=None):
    timestamp, nonce = str(int(time.time())), nonce or str(uuid4())
    signature = device["sign"].sign(signed_request(method, path, timestamp, nonce, raw), ec.ECDSA(hashes.SHA256()))
    return {"X-Orion-Device-Id": device["id"], "X-Orion-Timestamp": timestamp, "X-Orion-Nonce": nonce,
            "X-Orion-Signature": base64.b64encode(signature).decode()}


def test_history_page_returns_only_signed_contiguous_rows_with_exact_anchor(setup):
    client, account = setup["client"], setup["account"]
    path = "/v1/devices/rosters/page"
    response = client.get(path + "?after_version=0&limit=1", headers=account)
    assert response.status_code == 200
    assert response.json() == {"chain": setup["entries"][:1], "more": True}
    digest = hashlib.sha256(stable(setup["entries"][0]["roster"])).hexdigest()
    response = client.get(path + f"?after_version=1&after_hash={digest}&limit=16", headers=account)
    assert response.json() == {"chain": setup["entries"][1:], "more": False}
    last = hashlib.sha256(stable(setup["entries"][-1]["roster"])).hexdigest()
    assert client.get(path + f"?after_version=2&after_hash={last}", headers=account).json() == {"chain": [], "more": False}
    assert client.get(path + "?after_version=0").status_code == 401
    assert client.get(path + "?after_version=0", headers=headers(setup["root"], path)).status_code == 401


@pytest.mark.parametrize("query,status", [
    ("after_version=0&after_hash=" + "0" * 64, 400), ("after_version=1", 400),
    ("after_version=1&after_hash=" + "0" * 64, 409),
    ("after_version=3&after_hash=" + "0" * 64, 409),
    ("after_version=-1", 400), ("after_version=01", 400), ("after_version=true", 400),
    ("after_version=2147483648&after_hash=" + "0" * 64, 400),
    ("after_version=0&limit=17", 400), ("after_version=0&limit=0", 400),
    ("after_version=0&limit=01", 400), ("after_version=0&limit=1&limit=2", 400),
    ("after_version=0&after_version=0", 400), ("after_version=0&unknown=1", 400),
])
def test_history_page_rejects_untrusted_or_ambiguous_cursor(setup, query, status):
    assert setup["client"].get("/v1/devices/rosters/page?" + query, headers=setup["account"]).status_code == status


def test_server_over_129_renewals_uses_bounded_signed_pages(setup, tmp_path):
    members = setup["entries"][-1]["roster"]["members"]
    for _ in range(138):
        setup["roster"](members)
    assert setup["client"].get("/v1/devices/rosters", headers=setup["account"]).status_code == 409
    root = setup["root"]
    session = SealedSession(tmp_path / "paged.sqlite", setup["deployment"], public_signing_key(root["sign"].public_key()),
                            root["id"], root["sign"], root["enc"])
    sizes = []
    while True:
        cursor = session.history_cursor()
        query = f"?after_version={cursor['after_version']}&limit=16"
        if cursor["after_hash"] is not None:
            query += "&after_hash=" + cursor["after_hash"]
        response = setup["client"].get("/v1/devices/rosters/page" + query, headers=setup["account"])
        assert response.status_code == 200
        page = response.json()
        sizes.append(len(page["chain"]))
        session.accept_page(page["chain"], final=not page["more"])
        if not page["more"]:
            break
        with pytest.raises(EnvelopeError): session.current()
    assert max(sizes) == 16 and sum(sizes) == 140
    assert session.current()[root["id"]]["signing_key"] == public_signing_key(root["sign"].public_key())
    assert session.history_cursor()["after_version"] == 140


def publish(setup, value, device=None):
    raw = stable(value)
    return setup["client"].post("/v1/sealed/events", content=raw,
                                headers=headers(device or setup["root"], "/v1/sealed/events", "POST", raw))


def test_actual_encrypted_roundtrip_storage_and_durable_replay(setup):
    root, receiver, client = setup["root"], setup["receiver"], setup["client"]
    payload = {"type": "clipboard.text", "text": "synthetic-private-canary-7bb79", "nested": ["☄", True, 42]}
    value = root["session"].encrypt(receiver["id"], payload)
    assert publish(setup, value).json() == {"accepted": True, "duplicate": False}
    assert publish(setup, value).json()["duplicate"] is True
    response = client.get("/v1/sealed/events", headers=headers(receiver, "/v1/sealed/events"))
    assert response.status_code == 200
    assert payload["text"] not in response.text and payload["type"] not in response.text
    incoming = response.json()["events"][0]
    assert receiver["session"].receive(incoming) == payload
    with pytest.raises(EnvelopeError, match="already received"):
        receiver["session"].receive(incoming)
    restarted = SealedSession(receiver["session"].state, setup["deployment"], receiver["session"].pin,
                              receiver["id"], receiver["sign"], receiver["enc"])
    restarted.accept_chain(setup["entries"])
    with pytest.raises(EnvelopeError, match="already received"):
        restarted.receive(incoming)
    with sqlite3.connect(setup["database"]) as db:
        assert payload["text"] not in " ".join(str(row) for row in db.iterdump())
    for file in setup["database"].parent.glob("hosted.sqlite3*"):
        assert payload["text"].encode() not in file.read_bytes()
    path = "/v1/sealed/events/" + incoming["header"]["id"]
    assert client.delete(path, headers=headers(receiver, path, "DELETE")).status_code == 200
    assert client.get("/v1/sealed/events", headers=headers(receiver, "/v1/sealed/events")).json()["events"] == []


@pytest.mark.parametrize("path", ["/v1/link", "/v1/link/phone", "/v1/inbox", "/v1/tasks", "/v1/link/cloud", "/v1/link/peer/verify", "/web/session", "/v1/agents", "/openapi.json"])
def test_no_legacy_plaintext_route_mounted(setup, path):
    assert setup["client"].get(path, headers=setup["account"]).status_code == 404


def test_login_does_not_grant_mailbox_or_approve_device(setup):
    client, outsider = setup["client"], setup["outsider"]
    assert client.get("/v1/account", headers=setup["account"]).json()["device_trust_required"] is True
    assert client.get("/v1/sealed/events", headers=setup["account"]).status_code == 403
    setup["invite"](outsider)
    assert client.get("/v1/sealed/events", headers=headers(outsider, "/v1/sealed/events")).status_code == 403
    forged = copy.deepcopy(setup["entries"][-1]["roster"])
    forged["version"] += 1
    forged["previous_hash"] = hashlib.sha256(stable(setup["entries"][-1]["roster"])).hexdigest()
    forged["members"].append(enrollment(setup["deployment"], outsider["id"], outsider["sign"], outsider["enc"])["device"])
    forged["members"].sort(key=lambda item: item["id"])
    value = sign_roster(forged, outsider["sign"])
    assert client.post("/v1/devices/rosters", json=value, headers=setup["account"]).status_code == 403


def test_operator_key_substitution_root_replacement_and_rollback_rejected(setup):
    session, entries = setup["receiver"]["session"], setup["entries"]
    fork = copy.deepcopy(entries)
    fork[-1]["roster"]["members"][0]["encryption_key"] = export_public(generate_recipient())
    with pytest.raises(EnvelopeError):
        session.accept_chain(fork)
    assert session.roster is None
    session.accept_chain(entries)
    with pytest.raises(EnvelopeError):
        session.accept_chain(entries[:1])
    with pytest.raises(EnvelopeError, match="cannot be replaced"):
        SealedSession(session.state, setup["deployment"], public_signing_key(setup["outsider"]["sign"].public_key()),
                      setup["receiver"]["id"], setup["receiver"]["sign"], setup["receiver"]["enc"])


def test_revocation_fences_client_and_mailbox(setup):
    receiver, root, client = setup["receiver"], setup["root"], setup["client"]
    value = root["session"].encrypt(receiver["id"], {"type": "test", "text": "synthetic"})
    assert publish(setup, value).status_code == 200
    root_public = next(item for item in setup["entries"][0]["roster"]["members"] if item["id"] == root["id"])
    setup["roster"]([root_public])
    assert client.get("/v1/sealed/events", headers=headers(receiver, "/v1/sealed/events")).status_code == 403
    with pytest.raises(EnvelopeError):
        receiver["session"].accept_chain(setup["entries"])
    with pytest.raises(EnvelopeError):
        receiver["session"].accept_chain(setup["entries"][:-1])
    with pytest.raises(EnvelopeError):
        receiver["session"].receive(value)
    root["session"].accept_chain(setup["entries"])
    with pytest.raises(EnvelopeError):
        root["session"].encrypt(receiver["id"], {"type": "test"})
    assert publish(setup, value).status_code == 400
    with sqlite3.connect(setup["database"]) as db:
        assert db.execute("SELECT COUNT(*) FROM sealed_events").fetchone()[0] == 0


def test_transport_replay_and_invalid_signature(setup):
    client, root = setup["client"], setup["root"]
    request_headers = headers(root, "/v1/sealed/events")
    assert client.get("/v1/sealed/events", headers=request_headers).status_code == 200
    assert client.get("/v1/sealed/events", headers=request_headers).status_code == 409
    request_headers = headers(root, "/v1/sealed/events")
    request_headers["X-Orion-Signature"] = base64.b64encode(b"synthetic invalid").decode()
    assert client.get("/v1/sealed/events", headers=request_headers).status_code == 403


def test_verified_roster_does_not_alias_mutable_input_or_returned_members(setup):
    root, receiver = setup["root"], setup["receiver"]
    session = root["session"]
    original = copy.deepcopy(setup["entries"])
    session.accept_chain(original)
    wrong_key = export_public(setup["outsider"]["enc"])
    next(item for item in original[-1]["roster"]["members"] if item["id"] == receiver["id"])["encryption_key"] = wrong_key
    session.current()[receiver["id"]]["encryption_key"] = wrong_key
    value = session.encrypt(receiver["id"], {"type": "test", "text": "synthetic"})
    assert receiver["session"].receive(value)["text"] == "synthetic"
    next(item for item in session.roster["members"] if item["id"] == receiver["id"])["encryption_key"] = wrong_key
    with pytest.raises(EnvelopeError):
        session.encrypt(receiver["id"], {"type": "test"})


@pytest.mark.parametrize("change", [
    {"expires_at": 1}, {"expires_at": 2**53}, {"roster_version": 99},
    {"roster_hash": "0" * 64}, {"deployment_id": str(uuid4())}, {"protocol_version": 0},
])
def test_bad_routing_rejected_before_delivery(setup, change):
    value = setup["root"]["session"].encrypt(setup["receiver"]["id"], {"type": "test"})
    value["header"].update(change)
    assert publish(setup, value).status_code in {400, 409}
    with pytest.raises(EnvelopeError):
        setup["receiver"]["session"].receive(value)


def test_strict_body_limits_no_validation_echo(setup):
    client = setup["client"]
    for raw in [b'{"a":1,"a":2}', b'{"a":NaN}', b'"' + b'x' * 65536 + b'"', b'{"device":"synthetic-private-body"}']:
        response = client.post("/v1/devices/requests", content=raw, headers=setup["account"])
        assert response.status_code in {400, 413}
        assert "synthetic-private-body" not in response.text
        assert response.headers["Cache-Control"] == "no-store"


def test_refuse_legacy_database(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE devices(id TEXT)")
    auth = Auth0Config("https://synthetic.eu.auth0.com/", "audience", ("native",), "auth0|owner")
    with pytest.raises(ValueError, match="separate database"):
        Mailbox(HostedConfig(str(uuid4()), path, auth))


@pytest.mark.parametrize("change", ["deployment", "issuer", "subject", "audience"])
def test_existing_database_cannot_be_reassigned_to_another_account(setup, change):
    auth = Auth0Config("https://synthetic.eu.auth0.com/", "https://api.orion.example", ("native-client",), "auth0|synthetic")
    values = {"issuer": auth.issuer, "audience": auth.audience, "client_ids": auth.client_ids, "owner_subject": auth.owner_subject}
    if change == "deployment":
        deployment = str(uuid4())
    else:
        deployment = setup["deployment"]
        values[{"subject": "owner_subject"}.get(change, change)] = {
            "issuer": "https://other.eu.auth0.com/", "subject": "auth0|other", "audience": "https://other.example"
        }[change]
    with pytest.raises(ValueError, match="ownership"):
        Mailbox(HostedConfig(deployment, setup["database"], Auth0Config(**values)))


def catchup_suffix(setup, *, members=None):
    old = setup["entries"][-1]["roster"]
    expected = hashlib.sha256(stable(old)).hexdigest()
    expired = {**copy.deepcopy(old), "version": old["version"] + 1,
               "previous_hash": expected, "expires_at": int(time.time()) - 1}
    if members is not None:
        expired["members"] = sorted(members, key=lambda item: item["id"])
    first = sign_roster(expired, setup["root"]["sign"])
    final = {**copy.deepcopy(expired), "version": expired["version"] + 1,
             "previous_hash": hashlib.sha256(stable(expired)).hexdigest(),
             "expires_at": int(time.time()) + 3600}
    return {"expected_hash": expected, "chain": [first, sign_roster(final, setup["root"]["sign"])]}


def post_catchup(setup, value):
    return setup["client"].post("/v1/devices/rosters/catchup", json=value, headers=setup["account"])


def test_catchup_commits_expired_history_fresh_head_and_exact_retry(setup):
    value = catchup_suffix(setup)
    old_event = setup["root"]["session"].encrypt(setup["receiver"]["id"], {"type": "synthetic"})
    assert publish(setup, old_event).status_code == 200
    assert setup["client"].post("/v1/devices/rosters", json=value["chain"][0], headers=setup["account"]).status_code == 400
    response = post_catchup(setup, value)
    assert response.status_code == 200
    assert response.json()["version"] == 4
    with sqlite3.connect(setup["database"]) as db:
        assert db.execute("SELECT COUNT(*) FROM sealed_events").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM roster_catchups").fetchone()[0] == 1
    full = setup["entries"] + value["chain"]
    for device in (setup["root"], setup["receiver"]):
        device["session"].accept_chain(full)
    fresh = setup["root"]["session"].encrypt(setup["receiver"]["id"], {"type": "fresh"})
    assert publish(setup, fresh).status_code == 200
    assert setup["receiver"]["session"].receive(fresh) == {"type": "fresh"}
    assert post_catchup(setup, value).json() == response.json()
    # A duplicate receipt must not delete traffic published after the first commit.
    with sqlite3.connect(setup["database"]) as db:
        assert db.execute("SELECT COUNT(*) FROM sealed_events").fetchone()[0] == 1


@pytest.mark.parametrize("fault", ["final-expiry", "final-far-expiry", "gap", "previous", "deployment", "root-key", "member-key", "signature", "expected", "empty", "oversized"])
def test_catchup_invalid_suffix_is_atomic(setup, fault, monkeypatch):
    value = catchup_suffix(setup)
    # Keep the one-second validity boundary fixed through signature/HTTP work.
    # Otherwise a valid +24h horizon can be reached while the request is sent.
    now = int(time.time())
    monkeypatch.setattr(time, "time", lambda: now)
    final = value["chain"][-1]["roster"]
    if fault == "final-expiry": final["expires_at"] = int(time.time()) - 1
    elif fault == "final-far-expiry": final["expires_at"] = int(time.time()) + 86401
    elif fault == "gap": final["version"] += 1
    elif fault == "previous": final["previous_hash"] = "0" * 64
    elif fault == "deployment": final["deployment_id"] = str(uuid4())
    elif fault == "root-key":
        next(item for item in final["members"] if item["id"] == setup["root"]["id"])["signing_key"] = public_signing_key(setup["outsider"]["sign"].public_key())
    elif fault == "member-key":
        next(item for item in final["members"] if item["id"] == setup["receiver"]["id"])["encryption_key"] = export_public(setup["outsider"]["enc"])
    elif fault == "signature": value["chain"][0]["signature"] = base64.b64encode(b"bad").decode()
    elif fault == "expected": value["expected_hash"] = "0" * 64
    elif fault == "empty": value["chain"] = []
    elif fault == "oversized": value["chain"] *= 9
    if fault not in {"signature", "empty", "oversized"}:
        value["chain"][-1] = sign_roster(final, setup["root"]["sign"])
    before = setup["app"].state.mailbox.roster()
    response = post_catchup(setup, value)
    assert response.status_code in {400, 403, 409, 413}
    assert setup["app"].state.mailbox.roster() == before
    with sqlite3.connect(setup["database"]) as db:
        assert db.execute("SELECT COUNT(*) FROM roster_catchups").fetchone()[0] == 0


def test_catchup_new_device_requires_current_exact_pending_proof(setup):
    outsider = setup["outsider"]
    member = enrollment(setup["deployment"], outsider["id"], outsider["sign"], outsider["enc"])["device"]
    value = catchup_suffix(setup, members=setup["entries"][-1]["roster"]["members"] + [member])
    assert post_catchup(setup, value).status_code == 403
    setup["invite"](outsider)
    with sqlite3.connect(setup["database"]) as db:
        db.execute("UPDATE candidates SET expires_at=1 WHERE id=?", (outsider["id"],))
    assert post_catchup(setup, value).status_code == 403
    assert len(setup["app"].state.mailbox.roster()) == 2
    setup["invite"](outsider)
    assert post_catchup(setup, value).status_code == 200
    with sqlite3.connect(setup["database"]) as db:
        assert db.execute("SELECT 1 FROM used_devices WHERE id=?", (outsider["id"],)).fetchone()
        assert not db.execute("SELECT 1 FROM candidates WHERE id=?", (outsider["id"],)).fetchone()


def test_catchup_late_failure_restores_candidate_delivery_and_used_ids(setup):
    outsider = setup["outsider"]
    member = setup["invite"](outsider)
    value = catchup_suffix(setup, members=setup["entries"][-1]["roster"]["members"] + [member])
    event = setup["root"]["session"].encrypt(setup["receiver"]["id"], {"type": "synthetic"})
    assert publish(setup, event).status_code == 200
    final = value["chain"][-1]["roster"]
    final["members"][-1]["encryption_key"] = export_public(generate_recipient())
    value["chain"][-1] = sign_roster(final, setup["root"]["sign"])
    assert post_catchup(setup, value).status_code == 409
    with sqlite3.connect(setup["database"]) as db:
        assert db.execute("SELECT COUNT(*) FROM rosters").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM sealed_events").fetchone()[0] == 1
        assert db.execute("SELECT 1 FROM candidates WHERE id=?", (outsider["id"],)).fetchone()
        assert not db.execute("SELECT 1 FROM used_devices WHERE id=?", (outsider["id"],)).fetchone()


def test_catchup_concurrent_conflicting_heads_cas_and_no_reactivation(setup):
    value = catchup_suffix(setup)
    conflicting = copy.deepcopy(value)
    conflicting["chain"][-1]["roster"]["expires_at"] += 1
    conflicting["chain"][-1] = sign_roster(conflicting["chain"][-1]["roster"], setup["root"]["sign"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda item: post_catchup(setup, item).status_code, (value, conflicting)))
    assert sorted(statuses) == [200, 409]
    assert len(setup["app"].state.mailbox.roster()) == 4
    winning = value if post_catchup(setup, value).status_code == 200 else conflicting
    committed = setup["app"].state.mailbox.roster()
    final = committed[-1]["roster"]
    revocation = {**copy.deepcopy(final), "version": 5, "previous_hash": hashlib.sha256(stable(final)).hexdigest(),
                  "members": committed[0]["roster"]["members"]}
    assert setup["client"].post("/v1/devices/rosters", json=sign_roster(revocation, setup["root"]["sign"]), headers=setup["account"]).status_code == 200
    assert post_catchup(setup, winning).status_code == 200
    assert setup["app"].state.mailbox.roster()[-1]["roster"]["version"] == 5
    assert setup["client"].get("/v1/sealed/events", headers=headers(setup["receiver"], "/v1/sealed/events")).status_code == 403


def test_catchup_requires_account_and_preserves_protocol_version_bound(setup):
    value = catchup_suffix(setup)
    assert setup["client"].post("/v1/devices/rosters/catchup", json=value).status_code == 401
    assert setup["client"].post("/v1/devices/rosters/catchup", json=value, headers=headers(setup["root"], "/v1/devices/rosters/catchup", "POST", stable(value))).status_code == 401
    with sqlite3.connect(setup["database"]) as db:
        db.execute("UPDATE rosters SET version=2147483647 WHERE version=2")
    value["chain"][0]["roster"]["version"] = 2147483648
    value["chain"][0] = sign_roster(value["chain"][0]["roster"], setup["root"]["sign"])
    assert post_catchup(setup, value).status_code == 400


def test_catchup_genesis_can_be_expired_only_inside_atomic_fresh_suffix(setup, tmp_path):
    previous = setup["app"].state.mailbox.config
    mailbox = Mailbox(HostedConfig(previous.deployment_id, tmp_path / "fresh.sqlite", previous.auth))
    root = setup["root"]
    mailbox.candidate(enrollment(setup["deployment"], root["id"], root["sign"], root["enc"]))
    first = copy.deepcopy(setup["entries"][0]["roster"])
    first["expires_at"] = int(time.time()) - 10
    successor = {**copy.deepcopy(first), "version": 2, "previous_hash": hashlib.sha256(stable(first)).hexdigest(),
                 "expires_at": int(time.time()) + 600}
    value = {"expected_hash": None, "chain": [sign_roster(first, root["sign"]), sign_roster(successor, root["sign"])]}
    assert mailbox.catchup(value)["version"] == 2
    assert len(mailbox.roster()) == 2
    assert mailbox.catchup(value)["version"] == 2


def test_catchup_database_fault_rolls_back_every_step(setup):
    mailbox = setup["app"].state.mailbox
    value = catchup_suffix(setup)
    with sqlite3.connect(setup["database"]) as db:
        db.execute("CREATE TRIGGER synthetic_fault BEFORE INSERT ON rosters WHEN NEW.version=4 BEGIN SELECT RAISE(ABORT, 'synthetic transaction fault'); END")
    with pytest.raises(sqlite3.IntegrityError):
        mailbox.catchup(value)
    assert len(mailbox.roster()) == 2
    with sqlite3.connect(setup["database"]) as db:
        assert db.execute("SELECT COUNT(*) FROM roster_catchups").fetchone()[0] == 0
        db.execute("DROP TRIGGER synthetic_fault")
    assert mailbox.catchup(value)["version"] == 4


def test_catchup_exact_receipt_survives_restart_expiry_and_parallel_retry(setup, monkeypatch):
    mailbox = setup["app"].state.mailbox
    value = catchup_suffix(setup)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: mailbox.catchup(value), range(2)))
    assert results[0] == results[1]
    restarted = Mailbox(mailbox.config)
    final_expiry = value["chain"][-1]["roster"]["expires_at"]
    monkeypatch.setattr("orion_hub.hosted.time.time", lambda: final_expiry + 100)
    assert restarted.catchup(value) == results[0]
    assert restarted.roster()[-1]["roster"]["expires_at"] == final_expiry


def test_catchup_rejects_pending_key_substitution_and_removed_id_reuse(setup):
    outsider = setup["outsider"]
    member = setup["invite"](outsider)
    members = setup["entries"][-1]["roster"]["members"] + [member]
    value = catchup_suffix(setup, members=members)
    with sqlite3.connect(setup["database"]) as db:
        db.execute("UPDATE candidates SET encryption_key=? WHERE id=?", (export_public(generate_recipient()), outsider["id"]))
    assert post_catchup(setup, value).status_code == 403
    with sqlite3.connect(setup["database"]) as db:
        db.execute("UPDATE candidates SET encryption_key=? WHERE id=?", (member["encryption_key"], outsider["id"]))
    # A member introduced and then removed in the suffix is permanently retired.
    value["chain"][-1]["roster"]["members"] = setup["entries"][-1]["roster"]["members"]
    value["chain"][-1] = sign_roster(value["chain"][-1]["roster"], setup["root"]["sign"])
    assert post_catchup(setup, value).status_code == 200
    setup["entries"].extend(value["chain"])
    replacement = catchup_suffix(setup, members=members)
    assert post_catchup(setup, replacement).status_code == 409
    assert setup["client"].get("/v1/sealed/events", headers=headers(outsider, "/v1/sealed/events")).status_code == 403


def test_root_fetches_a_pending_devices_signed_approval_request(setup):
    """A phone offers its signed request so the root needs no long code typed across; the root still verifies it."""
    from orion_mini.hosted_approval import local_root, make_request_code, verify_request_code

    client, account, outsider = setup["client"], setup["account"], setup["outsider"]
    root = local_root(setup["deployment"], setup["root"]["id"], setup["root"]["sign"], setup["root"]["enc"])
    code = make_request_code(root, outsider["id"], outsider["sign"], outsider["enc"])
    offer = lambda value: client.post("/v1/devices/approval-requests", json={"code": value}, headers=account)

    assert offer(code).status_code == 409  # Not a pending candidate yet.
    setup["invite"](outsider)
    assert offer(code).status_code == 200
    listed = client.get("/v1/devices/approval-requests", headers=account)
    assert listed.status_code == 200 and listed.json() == {"requests": [code]}
    assert verify_request_code(listed.json()["requests"][0], root)["candidate"]["device"]["id"] == outsider["id"]

    # Forged or foreign requests never reach the list.
    value = json.loads(code.removeprefix("orion-approve-v1:"))
    value["data"]["nonce"] = "altered"
    assert offer("orion-approve-v1:" + json.dumps(value)).status_code == 403
    assert offer("not-a-request").status_code == 400
    assert client.post("/v1/devices/approval-requests", json={"code": code, "extra": 1}, headers=account).status_code == 400
    assert client.get("/v1/devices/approval-requests").status_code == 401

    # Once admitted, the device is no longer offered.
    setup["roster"]([setup["entries"][-1]["roster"]["members"][0], setup["entries"][-1]["roster"]["members"][1],
                     {key: value["data"]["candidate"]["device"][key] for key in ("id", "signing_key", "encryption_key")}])
    assert client.get("/v1/devices/approval-requests", headers=account).json() == {"requests": []}
