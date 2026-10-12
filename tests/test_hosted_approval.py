# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthetic public-code/roster approvals without UI, network or private storage."""
import base64
import copy
import hashlib
import json
import multiprocessing
import threading
import time
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import ec
import pytest

from orion_mini.hosted_crypto import EnvelopeError, canonical, generate_recipient
from orion_mini.hosted_session import SealedSession, enrollment, sign_roster
from orion_mini.hosted_approval import (
    ApprovalError, MAX_CODE_BYTES, REQUEST_PREFIX, ROOT_PREFIX, RootApproval,
    initialize_root, inspect_root_code, local_root, make_request_code, make_root_code,
    trust_root_code, verify_request_code,
    prepare_catchup, prepare_anchored_catchup,
)


@pytest.fixture
def setup(tmp_path):
    deployment = str(uuid4())
    signing = ec.generate_private_key(ec.SECP256R1())
    encryption = generate_recipient()
    root = local_root(deployment, "dev_" + "1" * 32, signing, encryption)
    session = SealedSession(tmp_path / "root.sqlite", deployment, root.signing_key, root.device_id, signing, encryption)
    pending = {**root.member(), "expires_at": int(time.time()) + 500}
    first = initialize_root(root, signing, encryption, pending, state=session.state)
    return root, signing, encryption, session, [first]


def requester(root, device="dev_" + "2" * 32):
    signing = ec.generate_private_key(ec.SECP256R1())
    encryption = generate_recipient()
    code = make_request_code(root, device, signing, encryption)
    data = verify_request_code(code, root)
    pending = {**data["candidate"]["device"], "expires_at": int(time.time()) + 500}
    return code, pending, signing, encryption


def rewrite(code, prefix, mutate):
    value = json.loads(code[len(prefix):])
    mutate(value)
    return prefix + canonical(value).decode()


def test_root_requires_explicit_independent_trust_and_full_fingerprint(setup):
    root, signing, _, _, _ = setup
    code = make_root_code(root, signing)
    assert len(code) <= MAX_CODE_BYTES and code.isascii()
    info = inspect_root_code(code)
    assert info["fingerprint"] == root.fingerprint
    assert len(root.fingerprint) == 64
    assert info["display_fingerprint"] == root.display_fingerprint
    assert "signing_key" not in info
    with pytest.raises(ApprovalError):
        trust_root_code(code)
    for false_confirmation in (1, "true", [], {}):
        with pytest.raises(ApprovalError):
            trust_root_code(code, trusted_out_of_band=false_confirmation)
    for fingerprint in (root.fingerprint[:8], "0" * 64, info):
        with pytest.raises(ApprovalError):
            trust_root_code(code, expected_fingerprint=fingerprint)
    assert trust_root_code(code, trusted_out_of_band=True) == root
    assert trust_root_code(code, expected_fingerprint=root.fingerprint) == root
    assert trust_root_code(code, expected_fingerprint=root.display_fingerprint) == root


def test_fingerprint_binds_deployment_root_id_and_both_public_keys(setup):
    root, signing, encryption, _, _ = setup
    other_signing = ec.generate_private_key(ec.SECP256R1())
    variants = [
        local_root(str(uuid4()), root.device_id, signing, encryption),
        local_root(root.deployment_id, "dev_" + "3" * 32, signing, encryption),
        local_root(root.deployment_id, root.device_id, other_signing, encryption),
        local_root(root.deployment_id, root.device_id, signing, generate_recipient()),
    ]
    assert all(variant.fingerprint != root.fingerprint for variant in variants)


def test_public_code_contains_no_private_keys_and_wrong_signer_rejected(setup):
    root, signing, _, _, _ = setup
    value = json.loads(make_root_code(root, signing)[len(ROOT_PREFIX):])
    assert set(value) == {"data", "signature"}
    assert value["data"]["root"] == root.member()
    assert "private" not in json.dumps(value).lower()
    with pytest.raises(ApprovalError):
        make_root_code(root, ec.generate_private_key(ec.SECP256R1()))


@pytest.mark.parametrize("field,value", [
    ("deployment_id", str(uuid4())), ("protocol_version", True), ("protocol_version", 2),
    ("expires_at", 1), ("expires_at", 9999999999), ("expires_at", True),
    ("nonce", "short"), ("nonce", "x" * 43),
])
def test_modified_root_code_is_rejected(setup, field, value):
    root, signing, _, _, _ = setup
    changed = rewrite(make_root_code(root, signing), ROOT_PREFIX, lambda obj: obj["data"].__setitem__(field, value))
    with pytest.raises(ApprovalError):
        trust_root_code(changed, trusted_out_of_band=True)


