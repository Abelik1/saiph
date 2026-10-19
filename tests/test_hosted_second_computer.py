# SPDX-License-Identifier: AGPL-3.0-or-later
"""A second computer joins a Saiph account like a phone. Offline, real crypto, synthetic data."""
from copy import deepcopy
import time
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
import requests

from orion_mini.hosted_runtime import NO_ACCESS, ROOT_ONLY, HostedController, HostedError
from orion_mini.hosted_transport import HostedTransport, TransportError

from test_hosted_runtime import CONFIG, Presence, SyntheticProtection, workspace


class SyntheticService:
    """One account's shared state: the signed roster chain and per-device inboxes."""

    def __init__(self):
        self.deployment = str(uuid4())
        self.chain, self.inboxes, self.requests, self.offered = [], {}, [], []
        # /v1/access (free trial notice) and whether the account is refused (403).
        self.access = {"entitled": True, "until": int(time.time()) + 30 * 86400, "kinds": ["paid"]}
        self.refused = False
        self.access_reads = 0

    def transport(self):
        service = self

        class Transport(HostedTransport):
            def _call(self, method, path, *, token=None, value=None):
                if token is not None:
                    assert token == "synthetic-access"
                if method == "GET" and path == "/v1/access":
                    service.access_reads += 1
                    return deepcopy(service.access)
                if service.refused:
                    raise TransportError(403)
                if method == "GET" and path == "/v1/account":
                    return {"deployment_id": service.deployment, "device_trust_required": True}
                if method == "GET" and path.startswith("/v1/devices/rosters/page?"):
                    after = int(parse_qs(urlsplit(path).query)["after_version"][0])
                    return {"chain": deepcopy(service.chain[after:]), "more": False}
                if method == "POST" and path == "/v1/devices/requests":
                    assert value["deployment_id"] == service.deployment
                    service.requests.append(value["device"]["id"])
                    return {"status": "pending", "expires_at": int(time.time()) + 300}
                if method == "POST" and path == "/v1/devices/approval-requests":
                    service.offered.append(value["code"])
                    return {"status": "offered", "expires_at": int(time.time()) + 300}
                if method == "GET" and path == "/v1/devices/approval-requests":
                    return {"requests": list(service.offered)}
                if method == "POST" and path == "/v1/devices/rosters":
                    assert value["roster"]["version"] == len(service.chain) + 1
                    service.chain.append(deepcopy(value))
                    return {"accepted": True}
                if method == "POST" and path == "/v1/sealed/events":
                    service.inboxes.setdefault(value["header"]["target"], []).append(deepcopy(value))
                    return {"accepted": True, "duplicate": False}
                inbox = service.inboxes.setdefault(self.session.device, []) if self.session else []
                if method == "GET" and path == "/v1/sealed/events":
                    return {"events": deepcopy(inbox)}
                if method == "DELETE" and path.startswith("/v1/sealed/events/"):
                    event = path.rsplit("/", 1)[1]
                    inbox[:] = [item for item in inbox if item["header"]["id"] != event]
                    return {"ok": True}
                pytest.fail(f"Unexpected synthetic Hosted route: {method} {path}")

        return Transport


def computer(tmp_path, name, service, monkeypatch, received):
    profile = workspace(tmp_path / name)
    profile.user_presence = Presence()
    profile.security_alert = lambda message: None
    controller = HostedController(profile, protection=SyntheticProtection(), transport_factory=service.transport())
    controller.clipboard_sink = lambda mime, data: received.append(data)
    controller.configure(CONFIG)
    controller.set_enabled(True)
    monkeypatch.setattr(controller, "_token", lambda: "synthetic-access")
    return controller


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("A synthetic Hosted test attempted a real HTTP request")
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)


