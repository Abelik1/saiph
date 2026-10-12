# SPDX-License-Identifier: AGPL-3.0-or-later
"""Disposable synthetic clients: actual TLS sockets and production adapters."""
from __future__ import annotations
import base64
import hashlib
import json
from pathlib import Path
import secrets
import sys
import time
from cryptography.hazmat.primitives import serialization
from orion_mini.hosted_files import prepare_attachment, upload_attachment, download_attachment, AttachmentError
from orion_mini.hosted_crypto import EnvelopeError
from orion_mini.hosted_session import SealedSession
from acceptance import (
    AcceptanceError, CLIENT, Client, account_token, node, reopened, wait_ready,
    RootApproval, initialize_root, make_root_code, trust_root_code,
    make_request_code, verify_request_code, prepare_catchup, enrollment,
    HostedTransport, DurableMailbox, TransportError, canonical,
)

CONTROL = Path('/control')

def control(operation, **data):
    request = CONTROL / 'request.json'
    response = CONTROL / 'response.json'
    response.unlink(missing_ok=True)
    staged = CONTROL / 'request.tmp'
    staged.write_text(json.dumps({'operation': operation, **data}))
    staged.replace(request)
    end = time.monotonic() + 60
    while time.monotonic() < end:
        if response.is_file():
            result = json.loads(response.read_text())
            if result != {'ok': True}:
                raise AcceptanceError('Host control operation failed')
            request.unlink(missing_ok=True)
            return
        time.sleep(0.1)
    raise AcceptanceError('Host control operation timed out')


def scan(sessions, canaries, tokens):
    needles = [value.encode() for value in canaries + tokens]
    for session in sessions:
        raw = b''.join(p.read_bytes() for p in session.state.parent.glob(session.state.name + '*') if p.is_file())
        if any(needle in raw for needle in needles):
            raise AcceptanceError('Sensitive material was present in client durable state')
    control('scan', canaries=canaries, tokens=tokens)


