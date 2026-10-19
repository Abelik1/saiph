# SPDX-License-Identifier: AGPL-3.0-or-later
"""Files directly over the local network: format, one-use claim, resume, hashes and the Cloud fallback.

Synthetic files and addresses only. Listeners bind on this machine; every
client dials 127.0.0.1 in place of the private address the invitation names.
"""
import hashlib
import json
import os
import socket
import threading
import time
from copy import deepcopy
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from orion_mini import lan_files
from orion_mini.lan_files import LanFailed, LanFileServer, LanUnreachable, fetch
from orion_mini.session_offer import (
    MAX_FILE_BYTES, OfferError, build_offer, file_request, read_file_invite, read_file_request, read_offer,
    read_refuse, refuse_payload, valid_filename,
)

RESOURCES = Path(__file__).resolve().parents[1] / "android" / "app" / "src" / "test" / "resources"
VECTORS = json.loads((RESOURCES / "lan-file-vectors.json").read_text(encoding="utf-8"))
NOW = VECTORS["now"]
ADDRESS = ["10.9.9.9"]


def local(_address):
    return "127.0.0.1"


def synthetic(path: Path, size: int, seed=7) -> str:
    block = hashlib.sha256(str(seed).encode()).digest() * 2048  # 64 KiB of repeatable bytes
    with path.open("wb") as output:
        left = size
        while left:
            output.write(block[:min(left, len(block))])
            left -= min(left, len(block))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def serve(path, *, sha256=None, **options):
    size = path.stat().st_size
    server = LanFileServer("get", path, name=path.name, size=size, sha256=sha256 or hashlib.sha256(path.read_bytes()).hexdigest(),
                           addresses=lambda: ADDRESS, **options)
    return server, read_file_invite(server.start(), int(time.time()))