def test_second_computer_joins_syncs_and_is_removed_by_the_main_computer(tmp_path, monkeypatch):
    service = SyntheticService()
    main_received, laptop_received = [], []
    main = computer(tmp_path, "main", service, monkeypatch, main_received)
    root_code = main.setup_root()

    laptop = computer(tmp_path, "laptop", service, monkeypatch, laptop_received)
    shown = laptop.inspect_join(root_code["code"])
    assert shown["fingerprint"] == root_code["fingerprint"]
    assert not laptop.identity.exists()  # Inspecting creates nothing.
    with pytest.raises(HostedError, match="Compare the whole fingerprint"):
        laptop.join(root_code["code"], False)
    assert not laptop.identity.exists()

    request = laptop.join(root_code["code"], True)
    assert laptop.status == "awaiting_approval"
    assert request["root_fingerprint"] == root_code["fingerprint"]
    assert request["modules"] and request["code"].startswith("orion-approve-v1:")
    assert service.requests == [main.info.device_id, laptop.info.device_id]
    assert laptop.snapshot()["role"] == "member"
    # The main computer finds the request itself; nothing long is typed across.
    offered = main.offered_requests()
    assert [item["device_id"] for item in offered] == [laptop.info.device_id]
    assert offered[0]["fingerprint"] == request["fingerprint"]
    service.offered.append("orion-approve-v1:{}")  # The service is untrusted: junk is dropped.
    assert [item["device_id"] for item in main.offered_requests()] == [laptop.info.device_id]
    with pytest.raises(HostedError, match=ROOT_ONLY):
        laptop.offered_requests()

    # Before approval the laptop signs nothing and stays waiting.
    laptop.step()
    assert laptop.status == "awaiting_approval"
    assert len(service.chain) == 1
    with pytest.raises(HostedError, match="main computer"):
        laptop.setup_root()
    for action in (lambda: laptop.inspect_request(request["code"]), lambda: laptop.revoke(main.info.device_id),
                   lambda: laptop.approve(request["code"], "Main", True)):
        with pytest.raises(HostedError, match=ROOT_ONLY):
            action()
    with pytest.raises(HostedError, match="main computer"):
        laptop.root_code()

    # The main computer sees the same fingerprint the laptop shows and approves it.
    inspected = main.inspect_request(laptop.request_code()["code"])
    assert inspected["device_id"] == laptop.info.device_id
    assert inspected["fingerprint"] == request["fingerprint"] == laptop.snapshot()["fingerprint"]
    assert main.approve(request["code"], "Synthetic laptop", True) == {"approved": laptop.info.device_id}

    laptop.step()
    assert laptop.status == "active"
    snapshot = laptop.snapshot()
    members = {row["id"]: row for row in snapshot["roster"]["members"]}
    assert members[main.info.device_id]["root"] and members[main.info.device_id]["label"] == "Main computer"
    assert members[laptop.info.device_id]["self"] and not members[laptop.info.device_id]["root"]
    assert snapshot["root_fingerprint"] == root_code["fingerprint"]

    # Clipboard both ways between the two computers.
    assert laptop.local_clipboard("text/plain", b"synthetic laptop text")
    laptop.step()
    main.step()
    assert main_received == [b"synthetic laptop text"]
    assert main.local_clipboard("text/plain", b"synthetic main text")
    main.step()
    laptop.step()
    assert laptop_received == [b"synthetic main text"]

    # A member never renews: only the main computer signs rosters.
    versions = len(service.chain)
    laptop.step()
    assert len(service.chain) == versions

    # Removal on the main computer stops the laptop at once.
    assert main.revoke(laptop.info.device_id) == {"revoked": laptop.info.device_id}
    laptop.step()
    assert laptop.status == "removed"
    assert "removed this computer" in laptop.error
    with pytest.raises(HostedError):
        laptop.send_file(str(tmp_path / "missing.txt"), main.info.device_id)


def test_join_refuses_another_account_and_an_account_without_a_main_computer(tmp_path, monkeypatch):
    first, second = SyntheticService(), SyntheticService()
    main = computer(tmp_path, "main", first, monkeypatch, [])
    code = main.setup_root()["code"]

    # Signed in to a different account than the main computer's code.
    stranger = computer(tmp_path, "stranger", second, monkeypatch, [])
    second.chain.append(deepcopy(first.chain[0]))  # Any non-empty chain; the account differs.
    with pytest.raises(HostedError, match="different Saiph account"):
        stranger.join(code, True)
    assert not stranger.identity.exists()

    # An account with no main computer yet: set up as the main computer instead.
    first.chain.clear()
    lonely = computer(tmp_path, "lonely", first, monkeypatch, [])
    with pytest.raises(HostedError, match="no main computer yet"):
        lonely.join(code, True)
    assert not lonely.identity.exists()


