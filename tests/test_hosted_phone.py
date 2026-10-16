# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hosted texts and calls: payload shapes, authorization and the shared Phone page.

Synthetic numbers, names and messages only. No HTTP provider is contacted; the
relay is an in-memory stub and every envelope uses the real sealed crypto.
"""
from copy import deepcopy
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from orion_mini import hosted_features as hf
from orion_mini.hosted_features import FeatureError, phone_command, read_phone_command, read_phone_data

MESSAGE = {"id": 41, "addresses": ["+15550100"], "body": "Synthetic hello", "timestamp": 1_760_000_000_000,
           "direction": "incoming", "subscription": 1}


def thread(**changes):
    return {"type": "sms.thread", "thread": 7, "recipients": ["+15550100"], "message": dict(MESSAGE), **changes}


# ------------------------------------------------------------------ payloads
@pytest.mark.parametrize("payload", [
    {"type": "phone.capabilities", "capabilities": ["files", "sms", "calls", "call-control"]},
    {"type": "phone.capabilities", "capabilities": []},
    thread(),
    {"type": "sms.messages", "thread": 7, "messages": [dict(MESSAGE), {**MESSAGE, "id": 42, "direction": "outgoing"}]},
    {"type": "sms.remove", "thread": 7},
    {"type": "sms.index", "thread": 7, "ids": [41, 42]},
    {"type": "call.state", "state": "ringing", "number": "+15550100", "name": "Synthetic Caller"},
    {"type": "call.state", "state": "ended", "number": "", "name": ""},
    {"type": "contacts.results", "query": "syn", "contacts": [{"name": "Synthetic Caller", "numbers": ["+15550100"]}]},
    {"type": "calls.log", "calls": [{"number": "+15550100", "name": "", "timestamp": 1, "duration": 3, "type": "missed"}]},
])
def test_phone_data_accepts_exact_shapes_and_strips_the_type(payload):
    kind, body = read_phone_data(deepcopy(payload))
    assert kind == payload["type"]
    assert body == {key: value for key, value in payload.items() if key != "type"}


@pytest.mark.parametrize("payload", [
    {**thread(), "checksum": 1},  # New fields are refused; new behaviour needs new types.
    thread(thread=True),
    thread(thread=-1),
    thread(thread=2**53),
    thread(recipients=["+1555"] * 11),
    thread(recipients=[""]),
    thread(recipients=["+1555\n0100"]),
    thread(message={**MESSAGE, "body": "x" * 4097}),
    thread(message={**MESSAGE, "direction": "sideways"}),
    thread(message={**MESSAGE, "attachments": []}),
    thread(message={**MESSAGE, "body": "\ud800"}),
    thread(message={**MESSAGE, "timestamp": 1.5}),
    {"type": "sms.messages", "thread": 7, "messages": []},
    {"type": "sms.messages", "thread": 7, "messages": [dict(MESSAGE)] * 11},
    {"type": "sms.index", "thread": 7, "ids": list(range(1001))},
    {"type": "call.state", "state": "on hold", "number": "", "name": ""},
    {"type": "call.state", "state": "ringing", "number": "+1555\x000100", "name": ""},
    {"type": "call.state", "state": "ringing", "number": "", "name": "x" * 241},
    {"type": "contacts.results", "query": "syn", "contacts": [{"name": "A", "numbers": ["1"] * 6}]},
    {"type": "contacts.results", "query": "syn", "contacts": [{"name": "A", "numbers": ["1" * 41]}]},
    {"type": "contacts.results", "query": "syn", "contacts": [{"name": "A", "numbers": []}] * 21},
    {"type": "calls.log", "calls": [{"number": "1", "name": "", "timestamp": 1, "duration": 3, "type": "voicemail"}]},
    {"type": "calls.log", "calls": [{"number": "1", "name": "", "timestamp": 1, "duration": 3, "type": "missed"}] * 51},
    {"type": "phone.capabilities", "capabilities": ["sms", "sms"]},
    {"type": "phone.capabilities", "capabilities": ["sms-group"]},  # Group replies are outside Hosted.
    {"type": "phone.capabilities", "capabilities": ["unknown-gallery"]},
    {"type": "phone.capabilities", "capabilities": "sms"},
    {"type": "sms.send", "thread": 7, "text": "Actions are never phone data"},
    {"type": "clipboard.text", "text": "x", "sha256": "0" * 64},
    "sms.thread",
])
def test_phone_data_rejects_every_other_shape(payload):
    with pytest.raises(FeatureError):
        read_phone_data(deepcopy(payload))


@pytest.mark.parametrize("payload", [
    {"type": "call.handled", "operation": "answer", "by": "Synthetic desk"},
    {"type": "call.handled", "operation": "reject", "by": ""},
    {"type": "call.refused", "request": "answer", "reason": "handled", "handled": "reject", "by": "Synthetic laptop"},
    {"type": "call.refused", "request": "reject", "reason": "not_ringing", "handled": "", "by": ""},
    {"type": "call.refused", "request": "dial", "reason": "in_call", "handled": "", "by": ""},
    {"type": "call.refused", "request": "dial", "reason": "dialing", "handled": "", "by": ""},
])
def test_call_race_results_have_exact_shapes(payload):
    assert read_phone_data(deepcopy(payload)) == (payload["type"], {k: v for k, v in payload.items() if k != "type"})


@pytest.mark.parametrize("payload", [
    {"type": "call.handled", "operation": "dial", "by": ""},
    {"type": "call.handled", "operation": "answer", "by": "x" * 41},
    {"type": "call.handled", "operation": "answer", "by": "Desk\nPC"},
    {"type": "call.handled", "operation": "answer"},
    {"type": "call.refused", "request": "answer", "reason": "handled", "handled": "", "by": ""},  # Handled by what?
    {"type": "call.refused", "request": "answer", "reason": "not_ringing", "handled": "answer", "by": ""},
    {"type": "call.refused", "request": "answer", "reason": "in_call", "handled": "", "by": ""},  # Dial reasons only.
    {"type": "call.refused", "request": "dial", "reason": "not_ringing", "handled": "", "by": ""},
    {"type": "call.refused", "request": "send", "reason": "handled", "handled": "answer", "by": ""},
])
def test_call_race_results_refuse_other_shapes(payload):
    with pytest.raises(FeatureError):
        read_phone_data(deepcopy(payload))


def test_subscribe_names_this_computer_in_one_short_line():
    assert hf.subscribe_payload("Synthetic desk") == {"type": "phone.subscribe", "label": "Synthetic desk"}
    assert hf.subscribe_payload("  Desk\n\tPC  ")["label"] == "DeskPC"
    assert hf.subscribe_payload("   ")["label"] == "Computer"
    assert len(hf.subscribe_payload("x" * 80)["label"]) == 40
    assert hf.read_subscribe({"type": "phone.subscribe", "label": "Synthetic desk"}) == "Synthetic desk"
    for bad in ({"type": "phone.subscribe", "label": ""}, {"type": "phone.subscribe", "label": "a\x00b"},
                {"type": "phone.subscribe", "label": "x" * 41}, {"type": "phone.subscribe", "label": "A", "root": True}):
        with pytest.raises(FeatureError):
            hf.read_subscribe(bad)


def test_refusals_are_plain_words():
    from orion_mini.hosted_runtime import refusal_text
    assert refusal_text({"reason": "handled", "handled": "answer", "by": "Kitchen PC"}) == "Answered on Kitchen PC."
    assert refusal_text({"reason": "handled", "handled": "reject", "by": "Kitchen PC"}) == "Declined on Kitchen PC."
    assert refusal_text({"reason": "handled", "handled": "answer", "by": ""}) == "Already handled on another computer."
    assert refusal_text({"reason": "in_call", "handled": "", "by": ""}) == "Not dialed: your phone is already on a call."
    assert refusal_text({"reason": "dialing", "handled": "", "by": ""}) == "Not dialed: your phone is already placing a call."


def test_phone_commands_are_built_exactly_and_bounded():
    assert phone_command("sms.sync", {}) == {"type": "sms.sync"}
    assert phone_command("sms.open", {"thread": 7}) == {"type": "sms.open", "thread": 7}
    assert phone_command("sms.send", {"thread": 7, "text": "On my way"}) == {"type": "sms.send", "thread": 7, "text": "On my way"}
    assert phone_command("sms.compose", {"addresses": ["+15550100"], "text": "Hi"}) == {
        "type": "sms.compose", "addresses": ["+15550100"], "text": "Hi"}
    assert phone_command("call.command", {"operation": "answer"}) == {"type": "call.command", "operation": "answer"}
    assert phone_command("call.dial", {"number": "+1 (555) 010-0"}) == {"type": "call.dial", "number": "+1 (555) 010-0"}
    assert phone_command("contacts.search", {"query": "Syn"}) == {"type": "contacts.search", "query": "Syn"}
    assert phone_command("calls.log.request", {}) == {"type": "calls.log.request"}
    # Every capability-gated action has a capability, and the phone checks the same table.
    assert set(hf.COMMAND_CAPABILITY) == {"photo.request", "sms.sync", "sms.open", "sms.send", "sms.compose", "call.command",
                                          "call.dial", "contacts.search", "calls.log.request"}


@pytest.mark.parametrize("kind,body", [
    ("sms.send", {"thread": 7, "text": "   "}),
    ("sms.send", {"thread": 7, "text": "x" * 4097}),
    ("sms.send", {"thread": 7, "text": "\U0001F600" * 2000}),  # Fits 4096 characters, not one sealed event.
    ("sms.send", {"thread": 7, "text": "Hi", "recipients": ["+15550100"]}),
    ("sms.send", {"thread": "7", "text": "Hi"}),
    ("sms.compose", {"addresses": ["+15550100", "+15550101"], "text": "Group"}),
    ("sms.compose", {"addresses": [], "text": "Nobody"}),
    ("sms.compose", {"addresses": ["+1555\n0100"], "text": "Hi"}),
    ("call.command", {"operation": "hold"}),
    ("call.dial", {"number": "*21*5550100#"}),  # MMI codes can change call forwarding.
    ("call.dial", {"number": "+()"}),
    ("contacts.search", {"query": ""}),
    ("contacts.search", {"query": "x" * 65}),
    ("calls.log.request", {"limit": 5}),
    ("sms.sync", {"all": True}),
    ("phone.ring", {}),
    ("media.command", {"source": "x", "action": "play"}),
    ("sms.attachment.request", {"thread": 7, "message": 41, "part": 1}),
])
def test_phone_commands_refuse_unsafe_or_out_of_scope_requests(kind, body):
    with pytest.raises(FeatureError):
        phone_command(kind, body)


def test_wire_contract_matches_the_android_phone():
    """The same literals are checked by android/.../HostedPhoneFramesTest.kt."""
    import json
    from orion_mini.hosted_crypto import canonical
    thread_wire = ('{"message":{"addresses":["+15550100"],"body":"Synthetic hello","direction":"incoming","id":41,'
                   '"subscription":1,"timestamp":1760000000000},"recipients":["+15550100"],"thread":7,"type":"sms.thread"}')
    assert canonical(thread()) == thread_wire.encode()
    assert read_phone_data(json.loads(thread_wire))[0] == "sms.thread"
    send_wire = '{"text":"On my way \\ud83d\\ude00","thread":7,"type":"sms.send"}'
    assert canonical(phone_command("sms.send", {"thread": 7, "text": "On my way \U0001F600"})) == send_wire.encode()
    assert canonical(hf.subscribe_payload("Synthetic desk")) == b'{"label":"Synthetic desk","type":"phone.subscribe"}'
    handled = '{"by":"Synthetic laptop","operation":"answer","type":"call.handled"}'
    refused = '{"by":"Synthetic laptop","handled":"answer","reason":"handled","request":"reject","type":"call.refused"}'
    busy = '{"by":"","handled":"","reason":"in_call","request":"dial","type":"call.refused"}'
    for wire in (handled, refused, busy):
        assert canonical(json.loads(wire)) == wire.encode() and read_phone_data(json.loads(wire))


def test_read_phone_command_rejects_data_and_extra_fields():
    with pytest.raises(FeatureError):
        read_phone_command(thread())
    with pytest.raises(FeatureError):
        read_phone_command({"type": "call.command", "operation": "answer", "number": "+15550100"})


# ------------------------------------------------------------------- runtime
CONFIG = {"service_url": "https://synthetic.example", "issuer": "https://identity.example/",
          "audience": "https://synthetic.example/api", "client_id": "synthetic-desktop"}


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


class Presence:
    def confirm(self, reason):
        return "verified"

    def cached_status(self):
        return "windows_hello"


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    """A root computer and one approved synthetic phone over an in-memory relay."""
    import requests
    from cryptography.hazmat.primitives.asymmetric import ec
    from orion_mini.hosted_approval import make_request_code, trust_root_code
    from orion_mini.hosted_crypto import generate_recipient
    from orion_mini.hosted_runtime import HostedController
    from orion_mini.hosted_session import SealedSession
    from orion_mini.hosted_transport import HostedTransport
    from orion_mini.phone_features import PhoneFeatures
    from orion_mini.storage import Store

    monkeypatch.setattr(requests.sessions.Session, "request",
                        lambda *a, **k: pytest.fail("Synthetic Hosted test attempted a real HTTP request"))
    deployment = str(uuid4())
    chain, published, incoming = [], [], []

    class SyntheticTransport(HostedTransport):
        def _call(self, method, path, *, token=None, value=None):
            if method == "GET" and path == "/v1/account":
                return {"deployment_id": deployment, "device_trust_required": True}
            if method == "GET" and path.startswith("/v1/devices/rosters/page?"):
                after = int(parse_qs(urlsplit(path).query)["after_version"][0])
                return {"chain": deepcopy(chain[after:]), "more": False}
            if method == "POST" and path == "/v1/devices/requests":
                return {"status": "pending", "expires_at": int(time.time()) + 300}
            if method == "POST" and path == "/v1/devices/rosters":
                chain.append(deepcopy(value))
                return {"accepted": True}
            if method == "POST" and path == "/v1/sealed/events":
                published.append(deepcopy(value))
                return {"accepted": True, "duplicate": False}
            if method == "GET" and path == "/v1/sealed/events":
                return {"events": deepcopy(incoming)}
            if method == "DELETE" and path.startswith("/v1/sealed/events/"):
                incoming[:] = [e for e in incoming if e["header"]["id"] != path.rsplit("/", 1)[1]]
                return {"ok": True}
            pytest.fail(f"Unexpected synthetic Hosted route: {method} {path}")

    profile = SimpleNamespace(root=tmp_path / "desktop", settings={"machine": {"name": "Synthetic desk"}}, save=lambda: None,
                              store=Store(tmp_path / "desktop" / "store"), user_presence=Presence())
    profile.phone_features = PhoneFeatures(profile)
    alerts, call_states = [], []
    profile.phone_alert = lambda title, text: alerts.append((title, text))
    controller = HostedController(profile, protection=SyntheticProtection(), transport_factory=SyntheticTransport)
    controller.call_state = call_states.append
    controller.configure(CONFIG)
    controller.set_enabled(True)
    monkeypatch.setattr(controller, "_token", lambda: "synthetic-access")
    root = trust_root_code(controller.setup_root()["code"], trusted_out_of_band=True)
    device = "dev_" + uuid4().hex
    signing, encryption = ec.generate_private_key(ec.SECP256R1()), generate_recipient()
    controller.approve(make_request_code(root, device, signing, encryption), "Synthetic phone", True)
    # A second approved, non-root device: the roster cannot say whether it is a computer.
    other = "dev_" + uuid4().hex
    other_signing, other_encryption = ec.generate_private_key(ec.SECP256R1()), generate_recipient()
    controller.approve(make_request_code(root, other, other_signing, other_encryption), "Synthetic laptop", True)
    phone = SealedSession(tmp_path / "phone.sqlite3", deployment, root.signing_key, device, signing, encryption)
    phone.accept_chain(deepcopy(chain))
    laptop = SealedSession(tmp_path / "laptop.sqlite3", deployment, root.signing_key, other, other_signing, other_encryption)
    laptop.accept_chain(deepcopy(chain))
    controller.step()
    published.clear()

    def send(payload, source=phone):
        incoming.append(source.encrypt(root.device_id, payload))
        controller.step()

    def received():
        """Decrypted actions the phone would receive, oldest first."""
        controller.step()  # Flush anything staged while handling the last delivery.
        result = [phone.authenticate(envelope) for envelope in published if envelope["header"]["target"] == device]
        published.clear()
        return result

    return SimpleNamespace(controller=controller, profile=profile, device=device, root=root, phone=phone, laptop=laptop,
                           send=send, received=received, alerts=alerts, call_states=call_states, chain=chain,
                           incoming=incoming, published=published, deployment=deployment)


def features(h):
    return h.profile.phone_features.snapshot()


def test_encrypted_gallery_previews_sync_and_permission_revocation(hosted):
    import base64
    h = hosted
    preview = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9").decode()
    photo = {"type": "photos.item", "id": "41", "name": "Synthetic.jpg", "timestamp": 1, "preview": preview}
    h.send(photo)
    assert features(h)["photos"] == []  # No advertised photo capability.
    h.send({"type": "phone.capabilities", "capabilities": ["files", "photos"]})
    h.send(photo)
    assert features(h)["photos"][0]["preview"] == preview
    assert features(h)["photos"][0]["photo_id"] == "41"
    h.controller.phone_command(h.device, "photo.request", {"id": "41"})
    assert any(value == {"type": "photo.request", "id": "41"} for value in h.received())
    h.send({"type": "photos.sync", "ids": []})
    assert features(h)["photos"] == []
    h.send(photo)
    h.send({"type": "phone.capabilities", "capabilities": ["files"]})
    assert features(h)["photos"] == []
    assert not h.controller._photos_asked


@pytest.mark.parametrize("changes", [
    {"id": "../private"}, {"id": "9007199254740992"}, {"preview": "https://evil.invalid/track"},
    {"preview": "data:image/svg+xml;base64,PHN2Zz4="}, {"preview": "data:image/jpeg;base64,bad!"},
    {"extra": "unrecognized"}, {"timestamp": -1},
])
def test_gallery_rejects_unbounded_ids_external_images_and_extra_fields(changes):
    import base64
    photo = {"type": "photos.item", "id": "41", "name": "Synthetic.jpg", "timestamp": 1,
             "preview": "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9").decode()}
    with pytest.raises(FeatureError):
        read_phone_data({**photo, **changes})


def test_gallery_original_rejects_unsolicited_or_mismatched_requests(hosted):
    h = hosted
    h.send({"type": "phone.capabilities", "capabilities": ["photos"]})
    envelope = {"header": {"source": h.device}}
    payload = {"type": "photo.original", "photo_id": "41", "request": str(uuid4()), "file": {}}
    with pytest.raises(FeatureError):
        h.controller._photo_original(envelope, payload)

    h.controller._photos_asked[(h.device, "41")] = (str(uuid4()), time.time() + 300)
    with pytest.raises(FeatureError):
        h.controller._photo_original(envelope, payload)
    h.controller._photos_asked[(h.device, "41")] = (payload["request"], time.time() - 1)
    with pytest.raises(FeatureError):
        h.controller._photo_original(envelope, payload)


def test_gallery_original_crosses_the_real_sealed_mailbox_and_streaming_decryption(hosted, tmp_path, monkeypatch):
    import base64
    from test_hosted_files import BlobRelay
    from orion_mini.hosted_files import prepare_attachment, upload_attachment
    h = hosted
    h.send({"type": "phone.capabilities", "capabilities": ["photos"]})
    h.send({"type": "photos.item", "id": "41", "name": "Synthetic.jpg", "timestamp": 1,
            "preview": "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9").decode()})
    h.profile.hosted_phone_command = h.controller.phone_command
    h.profile.phone_features.photo_request(h.device, "41", "prefetch")
    request = h.controller._photos_asked[(h.device, "41")][0]
    original = tmp_path / "synthetic-original.jpg"
    original.write_bytes(b"synthetic original photo bytes")
    encrypted = tmp_path / "gallery-encrypted"
    encrypted.mkdir()
    attachment = prepare_attachment(h.phone, h.root.device_id, original.resolve(), encrypted.resolve(), mime="image/jpeg")
    relay = BlobRelay()
    upload_attachment(relay, attachment)
    manifest = h.controller.session.authenticate(relay.envelope)
    monkeypatch.setattr(h.controller.transport, "download_blob_chunk", relay.download_blob_chunk)
    wrapped = h.phone.encrypt(h.root.device_id, {"type": "photo.original", "photo_id": "41", "request": request,
                                                "file": manifest}, ttl_seconds=300)
    h.incoming.append(wrapped)
    h.controller.step()
    cached = h.profile.phone_features.photo_cached(h.device, "41")
    assert cached is not None
    assert __import__('pathlib').Path(cached['path']).read_bytes() == original.read_bytes()
    assert (h.device, "41") not in h.controller._photos_asked
    h.incoming.append(wrapped)
    h.controller.step()
    assert len(list((h.profile.root / 'phone-originals').iterdir())) == 1



def test_capabilities_list_a_hosted_phone_and_ask_once_for_its_conversations(hosted):
    h = hosted
    assert h.controller.phones() == []
    h.send({"type": "phone.capabilities", "capabilities": ["files", "sms", "calls", "call-control"]})
    [phone] = h.controller.phones()
    assert phone["id"] == h.device and phone["name"] == "Synthetic phone" and phone["hosted"] and phone["online"]
    assert phone["capabilities"] == ["files", "sms", "calls", "call-control"]
    # This computer names itself to the phone, then asks once for the conversation list.
    assert h.received() == [{"type": "phone.subscribe", "label": "Synthetic desk"}, {"type": "sms.sync"}]
    h.send({"type": "phone.capabilities", "capabilities": ["files", "sms", "calls", "call-control"]})
    assert h.received() == []  # Asked once per run, and the subscription is renewed only every 90 s.


def test_subscription_is_renewed_with_later_heartbeats(hosted, monkeypatch):
    h = hosted
    h.send({"type": "phone.capabilities", "capabilities": ["calls"]})
    assert h.received() == [{"type": "phone.subscribe", "label": "Synthetic desk"}]
    later = time.time() + 95
    monkeypatch.setattr(h.controller, "clock", lambda: later)
    h.send({"type": "phone.capabilities", "capabilities": ["calls"]})
    assert h.received() == [{"type": "phone.subscribe", "label": "Synthetic desk"}]


def test_texts_and_calls_arrive_on_the_shared_phone_page(hosted):
    h = hosted
    h.send({"type": "phone.capabilities", "capabilities": ["sms", "calls"]})
    h.received()
    h.send(thread())
    h.send({"type": "sms.messages", "thread": 7, "messages": [{**MESSAGE, "id": 42, "body": "Second", "direction": "outgoing"}]})
    state = features(h)
    assert [(row["device_id"], row["thread"], row["recipients"]) for row in state["threads"]] == [(h.device, 7, ["+15550100"])]
    assert sorted(row["body"] for row in state["messages"]) == ["Second", "Synthetic hello"]
    h.send({"type": "call.state", "state": "ringing", "number": "+15550100", "name": "Synthetic Caller"})
    assert features(h)["calls"][0]["state"] == "ringing"
    assert h.alerts == [("Incoming call", "Synthetic Caller is calling. Answer or decline in Saiph.")]
    h.send({"type": "call.state", "state": "missed", "number": "+15550100", "name": ""})
    assert h.alerts[-1] == ("Missed call", "+15550100") and h.call_states == ["ringing", "missed"]
    h.send({"type": "sms.index", "thread": 7, "ids": [42]})
    assert [row["body"] for row in features(h)["messages"]] == ["Second"]
    h.send({"type": "sms.remove", "thread": 7})
    assert features(h)["threads"] == [] and features(h)["messages"] == []


def test_phone_data_needs_the_advertised_capability(hosted):
    h = hosted
    h.send(thread())  # No capabilities yet: nothing is shown.
    h.send({"type": "phone.capabilities", "capabilities": ["calls"]})
    h.send(thread())  # Calls only: texts are still refused.
    assert features(h)["threads"] == []
    h.send({"type": "call.state", "state": "ringing", "number": "", "name": ""})
    assert h.alerts == [("Incoming call", "Unknown caller is calling. Answer or decline in Saiph.")]


def test_fast_poll_runs_only_once_texts_or_calls_are_shared(hosted):
    h = hosted
    assert not h.controller._fast_poll()
    h.send({"type": "phone.capabilities", "capabilities": ["calls"]})
    assert h.controller._fast_poll()
    h.incoming.append(h.phone.encrypt(h.root.device_id, {"type": "call.state", "state": "ringing", "number": "", "name": ""}))
    h.controller.poll()  # Between full passes: no roster refresh, same checks.
    assert features(h)["calls"][0]["state"] == "ringing" and not h.incoming
    h.controller.set_enabled(False)
    h.incoming.append(h.phone.encrypt(h.root.device_id, {"type": "call.state", "state": "ended", "number": "", "name": ""}))
    h.controller.poll()
    assert h.incoming and features(h)["calls"][0]["state"] == "ringing"


def test_call_alerts_can_be_turned_off(hosted):
    h = hosted
    h.profile.settings["link"] = {"call_alerts": False}
    h.send({"type": "phone.capabilities", "capabilities": ["calls"]})
    h.send({"type": "call.state", "state": "ringing", "number": "+15550100", "name": ""})
    assert h.alerts == [] and features(h)["calls"][0]["state"] == "ringing"


def test_root_sends_actions_only_to_a_capable_online_phone(hosted):
    h = hosted
    c = h.controller
    with pytest.raises(ValueError, match="unavailable"):
        c.phone_command(h.device, "sms.compose", {"addresses": ["+15550100"], "text": "Hi"})
    h.send({"type": "phone.capabilities", "capabilities": ["sms", "calls", "call-control", "call-dial"]})
    h.received()
    h.send(thread())
    queued = c.phone_command(h.device, "sms.send", {"thread": 7, "text": "Synthetic reply"})
    c.step()
    [action] = h.received()
    assert action == {"type": "sms.send", "thread": 7, "text": "Synthetic reply"}
    assert queued["queued"] is True
    # The phone sees which device asked: only this root may cause phone actions.
    with pytest.raises(ValueError, match="unavailable"):
        c.phone_command(h.device, "sms.send", {"thread": 8, "text": "Unknown thread"})
    with pytest.raises(ValueError, match="no longer ringing"):
        c.phone_command(h.device, "call.command", {"operation": "answer"})
    h.send({"type": "call.state", "state": "ringing", "number": "+15550100", "name": ""})
    c.phone_command(h.device, "call.command", {"operation": "answer"})
    c.phone_command(h.device, "call.dial", {"number": "+15550100"})
    c.step()
    assert h.received() == [{"type": "call.command", "operation": "answer"}, {"type": "call.dial", "number": "+15550100"}]
    with pytest.raises(ValueError, match="number"):
        c.phone_command(h.device, "call.dial", {"number": "*#06#"})
    with pytest.raises(ValueError, match="unavailable"):
        c.phone_command(h.device, "contacts.search", {"query": "Syn"})  # Not advertised.
    with pytest.raises(ValueError, match="unavailable"):
        c.phone_command(h.device, "phone.ring", {})
    with pytest.raises(ValueError, match="no longer approved"):
        c.phone_command(c.info.device_id, "sms.sync", {})


def test_a_call_answered_elsewhere_stops_ringing_here_at_once(hosted):
    h = hosted
    c = h.controller
    h.send({"type": "phone.capabilities", "capabilities": ["calls", "call-control"]})
    h.received()
    h.send({"type": "call.state", "state": "ringing", "number": "+15550100", "name": "Synthetic Caller"})
    h.send({"type": "call.handled", "operation": "answer", "by": "Synthetic laptop"})
    [call] = features(h)["calls"]
    assert (call["state"], call["handled"], call["handled_by"], call["name"]) == ("active", "answer", "Synthetic laptop", "Synthetic Caller")
    assert h.call_states[-1] == "active" and len(h.alerts) == 1  # Only the ringing alert; no error.
    with pytest.raises(ValueError, match="^Answered on Synthetic laptop.$"):
        c.phone_command(h.device, "call.command", {"operation": "reject"})
    h.send({"type": "call.state", "state": "ended", "number": "+15550100", "name": ""})
    assert features(h)["calls"][0]["handled_by"] == "Synthetic laptop"  # Kept until the next call rings.
    h.send({"type": "call.state", "state": "ringing", "number": "+15550101", "name": ""})
    assert "handled_by" not in features(h)["calls"][0]


def test_losing_a_call_race_shows_who_won_rather_than_an_error(hosted, monkeypatch):
    h = hosted
    c = h.controller
    h.send({"type": "phone.capabilities", "capabilities": ["calls", "call-control", "call-dial"]})
    h.received()
    refused = {"type": "call.refused", "request": "answer", "reason": "handled", "handled": "reject", "by": "Synthetic laptop"}
    h.send(refused)  # Not asked by this computer: ignored.
    assert c.phones()[0]["call_notice"] is None
    h.send({"type": "call.state", "state": "ringing", "number": "+15550100", "name": ""})
    assert c.phone_command(h.device, "call.command", {"operation": "answer"})["queued"]
    h.send(refused)
    assert c.phones()[0]["call_notice"] == "Declined on Synthetic laptop."
    h.send({"type": "call.handled", "operation": "reject", "by": "Synthetic laptop"})
    assert features(h)["calls"][0]["state"] == "ended"
    # Two dials at once: the phone refuses the second and says why.
    c.phone_command(h.device, "call.dial", {"number": "+15550101"})
    assert c.phones()[0]["call_notice"] is None  # A new request clears the old note.
    h.send({"type": "call.refused", "request": "dial", "reason": "dialing", "handled": "", "by": ""})
    assert c.phones()[0]["call_notice"] == "Not dialed: your phone is already placing a call."
    later = time.time() + 61
    monkeypatch.setattr(c, "clock", lambda: later)
    assert c.phones()[0]["call_notice"] is None
    h.send({"type": "call.refused", "request": "dial", "reason": "in_call", "handled": "", "by": ""})
    assert c.phones()[0]["call_notice"] is None  # Outside this computer's request window.


def test_another_approved_device_cannot_act_through_this_computer(hosted):
    """Subscriptions and phone actions are for phones; this computer ignores them."""
    h = hosted
    h.send({"type": "phone.subscribe", "label": "Synthetic laptop"}, source=h.laptop)
    h.send({"type": "call.command", "operation": "answer"}, source=h.laptop)
    h.send({"type": "call.handled", "operation": "answer", "by": "Synthetic laptop"}, source=h.laptop)
    assert h.received() == [] and features(h)["calls"] == [] and h.controller.phones() == []


def test_group_threads_are_not_replied_to_from_hosted(hosted):
    h = hosted
    h.send({"type": "phone.capabilities", "capabilities": ["sms"]})
    h.send(thread(recipients=["+15550100", "+15550101"]))
    with pytest.raises(ValueError, match="Group replies"):
        h.controller.phone_command(h.device, "sms.send", {"thread": 7, "text": "Hi all"})


def test_offline_phone_gets_nothing(hosted, monkeypatch):
    h = hosted
    h.send({"type": "phone.capabilities", "capabilities": ["call-dial"]})
    h.received()
    later = time.time() + 600
    monkeypatch.setattr(h.controller, "clock", lambda: later)
    assert h.controller.phones()[0]["online"] is False
    with pytest.raises(ValueError, match="offline"):
        h.controller.phone_command(h.device, "call.dial", {"number": "+15550100"})


def test_contact_results_and_call_history_answer_only_a_recent_request_and_stay_in_memory(hosted, monkeypatch):
    h = hosted
    results = {"type": "contacts.results", "query": "Syn", "contacts": [{"name": "Synthetic Caller", "numbers": ["+15550100"]}]}
    history = {"type": "calls.log", "calls": [{"number": "+15550100", "name": "", "timestamp": 1, "duration": 0, "type": "missed"}]}
    h.send({"type": "phone.capabilities", "capabilities": ["contacts", "call-log"]})
    h.received()
    h.send(results)
    h.send(history)
    assert features(h)["contacts"] == [] and features(h)["call_logs"] == []  # Unrequested answers are dropped.
    h.controller.phone_command(h.device, "contacts.search", {"query": "Syn"})
    h.controller.phone_command(h.device, "calls.log.request", {})
    h.controller.step()
    assert h.received() == [{"type": "contacts.search", "query": "Syn"}, {"type": "calls.log.request"}]
    h.send(results)
    h.send(history)
    assert features(h)["contacts"][0]["contacts"][0]["name"] == "Synthetic Caller"
    assert features(h)["call_logs"][0]["calls"][0]["type"] == "missed"
    with h.profile.store.connect() as db:
        stored = " ".join(row[0] for row in db.execute("SELECT data FROM records"))
    assert "Synthetic Caller" not in stored  # Answers are kept in memory only.
    h.controller._asked[(h.device, "contacts.search")] -= 120
    h.send({**results, "query": "Late"})
    assert all(row["query"] != "Late" for row in features(h)["contacts"])


def test_phone_actions_sent_to_the_root_have_no_effect(hosted):
    h = hosted
    h.send({"type": "phone.capabilities", "capabilities": ["sms", "calls", "call-control"]})
    h.received()
    for payload in ({"type": "sms.send", "thread": 7, "text": "Reflected"}, {"type": "call.command", "operation": "answer"},
                    {"type": "call.dial", "number": "+15550100"}):
        h.send(payload)
    assert h.received() == [] and features(h)["threads"] == []
    assert h.controller.mailbox.uncertain() == []  # Each was completed as a refused delivery.


def test_revoking_a_phone_removes_its_texts_and_calls(hosted):
    h = hosted
    h.send({"type": "phone.capabilities", "capabilities": ["sms", "calls"]})
    h.send(thread())
    h.send({"type": "call.state", "state": "active", "number": "+15550100", "name": ""})
    assert features(h)["threads"] and features(h)["calls"]
    h.controller.revoke(h.device)
    assert features(h)["threads"] == [] and features(h)["messages"] == [] and features(h)["calls"] == []
    assert h.controller.phones() == [] and not h.controller.is_phone(h.device)


def test_phone_page_routes_actions_and_lists_hosted_phones(tmp_path):
    """Link desktops keep their path; a hosted phone's actions go to the controller."""
    from orion_mini.phone_features import PhoneFeatures
    from orion_mini.storage import Store

    calls = []
    hosted_phone = {"id": "dev_hosted", "name": "Synthetic phone", "online": True, "hosted": True, "capabilities": ["sms"]}
    workspace = SimpleNamespace(store=Store(tmp_path), phone=None, phone_runtime=None,
                                hosted_phones=lambda: [hosted_phone],
                                hosted_phone_command=lambda d, k, p: calls.append((d, k, p)) or {"queued": True} if d == "dev_hosted" else None,
                                hosted_phone_file=lambda d, path: {"sent": True} if d == "dev_hosted" else None)
    phone_features = PhoneFeatures(workspace)
    phone_features.event({"type": "sms.thread", "source": "dev_hosted", "id": "x",
                          "payload": {"thread": 7, "recipients": ["+15550100"], "message": dict(MESSAGE)}}, None)
    assert phone_features.dispatch("phone.sms.send", {"device_id": "dev_hosted", "thread": 7, "text": "Hi"}) == {"queued": True}
    assert phone_features.dispatch("phone.dial", {"device_id": "dev_hosted", "number": "+15550100"}) == {"queued": True}
    assert phone_features.send_file("dev_hosted", str(tmp_path / "x")) == {"sent": True}
    assert calls == [("dev_hosted", "sms.send", {"thread": 7, "text": "Hi"}), ("dev_hosted", "call.dial", {"number": "+15550100"})]
    assert phone_features._has("dev_hosted", "sms") and not phone_features._has("dev_hosted", "sms-group")
    with pytest.raises(ValueError, match="offline"):
        phone_features.dispatch("phone.dial", {"device_id": "dev_link", "number": "+15550100"})


def test_link_workspace_merges_hosted_phones_only_while_hosted_is_on(tmp_path, monkeypatch):
    import platform
    from orion_mini.link_service import LinkWorkspace

    monkeypatch.setattr(platform, "node", lambda: "Synthetic computer")  # Avoid a slow system query.
    workspace = LinkWorkspace(tmp_path)
    assert workspace.phone_snapshot()["devices"] == []
    assert workspace.hosted_phone_command("dev_hosted", "sms.sync", {}) is None
    phone = {"id": "dev_hosted", "name": "Synthetic phone", "online": False, "hosted": True, "capabilities": ["sms"]}
    workspace._hosted = SimpleNamespace(enabled=lambda: True, phones=lambda: [phone], is_phone=lambda d: d == "dev_hosted",
                                        phone_command=lambda d, k, p: {"queued": True, "kind": k})
    assert workspace.phone_snapshot()["devices"] == [phone]
    assert workspace.hosted_phone_command("dev_hosted", "sms.sync", {}) == {"queued": True, "kind": "sms.sync"}
    assert workspace.hosted_phone_command("dev_link", "sms.sync", {}) is None
    workspace._hosted.enabled = lambda: False
    assert workspace.phone_snapshot()["devices"] == []
