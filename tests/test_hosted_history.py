# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signed history paging, migration and durable root commitments."""
import copy
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from orion_mini.hosted_approval import ApprovalError, RootApproval, initialize_root, local_root, prepare_anchored_catchup
from orion_mini.hosted_crypto import EnvelopeError, canonical, export_public, generate_recipient
from orion_mini.hosted_session import SealedSession, public_signing_key, sign_roster


@pytest.fixture
def history(tmp_path):
    signing = ec.generate_private_key(ec.SECP256R1())
    encryption = generate_recipient()
    root = local_root(str(uuid4()), "dev_" + "1" * 32, signing, encryption)
    session = SealedSession(tmp_path / "state.sqlite", root.deployment_id, root.signing_key, root.device_id, signing, encryption)
    first = initialize_root(root, signing, encryption, {**root.member(), "expires_at": int(time.time()) + 500}, state=session.state)
    return root, signing, encryption, session, [first]


def append(chain, root, signing, *, members=None, expires=None):
    entry = sign_roster({"deployment_id": root.deployment_id, "version": len(chain) + 1,
        "previous_hash": hashlib.sha256(canonical(chain[-1]["roster"])).hexdigest(),
        "expires_at": int(time.time()) + 3600 if expires is None else expires,
        "members": sorted(members or chain[-1]["roster"]["members"], key=lambda member: member["id"])}, signing)
    chain.append(entry)
    return entry


def restart(history):
    root, signing, encryption, session, _ = history
    return SealedSession(session.state, root.deployment_id, root.signing_key, root.device_id, signing, encryption)


def test_paging_over_129_renewals_and_restart_without_lifetime_chain(history):
    root, _, _, session, chain = history
    session.accept_page(chain, final=True)
    for _ in range(140):
        proposal = RootApproval(session, root).renew()
        session.accept_page([proposal], final=True)
        if proposal["roster"]["version"] % 17 == 0:
            session = restart(history)
            with pytest.raises(EnvelopeError):
                session.current()
            session.accept_page([], final=True)
    assert session.history_cursor()["after_version"] == 141
    assert session.current()[root.device_id] == root.member()
    with session.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM approval_proposals").fetchone()[0] == 141


def test_restart_midpage_expired_history_never_grants_content(history):
    root, signing, _, session, chain = history
    chain[0] = sign_roster({**chain[0]["roster"], "expires_at": int(time.time()) - 500}, signing)
    for _ in range(35):
        append(chain, root, signing, expires=int(time.time()) - 1)
    append(chain, root, signing)
    session.accept_page(chain[:16], final=False)
    with pytest.raises(EnvelopeError):
        session.current()
    session = restart(history)
    session.accept_page(chain[16:32], final=False)
    with pytest.raises(EnvelopeError):
        session.current()
    session.accept_page(chain[32:], final=True)
    assert session.history_cursor()["after_version"] == 37


@pytest.mark.parametrize("fault", ["gap", "hash", "signature", "root", "deployment", "rollback", "extra", "version_bool"])
def test_invalid_page_preserves_durable_anchor_and_clears_content(history, fault):
    root, signing, _, session, chain = history
    session.accept_page(chain, final=True)
    original = session.history_cursor()
    page = [append(chain, root, signing)]
    if fault == "gap": page[0]["roster"]["version"] += 1
    elif fault == "hash": page[0]["roster"]["previous_hash"] = "0" * 64
    elif fault == "signature": page[0]["signature"] = "AA=="
    elif fault == "root": page[0]["roster"]["members"][0]["encryption_key"] = export_public(generate_recipient())
    elif fault == "deployment": page[0]["roster"]["deployment_id"] = str(uuid4())
    elif fault == "rollback": page = [chain[0]]
    elif fault == "extra": page[0]["extra"] = True
    elif fault == "version_bool": page[0]["roster"]["version"] = True
    with pytest.raises(EnvelopeError): session.accept_page(page, final=True)
    assert session.history_cursor() == original
    with pytest.raises(EnvelopeError): session.current()