@pytest.mark.parametrize("change", [
    "duplicate", "whitespace", "extra-field", "non-ascii", "wrong-prefix", "truncated", "too-long", "nan", "nested",
])
def test_canonical_bounded_code_parser_rejects_ambiguous_inputs(setup, change):
    root, signing, _, _, _ = setup
    code = make_root_code(root, signing)
    if change == "duplicate":
        code = code.replace('"protocol_version":1', '"protocol_version":1,"protocol_version":1')
    elif change == "whitespace":
        code = code.replace('"protocol_version":1', '"protocol_version": 1')
    elif change == "extra-field":
        code = rewrite(code, ROOT_PREFIX, lambda obj: obj.__setitem__("extra", "field"))
    elif change == "non-ascii":
        code += "é"
    elif change == "wrong-prefix":
        code = code.replace(ROOT_PREFIX, REQUEST_PREFIX, 1)
    elif change == "truncated":
        code = code[:-1]
    elif change == "too-long":
        code += "x" * MAX_CODE_BYTES
    elif change == "nan":
        code = code.replace('"protocol_version":1', '"protocol_version":NaN')
    else:
        code = ROOT_PREFIX + "[" * 100 + "]" * 100
    with pytest.raises(ApprovalError, match="^Cannot verify device approval\\.$"):
        trust_root_code(code, trusted_out_of_band=True)


def test_request_binds_complete_enrollment_root_expiry_nonce_and_proof(setup):
    root, _, _, _, _ = setup
    code, pending, signing, encryption = requester(root)
    data = verify_request_code(code, root)
    assert len(code) <= MAX_CODE_BYTES
    assert data["root_fingerprint"] == root.fingerprint
    assert data["deployment_id"] == root.deployment_id
    assert data["candidate"]["device"] == {key: pending[key] for key in ("id", "signing_key", "encryption_key")}
    assert data["candidate"]["device"] == enrollment(root.deployment_id, pending["id"], signing, encryption)["device"]
    assert len(data["nonce"]) == 43 and int(time.time()) < data["expires_at"] <= int(time.time()) + 600
    code2 = make_request_code(root, pending["id"], signing, encryption)
    assert verify_request_code(code2, root)["nonce"] != data["nonce"]


@pytest.mark.parametrize("field", ["deployment", "root", "signing", "encryption", "device", "nonce", "expiry", "proof", "signature"])
def test_request_tampering_rejected_before_approval(setup, field):
    root, _, _, _, _ = setup
    code, _, _, _ = requester(root)

    def mutate(obj):
        data = obj["data"]
        if field == "deployment": data["deployment_id"] = str(uuid4())
        elif field == "root": data["root_fingerprint"] = "0" * 64
        elif field == "signing": data["candidate"]["device"]["signing_key"] = root.signing_key
        elif field == "encryption": data["candidate"]["device"]["encryption_key"] = root.encryption_key
        elif field == "device": data["candidate"]["device"]["id"] = "dev_" + "9" * 32
        elif field == "nonce": data["nonce"] = "x" * 43
        elif field == "expiry": data["expires_at"] = int(time.time()) + 200
        elif field == "proof": data["candidate"]["proof"] = base64.b64encode(b"invalid").decode()
        else: obj["signature"] = base64.b64encode(b"invalid").decode()

    with pytest.raises(ApprovalError):
        verify_request_code(rewrite(code, REQUEST_PREFIX, mutate), root)


def test_request_cannot_switch_to_other_pinned_root_or_root_device(setup):
    root, signing, encryption, _, _ = setup
    code, _, _, _ = requester(root)
    other = local_root(root.deployment_id, "dev_" + "3" * 32, ec.generate_private_key(ec.SECP256R1()), generate_recipient())
    with pytest.raises(ApprovalError):
        verify_request_code(code, other)
    with pytest.raises(ApprovalError):
        make_request_code(root, root.device_id, signing, encryption)


