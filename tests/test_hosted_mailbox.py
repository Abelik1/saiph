# SPDX-License-Identifier: AGPL-3.0-or-later
import copy
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
pytest.importorskip("tink")
from cryptography.hazmat.primitives.asymmetric import ec

from orion_mini.hosted_crypto import EnvelopeError, canonical, export_public, generate_recipient
from orion_mini.hosted_session import SealedSession, public_signing_key, sign_roster
from orion_mini.hosted_mailbox import DurableMailbox
from orion_mini.hosted_transport import TransportError


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


def reopen(session, chain):
    result = SealedSession(session.state, session.deployment, session.pin, session.device, session.signing, session.encryption)
    result.accept_chain(chain)
    return result


def test_durable_before_ack_and_restart_no_plaintext(pair):
    sender, receiver, chain = pair
    content = "SYNTHETIC-PRIVATE-" + uuid4().hex
    event = sender.encrypt(receiver.device, {"type": "sms.send", "body": content})
    inbox = DurableMailbox(receiver)
    assert inbox.ingest(event)
    restarted = DurableMailbox(reopen(receiver, chain))
    assert not restarted.ingest(event)
    assert restarted.pending() == [event]
    assert restarted.claim(event["header"]["id"])["body"] == content
    restarted.complete(event["header"]["id"], "succeeded")
    assert not restarted.ingest(event)
    assert restarted.pending() == []
    for path in receiver.state.parent.iterdir():
        if path.is_file():
            assert content.encode() not in path.read_bytes()


def test_claim_survives_crash_and_does_not_repeat_effect(pair):
    sender, receiver, chain = pair
    event = sender.encrypt(receiver.device, {"type": "call.answer"})
    mailbox = DurableMailbox(receiver)
    mailbox.ingest(event)
    mailbox.claim(event["header"]["id"])
    recovered = DurableMailbox(reopen(receiver, chain))
    assert recovered.uncertain() == [event["header"]["id"]]
    assert recovered.pending() == []
    with pytest.raises(EnvelopeError):
        recovered.claim(event["header"]["id"])
    recovered.complete(event["header"]["id"], "uncertain")
    recovered.complete(event["header"]["id"], "uncertain")
    with pytest.raises(EnvelopeError):
        recovered.complete(event["header"]["id"], "succeeded")


def test_ingest_transaction_failure_leaves_no_replay_claim(pair):
    sender, receiver, _ = pair
    event = sender.encrypt(receiver.device, {"type": "test"})
    mailbox = DurableMailbox(receiver)
    with receiver.connect() as db:
        db.execute("CREATE TRIGGER fail_inbox BEFORE INSERT ON hosted_incoming BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        mailbox.ingest(event)
    with receiver.connect() as db:
        assert db.execute("SELECT count(*) FROM received").fetchone() == (0,)
        db.execute("DROP TRIGGER fail_inbox")
    assert mailbox.ingest(event)


def test_concurrent_delivery_is_claimed_once(pair):
    sender, receiver, chain = pair
    event = sender.encrypt(receiver.device, {"type": "test"})
    a, b = DurableMailbox(receiver), DurableMailbox(reopen(receiver, chain))
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(lambda box: box.ingest(event), [a, b])) == [False, True]


def test_conflicting_duplicate_and_tamper_rejected(pair):
    sender, receiver, _ = pair
    event = sender.encrypt(receiver.device, {"type": "test"})
    mailbox = DurableMailbox(receiver)
    mailbox.ingest(event)
    # Even a valid re-encryption of the same ID cannot replace its first bytes.
    from orion_mini.hosted_crypto import seal
    conflict = {**event, "ciphertext": seal(export_public(receiver.encryption), sender.signing, event["header"], {"type": "other"})}
    with pytest.raises(EnvelopeError, match="Conflicting"):
        mailbox.ingest(conflict)
    with receiver.connect() as db:
        db.execute("UPDATE hosted_incoming SET envelope=?", (json.dumps(conflict).encode(),))
    with pytest.raises(EnvelopeError):
        mailbox.claim(event["header"]["id"])