def test_join_refuses_an_invalid_code_or_an_existing_identity(tmp_path, monkeypatch):
    service = SyntheticService()
    main = computer(tmp_path, "main", service, monkeypatch, [])
    code = main.setup_root()["code"]
    with pytest.raises(HostedError, match="already has a Saiph Cloud identity"):
        main.inspect_join(code)  # An existing identity is never replaced.
    other = computer(tmp_path, "other", service, monkeypatch, [])
    with pytest.raises(HostedError, match="invalid or expired"):
        other.inspect_join(code[:-4] + "AAAA")
    with pytest.raises(HostedError, match="invalid or expired"):
        other.join("orion-root-v1:not-a-code", True)
    assert not other.identity.exists()


def test_setup_refuses_a_second_main_computer_and_points_to_join(tmp_path, monkeypatch):
    service = SyntheticService()
    computer(tmp_path, "main", service, monkeypatch, []).setup_root()
    second = computer(tmp_path, "second", service, monkeypatch, [])
    with pytest.raises(HostedError, match="Join as another computer"):
        second.setup_root()
    assert not second.identity.exists()


def test_a_member_stays_connected_after_restart_without_its_own_root_keys(tmp_path, monkeypatch):
    service = SyntheticService()
    main = computer(tmp_path, "main", service, monkeypatch, [])
    code = main.setup_root()["code"]
    laptop = computer(tmp_path, "laptop", service, monkeypatch, [])
    request = laptop.join(code, True)
    main.approve(request["code"], "Synthetic laptop", True)
    profile, protection = laptop.workspace, laptop._protection
    laptop._deactivate("off")
    restarted = HostedController(profile, protection=protection, transport_factory=service.transport())
    monkeypatch.setattr(restarted, "_token", lambda: "synthetic-access")
    restarted.step()
    assert restarted.status == "active" and restarted.info.role == "member"
    assert restarted.root.device_id == main.info.device_id
    # A tampered pin can never become a different main computer.
    (restarted.folder / "root-pin.json").write_text("{}", encoding="utf-8")
    again = HostedController(profile, protection=protection, transport_factory=service.transport())
    monkeypatch.setattr(again, "_token", lambda: "synthetic-access")
    again.step()
    again.step()
    assert again.status == "keys_unavailable"
    assert again.session is None


def test_account_without_access_is_told_to_start_a_trial_or_subscribe(tmp_path, monkeypatch):
    """The service answers 403 until the account has a trial, subscription or invitation; say so instead of 'unreachable'."""
    service = SyntheticService()
    main = computer(tmp_path, "main", service, monkeypatch, [])
    root_code = main.setup_root()

    class NoAccess(HostedTransport):
        def _call(self, method, path, *, token=None, value=None):
            raise TransportError(403)

    newcomer = computer(tmp_path, "newcomer", service, monkeypatch, [])
    newcomer._transport_factory = NoAccess
    with pytest.raises(HostedError, match="no Saiph Cloud access yet") as error:
        newcomer.setup_root()
    assert str(error.value) == NO_ACCESS
    assert "free trial" in NO_ACCESS
    assert not newcomer.identity.exists()
    with pytest.raises(HostedError, match="no Saiph Cloud access yet"):
        newcomer.join(root_code["code"], True)
    assert not newcomer.identity.exists()


def test_join_button_pins_only_the_main_computer_the_owner_compared(tmp_path, monkeypatch):
    """No pasted code: Saiph Cloud names the main computer; nothing is pinned until the owner confirms it."""
    service = SyntheticService()
    main = computer(tmp_path, "main", service, monkeypatch, [])
    root_code = main.setup_root()
    laptop = computer(tmp_path, "laptop", service, monkeypatch, [])
    shown = laptop.inspect_account_root()
    assert shown == {"device_id": main.info.device_id, "fingerprint": root_code["fingerprint"]}
    assert not laptop.identity.exists() and not laptop._pin_path.exists()  # Showing pins nothing.
    with pytest.raises(HostedError, match="Compare the whole fingerprint"):
        laptop.join_account(shown["fingerprint"], False)
    with pytest.raises(HostedError, match="different main computer"):
        laptop.join_account("0000 " * 15 + "0000", True)
    assert not laptop.identity.exists() and not laptop._pin_path.exists()
    request = laptop.join_account(shown["fingerprint"], True)
    assert request["root_fingerprint"] == root_code["fingerprint"] and laptop.status == "awaiting_approval"
    assert [item["device_id"] for item in main.pending_approvals()["requests"]] == [laptop.info.device_id]


