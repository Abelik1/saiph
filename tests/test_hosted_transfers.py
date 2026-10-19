# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cloud file sends across a network drop, with real cryptography and the real Hub service offline.

Synthetic files only. The upload transport is wrapped to drop or lose replies;
the recipient phone reads its mailbox from the same in-process service.
"""
import io
import time

import pytest

pytest.importorskip("tink")

from orion_mini.hosted_crypto import canonical
from orion_mini.hosted_files import CHUNK_BYTES, DOMAIN, _manifest, prepare_attachment, upload_attachment
from orion_mini.hosted_login import TokenGrant
from orion_mini.hosted_runtime import HostedController, HostedError
from orion_mini.hosted_transfers import MAX_PLAINTEXT, RETRY_SECONDS, SENT_SECONDS, too_large
from orion_mini.hosted_transport import TransportError

from test_hosted_sign_in_boundary import enrolled  # noqa: F401  (fixture)


class Network:
    """A link that can go down after some chunks, or deliver a request but lose its reply."""
    def __init__(self):
        self.down = False
        self.drop_after = None  # Go down once this many chunks were accepted.
        self.lose_publish_reply = False
        self.refresh_at = None  # Re-verify the roster while this chunk is sent, as the scheduler does.
        self.conflict_at = None  # The service answers 409 to this chunk once.
        self.accepted_chunks = []  # Chunk indexes the service accepted, in order.
        self.publishes = 0
        self.deleted_blobs = []

    def install(self, controller):
        base = controller._transport_factory
        network = self

        def factory(url, session):
            transport = base(url, session)
            original = transport._call

            def call(method, path, *, token=None, value=None):
                if network.down:
                    raise TransportError()
                chunk = "/chunks/" in path
                if chunk and network.drop_after is not None and len(network.accepted_chunks) >= network.drop_after:
                    network.down, network.drop_after = True, None
                    raise TransportError()
                if chunk and network.conflict_at is not None and len(network.accepted_chunks) >= network.conflict_at:
                    network.conflict_at = None
                    raise TransportError(409)
                if chunk and network.refresh_at is not None and len(network.accepted_chunks) >= network.refresh_at:
                    # SealedSession.accept_page withdraws approval while it verifies, on another thread.
                    network.refresh_at = None
                    held = session.roster, session.digest
                    session.roster, session.digest = None, None
                    try:
                        session.current()  # HostedTransport._call checks approval before every signed request.
                    finally:
                        session.roster, session.digest = held
                if method == "DELETE" and "/v1/sealed/blobs/" in path:
                    network.deleted_blobs.append(path.rsplit("/", 1)[1])
                result = original(method, path, token=token, value=value)
                if chunk:
                    network.accepted_chunks.append(int(path.rsplit("/", 1)[1]))
                if path == "/v1/sealed/events" and method == "POST":
                    network.publishes += 1
                    if network.lose_publish_reply:
                        network.lose_publish_reply = False
                        raise TransportError()  # Delivered, but the reply never arrived.
                return result

            transport._call = call
            return transport

        controller._transport_factory = factory
        return self


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def offers(phone_transport):
    return phone_transport._call("GET", "/v1/sealed/events")["events"]


def received_bytes(phone, phone_transport, envelope):
    payload, primitive = _manifest(phone, envelope)
    ciphertext = b"".join(phone_transport.download_blob_chunk(payload["blob"]["id"], index)
                          for index in range((payload["ciphertext_size"] + CHUNK_BYTES - 1) // CHUNK_BYTES))
    with primitive.new_decrypting_stream(io.BytesIO(ciphertext), DOMAIN + canonical(payload["blob"])) as decrypted:
        return payload["name"], decrypted.read()


def row(controller, job_id):
    return next(item for item in controller.snapshot()["transfers"] if item["id"] == job_id)


def outgoing(controller):
    folder = controller.folder / "outgoing"
    return sorted(path.name for path in folder.iterdir()) if folder.exists() else []


@pytest.fixture
def sending(enrolled, tmp_path):  # noqa: F811
    controller, phone, phone_transport, device, _ = enrolled
    clock = Clock()
    controller.transfers.monotonic = clock
    alerts = []
    controller.transfer_alert = alerts.append
    network = Network().install(controller)
    source = tmp_path / "synthetic-holiday.bin"
    source.write_bytes(bytes(range(256)) * 520)  # 133 120 bytes: five ciphertext chunks.
    return controller, phone, phone_transport, device, source, network, clock, alerts


def test_drop_mid_upload_resumes_after_connectivity_returns_and_delivers_one_offer(sending):
    controller, phone, phone_transport, device, source, network, clock, alerts = sending
    network.drop_after = 2
    queued = controller.send_file(str(source), device)
    assert queued["queued"] and queued["target_name"] == "Synthetic phone"
    assert row(controller, queued["id"])["state"] == "queued"

    controller.transfers.run_due()
    state = row(controller, queued["id"])
    assert state["state"] == "retrying" and "unreachable" in state["error"] and state["retry_in"] == 2
    assert 0 < state["progress"] < 1
    assert len(outgoing(controller)) == 1  # The same ciphertext is kept for the retry.
    assert offers(phone_transport) == []

    # Still down at the next backoff: it keeps waiting, visibly.
    clock.now += 2
    controller.transfers.run_due()
    assert row(controller, queued["id"])["state"] == "retrying"
    assert row(controller, queued["id"])["attempts"] == 2

    # Connectivity returns: the next successful Cloud pass retries at once rather than at the backoff.
    network.down = False
    controller.step()
    assert controller.status == "active"
    controller.transfers.run_due()
    assert row(controller, queued["id"])["state"] == "sent"
    assert row(controller, queued["id"])["progress"] == 1.0
    # Resumed after the last accepted chunk instead of starting again.
    assert network.accepted_chunks == [0, 1, 2, 3, 4]
    events = offers(phone_transport)
    assert len(events) == 1
    assert received_bytes(phone, phone_transport, events[0]) == (source.name, source.read_bytes())
    assert outgoing(controller) == []
    assert alerts == []  # A send from inside the app shows its state there.


def test_lost_publish_reply_is_retried_with_the_same_event_and_shows_one_offer(sending):
    controller, phone, phone_transport, device, source, network, clock, alerts = sending
    network.lose_publish_reply = True
    queued = controller.send_file(str(source), device, notify=True)
    controller.transfers.run_due()
    assert row(controller, queued["id"])["state"] == "retrying"
    clock.now += 2
    controller.transfers.run_due()
    assert row(controller, queued["id"])["state"] == "sent"
    assert network.publishes == 2  # The relay saw the identical event twice and kept one.
    assert len(offers(phone_transport)) == 1
    assert outgoing(controller) == []
    assert alerts == ["Sent synthetic-holiday.bin to Synthetic phone."]


def test_roster_refresh_mid_upload_carries_on_with_the_same_blob(sending):
    # Physical run 2026-10-18: every 19 MiB send restarted at ~50% because the scheduler's
    # roster refresh briefly withdrew approval and the upload re-encrypted from scratch.
    controller, phone, phone_transport, device, source, network, clock, alerts = sending
    network.refresh_at = 2
    queued = controller.send_file(str(source), device)
    controller.transfers.run_due()
    state = row(controller, queued["id"])
    assert state["state"] == "sent" and state["attempts"] == 1
    assert network.accepted_chunks == [0, 1, 2, 3, 4]
    events = offers(phone_transport)
    assert len(events) == 1
    assert received_bytes(phone, phone_transport, events[0]) == (source.name, source.read_bytes())
    assert outgoing(controller) == []


def test_abandoned_upload_is_released_on_the_relay(sending):
    # Abandoned blobs used to count against the recipient's four pending blobs until they
    # expired, so the following attempts were refused for minutes.
    controller, phone, phone_transport, device, source, network, clock, alerts = sending
    network.conflict_at = 2
    queued = controller.send_file(str(source), device)
    controller.transfers.run_due()
    assert row(controller, queued["id"])["state"] == "retrying"
    assert len(network.deleted_blobs) == 1
    clock.now += 2
    controller.transfers.run_due()
    assert row(controller, queued["id"])["state"] == "sent"
    events = offers(phone_transport)
    assert len(events) == 1
    assert received_bytes(phone, phone_transport, events[0]) == (source.name, source.read_bytes())


def test_long_outage_fails_visibly_cleans_up_and_retry_sends_once(sending):
    controller, phone, phone_transport, device, source, network, clock, alerts = sending
    network.down = True
    queued = controller.send_file(str(source), device)
    controller.transfers.run_due()
    assert row(controller, queued["id"])["state"] == "retrying"
    assert len(outgoing(controller)) == 1
    clock.now += RETRY_SECONDS + 1
    controller.transfers.run_due()
    failed = row(controller, queued["id"])
    assert failed["state"] == "failed"
    assert failed["error"] == "Saiph Cloud stayed unreachable for 10 minutes. Nothing was sent."
    assert outgoing(controller) == []  # Final failure leaves no orphaned ciphertext.
    assert alerts == ["synthetic-holiday.bin wasn't sent to Synthetic phone. Open Saiph to retry."]
    with pytest.raises(HostedError, match="no longer available"):
        controller.dismiss_transfer("not-a-transfer")

    network.down = False
    assert controller.retry_transfer(queued["id"]) == {"queued": True, "id": queued["id"]}
    controller.transfers.run_due()
    assert row(controller, queued["id"])["state"] == "sent"
    assert len(offers(phone_transport)) == 1


def test_sent_state_names_the_device_briefly(sending):
    controller, phone, phone_transport, device, source, network, clock, alerts = sending
    queued = controller.send_file(str(source), device)
    controller.transfers.run_due()
    sent = row(controller, queued["id"])
    assert (sent["state"], sent["target_name"], sent["name"]) == ("sent", "Synthetic phone", source.name)
    clock.now += SENT_SECONDS + 1
    assert controller.snapshot()["transfers"] == []


def test_oversize_file_is_refused_before_encryption(sending, tmp_path):
    controller, phone, phone_transport, device, source, network, clock, alerts = sending
    large = tmp_path / "synthetic-large.bin"
    with large.open("wb") as handle:
        handle.truncate(25 * 1_048_576)  # Sparse: nothing is read or encrypted.
    with pytest.raises(HostedError) as refused:
        controller.send_file(str(large), device)
    assert str(refused.value) == ("Saiph Cloud sends files up to 19.9 MB. This file is 25.0 MB: connect this computer "
                                  "to the same Wi-Fi or network as the other device to send it directly. Nothing was sent.")
    assert controller.snapshot()["transfers"] == [] and outgoing(controller) == []
    assert offers(phone_transport) == []
    assert controller.snapshot()["file_limit"] == MAX_PLAINTEXT == 20_967_424
    assert too_large(MAX_PLAINTEXT + 1).endswith("This file is 20.0 MB. Nothing was sent.")


def test_turning_cloud_off_stops_a_waiting_send(sending):
    controller, phone, phone_transport, device, source, network, clock, alerts = sending
    network.down = True
    queued = controller.send_file(str(source), device)
    controller.transfers.run_due()
    controller.set_enabled(False)
    assert row(controller, queued["id"])["state"] == "failed"
    assert outgoing(controller) == []


def test_restart_keeps_offers_and_removes_orphaned_ciphertext(enrolled, tmp_path):  # noqa: F811
    controller, phone, phone_transport, device, _ = enrolled
    controller.step()
    source = tmp_path / "synthetic-from-phone.txt"
    source.write_bytes(b"Synthetic file from the phone")
    folder = tmp_path / "phone-outgoing"
    folder.mkdir()
    upload_attachment(phone_transport, prepare_attachment(phone, controller.info.device_id, source.resolve(), folder.resolve()))
    controller.step()
    [offer] = controller.snapshot()["offers"]
    assert offer["name"] == source.name and offer["expires_at"] > time.time()

    # A crash left ciphertext behind; only sealed files are removed.
    leftover = controller.folder / "outgoing"
    leftover.mkdir(exist_ok=True)
    (leftover / "abandoned.orion-sealed").write_bytes(b"opaque")
    (leftover / "keep.txt").write_bytes(b"not ours")
    workspace, protection, factory = controller.workspace, controller._protection, controller._transport_factory
    controller.stop()

    restarted = HostedController(workspace, protection=protection, transport_factory=factory)
    restarted.transfers.background = False
    assert sorted(path.name for path in leftover.iterdir()) == ["keep.txt"]
    restarted._account()._accept(TokenGrant("synthetic-access", time.time() + 3600, None))
    restarted.step()
    assert [item["id"] for item in restarted.snapshot()["offers"]] == [offer["id"]]
    saved = restarted.save_offer(offer["id"], tmp_path / "downloads")
    assert (tmp_path / "downloads" / source.name).read_bytes() == source.read_bytes() and saved["path"]
    restarted.stop()


def test_clipboard_text_over_the_limit_says_so(enrolled):  # noqa: F811
    controller = enrolled[0]
    controller.step()
    assert controller.local_clipboard("text/plain", b"x" * 16_385) is False
    assert controller.snapshot()["clipboard_notice"] == "This clipboard text is too large to share. Send it as a file."
    assert controller.local_clipboard("text/plain", b"Synthetic short text") is True
    assert controller.snapshot()["clipboard_notice"] == ""