def test_expired_and_revoked_pending_not_dispatched(pair, monkeypatch):
    sender, receiver, chain = pair
    event = sender.encrypt(receiver.device, {"type": "call.answer"})
    mailbox = DurableMailbox(receiver)
    mailbox.ingest(event)
    monkeypatch.setattr(time, "time", lambda: event["header"]["expires_at"])
    assert mailbox.pending() == []
    with pytest.raises(EnvelopeError):
        mailbox.claim(event["header"]["id"])
    monkeypatch.undo()
    revoked = sign_roster({**chain[-1]["roster"], "version": 3,
                          "previous_hash": hashlib.sha256(canonical(chain[-1]["roster"])).hexdigest(),
                          "members": chain[0]["roster"]["members"]}, sender.signing)
    with pytest.raises(EnvelopeError):
        receiver.accept_chain(chain + [revoked])
    with pytest.raises(EnvelopeError):
        mailbox.claim(event["header"]["id"])


def test_exact_outbox_retry_after_lost_response(pair):
    sender, receiver, chain = pair
    outbox = DurableMailbox(sender)
    event_id = outbox.stage(receiver.device, {"type": "sms.send", "body": "synthetic"})
    sent = []
    class Relay:
        def publish(self, envelope):
            sent.append(copy.deepcopy(envelope))
            if len(sent) == 1:
                raise TransportError()
            return {"accepted": True, "duplicate": True}
    relay = Relay()
    with pytest.raises(TransportError):
        outbox.flush(relay)
    restarted = DurableMailbox(reopen(sender, chain))
    assert restarted.flush(relay) == 1
    assert sent[0] == sent[1] and sent[0]["header"]["id"] == event_id
    assert restarted.flush(relay) == 0


def test_poll_ack_timeout_redelivery_and_no_ack_on_failed_ingest(pair):
    sender, receiver, _ = pair
    event = sender.encrypt(receiver.device, {"type": "test"})
    mailbox = DurableMailbox(receiver)
    acknowledgements = []
    class Relay:
        def events(self): return [event]
        def acknowledge(self, event_id):
            acknowledgements.append(event_id)
            assert mailbox.pending() == [event]
            if len(acknowledgements) == 1: raise TransportError()
    with pytest.raises(TransportError): mailbox.poll(Relay())
    assert mailbox.poll(Relay()) == 0
    event["header"]["roster_hash"] = "f" * 64
    with pytest.raises(EnvelopeError): mailbox.poll(Relay())
    assert len(acknowledgements) == 2


def test_legacy_claim_cannot_silently_drop_actions(pair):
    sender, receiver, _ = pair
    event = sender.encrypt(receiver.device, {"type": "test"})
    receiver.receive(event)
    with pytest.raises(EnvelopeError, match="outside"):
        DurableMailbox(receiver).ingest(event)


def test_completion_does_not_store_user_text(pair):
    _, receiver, _ = pair
    with pytest.raises(EnvelopeError): DurableMailbox(receiver).complete(str(uuid4()), "private body")


def test_mailbox_cannot_rebind_to_another_approved_identity(pair):
    sender, receiver, chain = pair
    DurableMailbox(receiver)
    another = SealedSession(receiver.state, receiver.deployment, receiver.pin, sender.device, sender.signing, sender.encryption)
    another.accept_chain(chain)
    with pytest.raises(EnvelopeError, match="identity"):
        DurableMailbox(another)


def test_outbox_is_fenced_when_roster_changes(pair):
    sender, receiver, chain = pair
    box = DurableMailbox(sender)
    box.stage(receiver.device, {"type": "sms.send", "body": "synthetic"})
    third = sign_roster({**chain[-1]["roster"], "version": 3,
                        "previous_hash": hashlib.sha256(canonical(chain[-1]["roster"])).hexdigest()}, sender.signing)
    sender.accept_chain(chain + [third])
    class Relay:
        def publish(self, _): pytest.fail("Old roster ciphertext cannot be sent")
    assert box.flush(Relay()) == 0