def test_initialize_approve_and_revoke_use_existing_signed_chain(setup, tmp_path):
    root, _, _, session, chain = setup
    code, pending, signing, encryption = requester(root)
    approval = RootApproval(session, root, chain)
    second = approval.approve(code, pending)
    assert second["roster"]["version"] == 2
    assert len(second["roster"]["members"]) == 2
    assert approval.approve(code, pending) == second
    chain.append(second)
    requester_session = SealedSession(tmp_path / "requester.sqlite", root.deployment_id, root.signing_key, pending["id"], signing, encryption)
    requester_session.accept_chain(chain)
    session.accept_chain(chain)
    encrypted = session.encrypt(pending["id"], {"type": "synthetic"})
    assert requester_session.receive(encrypted) == {"type": "synthetic"}
    third = RootApproval(session, root, chain).revoke(pending["id"])
    chain.append(third)
    session.accept_chain(chain)
    assert list(session.current()) == [root.device_id]
    with pytest.raises(Exception, match="Cannot verify device trust"):
        requester_session.accept_chain(chain)
    # The signed chain remembers removed IDs; a fresh request cannot re-admit.
    with pytest.raises(ApprovalError):
        RootApproval(session, root, chain).approve(code, pending)


@pytest.mark.parametrize("change", ["id", "signing", "encryption", "expired", "far-expiry", "bool-expiry", "missing", "extra"])
def test_pending_candidate_must_match_verified_public_request_exactly(setup, change):
    root, _, _, session, chain = setup
    code, pending, _, _ = requester(root)
    if change == "id": pending["id"] = "dev_" + "8" * 32
    elif change == "signing": pending["signing_key"] = root.signing_key
    elif change == "encryption": pending["encryption_key"] = root.encryption_key
    elif change == "expired": pending["expires_at"] = 1
    elif change == "far-expiry": pending["expires_at"] = 9999999999
    elif change == "bool-expiry": pending["expires_at"] = True
    elif change == "missing": del pending["expires_at"]
    else: pending["extra"] = "field"
    with pytest.raises(ApprovalError):
        RootApproval(session, root, chain).approve(code, pending)


def test_untrusted_server_chain_cannot_replace_local_root(setup):
    root, _, _, session, chain = setup
    attacker_signing = ec.generate_private_key(ec.SECP256R1())
    attacker_encryption = generate_recipient()
    attacker = local_root(root.deployment_id, root.device_id, attacker_signing, attacker_encryption)
    attacker_pending = {**attacker.member(), "expires_at": int(time.time()) + 500}
    bad_chain = [initialize_root(attacker, attacker_signing, attacker_encryption, attacker_pending, state=session.state.with_name("attacker.sqlite"))]
    with pytest.raises(ApprovalError):
        RootApproval(session, root, bad_chain)
    with pytest.raises(ApprovalError):
        RootApproval(session, attacker, chain)


def test_nonroot_cannot_approve_and_root_cannot_be_revoked(setup, tmp_path):
    root, _, _, session, chain = setup
    code, pending, signing, encryption = requester(root)
    chain.append(RootApproval(session, root, chain).approve(code, pending))
    other = SealedSession(tmp_path / "other.sqlite", root.deployment_id, root.signing_key, pending["id"], signing, encryption)
    with pytest.raises(ApprovalError):
        RootApproval(other, root, chain)
    with pytest.raises(ApprovalError):
        RootApproval(session, root, chain).revoke(root.device_id)
    with pytest.raises(ApprovalError):
        RootApproval(session, root, chain).revoke("dev_" + "9" * 32)


def test_expired_code_not_reusable_and_roster_renewal_single_use(setup, monkeypatch):
    root, signing, _, session, chain = setup
    root_code = make_root_code(root, signing, ttl_seconds=1)
    request_code, _, _, _ = requester(root)
    now = time.time()
    monkeypatch.setattr("orion_mini.hosted_approval.time.time", lambda: now + 601)
    with pytest.raises(ApprovalError):
        trust_root_code(root_code, trusted_out_of_band=True)
    with pytest.raises(ApprovalError):
        verify_request_code(request_code, root)
    approval = RootApproval(session, root, chain)
    renewed = approval.renew()
    assert renewed["roster"]["members"] == chain[0]["roster"]["members"]
    assert approval.renew() == renewed


def test_renewal_due_tracks_current_roster_expiry(setup):
    # The server refuses all devices once the latest roster expires; only the
    # root can renew, so its scheduler needs to know when renewal is due.
    root, _, _, session, chain = setup
    approval = RootApproval(session, root, chain)
    expiry = chain[-1]["roster"]["expires_at"]
    assert approval.expires_at == expiry
    assert not approval.renewal_due(margin_seconds=900, now=expiry - 901)
    assert approval.renewal_due(margin_seconds=900, now=expiry - 900)
    assert approval.renewal_due(margin_seconds=900, now=expiry + 1)
    for margin in (0, 86400, True, "900"):
        with pytest.raises(ApprovalError):
            approval.renewal_due(margin_seconds=margin, now=expiry)