def main():
    config = json.load(sys.stdin)
    jwt_key = serialization.load_pem_private_key(config['jwt_signing_pem'].encode(), password=None)
    endpoints, deployments, owners = config['endpoints'], config['deployments'], config['owners']
    private = Path('/tmp/orion-clients')
    private.mkdir(mode=0o700)
    ca = Path('/fixture/ca.crt')
    receipt = {'checks': {}, 'status': 'running'}
    step = 'services-ready'
    try:
        clients = [Client(base, ca) for base in endpoints]
        step = "services-ready"
        for client in clients:
            wait_ready(client)

        tokens = [account_token(jwt_key, owner) for owner in owners]
        step = "account-isolation"
        roots_sessions = [node(private, deployment) for deployment in deployments]
        account_http = [HostedTransport(endpoints[index], pair[1], ca_bundle=ca) for index, pair in enumerate(roots_sessions)]
        for index, client in enumerate(clients):
            account_http[index].account(tokens[index])
            client.call("GET", "/v1/account", token=tokens[1 - index], expected=401)
            client.call("GET", "/v1/account", token=account_token(jwt_key, owners[index], aud=CLIENT), expected=401)
            client.call("GET", "/v1/account", token=account_token(jwt_key, owners[index], azp="unapproved-client"), expected=401)
        receipt["checks"][step] = True
        step = "trusted-enrollment"
        root, sender = roots_sessions[0]
        root_code = make_root_code(root, sender.signing)
        pinned = trust_root_code(root_code, expected_fingerprint=root.fingerprint)
        _, receiver = node(private, deployments[0], pinned)
        root_enrollment = enrollment(deployments[0], sender.device, sender.signing, sender.encryption)
        clients[1].call("POST", "/v1/devices/requests", token=tokens[1], value=root_enrollment, expected=400)
        pending = account_http[0].enroll(tokens[0], root_enrollment)
        first = initialize_root(root, sender.signing, sender.encryption,
            {**root.member(), "expires_at": pending["expires_at"]}, state=sender.state)
        account_http[0].submit_roster(tokens[0], first)
        request_code = make_request_code(pinned, receiver.device, receiver.signing, receiver.encryption)
        request = verify_request_code(request_code, root)
        pending = account_http[0].enroll(tokens[0], request["candidate"])
        second = RootApproval(sender, root, [first]).approve(request_code,
            {**request["candidate"]["device"], "expires_at": pending["expires_at"]})
        account_http[0].submit_roster(tokens[0], second)
        chain = account_http[0].rosters(tokens[0])
        sender.accept_chain(chain)
        receiver.accept_chain(chain)
        receipt["checks"][step] = True
        step = "expired-proposal-catchup"
        expected_head = hashlib.sha256(canonical(chain[-1]["roster"])).hexdigest()
        expired_step = RootApproval(sender, root, chain).renew(roster_ttl_seconds=1)
        # Wait for a bounded synthetic one-second commitment to expire.
        while int(time.time()) <= expired_step["roster"]["expires_at"]:
            time.sleep(0.1)
        catchup = prepare_catchup(sender, root, chain + [expired_step], expected_hash=expected_head)
        invalid_catchup = json.loads(json.dumps(catchup))
        invalid_catchup["chain"][-1]["signature"] = base64.b64encode(b"invalid-signature").decode()
        clients[0].call("POST", "/v1/devices/rosters/catchup", token=tokens[0], value=invalid_catchup, expected=403)
        if account_http[0].rosters(tokens[0]) != chain:
            raise AcceptanceError("Failed catch-up changed current roster")
        accepted_catchup = clients[0].call("POST", "/v1/devices/rosters/catchup", token=tokens[0], value=catchup)
        if clients[0].call("POST", "/v1/devices/rosters/catchup", token=tokens[0], value=catchup) != accepted_catchup:
            raise AcceptanceError("Catch-up retry was not idempotent")
        chain = account_http[0].rosters(tokens[0])
        sender.accept_chain(chain)
        receiver.accept_chain(chain)
        receipt["checks"][step] = True
        send_http, receive_http = HostedTransport(endpoints[0], sender, ca_bundle=ca), HostedTransport(endpoints[0], receiver, ca_bundle=ca)
        outgoing, incoming = DurableMailbox(sender), DurableMailbox(receiver)
        step = "sealed-delivery"
        kinds = ["clipboard.text", "notification.posted", "sms.thread", "call.state", "file.metadata", "photo.metadata"]
        canaries = ["ORION-SYNTHETIC-CONTENT-" + secrets.token_hex(24) for _ in kinds]
        expected = {}
        for kind, canary in zip(kinds, canaries):
            payload = {"type": kind, "synthetic_body": canary}
            expected[outgoing.stage(receiver.device, payload, ttl_seconds=300)] = payload

        class LostPublishResponse:
            def publish(self, envelope):
                send_http.publish(envelope)
                raise TransportError()  # Server accepted; response was lost.

        try:
            outgoing.flush(LostPublishResponse())
            raise AcceptanceError("Synthetic response loss did not occur")
        except TransportError:
            pass
        sender = reopened(sender, chain)
        outgoing = DurableMailbox(sender)
        send_http = HostedTransport(endpoints[0], sender, ca_bundle=ca)
        if outgoing.flush(send_http) != 6:
            raise AcceptanceError("Encrypted outbox did not recover exact retries")
        delivered = receive_http.events()
        if len(delivered) != 6 or {event["header"]["id"] for event in delivered} != set(expected):
            raise AcceptanceError("Encrypted delivery mismatch")
        if any(not incoming.ingest(event) for event in delivered):
            raise AcceptanceError("Unexpected initial replay")
        scan([sender, receiver], canaries, tokens)
        receipt["checks"]["content-absence-before-ack"] = True
        receipt["checks"]["lost-publish-response-exact-retry"] = True
        receipt["checks"][step] = True
        step = "persisted-restart"
        control("restart-a")
        step = "restart-services-ready"
        wait_ready(clients[0])
        step = "restart-client-open"
        receiver = reopened(receiver, chain)
        incoming = DurableMailbox(receiver)
        receive_http = HostedTransport(endpoints[0], receiver, ca_bundle=ca)
        # Reconnect both peers/account controller after deployment replacement;
        # stale pre-restart connection pools are not an application retry loop.
        send_http.close()
        send_http = HostedTransport(endpoints[0], sender, ca_bundle=ca)
        account_http[0].close()
        account_http[0] = HostedTransport(endpoints[0], sender, ca_bundle=ca)
        step = "restart-server-queue"
        if receive_http.events() != delivered:
            raise AcceptanceError("Mailbox did not persist restart")
        step = "restart-durable-replay-ack"
        if incoming.poll(receive_http) != 0 or receive_http.events():
            raise AcceptanceError("Durable pre-ack inbox did not suppress replay")
        step = "restart-local-inbox"
        pending_envelopes = incoming.pending()
        if {event["header"]["id"] for event in pending_envelopes} != set(expected):
            raise AcceptanceError("Encrypted local inbox did not persist restart")
        for event in pending_envelopes:
            identifier = event["header"]["id"]
            if incoming.claim(identifier) != expected[identifier]:
                raise AcceptanceError("Feature payload changed")
            incoming.complete(identifier, "succeeded")
        if incoming.pending():
            raise AcceptanceError("Completed synthetic features were repeated")
        step = "cross-deployment-device-rejection"
        clients[1].call("GET", "/v1/sealed/events", expected=401)
        Client(endpoints[1], ca, receiver).call("GET", "/v1/sealed/events", expected=403)
        receipt["checks"]["persisted-restart"] = True
        receipt["checks"]["six-feature-payloads-claimed-once"] = True
        receipt["checks"]["client-state-reopen-before-ack"] = True
        step = "encrypted-file-byte-roundtrip"
        ciphertext_folder = private / "ciphertext-staging"
        ciphertext_folder.mkdir(mode=0o700)
        file_canary = "ORION-SYNTHETIC-FILE-BODY-" + secrets.token_hex(24)
        filename = "ORION-PRIVATE-FILENAME-" + secrets.token_hex(16) + ".bin"
        private_mime = "application/x-orion-test-" + secrets.token_hex(12)
        canaries.extend([file_canary, filename, private_mime])
        source = private / filename
        # Cross two 1 MiB streaming-AEAD segment boundaries and many relay chunks.
        original = file_canary.encode() + secrets.token_bytes(2 * 1024 * 1024 + 123_456)
        source.write_bytes(original)
        # Actual supported streaming encryption and real opaque blob routes.
        prepared = prepare_attachment(sender, receiver.device, source, ciphertext_folder, mime=private_mime)
        upload_attachment(send_http, prepared)
        upload_attachment(send_http, prepared)  # All chunks and manifest retry exactly.
        envelopes = receive_http.events()
        if envelopes != [prepared.envelope]:
            raise AcceptanceError("Attachment manifest retry duplicated delivery")
        scan([sender, receiver], canaries, tokens)
        receipt["checks"]["encrypted-file-content-absence-before-ack"] = True

        class CorruptDownload:
            def download_blob_chunk(self, blob_id, index):
                raw = receive_http.download_blob_chunk(blob_id, index)
                return bytes([raw[0] ^ 1]) + raw[1:] if index == 0 else raw

        rejected_destination = private / "corrupt-file-must-not-appear.bin"
        try:
            download_attachment(receiver, CorruptDownload(), envelopes[0], rejected_destination)
            raise AcceptanceError("Corrupt attachment was published")
        except AttachmentError:
            if rejected_destination.exists():
                raise AcceptanceError("Rejected attachment became visible")
        destination = private / "verified-file.bin"
        download_attachment(receiver, receive_http, envelopes[0], destination)
        if destination.read_bytes() != original:
            raise AcceptanceError("Attachment bytes changed")
        receive_http.acknowledge(envelopes[0]["header"]["id"])
        receive_http.delete_blob(prepared.descriptor["id"])
        receipt["checks"][step] = True
        receipt["checks"]["corrupt-attachment-never-published"] = True

        step = "encrypted-photo-image-byte-roundtrip"
        # A valid tiny PNG exercises image/photo transport, not a gallery UI.
        image = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5WQAAAAASUVORK5CYII=")
        for kind in ("photo", "clipboard.image"):
            image_name = "ORION-PRIVATE-IMAGE-" + secrets.token_hex(16) + ".png"
            canaries.append(image_name)
            image_source = private / image_name
            image_source.write_bytes(image)
            prepared_image = prepare_attachment(sender, receiver.device, image_source, ciphertext_folder, kind=kind, mime="image/png")
            upload_attachment(send_http, prepared_image)
            image_envelopes = receive_http.events()
            if image_envelopes != [prepared_image.envelope]:
                raise AcceptanceError("Image manifest mismatch")
            scan([sender, receiver], canaries, tokens)
            image_destination = private / ("verified-" + kind + ".png")
            download_attachment(receiver, receive_http, image_envelopes[0], image_destination)
            if image_destination.read_bytes() != image:
                raise AcceptanceError("Image bytes changed")
            receive_http.acknowledge(image_envelopes[0]["header"]["id"])
            receive_http.delete_blob(prepared_image.descriptor["id"])
        receipt["checks"][step] = True
        step = "revocation"
        # Retain an old-generation event when revocation happens; scanning
        # earlier already proved absence while its plaintext canaries queued.
        outgoing.stage(receiver.device, {"type": "test.revocation", "synthetic_body": canaries[0]}, ttl_seconds=300)
        step = "revocation-publish"
        outgoing.flush(send_http)
        step = "revocation-queued-content-scan"
        scan([sender, receiver], canaries, tokens)
        step = "revocation-proposal"
        revoked = RootApproval(sender, root, chain).revoke(receiver.device)
        step = "revocation-submit"
        account_http[0].submit_roster(tokens[0], revoked)
        step = "revocation-denied-device"
        Client(endpoints[0], ca, receiver).call("GET", "/v1/sealed/events", expected=403)
        step = "revocation-queue-empty"
        sender.accept_chain(chain + [revoked])
        if HostedTransport(endpoints[0], sender, ca_bundle=ca).events():
            raise AcceptanceError("Old generation queue was retained")
        receipt["checks"]["revocation"] = True
        step = "signed-history-beyond-128"
        while sender.roster["version"] < 145:
            renewal = RootApproval(sender, root).renew()
            account_http[0].submit_roster(tokens[0], renewal)
            sender.accept_page([renewal], final=True)
        if sender.roster["version"] != 145:
            raise AcceptanceError("Long signed history stopped early")
        clients[0].call("GET", "/v1/devices/rosters", token=tokens[0], expected=409)
        clients[0].call("GET", "/v1/devices/rosters/page?after_version=1&after_hash=" + "0" * 64,
                        token=tokens[0], expected=409)
        receipt["checks"][step] = True

        step = "bounded-history-page-reopen-resume"
        history_state = private / "root-paged-history.sqlite3"
        paged = SealedSession(history_state, sender.deployment, sender.pin,
                              sender.device, sender.signing, sender.encryption)
        paged_http = HostedTransport(endpoints[0], paged, ca_bundle=ca)
        if paged_http.refresh_roster(tokens[0], max_pages=2) is not False:
            raise AcceptanceError("Bounded history refresh did not pause")
        if paged.history_cursor()["after_version"] != 32:
            raise AcceptanceError("Verified history progress was not retained")
        try:
            paged.current()
            raise AcceptanceError("Partial history granted content authority")
        except EnvelopeError:
            pass
        paged_http.close()
        # Same pinned keys, a new session object and the persisted 32-step checkpoint.
        paged = SealedSession(history_state, sender.deployment, sender.pin,
                              sender.device, sender.signing, sender.encryption)
        paged_http = HostedTransport(endpoints[0], paged, ca_bundle=ca)
        if paged.history_cursor()["after_version"] != 32:
            raise AcceptanceError("History checkpoint was lost after reopen")
        rounds = 0
        while not paged_http.refresh_roster(tokens[0], max_pages=2):
            rounds += 1
            if rounds > 4:
                raise AcceptanceError("Bounded history refresh did not finish")
        if paged.history_cursor()["after_version"] != 145 or paged.current() != sender.current():
            raise AcceptanceError("Paged final authority did not match current head")
        with paged.connect() as db:
            retired_ids = {row[0] for row in db.execute("SELECT id FROM history_used")}
        if receiver.device not in retired_ids:
            raise AcceptanceError("Paged history forgot a retired device")
        receipt["checks"][step] = True

        step = "failed-refresh-invalidates-content-authority"
        try:
            paged_http.refresh_roster(tokens[1])
            raise AcceptanceError("Wrong account refresh was accepted")
        except TransportError as error:
            if error.status != 401:
                raise AcceptanceError("Wrong account refresh had unexpected status")
        try:
            paged.current()
            raise AcceptanceError("Failed refresh retained content authority")
        except EnvelopeError:
            pass
        if not paged_http.refresh_roster(tokens[0]) or paged.current() != sender.current():
            raise AcceptanceError("Verified refresh could not restore authority")
        receipt["checks"][step] = True
        step = "content-absence"
        scan([sender, receiver, paged], canaries, tokens)
        receipt["checks"][step] = True
        receipt["checks"]["fresh-other-deployment-remains-empty"] = account_http[1].rosters(tokens[1]) == []
        if not receipt["checks"]["fresh-other-deployment-remains-empty"]:
            raise AcceptanceError("Independent deployment was changed")
        receipt['status'] = 'passed'
    except Exception as error:
        receipt['status'] = 'failed'
        receipt['failed_step'] = step
        receipt['error_category'] = type(error).__name__
        if isinstance(error, TransportError):
            receipt['http_status'] = error.status
    (CONTROL / 'result.json').write_text(json.dumps(receipt))
    return 0 if receipt['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