def test_join_button_refuses_a_substituted_main_computer(tmp_path, monkeypatch):
    service = SyntheticService()
    main = computer(tmp_path, "main", service, monkeypatch, [])
    main.setup_root()
    laptop = computer(tmp_path, "laptop", service, monkeypatch, [])
    shown = laptop.inspect_account_root()
    # A malicious relay swaps the genesis keys after the owner compared the real ones.
    from cryptography.hazmat.primitives.asymmetric import ec
    from orion_mini.hosted_session import public_signing_key
    service.chain[0]["roster"]["members"][0]["signing_key"] = public_signing_key(ec.generate_private_key(ec.SECP256R1()).public_key())
    with pytest.raises(HostedError, match="different main computer"):
        laptop.join_account(shown["fingerprint"], True)
    assert not laptop.identity.exists()


def test_pasted_code_join_is_bound_to_the_displayed_fingerprint(tmp_path, monkeypatch):
    service = SyntheticService()
    main = computer(tmp_path, "main", service, monkeypatch, [])
    root_code = main.setup_root()
    laptop = computer(tmp_path, "laptop", service, monkeypatch, [])
    with pytest.raises(HostedError, match="invalid or expired"):
        laptop.join(root_code["code"], True, "0000 " * 15 + "0000")
    assert not laptop.identity.exists()
    assert laptop.join(root_code["code"], True, root_code["fingerprint"])["root_fingerprint"] == root_code["fingerprint"]


def test_main_computer_can_deny_or_block_and_is_warned_about_many_requests(tmp_path, monkeypatch):
    service = SyntheticService()
    main = computer(tmp_path, "main", service, monkeypatch, [])
    root_code = main.setup_root()
    joiners = []
    for name in ("one", "two"):
        joiner = computer(tmp_path, name, service, monkeypatch, [])
        joiner.join(root_code["code"], True, root_code["fingerprint"])
        joiners.append(joiner)
    first, second = (joiner.info.device_id for joiner in joiners)
    view = main.pending_approvals()
    assert view["waiting"] == 2 and len(view["requests"]) == 1 and view["flood"] is False
    assert view["requests"][0]["location"] is None  # Saiph Cloud does not report locations yet.
    assert main.deny_request(first) == {"denied": True}
    assert [item["device_id"] for item in main.offered_requests()] == [second]
    assert main.block_device(second) == {"blocked": True}
    assert main.offered_requests() == []
    blocked_code = next(code for code in service.offered if second in code)
    with pytest.raises(HostedError, match="blocked"):
        main.approve(blocked_code, "Laptop", True)
    # Blocking survives a restart of the main computer's controller.
    again = HostedController(main.workspace, protection=main._protection, transport_factory=service.transport())
    monkeypatch.setattr(again, "_token", lambda: "synthetic-access")
    again.step()
    assert all(item["device_id"] != second for item in again.offered_requests())
    for name in ("three", "four", "five"):
        computer(tmp_path, name, service, monkeypatch, []).join(root_code["code"], True, root_code["fingerprint"])
    assert again.pending_approvals()["flood"] is True


