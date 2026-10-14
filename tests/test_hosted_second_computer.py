# SPDX-License-Identifier: AGPL-3.0-or-later
"""A second computer joins a Saiph account like a phone. Offline, real crypto, synthetic data."""
from copy import deepcopy
import time
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
import requests

from orion_mini.hosted_runtime import ROOT_ONLY, HostedController, HostedError
from orion_mini.hosted_transport import HostedTransport

from test_hosted_runtime import CONFIG, Presence, SyntheticProtection, workspace


class SyntheticService:
    """One account's shared state: the signed roster chain and per-device inboxes."""

    def __init__(self):
        self.deployment = str(uuid4())
        self.chain, self.inboxes, self.requests = [], {}, []

    def transport(self):
        service = self

        class Transport(HostedTransport):
            def _call(self, method, path, *, token=None, value=None):
                if token is not None:
                    assert token == "synthetic-access"
                if method == "GET" and path == "/v1/account":
                    return {"deployment_id": service.deployment, "device_trust_required": True}
                if method == "GET" and path.startswith("/v1/devices/rosters/page?"):
                    after = int(parse_qs(urlsplit(path).query)["after_version"][0])
                    return {"chain": deepcopy(service.chain[after:]), "more": False}
                if method == "POST" and path == "/v1/devices/requests":
                    assert value["deployment_id"] == service.deployment
                    service.requests.append(value["device"]["id"])
                    return {"status": "pending", "expires_at": int(time.time()) + 300}
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
    with pytest.raises(HostedError, match="already has a Saiph Hosted identity"):
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
    assert again.status == "keys_unavailable"
    assert again.session is None