@pytest.mark.parametrize("ttl", [0, 601, True, "300"])
def test_code_ttl_bounds(setup, ttl):
    root, signing, _, _, _ = setup
    with pytest.raises(ApprovalError):
        make_root_code(root, signing, ttl_seconds=ttl)


def test_initialize_requires_own_root_keys_and_exact_pending(setup):
    root, signing, encryption, session, _ = setup
    pending = {**root.member(), "expires_at": int(time.time()) + 500}
    with pytest.raises(ApprovalError):
        initialize_root(root, ec.generate_private_key(ec.SECP256R1()), encryption, pending, state=session.state)
    with pytest.raises(ApprovalError):
        initialize_root(root, signing, generate_recipient(), pending, state=session.state)
    pending["signing_key"] = "not-a-key"
    with pytest.raises(ApprovalError):
        initialize_root(root, signing, encryption, pending, state=session.state)


def test_proposal_stales_after_session_advances_and_caller_chain_cannot_mutate_it(setup):
    root, _, _, session, chain = setup
    approval = RootApproval(session, root, chain)
    frozen = copy.deepcopy(chain)
    chain[0]["roster"]["members"][0]["encryption_key"] = "tampered"
    renewed = approval.renew()
    assert renewed["roster"]["members"] == frozen[0]["roster"]["members"]
    next_approval = RootApproval(session, root, frozen)
    session.accept_chain(frozen + [renewed])
    with pytest.raises(ApprovalError):
        next_approval.renew()


def test_prototype_roster_version_limit_fails_closed(setup):
    root, signing, _, session, chain = setup
    for version in range(2, 129):
        previous = chain[-1]["roster"]
        roster = {**previous, "version": version, "previous_hash": hashlib.sha256(canonical(previous)).hexdigest()}
        chain.append(sign_roster(roster, signing))
    with pytest.raises(ApprovalError):
        RootApproval(session, root, chain).renew()


def test_member_limit_rejects_a_thirty_third_device(setup):
    root, signing, _, session, chain = setup
    members = [root.member()]
    for number in range(2, 33):
        other_signing = ec.generate_private_key(ec.SECP256R1())
        other_encryption = generate_recipient()
        members.append(enrollment(root.deployment_id, "dev_" + f"{number:032x}", other_signing, other_encryption)["device"])
    previous = chain[-1]["roster"]
    roster = {**previous, "version": 2, "previous_hash": hashlib.sha256(canonical(previous)).hexdigest(),
              "members": sorted(members, key=lambda member: member["id"])}
    chain.append(sign_roster(roster, signing))
    code, pending, _, _ = requester(root, "dev_" + "9" * 32)
    with pytest.raises(ApprovalError):
        RootApproval(session, root, chain).approve(code, pending)


def test_public_only_keyset_cannot_initialize_root_or_generate_request(setup):
    root, signing, encryption, _, _ = setup
    with pytest.raises(ApprovalError):
        local_root(root.deployment_id, root.device_id, signing, encryption.public_keyset_handle())
    with pytest.raises(ApprovalError):
        make_request_code(root, "dev_" + "2" * 32, signing, encryption.public_keyset_handle())


def test_concurrent_approval_proposes_once(setup):
    root, _, _, session, chain = setup
    code, pending, _, _ = requester(root)
    approval = RootApproval(session, root, chain)
    start = threading.Barrier(3)
    results = []

    def propose():
        start.wait()
        try:
            approval.approve(code, pending)
            results.append("signed")
        except ApprovalError:
            results.append("rejected")

    workers = [threading.Thread(target=propose) for _ in range(2)]
    for worker in workers:
        worker.start()
    start.wait()
    for worker in workers:
        worker.join(timeout=3)
        assert not worker.is_alive()
    assert results == ["signed", "signed"]