def test_device_names_and_kinds_reach_every_computer(tmp_path, monkeypatch):
    """No more "Main computer", "Device", "Device": names the owner chose, and phone/computer kinds."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from orion_mini.hosted_approval import make_request_code, trust_root_code
    from orion_mini.hosted_crypto import generate_recipient
    from orion_mini.hosted_features import FeatureError, read_device_labels
    service = SyntheticService()
    main = computer(tmp_path, "main", service, monkeypatch, [])
    main.workspace.settings["machine"] = {"name": "Desk"}
    root_code = main.setup_root()
    laptop = computer(tmp_path, "laptop", service, monkeypatch, [])
    laptop.workspace.settings["machine"] = {"name": "Travel laptop"}
    request = laptop.join(root_code["code"], True, root_code["fingerprint"])
    main.approve(request["code"], "Laptop", True)
    root = trust_root_code(root_code["code"], trusted_out_of_band=True)
    phone = "dev_" + uuid4().hex
    main.approve(make_request_code(root, phone, ec.generate_private_key(ec.SECP256R1()), generate_recipient()), "Pixel", True)
    main.workspace.store.save("hosted_phone", {"id": phone, "capabilities": ["files"], "seen_at": int(time.time())})
    for _ in range(3):
        laptop.step(); main.step()
    on_main = {row["id"]: row for row in main.snapshot()["roster"]["members"]}
    assert (on_main[laptop.info.device_id]["label"], on_main[laptop.info.device_id]["kind"]) == ("Laptop", "computer")
    assert (on_main[phone]["label"], on_main[phone]["kind"]) == ("Pixel", "phone")
    on_laptop = {row["id"]: row for row in laptop.snapshot()["roster"]["members"]}
    assert (on_laptop[main.info.device_id]["label"], on_laptop[main.info.device_id]["kind"]) == ("Desk", "computer")
    assert (on_laptop[phone]["label"], on_laptop[phone]["kind"]) == ("Pixel", "phone")
    # Only the main computer's list counts; shapes are exact.
    with pytest.raises(FeatureError):
        laptop._device_event(phone, {"type": "device.labels", "labels": []})
    for bad in ({"type": "device.labels", "labels": [{"id": "x", "label": "A", "kind": "phone"}]},
                {"type": "device.labels", "labels": [{"id": phone, "label": "A\n", "kind": "phone"}]},
                {"type": "device.labels", "labels": [{"id": phone, "label": "A", "kind": "tablet"}]}):
        with pytest.raises(FeatureError):
            read_device_labels(bad)


def test_a_new_account_without_a_trial_is_offered_one(tmp_path, monkeypatch):
    service = SyntheticService()
    service.refused, service.access = True, {"entitled": False, "until": None, "kinds": []}
    newcomer = computer(tmp_path, "newcomer", service, monkeypatch, [])
    with pytest.raises(HostedError, match="Start your free trial or subscribe"):
        newcomer.setup_root()
    assert newcomer.snapshot()["access"]["state"] == "none"
    assert not newcomer.identity.exists()


def test_trial_days_left_appear_while_connected(tmp_path, monkeypatch):
    service = SyntheticService()
    end = int(time.time()) + 3 * 86400 - 60
    service.access = {"entitled": True, "until": end, "kinds": ["trial"], "trial_until": end}
    main = computer(tmp_path, "main", service, monkeypatch, [])
    main.setup_root()
    main.step()
    access = main.snapshot()["access"]
    assert access["state"] == "trial" and access["days_left"] == 3 and access["trial_until"] == end
    assert access["message"].startswith("Free trial: 3 days left.")
    reads = service.access_reads
    main.step()
    assert service.access_reads == reads, "fetched again only every few hours"


def test_trial_expiry_pauses_cloud_with_a_subscribe_prompt_and_keeps_everything(tmp_path, monkeypatch):
    service = SyntheticService()
    end = int(time.time()) + 86400
    service.access = {"entitled": True, "until": end, "kinds": ["trial"], "trial_until": end}
    main = computer(tmp_path, "main", service, monkeypatch, [])
    main.setup_root()
    main.step()
    assert main.status == "active"
    # The trial runs out: the service refuses the account until it subscribes.
    service.refused = True
    service.access = {"entitled": False, "until": None, "kinds": [], "trial_until": end - 2 * 86400}
    main.step()
    assert main.status == "no_access"
    assert main.error.startswith("Your free trial has ended.") and "Nothing was deleted" in main.error
    snapshot = main.snapshot()
    assert snapshot["access"]["state"] == "trial_ended" and snapshot["access"]["message"] == main.error
    assert main.identity.exists(), "the computer keeps its Cloud identity and keys"
    assert len(service.chain) == 1, "nothing on the service was touched"
    # Subscribing (a paid grant) reconnects on the next pass with the same identity.
    service.refused = False
    service.access = {"entitled": True, "until": end + 30 * 86400, "kinds": ["paid"], "trial_until": end - 2 * 86400}
    main.step()
    assert main.status == "active" and main.error == ""
    assert main.snapshot()["access"]["state"] == "active"