def test_expired_final_retains_highwater_without_enabling_older_fresh_authority(history):
    root, signing, _, session, chain = history
    session.accept_page(chain, final=True)
    expired = append(chain, root, signing, expires=int(time.time()) - 1)
    with pytest.raises(EnvelopeError): session.accept_page([expired], final=True)
    assert session.history_cursor()["after_version"] == 2
    with pytest.raises(EnvelopeError): session.accept_chain(chain[:1])
    session = restart(history)
    with pytest.raises(EnvelopeError): session.accept_page([], final=True)
    assert RootApproval(session, root).renew()["roster"]["version"] == 3


def test_old_database_requires_full_verified_migration_and_cannot_reset_tombstones(history):
    root, signing, _, session, chain = history
    session.accept_chain(chain)
    with session.connect() as db:
        db.execute("DELETE FROM history_anchor")
        db.execute("DELETE FROM history_used")
    with pytest.raises(EnvelopeError): session.history_cursor()
    with pytest.raises(EnvelopeError): session.accept_page([append(chain, root, signing)], final=True)
    session.accept_chain(chain)
    assert session.history_cursor()["after_version"] == 2
    extra = {"id": "dev_" + "2" * 32, "signing_key": public_signing_key(ec.generate_private_key(ec.SECP256R1()).public_key()),
             "encryption_key": export_public(generate_recipient())}
    session.accept_page([append(chain, root, signing, members=[root.member(), extra])], final=True)
    session.accept_page([append(chain, root, signing, members=[root.member()])], final=True)
    session = restart(history)
    bad = append(chain, root, signing, members=[root.member(), extra])
    with pytest.raises(EnvelopeError): session.accept_page([bad], final=True)
    assert session.history_cursor()["after_version"] == 4
    with pytest.raises(EnvelopeError): session.accept_chain(chain[:2])
    assert session.history_cursor()["after_version"] == 4


def test_concurrent_conflicting_pages_only_one_advances(history):
    root, signing, _, session, chain = history
    session.accept_page(chain, final=True)
    a = append(copy.deepcopy(chain), root, signing)
    b = sign_roster({**a["roster"], "expires_at": a["roster"]["expires_at"] + 1}, signing)
    def accept(entry):
        try:
            restart(history).accept_page([entry], final=True)
            return True
        except EnvelopeError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(accept, (a, b))) == [False, True]
    assert session.history_cursor()["after_version"] == 2
    with pytest.raises(EnvelopeError): session.current()


def test_atomic_anchor_failure_and_revocation_highwater(history):
    root, signing, _, session, chain = history
    session.accept_page(chain, final=True)
    with session.connect() as db:
        db.execute("CREATE TRIGGER fail_anchor BEFORE INSERT ON history_anchor BEGIN SELECT RAISE(ABORT,'synthetic'); END")
    page = [append(chain, root, signing)]
    with pytest.raises(EnvelopeError): session.accept_page(page, final=True)
    assert session.history_cursor()["after_version"] == 1
    with session.connect() as db: db.execute("DROP TRIGGER fail_anchor")
    session.accept_page(page, final=True)
    other = SealedSession(session.state.parent / "other.sqlite", root.deployment_id, root.signing_key,
        "dev_" + "3" * 32, ec.generate_private_key(ec.SECP256R1()), generate_recipient())
    with pytest.raises(EnvelopeError): other.accept_page(chain, final=True)
    assert other.history_cursor()["after_version"] == 2
    with pytest.raises(EnvelopeError): other.accept_page([chain[0]], final=True)


