# SPDX-License-Identifier: AGPL-3.0-or-later
"""Desktop preview gates and safety boundaries using synthetic profiles."""
from types import SimpleNamespace

import pytest

from orion_mini.hosted_runtime import HostedController, HostedError, hosted_enabled, validate_config
from orion_mini.hosted_features import clipboard_payload, read_clipboard, FeatureError


CONFIG = {"service_url": "https://synthetic.example", "issuer": "https://identity.example/",
          "audience": "https://synthetic.example/api", "client_id": "synthetic-desktop"}


def workspace(tmp_path, settings=None):
    from orion_mini.storage import Store
    return SimpleNamespace(root=tmp_path, settings=settings or {}, save=lambda: None, store=Store(tmp_path / "store"))


class Presence:
    """Records verification requests; ``refuse`` simulates a cancelled Windows Hello prompt."""
    def __init__(self):
        self.reasons, self.refuse = [], False

    def confirm(self, reason):
        from orion_mini.user_presence import UserVerificationError
        self.reasons.append(reason)
        if self.refuse:
            raise UserVerificationError("Verification was cancelled. Nothing was changed.")
        return "verified"

    def cached_status(self):
        return "windows_hello"


@pytest.mark.parametrize("settings", [{}, {"hosted": {}}, {"hosted": {"enabled": False}},
                                     {"hosted": {"enabled": "true"}}, {"hosted": {"enabled": 1}}])
def test_default_off_never_opens_transport_or_creates_secret_material(tmp_path, settings):
    def forbidden(*args, **kwargs):
        pytest.fail("Disabled Hosted attempted to create a transport")

    profile = workspace(tmp_path, settings)
    controller = HostedController(profile, transport_factory=forbidden)
    controller.step()
    assert not hosted_enabled(settings)
    assert controller.status == "off"
    assert not controller.local_clipboard("text/plain", b"synthetic")
    assert not (tmp_path / "hosted").exists()
    assert profile.settings == settings


def test_enabling_requires_configuration_and_refuses_self_hosted_pairing(tmp_path):
    profile = workspace(tmp_path)
    controller = HostedController(profile)
    with pytest.raises(HostedError):
        controller.set_enabled(True)
    controller.configure(CONFIG)
    profile.settings["hub"] = {"paired": True}
    with pytest.raises(HostedError, match="self-hosted"):
        controller.set_enabled(True)
    assert not controller.enabled()
    assert not (tmp_path / "hosted").exists()
    profile.settings["hub"]["paired"] = False
    controller.set_enabled(True)
    assert controller.enabled() and controller.blocks_self_hosted()
    controller.set_enabled(False)
    assert not controller.blocks_self_hosted()


def test_sign_in_selects_google_explicitly_and_keeps_legacy_route(tmp_path, monkeypatch):
    calls = []
    controller = HostedController(workspace(tmp_path, {"hosted": {**CONFIG, "enabled": True}}))
    monkeypatch.setattr(controller, "_account", lambda: SimpleNamespace(begin_sign_in=lambda **options: calls.append(options)))
    controller.sign_in(google=True)
    controller.sign_in()
    assert calls == [{"google": True}, {}]
    with pytest.raises(HostedError):
        controller.sign_in(google="true")


@pytest.mark.parametrize("url", ["http://synthetic.example", "https://user:pass@synthetic.example",
    "https://synthetic.example/private", "https://synthetic.example?token=synthetic",
    "https://synthetic.example/#private", "https://synthetic.example\\private"])
def test_service_configuration_rejects_credentials_and_ambiguous_urls(url):
    with pytest.raises(HostedError):
        validate_config({**CONFIG, "service_url": url})