def wait(condition, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return False


class Cutter:
    """A TCP relay between client and listener that can drop every connection and refuse new ones."""

    def __init__(self, port):
        self.port, self.down, self.cut_after = port, False, None
        self.forwarded = 0
        self.sockets = []
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.address = self.listener.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                client, _ = self.listener.accept()
            except OSError:
                return
            if self.down:
                client.close()
                continue
            upstream = socket.create_connection(("127.0.0.1", self.port))
            self.sockets += [client, upstream]
            threading.Thread(target=self._pipe, args=(client, upstream, False), daemon=True).start()
            threading.Thread(target=self._pipe, args=(upstream, client, True), daemon=True).start()

    def _pipe(self, source, target, downstream):
        try:
            while data := source.recv(65536):
                target.sendall(data)
                if downstream:
                    self.forwarded += len(data)
                    if self.cut_after is not None and self.forwarded >= self.cut_after:
                        self.cut_after = None
                        self.cut()
        except OSError:
            pass
        finally:
            for item in (source, target):
                try:
                    item.close()
                except OSError:
                    pass

    def cut(self):
        """The Wi-Fi drops: open connections die and new ones are refused until restore()."""
        self.down = True
        for item in self.sockets:
            try:
                item.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.sockets = []

    def restore(self):
        self.down = False


# ------------------------------------------------------------------ format
@pytest.mark.parametrize("case", VECTORS["names"], ids=lambda case: repr(case["name"])[:40])
def test_file_names_match_the_android_phone(case):
    assert valid_filename(case["name"]) is case["valid"]


@pytest.mark.parametrize("case", VECTORS["requests"], ids=lambda case: case["name"])
def test_upload_requests_match_the_android_phone(case):
    if case["valid"]:
        assert read_file_request(deepcopy(case["payload"]), NOW) == case["payload"]
    else:
        with pytest.raises(OfferError):
            read_file_request(deepcopy(case["payload"]), NOW)


@pytest.mark.parametrize("case", VECTORS["refusals"], ids=lambda case: case["name"])
def test_refusals_match_the_android_phone(case):
    if case["valid"]:
        assert read_refuse(deepcopy(case["payload"])) == case["payload"]
    else:
        with pytest.raises(OfferError):
            read_refuse(deepcopy(case["payload"]))


def test_file_offer_carries_the_exact_size_and_digest_in_a_sealed_offer(tmp_path):
    source = tmp_path / "Synthetic holiday.mp4"
    digest = synthetic(source, 300_000)
    server, invite = serve(source)
    try:
        offer = build_offer("file", server_invite := lan_files.file_invite_code(dict(invite), int(time.time())))
        assert read_offer(offer)["invite"] == server_invite
        assert offer["expires_at"] == invite["expires"] and invite["expires"] - time.time() <= 100  # Room for clock skew under the 120 s maximum.
        assert invite["mode"] == "get" and invite["request"] == "" and invite["addresses"] == ADDRESS
        assert (invite["name"], invite["size"], invite["sha256"]) == ("Synthetic holiday.mp4", 300_000, digest)
    finally:
        server.close()
    request = file_request("Synthetic phone video.mp4", MAX_FILE_BYTES, "f" * 64)
    assert read_file_request(request) == request and request["expires_at"] - time.time() <= 100
    assert refuse_payload("c" * 32, "storage")["reason"] == "storage"
    with pytest.raises(OfferError):
        file_request("Synthetic.mp4", MAX_FILE_BYTES + 1, "f" * 64)


# --------------------------------------------------------- server, client
def test_download_is_exact_and_the_listener_reports_sent_only_after_the_receiver_confirms(tmp_path):
    source = tmp_path / "Synthetic.bin"
    digest = synthetic(source, 6 * 1024 * 1024 + 123)
    server, invite = serve(source)
    seen = []
    out = fetch(invite, tmp_path / "received.part", progress=seen.append, dial=local)
    assert hashlib.sha256(out.read_bytes()).hexdigest() == digest
    assert seen[0] == 0 and seen[-1] == source.stat().st_size
    assert wait(lambda: server.status()["state"] == "done")
    assert server.status()["bytes"] == source.stat().st_size


def test_invitation_secret_works_once(tmp_path):
    source = tmp_path / "Synthetic.bin"
    synthetic(source, 1000)
    server, invite = serve(source)
    fetch(invite, tmp_path / "first.part", dial=local)
    with pytest.raises(LanUnreachable):
        fetch(invite, tmp_path / "replay.part", dial=local)  # The same offer again, or a second device.
    assert not (tmp_path / "replay.part").exists()

    # A wrong secret, and a resume token that was never issued, get nothing from a fresh listener.
    other, second = serve(source)
    try:
        wrong = dict(second, secret="A" * 43)
        with pytest.raises(LanUnreachable):
            fetch(wrong, tmp_path / "wrong.part", dial=local)
        connection = lan_files._connect("x", second["port"], second["certificate"], timeout=4, dial=local)
        connection.request("GET", f"/file/{second['session']}", headers={"Authorization": "Resume " + "B" * 43})
        assert connection.getresponse().status == 403
        connection.close()
        assert other.status()["state"] == "waiting"  # Still claimable by the real recipient.
        fetch(second, tmp_path / "real.part", dial=local)
    finally:
        other.close()


def test_pinned_certificate_is_checked_before_the_secret_is_sent(tmp_path):
    source = tmp_path / "Synthetic.bin"
    synthetic(source, 1000)
    server, invite = serve(source)
    try:
        with pytest.raises(LanUnreachable):
            fetch(dict(invite, certificate="0" * 64), tmp_path / "pinned.part", dial=local)
        assert server.status()["state"] == "waiting"  # Nothing was claimed with the secret.
    finally:
        server.close()


def test_download_resumes_after_a_dropped_connection_and_stays_exact(tmp_path):
    source = tmp_path / "Synthetic.bin"
    digest = synthetic(source, 8 * 1024 * 1024)
    server, invite = serve(source)
    relay = Cutter(invite["port"])
    relay.cut_after = 3 * 1024 * 1024
    threading.Timer(1.5, relay.restore).start()  # The Wi-Fi comes back.
    out = fetch(dict(invite, port=relay.address), tmp_path / "received.part", dial=local)
    assert hashlib.sha256(out.read_bytes()).hexdigest() == digest
    assert wait(lambda: server.status()["state"] == "done")


def test_a_drop_longer_than_the_resume_window_fails_visibly(tmp_path, monkeypatch):
    monkeypatch.setattr(lan_files, "RESUME_SECONDS", 3)
    monkeypatch.setattr(lan_files, "RETRY_SECONDS", 0.2)
    source = tmp_path / "Synthetic.bin"
    synthetic(source, 8 * 1024 * 1024)
    server, invite = serve(source)
    relay = Cutter(invite["port"])
    relay.cut_after = 2 * 1024 * 1024  # Never restored.
    with pytest.raises(LanFailed) as failed:
        fetch(dict(invite, port=relay.address), tmp_path / "received.part", dial=local)
    assert failed.value.text == "lost"
    assert not (tmp_path / "received.part").exists()
    assert wait(lambda: server.status() == {**server.status(), "state": "failed", "error": "lost"})


def test_hash_mismatch_deletes_the_copy_and_fails_both_sides(tmp_path):
    source = tmp_path / "Synthetic.bin"
    synthetic(source, 200_000)
    server, invite = serve(source, sha256="0" * 64)  # The offer promises other content.
    with pytest.raises(LanFailed) as failed:
        fetch(invite, tmp_path / "received.part", dial=local)
    assert failed.value.text == "mismatch"
    assert not (tmp_path / "received.part").exists()
    assert wait(lambda: server.status()["state"] == "failed" and server.status()["error"] == "mismatch")


def upload(invite, data, *, cut_at=None):
    def connect():
        return lan_files._connect("x", invite["port"], invite["certificate"], timeout=4, dial=local)
    connection = connect()
    connection.request("POST", f"/file/{invite['session']}/claim", body=b"", headers={"Authorization": "Bearer " + invite["secret"]})
    token = json.loads(connection.getresponse().read())["resume"]
    connection.close()
    if cut_at is not None:
        connection = connect()
        connection.putrequest("PUT", f"/file/{invite['session']}?offset=0")
        connection.putheader("Authorization", "Resume " + token)
        connection.putheader("Content-Length", str(len(data)))
        connection.endheaders()
        connection.send(data[:cut_at])
        connection.close()  # The phone's Wi-Fi drops mid-upload.
        time.sleep(0.3)
    connection = connect()
    connection.request("GET", f"/file/{invite['session']}/received", headers={"Authorization": "Resume " + token})
    received = json.loads(connection.getresponse().read())["received"]
    connection.close()
    connection = connect()
    connection.request("PUT", f"/file/{invite['session']}?offset={received}", body=data[received:],
                       headers={"Authorization": "Resume " + token})
    response = connection.getresponse()
    result = response.status, json.loads(response.read())
    connection.close()
    return received, result


def test_phone_upload_resumes_and_is_verified_before_it_counts(tmp_path):
    data = os.urandom(3 * 1024 * 1024)
    target = tmp_path / ("a" * 32 + lan_files.PART)
    server = LanFileServer("put", target, name="Synthetic phone video.mp4", size=len(data),
                           sha256=hashlib.sha256(data).hexdigest(), request="d" * 32, addresses=lambda: ADDRESS)
    invite = read_file_invite(server.start(), int(time.time()))
    assert invite["mode"] == "put" and invite["request"] == "d" * 32
    received, result = upload(invite, data, cut_at=1024 * 1024 + 7)
    assert 0 < received <= 1024 * 1024 + 7
    assert result == (200, {"ok": True})
    assert server.status()["state"] == "done" and target.read_bytes() == data


def test_phone_upload_with_other_content_is_refused_and_removed(tmp_path):
    data = os.urandom(100_000)
    target = tmp_path / ("b" * 32 + lan_files.PART)
    server = LanFileServer("put", target, name="Synthetic.bin", size=len(data), sha256="0" * 64,
                           request="d" * 32, addresses=lambda: ADDRESS)
    invite = read_file_invite(server.start(), int(time.time()))
    assert upload(invite, data)[1] == (422, {"ok": False})
    assert server.status()["state"] == "failed" and server.status()["error"] == "mismatch"
    assert not target.exists()


def test_an_unclaimed_invitation_expires(tmp_path):
    source = tmp_path / "Synthetic.bin"
    synthetic(source, 1000)
    server, invite = serve(source, invite_seconds=1)
    assert wait(lambda: server.status()["state"] == "expired", 5)
    with pytest.raises(LanUnreachable):
        fetch(invite, tmp_path / "late.part", dial=local)


# ---------------------------------------------------- with Saiph Cloud
from orion_mini.hosted_runtime import HostedError  # noqa: E402
from orion_mini.hosted_transfers import LAN_WAIT, MAX_PLAINTEXT  # noqa: E402

pytest.importorskip("tink")
from test_hosted_sign_in_boundary import enrolled  # noqa: E402,F401  (fixture)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def events(phone, phone_transport):
    """Decrypted events the phone has been sent, oldest first."""
    found = []
    for envelope in phone_transport._call("GET", "/v1/sealed/events")["events"]:
        found.append(phone.authenticate(envelope))
    return found


def flush(controller):
    controller.mailbox.flush(controller.transport)


def row(controller, job_id):
    return next(item for item in controller.snapshot()["transfers"] if item["id"] == job_id)


@pytest.fixture
def lan(enrolled, tmp_path):  # noqa: F811
    controller, phone, phone_transport, device, _ = enrolled
    controller.lan_addresses = lambda: ADDRESS
    controller.lan_inbox.dial = local
    clock = Clock()
    controller.transfers.monotonic = clock
    controller.transfer_alert = lambda message: None
    return controller, phone, phone_transport, device, clock


def offered_invite(phone, phone_transport):
    offers = [event for event in events(phone, phone_transport) if event.get("type") == "session.offer"]
    assert len(offers) == 1 and offers[0]["service"] == "file"
    return offers[0], read_file_invite(offers[0]["invite"], int(time.time()))


def test_large_file_goes_directly_and_is_sent_once_the_phone_confirms(lan, tmp_path):
    controller, phone, phone_transport, device, clock = lan
    source = tmp_path / "Synthetic large.bin"
    digest = synthetic(source, MAX_PLAINTEXT + 3 * 1024 * 1024)  # Over the Cloud limit.
    queued = controller.send_file(str(source), device)
    controller.transfers.run_due()
    assert row(controller, queued["id"])["state"] == "connecting"
    assert row(controller, queued["id"])["route"] == "lan"
    flush(controller)
    offer, invite = offered_invite(phone, phone_transport)
    assert (invite["name"], invite["size"], invite["sha256"]) == (source.name, source.stat().st_size, digest)
    out = fetch(invite, tmp_path / "phone-copy.part", dial=local)
    assert hashlib.sha256(out.read_bytes()).hexdigest() == digest
    def sent():
        clock.now += 0.6  # The job is checked again every half second.
        controller.transfers.run_due()
        return row(controller, queued["id"])["state"] == "sent"
    assert wait(sent)
    assert row(controller, queued["id"])["progress"] == 1.0
    # Nothing went through the relay.
    assert not [event for event in events(phone, phone_transport) if event.get("type") == "file.encrypted"]


def test_small_file_falls_back_to_saiph_cloud_when_the_phone_never_connects(lan, tmp_path):
    controller, phone, phone_transport, device, clock = lan
    source = tmp_path / "Synthetic small.bin"
    synthetic(source, 150_000)
    queued = controller.send_file(str(source), device)
    controller.transfers.run_due()
    assert row(controller, queued["id"])["state"] == "connecting"
    assert controller._fast_poll()  # The answer is awaited promptly.
    clock.now += LAN_WAIT + 1
    controller.transfers.run_due()
    assert row(controller, queued["id"])["route"] == "cloud"
    assert row(controller, queued["id"])["state"] == "sent"
    flush(controller)
    assert wait(lambda: (flush(controller), any(e.get("type") == "session.close" for e in events(phone, phone_transport)))[1])
    kinds = [event.get("type") for event in events(phone, phone_transport)]
    assert kinds.count("file.encrypted") == 1 and kinds.count("session.offer") == 1


def test_refusal_falls_back_at_once_and_a_large_file_says_what_to_do(lan, tmp_path):
    controller, phone, phone_transport, device, clock = lan
    small, large = tmp_path / "Synthetic small.bin", tmp_path / "Synthetic large.bin"
    synthetic(small, 50_000)
    with large.open("wb") as handle:
        handle.truncate(MAX_PLAINTEXT + 1)
    first = controller.send_file(str(small), device)
    controller.transfers.run_due()
    flush(controller)
    offer, _ = offered_invite(phone, phone_transport)
    # The phone could not reach this computer: it says so through Saiph Cloud.
    phone_transport.publish(phone.encrypt(controller.info.device_id, refuse_payload(offer["id"], "unreachable"), ttl_seconds=60))
    controller.step()
    controller.transfers.run_due()
    assert row(controller, first["id"])["state"] == "sent" and row(controller, first["id"])["route"] == "cloud"

    second = controller.send_file(str(large), device)
    controller.transfers.run_due()
    clock.now += LAN_WAIT + 1
    controller.transfers.run_due()
    failed = row(controller, second["id"])
    assert failed["state"] == "failed"
    assert failed["error"] == ("Synthetic phone didn't answer on your network. Saiph Cloud sends files up to 19.9 MB and "
                               "this file is 20.0 MB, so both devices must be on the same Wi-Fi or network with Saiph "
                               "open. Nothing was sent.")


def test_large_file_without_a_private_network_is_refused_before_anything_is_sent(lan, tmp_path):
    controller, phone, phone_transport, device, clock = lan
    controller.lan_addresses = lambda: []
    large = tmp_path / "Synthetic large.bin"
    with large.open("wb") as handle:
        handle.truncate(25 * 1_048_576)
    with pytest.raises(HostedError) as refused:
        controller.send_file(str(large), device)
    assert "Saiph Cloud sends files up to 19.9 MB. This file is 25.0 MB" in str(refused.value)
    assert controller.snapshot()["transfers"] == []


def test_computer_offer_is_received_privately_then_saved_to_downloads(lan, tmp_path):
    controller, phone, phone_transport, device, clock = lan
    source = tmp_path / "Synthetic from laptop.bin"
    digest = synthetic(source, 2 * 1024 * 1024 + 5)
    server, invite = serve(source)
    offer = build_offer("file", lan_files.file_invite_code(dict(invite), int(time.time())))
    controller._lan_event(device, "session.offer", offer)  # From another approved computer.
    controller._lan_event(device, "session.offer", offer)  # A repeated offer is ignored.
    assert wait(lambda: any(item.get("state") == "ready" for item in controller.snapshot()["offers"]))
    rows = [item for item in controller.snapshot()["offers"] if item.get("route") == "lan"]
    assert len(rows) == 1 and rows[0]["name"] == source.name and rows[0]["expires_at"] > time.time()
    assert server.status()["state"] == "done"
    downloads = tmp_path / "Downloads" / "Saiph"
    first = Path(controller.save_offer(rows[0]["id"], downloads)["path"])
    assert first == downloads / source.name and hashlib.sha256(first.read_bytes()).hexdigest() == digest
    assert list((controller.folder / "incoming").iterdir()) == []
    assert all(item.get("route") != "lan" for item in controller.snapshot()["offers"])


def test_unreachable_computer_offer_is_refused_without_a_row(lan, tmp_path):
    controller, phone, phone_transport, device, clock = lan
    source = tmp_path / "Synthetic.bin"
    synthetic(source, 1000)
    server, invite = serve(source)
    server.close()  # Nobody listens any more.
    offer = build_offer("file", lan_files.file_invite_code(dict(invite), int(time.time())))
    controller._lan_event(device, "session.offer", offer)
    assert wait(lambda: (flush(controller), [e for e in events(phone, phone_transport) if e.get("type") == "session.refuse"])[1])
    refusal = [e for e in events(phone, phone_transport) if e.get("type") == "session.refuse"][0]
    assert refusal == {"type": "session.refuse", "version": 1, "id": offer["id"], "reason": "unreachable"}
    assert not [item for item in controller.snapshot()["offers"] if item.get("route") == "lan"]


def test_phone_request_gets_an_upload_invitation_and_the_file_waits_for_save(lan, tmp_path):
    controller, phone, phone_transport, device, clock = lan
    controller.workspace.store.save("hosted_phone", {"id": device, "capabilities": [], "seen_at": int(time.time())})
    data = os.urandom(1024 * 1024 + 99)
    request = file_request("Synthetic phone video.mp4", len(data), hashlib.sha256(data).hexdigest())
    controller._lan_event(device, "file.lan.request", request)
    flush(controller)
    offer, invite = offered_invite(phone, phone_transport)
    assert invite["mode"] == "put" and invite["request"] == request["id"] and invite["size"] == len(data)
    assert upload(invite, data, cut_at=300_000)[1] == (200, {"ok": True})
    assert wait(lambda: any(item.get("state") == "ready" for item in controller.snapshot()["offers"]))
    item = next(item for item in controller.snapshot()["offers"] if item.get("route") == "lan")
    saved = Path(controller.save_offer(item["id"], tmp_path / "Downloads")["path"])
    assert saved.read_bytes() == data
    assert controller.workspace.store.get("phone_file", item["id"])["name"] == "Synthetic phone video.mp4"


def test_not_enough_space_is_refused_and_shown(lan, tmp_path, monkeypatch):
    controller, phone, phone_transport, device, clock = lan
    monkeypatch.setattr(lan_files, "free_space", lambda folder: 10)
    request = file_request("Synthetic phone video.mp4", 500 * 1024 * 1024, "f" * 64)
    controller.workspace.store.save("hosted_phone", {"id": device, "capabilities": [], "seen_at": int(time.time())})
    controller._lan_event(device, "file.lan.request", request)
    flush(controller)
    refusal = [e for e in events(phone, phone_transport) if e.get("type") == "session.refuse"]
    assert refusal and refusal[0]["reason"] == "storage" and refusal[0]["id"] == request["id"]
    failed = next(item for item in controller.snapshot()["offers"] if item.get("route") == "lan")
    assert failed["state"] == "failed" and "Not enough free space" in failed["error"]
    controller.dismiss_transfer(failed["id"])
    assert not [item for item in controller.snapshot()["offers"] if item.get("route") == "lan"]