def test_anchored_catchup_keeps_exact_journal_intent_after_expiry_and_restart(history, monkeypatch):
    root, _, _, session, chain = history
    session.accept_page(chain, final=True)
    server_hash = session.history_cursor()["after_hash"]
    proposal = RootApproval(session, root).renew(roster_ttl_seconds=1)
    monkeypatch.setattr("time.time", lambda: proposal["roster"]["expires_at"] + 1)
    session = restart(history)
    result = prepare_anchored_catchup(session, root, expected_hash=server_hash)
    assert result["chain"][0] == proposal
    assert result["chain"][1]["roster"]["previous_hash"] == hashlib.sha256(canonical(proposal["roster"])).hexdigest()
    assert prepare_anchored_catchup(session, root, expected_hash=server_hash) == result
    with pytest.raises(EnvelopeError): session.current()
    with pytest.raises(ApprovalError): prepare_anchored_catchup(session, root, expected_hash="0" * 64)
    # No historical bytes are silently discarded, including expired genesis.
    genesis = prepare_anchored_catchup(session, root, expected_hash=None)
    assert genesis["chain"] == chain + result["chain"]


def test_page_bounds_and_anchor_corruption_fail_closed(history):
    _, _, _, session, chain = history
    for page, final in ((chain * 17, False), ([], False), (chain, 1), ({}, True)):
        with pytest.raises(EnvelopeError): session.accept_page(page, final=final)
    session.accept_page(chain, final=False)
    with session.connect() as db: db.execute("UPDATE history_anchor SET root='{}'")
    with pytest.raises(EnvelopeError): session.accept_page([], final=True)
    with pytest.raises(ApprovalError): RootApproval(session, history[0])


@pytest.mark.parametrize("revoked", [False, True])
def test_expired_nonroot_legacy_profile_migrates_without_content_then_pages(history, revoked):
    root, signing, _, _, chain = history
    signing_other, encryption_other = ec.generate_private_key(ec.SECP256R1()), generate_recipient()
    member = {"id": "dev_" + "4" * 32, "signing_key": public_signing_key(signing_other.public_key()),
              "encryption_key": export_public(encryption_other)}
    append(chain, root, signing, members=[root.member(), member], expires=int(time.time()) - 10)
    if revoked:
        append(chain, root, signing, members=[root.member()], expires=int(time.time()) - 1)
    other = SealedSession(history[3].state.parent / "old-nonroot.sqlite", root.deployment_id, root.signing_key,
                          member["id"], signing_other, encryption_other)
    # Exact old-schema highwater, with no signed anchor or tombstones yet.
    digest = hashlib.sha256(canonical(chain[-1]["roster"])).hexdigest()
    with other.connect() as db:
        db.execute("INSERT INTO trust VALUES(1,?,?,?,?)", (root.deployment_id, root.signing_key, len(chain), digest))
    with pytest.raises(EnvelopeError): other.accept_chain(chain)
    with pytest.raises(EnvelopeError): other.history_cursor()
    other.migrate_chain(chain)
    assert other.history_cursor() == {"after_version": len(chain), "after_hash": digest}
    with pytest.raises(EnvelopeError): other.current()
    fresh = append(chain, root, signing)
    if revoked:
        with pytest.raises(EnvelopeError): other.accept_page([fresh], final=True)
    else:
        other.accept_page([fresh], final=True)
        assert other.current()[member["id"]] == member
    assert other.history_cursor()["after_version"] == len(chain)


def test_historical_migration_preserves_highwater_and_tombstones_even_when_fresh(history):
    root, signing, _, session, chain = history
    session.accept_chain(chain)
    session.migrate_chain(chain)
    with pytest.raises(EnvelopeError): session.current()
    session.accept_page([], final=True)
    session.invalidate()
    with pytest.raises(EnvelopeError): session.current()
    assert session.history_cursor()["after_version"] == 1
    fork = sign_roster({**chain[0]["roster"], "expires_at": chain[0]["roster"]["expires_at"] + 1}, signing)
    with pytest.raises(EnvelopeError): session.migrate_chain([fork])
    assert session.history_cursor()["after_hash"] == hashlib.sha256(canonical(chain[0]["roster"])).hexdigest()
    with session.connect() as db: db.execute("INSERT INTO history_used VALUES(?)", ("dev_" + "5" * 32,))
    with pytest.raises(EnvelopeError): session.migrate_chain(chain)
    with pytest.raises(EnvelopeError): session.current()