def test_clock_blocked_scheduler_cannot_sync_even_with_a_locally_valid_roster(tmp_path, monkeypatch):
    now = 1900000000
    profile = workspace(tmp_path, {"hosted": {**CONFIG, "enabled": True}})
    controller = HostedController(profile, clock=lambda: now)
    monkeypatch.setattr(controller.identity, "exists", lambda: True)
    monkeypatch.setattr(controller, "_token", lambda: "synthetic-access")
    monkeypatch.setattr(controller, "_open", lambda: None)
    monkeypatch.setattr(controller, "_refresh", lambda token: None)
    monkeypatch.setattr(controller, "_active", lambda: True)
    controller.session = SimpleNamespace(roster={"expires_at": now + 12 * 3600})
    controller.transport = SimpleNamespace(server_offset=3601)
    effects = []
    monkeypatch.setattr(controller, "_sync", lambda: effects.append("synced"))
    controller.step()
    assert controller.status == "clock"
    assert controller.decision.blocked
    assert effects == []


def test_disabling_invalidates_session_clears_offers_and_closes_transport(tmp_path):
    profile = workspace(tmp_path, {"hosted": {**CONFIG, "enabled": True}})
    controller = HostedController(profile)
    effects = []
    controller.session = SimpleNamespace(invalidate=lambda: effects.append("invalidated"))
    controller.transport = SimpleNamespace(close=lambda: effects.append("closed"))
    controller._offers["synthetic"] = {}
    controller._outgoing_clipboard = {"type": "clipboard.text"}
    controller.set_enabled(False)
    assert effects == ["closed", "invalidated"]
    assert controller.session is controller.transport is None
    assert controller._offers == {} and controller._outgoing_clipboard is None
    assert not controller.local_clipboard("text/plain", b"synthetic-after-off")


def test_clipboard_payload_integrity_limit_and_local_echo_suppression(tmp_path):
    data = "synthetic text λ".encode()
    payload = clipboard_payload(data)
    assert read_clipboard(payload) == data
    with pytest.raises(FeatureError):
        read_clipboard({**payload, "text": "tampered"})
    with pytest.raises(FeatureError):
        clipboard_payload(b"x" * 16385)
    profile = workspace(tmp_path, {"hosted": {**CONFIG, "enabled": True}})
    controller = HostedController(profile)
    controller.session = object()
    assert controller.local_clipboard("text/plain", data)
    assert not controller.local_clipboard("text/plain", data)
    assert not controller.local_clipboard("image/png", b"synthetic-image")
    profile.settings["link"] = {"clipboard": False}
    assert not controller.local_clipboard("text/plain", b"different")


@pytest.mark.parametrize("failure_kind", ["protected_storage", "filesystem"])
def test_sign_out_deactivates_runtime_even_if_saved_token_cannot_be_deleted(tmp_path, failure_kind):
    from orion_mini.hosted_keys import KeyStorageError
    failure = KeyStorageError if failure_kind == "protected_storage" else PermissionError

    profile = workspace(tmp_path, {"hosted": {**CONFIG, "enabled": True}})
    controller = HostedController(profile)
    effects = []

    def fail_sign_out():
        raise failure()

    controller.account = SimpleNamespace(sign_out=fail_sign_out)
    controller.session = SimpleNamespace(invalidate=lambda: effects.append("invalidated"))
    controller.transport = SimpleNamespace(close=lambda: effects.append("closed"))
    controller._offers["synthetic-offer"] = {}
    controller._outgoing_clipboard = {"type": "clipboard.text"}
    with pytest.raises(failure):
        controller.sign_out()
    assert effects == ["closed", "invalidated"]
    assert controller.status == "off"
    assert not controller.enabled()
    controller.step()
    assert controller.session is controller.transport is None
    assert controller._offers == {} and controller._outgoing_clipboard is None
    assert not controller.local_clipboard("text/plain", b"synthetic-after-signout")


class SyntheticProtection:
    def __init__(self):
        import tink
        from tink import aead
        aead.register()
        self.key = tink.new_keyset_handle(aead.aead_key_templates.AES256_GCM).primitive(aead.Aead)

    def load(self, context):
        return self.key

    def create(self, context):
        return self.key