def test_durable_proposal_retries_exact_bytes_across_instances_and_restart(setup, monkeypatch):
    root, signing, encryption, session, chain = setup
    code, pending, _, _ = requester(root)
    first = RootApproval(session, root, chain).approve(code, pending)
    now = time.time()
    monkeypatch.setattr("orion_mini.hosted_approval.time.time", lambda: now + 10)
    restarted = SealedSession(session.state, root.deployment_id, root.signing_key, root.device_id, signing, encryption)
    retried = RootApproval(restarted, root, chain).approve(code, pending)
    assert canonical(first) == canonical(retried)
    other_code, other_pending, _, _ = requester(root, "dev_" + "3" * 32)
    with pytest.raises(ApprovalError):
        RootApproval(restarted, root, chain).approve(other_code, other_pending)
    with pytest.raises(ApprovalError):
        RootApproval(restarted, root, chain).renew()


def test_genesis_is_durable_and_cannot_be_resigned_differently(setup, monkeypatch):
    root, signing, encryption, session, chain = setup
    now = time.time()
    monkeypatch.setattr("orion_mini.hosted_approval.time.time", lambda: now + 10)
    pending = {**root.member(), "expires_at": int(time.time()) + 500}
    retried = initialize_root(root, signing, encryption, pending, state=session.state)
    assert canonical(retried) == canonical(chain[0])
    with pytest.raises(ApprovalError):
        initialize_root(root, signing, encryption, pending, state=session.state, roster_ttl_seconds=7200)
    other_recipient = generate_recipient()
    different = local_root(root.deployment_id, root.device_id, signing, other_recipient)
    with pytest.raises(ApprovalError):
        initialize_root(different, signing, other_recipient, {**different.member(), "expires_at": int(time.time()) + 500}, state=session.state)


def test_concurrent_conflicting_instances_cannot_sign_forks(setup):
    root, signing, encryption, session, chain = setup
    other_session = SealedSession(session.state, root.deployment_id, root.signing_key, root.device_id, signing, encryption)
    approvals = [RootApproval(session, root, chain), RootApproval(other_session, root, chain)]
    requests = [requester(root, "dev_" + digit * 32)[:2] for digit in ("2", "3")]
    start = threading.Barrier(3)
    results = []

    def propose(index):
        start.wait()
        try:
            results.append(approvals[index].approve(*requests[index]))
        except ApprovalError:
            results.append(None)

    workers = [threading.Thread(target=propose, args=(index,)) for index in range(2)]
    for worker in workers: worker.start()
    start.wait()
    for worker in workers:
        worker.join(timeout=3)
        assert not worker.is_alive()
    assert sum(result is not None for result in results) == 1


def test_expired_root_can_renew_without_reenabling_expired_content(setup, monkeypatch, tmp_path):
    root, signing, encryption, session, chain = setup
    code, pending, other_signing, other_encryption = requester(root)
    chain.append(RootApproval(session, root, chain).approve(code, pending))
    session.accept_chain(chain)
    other = SealedSession(tmp_path / "other-expired.sqlite", root.deployment_id, root.signing_key, pending["id"], other_signing, other_encryption)
    other.accept_chain(chain)
    old_event = other.encrypt(root.device_id, {"type": "synthetic"})
    future = chain[-1]["roster"]["expires_at"] + 1
    monkeypatch.setattr("orion_mini.hosted_session.time.time", lambda: future)
    with pytest.raises(Exception, match="Current device approval"):
        session.encrypt(pending["id"], {"type": "synthetic"})
    with pytest.raises(Exception, match="Current device approval"):
        session.receive(old_event)
    with pytest.raises(Exception, match="Cannot verify device trust"):
        session.accept_chain(chain)
    with pytest.raises(Exception, match="Cannot verify device trust"):
        other.root_history(chain)
    restarted = SealedSession(session.state, root.deployment_id, root.signing_key, root.device_id, signing, encryption)
    renewed = RootApproval(restarted, root, chain).renew()
    assert renewed["roster"]["expires_at"] > future
    assert restarted.roster is None and restarted.digest is None
    with pytest.raises(Exception, match="Current device approval"):
        restarted.encrypt(pending["id"], {"type": "synthetic"})
    with pytest.raises(Exception, match="Current device approval"):
        restarted.receive(old_event)
    chain.append(renewed)
    restarted.accept_chain(chain)
    other.accept_chain(chain)
    assert other.receive(restarted.encrypt(pending["id"], {"type": "fresh"})) == {"type": "fresh"}