def test_old_pending_prefix_cannot_starve_fresh_events_after_restart(pair):
    sender, receiver, chain = pair
    box = DurableMailbox(receiver)
    for _ in range(101):
        box.ingest(sender.encrypt(receiver.device, {"type": "test.old"}))
    renewal = sign_roster({**chain[-1]["roster"], "version": 3,
                          "previous_hash": hashlib.sha256(canonical(chain[-1]["roster"])).hexdigest()}, sender.signing)
    chain.append(renewal)
    sender.accept_chain(chain)
    receiver.accept_chain(chain)
    fresh = sender.encrypt(receiver.device, {"type": "test.fresh"})
    box.ingest(fresh)
    recovered = DurableMailbox(reopen(receiver, chain))
    assert recovered.pending() == [fresh]
    assert recovered.claim(fresh["header"]["id"]) == {"type": "test.fresh"}


def test_actual_process_exit_after_claim_never_repeats_action(pair):
    """Synthetic keys travel over stdin only; no key fixture or payload output."""
    import base64
    from cryptography.hazmat.primitives import serialization
    from tink import proto_keyset_format, secret_key_access
    sender, receiver, chain = pair
    canary = "PROCESS-ONLY-SYNTHETIC-" + uuid4().hex
    event = sender.encrypt(receiver.device, {"type": "sms.send", "body": canary}, ttl_seconds=300)
    DurableMailbox(receiver).ingest(event)
    # A new interpreter opens existing ciphertext state. Real native key loading
    # is covered separately; these disposable keys are injected only in memory.
    fixture = {"state": str(receiver.state), "deployment": receiver.deployment, "root": receiver.pin,
               "device": receiver.device, "chain": chain, "event_id": event["header"]["id"],
               "signing": base64.b64encode(receiver.signing.private_bytes(serialization.Encoding.DER,
                   serialization.PrivateFormat.PKCS8, serialization.NoEncryption())).decode(),
               "recipient": base64.b64encode(proto_keyset_format.serialize(receiver.encryption, secret_key_access.TOKEN)).decode()}
    code = '''
import base64,json,sys,os
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from tink import proto_keyset_format,secret_key_access
from orion_mini.hosted_session import SealedSession
from orion_mini.hosted_mailbox import DurableMailbox
from orion_mini.hosted_crypto import EnvelopeError
v=json.load(sys.stdin)
s=SealedSession(Path(v['state']),v['deployment'],v['root'],v['device'],
    serialization.load_der_private_key(base64.b64decode(v['signing']),password=None),
    proto_keyset_format.parse(base64.b64decode(v['recipient']),secret_key_access.TOKEN))
s.accept_chain(v['chain'])
b=DurableMailbox(s)
if v['mode']=='claim':
    b.claim(v['event_id'])
    os._exit(23) # No completion, interpreter cleanup or auto-retry.
try:
    b.claim(v['event_id'])
    sys.exit(2)
except EnvelopeError:
    assert b.uncertain()==[v['event_id']]
    b.complete(v['event_id'],'uncertain')
'''
    def child(mode):
        import os
        environment = {**os.environ, "PYTHONPATH": str(__import__('pathlib').Path(__file__).resolve().parents[1] / "src")}
        return subprocess.run([sys.executable, "-c", code], input=json.dumps({**fixture, "mode": mode}).encode(),
                              capture_output=True, env=environment, timeout=30)
    crashed, recovered = child("claim"), child("recover")
    assert crashed.returncode == 23 and recovered.returncode == 0
    assert canary.encode() not in crashed.stdout + crashed.stderr + recovered.stdout + recovered.stderr
    for path in receiver.state.parent.glob(receiver.state.name + "*"):
        assert canary.encode() not in path.read_bytes()