@pytest.mark.parametrize("restart_before_change", [False, True])
def test_disabling_refresh_persistence_clears_encrypted_vault_and_cannot_restore_it(tmp_path, restart_before_change):
    from orion_mini.hosted_login import TokenGrant
    from orion_mini.hosted_tokens import SignInRequired

    profile = workspace(tmp_path)
    protection = SyntheticProtection()
    revoked = []
    controller = HostedController(profile, protection=protection, revoker=lambda _, token: revoked.append(token))
    controller.configure({**CONFIG, "refresh_tokens": True})
    original = controller._account()
    original._accept(TokenGrant("synthetic-access", 5000, "synthetic-old-refresh"))
    vault = original._vault
    assert vault.load() == "synthetic-old-refresh"
    if restart_before_change:
        controller = HostedController(profile, protection=protection, revoker=lambda _, token: revoked.append(token))
    controller.configure({**CONFIG, "refresh_tokens": False})
    assert vault.load() is None
    assert revoked == ["synthetic-old-refresh"]
    assert controller.settings["refresh_tokens"] is False
    controller.configure({**CONFIG, "refresh_tokens": True})
    restored = controller._account()
    assert restored.status == "signed_out"
    with pytest.raises(SignInRequired):
        restored.access_token()


def test_configuring_another_deployment_clears_previous_refresh_before_context_change(tmp_path):
    from orion_mini.hosted_login import TokenGrant
    from orion_mini.hosted_tokens import SignInRequired

    profile = workspace(tmp_path)
    protection = SyntheticProtection()
    controller = HostedController(profile, protection=protection, revoker=lambda *_: None)
    controller.configure({**CONFIG, "refresh_tokens": True})
    original = controller._account()
    original._accept(TokenGrant("synthetic-access", 5000, "synthetic-old-refresh"))
    vault = original._vault
    controller.configure({**CONFIG, "client_id": "synthetic-other-client", "refresh_tokens": True})
    assert vault.load() is None
    assert controller._account().status == "signed_out"
    with pytest.raises(SignInRequired):
        controller._account().access_token()