def _process_propose(state, root_dict, signing_pem, encryption_bytes, chain, request_code, pending, gate, result):
    from cryptography.hazmat.primitives import serialization
    from tink import proto_keyset_format, secret_key_access
    from orion_mini.hosted_approval import TrustedRoot
    from pathlib import Path
    root = TrustedRoot(**root_dict)
    signing = serialization.load_pem_private_key(signing_pem, password=None)
    encryption = proto_keyset_format.parse(encryption_bytes, secret_key_access.TOKEN)
    session = SealedSession(Path(state), root.deployment_id, root.signing_key, root.device_id, signing, encryption)
    approval = RootApproval(session, root, chain)
    gate.wait(10)
    try:
        result.put(("signed", canonical(approval.approve(request_code, pending))))
    except ApprovalError:
        result.put(("rejected", b""))


def test_separate_processes_share_the_same_proposal_cas(setup):
    from cryptography.hazmat.primitives import serialization
    from dataclasses import asdict
    from tink import proto_keyset_format, secret_key_access
    root, signing, encryption, session, chain = setup
    # Synthetic private keys travel only through multiprocessing's private IPC;
    # no fixture writes them to disk or logs them.
    pem = signing.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    recipient = proto_keyset_format.serialize(encryption, secret_key_access.TOKEN)
    context = multiprocessing.get_context("spawn")
    gate = context.Event()
    result = context.Queue()
    requests = [requester(root, "dev_" + digit * 32)[:2] for digit in ("2", "3")]
    workers = [context.Process(target=_process_propose, args=(str(session.state), asdict(root), pem, recipient, chain, *request, gate, result)) for request in requests]
    for worker in workers: worker.start()
    gate.set()
    outcomes = [result.get(timeout=20) for _ in workers]
    for worker in workers:
        worker.join(timeout=20)
        assert worker.exitcode == 0
    result.close()
    result.join_thread()
    assert sorted(outcome[0] for outcome in outcomes) == ["rejected", "signed"]


def test_withheld_expired_proposal_remains_exact_commitment_and_fails_closed(setup, monkeypatch):
    root, signing, encryption, session, chain = setup
    approval = RootApproval(session, root, chain)
    assert approval.pending_proposal() is None
    proposal = approval.renew()
    future = proposal["roster"]["expires_at"] + 1
    monkeypatch.setattr("orion_mini.hosted_approval.time.time", lambda: future)
    restarted = SealedSession(session.state, root.deployment_id, root.signing_key, root.device_id, signing, encryption)
    retry = RootApproval(restarted, root, chain)
    assert canonical(retry.pending_proposal()) == canonical(proposal)
    assert canonical(retry.renew()) == canonical(proposal)
    assert proposal["roster"]["expires_at"] < int(time.time())
    with pytest.raises(ApprovalError):
        retry.renew(roster_ttl_seconds=7200)
    with pytest.raises(Exception, match="Cannot verify device trust"):
        restarted.accept_chain(chain + [proposal])
    with pytest.raises(Exception, match="Current device approval"):
        restarted.current()


def test_prepare_catchup_extends_expired_commitment_without_fork_or_content_authority(setup, monkeypatch):
    root, signing, encryption, session, chain = setup
    proposal = RootApproval(session, root, chain).renew()
    future = proposal["roster"]["expires_at"] + 1
    monkeypatch.setattr("orion_mini.hosted_approval.time.time", lambda: future)
    expected = hashlib.sha256(canonical(chain[-1]["roster"])).hexdigest()
    restarted = SealedSession(session.state, root.deployment_id, root.signing_key, root.device_id, signing, encryption)
    payload = prepare_catchup(restarted, root, chain + [proposal], expected_hash=expected)
    assert payload["expected_hash"] == expected
    assert canonical(payload["chain"][0]) == canonical(proposal)
    assert payload["chain"][-1]["roster"]["expires_at"] > future
    assert payload["chain"][-1]["roster"]["previous_hash"] == hashlib.sha256(canonical(proposal["roster"])).hexdigest()
    with pytest.raises(Exception, match="Current device approval"):
        restarted.current()
    assert canonical(prepare_catchup(restarted, root, chain + [proposal], expected_hash=expected)) == canonical(payload)
    restarted.accept_chain(chain + payload["chain"])
    assert restarted.current()[root.device_id] == root.member()


def test_prepare_catchup_supports_expired_genesis_exact_commitment(setup, monkeypatch):
    root, _, _, session, chain = setup
    monkeypatch.setattr("orion_mini.hosted_approval.time.time", lambda: chain[0]["roster"]["expires_at"] + 1)
    payload = prepare_catchup(session, root, chain, expected_hash=None)
    assert payload["expected_hash"] is None
    assert canonical(payload["chain"][0]) == canonical(chain[0])
    assert payload["chain"][1]["roster"]["version"] == 2
    assert session.roster is None


@pytest.mark.parametrize("fault", ["unknown-head", "invalid-head", "fork", "nonroot", "batch"])
def test_prepare_catchup_rejects_invalid_authority_or_unbounded_suffix(setup, tmp_path, fault):
    root, signing, encryption, session, chain = setup
    expected = None
    if fault == "unknown-head": expected = "0" * 64
    elif fault == "invalid-head": expected = True
    elif fault == "fork": chain[0]["roster"]["members"][0]["encryption_key"] = root.signing_key
    elif fault == "nonroot":
        session = SealedSession(tmp_path / "nonroot.sqlite", root.deployment_id, root.signing_key,
                                "dev_" + "2" * 32, signing, encryption)
    elif fault == "batch":
        for _ in range(16): chain.append(RootApproval(session, root, chain).renew())
    with pytest.raises(ApprovalError):
        prepare_catchup(session, root, chain, expected_hash=expected)


def test_prepare_catchup_never_replaces_an_expired_fresh_successor(setup, monkeypatch):
    root, _, _, session, chain = setup
    first_payload = prepare_catchup(session, root, chain, expected_hash=None)
    expired_successor = first_payload["chain"][-1]
    monkeypatch.setattr("orion_mini.hosted_approval.time.time", lambda: expired_successor["roster"]["expires_at"] + 1)
    with pytest.raises(ApprovalError):
        prepare_catchup(session, root, chain, expected_hash=None)
    recovered = prepare_catchup(session, root, chain + [expired_successor], expected_hash=None)
    assert canonical(recovered["chain"][:2]) == canonical(first_payload["chain"])
    assert recovered["chain"][-1]["roster"]["version"] == 3


def test_anchor_catchup_preserves_approved_intent_after_expiry(setup, monkeypatch):
    root, _, _, session, chain = setup
    session.accept_chain(chain)
    expected = session.history_cursor()["after_hash"]
    code, pending, _, _ = requester(root)
    proposal = RootApproval(session, root).approve(code, pending, roster_ttl_seconds=1)
    monkeypatch.setattr("time.time", lambda: proposal["roster"]["expires_at"] + 1)
    result = prepare_anchored_catchup(session, root, expected_hash=expected)
    assert result["chain"][0] == proposal
    assert result["chain"][1]["roster"]["members"] == proposal["roster"]["members"]
    assert result["chain"][1]["roster"]["version"] == 3
    assert prepare_anchored_catchup(session, root, expected_hash=expected) == result
    with pytest.raises(EnvelopeError): session.current()


def test_anchor_catchup_reuses_fresh_pending_approval_without_changing_it(setup):
    root, _, _, session, chain = setup
    session.accept_chain(chain)
    expected = session.history_cursor()["after_hash"]
    code, pending, _, _ = requester(root)
    proposal = RootApproval(session, root).approve(code, pending)
    assert prepare_anchored_catchup(session, root, expected_hash=expected)["chain"] == [proposal]
    assert RootApproval(session, root).pending_proposal() == proposal


def test_anchor_catchup_missing_journal_fails_without_new_signature(setup):
    root, signing, _, session, chain = setup
    session.accept_chain(chain)
    expected = session.history_cursor()["after_hash"]
    outside_journal = sign_roster({**chain[0]["roster"], "version": 2, "previous_hash": expected}, signing)
    session.accept_page([outside_journal], final=False)
    with session.connect() as db: before = db.execute("SELECT COUNT(*) FROM approval_proposals").fetchone()[0]
    with pytest.raises(ApprovalError): prepare_anchored_catchup(session, root, expected_hash=expected)
    with session.connect() as db: assert db.execute("SELECT COUNT(*) FROM approval_proposals").fetchone()[0] == before


def test_anchor_root_approval_requires_exact_root_identity(setup, tmp_path):
    root, signing, encryption, session, chain = setup
    session.accept_chain(chain)
    other = SealedSession(tmp_path / "other-root.sqlite", root.deployment_id, root.signing_key,
                          "dev_" + "9" * 32, signing, encryption)
    with pytest.raises(EnvelopeError): other.accept_page(chain, final=True)
    with pytest.raises(ApprovalError): RootApproval(other, root)