def test_root_approval_clipboard_restart_and_revocation_use_real_crypto_offline(tmp_path, monkeypatch):
    """Exercise the controller/protocol boundary; no HTTP provider is contacted."""
    from copy import deepcopy
    import time
    from urllib.parse import parse_qs, urlsplit
    from uuid import uuid4
    import requests
    from cryptography.hazmat.primitives.asymmetric import ec
    from orion_mini.hosted_approval import make_request_code, trust_root_code
    from orion_mini.hosted_crypto import EnvelopeError, generate_recipient
    from orion_mini.hosted_session import SealedSession
    from orion_mini.hosted_transport import HostedTransport

    def forbidden_network(*args, **kwargs):
        pytest.fail("Synthetic Hosted lifecycle attempted a real HTTP request")

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden_network)
    deployment = str(uuid4())
    chain, published, incoming, acknowledged = [], [], [], []

    class SyntheticTransport(HostedTransport):
        def _call(self, method, path, *, token=None, value=None):
            if token is not None:
                assert token == "synthetic-access"
            if method == "GET" and path == "/v1/account":
                return {"deployment_id": deployment, "device_trust_required": True}
            if method == "GET" and path.startswith("/v1/devices/rosters/page?"):
                query = parse_qs(urlsplit(path).query)
                after = int(query["after_version"][0])
                return {"chain": deepcopy(chain[after:]), "more": False}
            if method == "POST" and path == "/v1/devices/requests":
                assert value["deployment_id"] == deployment
                return {"status": "pending", "expires_at": int(time.time()) + 300}
            if method == "POST" and path == "/v1/devices/rosters":
                assert value["roster"]["version"] == len(chain) + 1
                chain.append(deepcopy(value))
                return {"accepted": True}
            if method == "POST" and path == "/v1/sealed/events":
                published.append(deepcopy(value))
                return {"accepted": True, "duplicate": False}
            if method == "GET" and path == "/v1/sealed/events":
                return {"events": deepcopy(incoming)}
            if method == "DELETE" and path.startswith("/v1/sealed/events/"):
                acknowledged.append(path.rsplit("/", 1)[1])
                incoming[:] = [event for event in incoming if event["header"]["id"] != acknowledged[-1]]
                return {"ok": True}
            pytest.fail(f"Unexpected synthetic Hosted route: {method} {path}")

    profile = workspace(tmp_path / "desktop")
    profile.user_presence = presence = Presence()
    alerts = []
    profile.security_alert = alerts.append
    protection = SyntheticProtection()
    received = []
    controller = HostedController(profile, protection=protection, transport_factory=SyntheticTransport)
    controller.clipboard_sink = lambda mime, data: received.append((mime, data))
    controller.configure(CONFIG)
    controller.set_enabled(True)
    monkeypatch.setattr(controller, "_token", lambda: "synthetic-access")
    root_code = controller.setup_root()
    root = trust_root_code(root_code["code"], trusted_out_of_band=True)
    assert root_code["modules"] and root_code["fingerprint"] == root.display_fingerprint
    assert chain[0]["roster"]["expires_at"] - int(time.time()) > 11 * 3600

    device = "dev_" + uuid4().hex
    signing = ec.generate_private_key(ec.SECP256R1())
    encryption = generate_recipient()
    request = make_request_code(root, device, signing, encryption)
    assert controller.inspect_request(request)["device_id"] == device
    with pytest.raises(HostedError, match="fingerprint"):
        controller.approve(request, "Synthetic phone", False)
    assert len(chain) == 1 and not presence.reasons
    # A cancelled Windows Hello prompt stops approval before any roster is signed.
    presence.refuse = True
    with pytest.raises(ValueError, match="cancelled"):
        controller.approve(request, "Synthetic phone", True)
    assert len(chain) == 1 and not alerts
    presence.refuse = False
    assert controller.approve(request, "Synthetic phone", True) == {"approved": device}
    assert presence.reasons[-1] == 'approve the device "Synthetic phone" for your Saiph account'
    assert alerts == ["Synthetic phone was approved for your Saiph account. If this wasn't you, remove it in Settings."]
    assert [(e["kind"], e["device_id"]) for e in controller.snapshot()["security_events"]] == [("added", device)]
    phone = SealedSession(tmp_path / "phone.sqlite3", deployment, root.signing_key, device, signing, encryption)
    phone.accept_chain(deepcopy(chain))
    assert controller._labels()[device] == "Synthetic phone"
    assert controller.local_clipboard("text/plain", b"synthetic desktop text")
    controller.step()
    assert controller.status == "active"
    assert len(published) == 1
    assert read_clipboard(phone.authenticate(published[0])) == b"synthetic desktop text"
    incoming.append(phone.encrypt(root.device_id, clipboard_payload(b"synthetic phone text")))
    incoming_id = incoming[0]["header"]["id"]
    controller.step()
    assert received == [("text/plain", b"synthetic phone text")]
    assert acknowledged == [incoming_id]
    assert not controller.local_clipboard("text/plain", b"synthetic phone text")
    controller.step()
    assert received == [("text/plain", b"synthetic phone text")]

    # The same protected identity and durable trust survive a controller restart.
    controller._deactivate("off")
    restarted = HostedController(profile, protection=protection, transport_factory=SyntheticTransport)
    monkeypatch.setattr(restarted, "_token", lambda: "synthetic-access")
    restarted.step()
    assert restarted.status == "active"
    assert restarted.info.device_id == root.device_id
    assert restarted.revoke(device) == {"revoked": device}
    assert presence.reasons[-1] == "remove a device from your Saiph account"
    assert alerts[-1] == "Synthetic phone was removed from your Saiph account."
    assert device not in restarted.session.current()
    assert device not in restarted._labels()
    with pytest.raises(EnvelopeError):
        phone.accept_chain(deepcopy(chain))
    with pytest.raises(EnvelopeError):
        restarted.session.encrypt(device, clipboard_payload(b"after revocation"))
    restarted.set_enabled(False)
    assert restarted.session is restarted.transport is None
