# SPDX-License-Identifier: AGPL-3.0-or-later
import base64
import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4

import pytest
pytest.importorskip("tink")
import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from orion_mini.hosted_transport import HostedTransport, TransportError, strict_json


class Session:
    deployment = str(uuid4())
    device = "dev_" + uuid4().hex
    signing = ec.generate_private_key(ec.SECP256R1())
    def current(self): return {}
    def invalidate(self): self.active = False


class Adapter(requests.adapters.BaseAdapter):
    def __init__(self, body=b'{"events":[]}', status=200, content_type="application/json"):
        self.body, self.status, self.content_type, self.calls = body, status, content_type, []
    def send(self, request, **kwargs):
        self.calls.append((request, kwargs))
        response = requests.Response()
        response.status_code = self.status
        response.headers["Content-Type"] = self.content_type
        import io
        response.raw = io.BytesIO(self.body)
        return response
    def close(self): pass


@pytest.mark.parametrize("origin", ["http://relay.test", "https://a:b@relay.test", "https://relay.test/path",
                                  "https://relay.test?token=x", "https://relay.test/#x", "https://relay.test:abc", "https://relay.test\n", "https://relay.test\\x", "https:///x", None])
def test_unsafe_origin_rejected(origin):
    with pytest.raises(TransportError): HostedTransport(origin, Session())


def test_signed_device_request_and_no_environment_or_cookies(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://untrusted.invalid")
    transport = HostedTransport("https://relay.test", Session())
    transport.http.cookies.set("owner_session", "never-forward")
    adapter = Adapter()
    transport.http.mount("https://", adapter)
    assert transport.events() == []
    request, options = adapter.calls[0]
    assert options["verify"] is True and options["proxies"] == {}
    assert "Authorization" not in request.headers and "Cookie" not in request.headers
    assert not transport.http.trust_env
    headers = request.headers
    raw = f"GET\n/v1/sealed/events\n{headers['X-Orion-Timestamp']}\n{headers['X-Orion-Nonce']}\n{hashlib.sha256(b'').hexdigest()}".encode()
    Session.signing.public_key().verify(base64.b64decode(headers["X-Orion-Signature"]), raw, ec.ECDSA(hashes.SHA256()))


def test_account_binding_and_separate_bearer():
    session = Session()
    transport = HostedTransport("https://relay.test", session)
    adapter = Adapter(json.dumps({"deployment_id": session.deployment, "device_trust_required": True}).encode())
    transport.http.mount("https://", adapter)
    transport.account("synthetic-token")
    assert adapter.calls[0][0].headers["Authorization"] == "Bearer synthetic-token"
    assert "X-Orion-Signature" not in adapter.calls[0][0].headers
    adapter.body = json.dumps({"deployment_id": str(uuid4()), "device_trust_required": True}).encode()
    with pytest.raises(TransportError): transport.account("synthetic-token")


@pytest.mark.parametrize("body,status,kind", [(b'{}',302,"application/json"), (b'{"events":[],"events":[]}',200,"application/json"),
    (b'{"events":NaN}',200,"application/json"), (b'[]',200,"application/json"), (b'{}',200,"text/html"),
    (b'{"events":[null]}',401,"application/json"), (b'{"events":[]}',500,"application/json")])
def test_invalid_responses_and_redirects_fail_closed(body,status,kind):
    transport = HostedTransport("https://relay.test", Session())
    adapter = Adapter(body,status,kind)
    transport.http.mount("https://", adapter)
    with pytest.raises(TransportError) as error: transport.events()
    assert len(adapter.calls) == 1
    assert error.value.args == ("Hosted service request failed.",)


def test_ack_path_and_token_injection_rejected():
    transport = HostedTransport("https://relay.test", Session())
    for event_id in ["../other", "a?x", str(uuid4()).upper(), None]:
        with pytest.raises(TransportError): transport.acknowledge(event_id)
    for token in ["x\r\nOther:1", "", "x " ,None]:
        if token is not None:
            with pytest.raises(TransportError): transport.account(token)


def test_response_bounded():
    transport = HostedTransport("https://relay.test", Session())
    adapter = Adapter(b" " * 8_388_609)
    transport.http.mount("https://", adapter)
    with pytest.raises(TransportError): transport.events()


def test_only_explicit_valid_ca_path(tmp_path):
    for invalid in [False, True, "unsafe.pem", tmp_path / "absent"]:
        with pytest.raises(TransportError): HostedTransport("https://relay.test", Session(), ca_bundle=invalid)
    ca = tmp_path / "synthetic-ca.pem"
    ca.write_text("public synthetic fixture")
    assert HostedTransport("https://relay.test", Session(), ca_bundle=ca).verify == str(ca.resolve())


def test_blob_chunk_routes_are_signed_and_bounded():
    transport = HostedTransport("https://relay.test", Session())
    blob_id, raw = str(uuid4()), b"synthetic ciphertext" * 100
    adapter = Adapter(b'{"accepted":true,"duplicate":false}')
    transport.http.mount("https://", adapter)
    transport.upload_blob_chunk(blob_id, 639, raw)
    request = adapter.calls[-1][0]
    assert request.url.endswith("/v1/sealed/blobs/" + blob_id + "/chunks/639")
    assert "X-Orion-Signature" in request.headers and "Authorization" not in request.headers
    assert json.loads(request.body) == {"data": base64.b64encode(raw).decode()}
    for index in [-1, 640, True, None, "0"]:
        with pytest.raises(TransportError): transport.upload_blob_chunk(blob_id, index, raw)
        with pytest.raises(TransportError): transport.download_blob_chunk(blob_id, index)
    for data in [b"", b"x" * 32769, "bad", bytearray(b"x")]:
        with pytest.raises(TransportError): transport.upload_blob_chunk(blob_id, 0, data)
    assert len(adapter.calls) == 1
    adapter.body = json.dumps({"data": base64.b64encode(raw).decode()}).encode()
    assert transport.download_blob_chunk(blob_id, 0) == raw
    adapter.body = b'{"ready":true}'
    assert transport.complete_blob(blob_id) == {"ready": True}
    adapter.body = b'{"ok":true}'
    assert transport.delete_blob(blob_id) == {"ok": True}


@pytest.mark.parametrize("response", [{"data": ""}, {"data": "%%%"}, {"data": "eB=="},
    {"data": base64.b64encode(b"x" * 32769).decode()}, {"data": "eA==", "extra": 1}, {"data": None}])
def test_bad_ciphertext_response_rejected(response):
    transport = HostedTransport("https://relay.test", Session())
    adapter = Adapter(json.dumps(response).encode())
    transport.http.mount("https://", adapter)
    with pytest.raises(TransportError): transport.download_blob_chunk(str(uuid4()), 0)


def test_bad_blob_identifiers_never_become_request_paths():
    transport = HostedTransport("https://relay.test", Session())
    adapter = Adapter()
    transport.http.mount("https://", adapter)
    for blob_id in ["../other", "a?x", str(uuid4()).upper(), None, 7]:
        for operation in [transport.complete_blob, transport.delete_blob]:
            with pytest.raises(TransportError): operation(blob_id)
        with pytest.raises(TransportError): transport.download_blob_chunk(blob_id, 0)
    assert adapter.calls == []


def test_blob_allocation_requires_exact_local_approval():
    session = Session()
    target = "dev_" + uuid4().hex
    session.current = lambda: {session.device: {}, target: {}}
    session.roster, session.digest = {"version": 3}, "a" * 64
    transport = HostedTransport("https://relay.test", session)
    adapter = Adapter(b'{"accepted":true,"duplicate":false}')
    transport.http.mount("https://", adapter)
    descriptor = {"id": str(uuid4()), "target": target, "roster_version": 3, "roster_hash": session.digest,
                  "expires_at": int(time.time()) + 100, "size": 2, "sha256": "b" * 64}
    transport.allocate_blob(descriptor)
    for name, value in [("target", session.device), ("target", "other"), ("roster_version", 2),
                        ("roster_hash", "c" * 64), ("expires_at", 1), ("size", True), ("size", 20971521),
                        ("sha256", "wrong"), ("name", "private name")]:
        with pytest.raises(TransportError): transport.allocate_blob({**descriptor, name: value})
    assert len(adapter.calls) == 1


def test_roster_pages_have_bounded_explicit_continuation():
    transport = HostedTransport("https://relay.test", Session())
    adapter = Adapter(b'{"chain":[],"more":false}')
    transport.http.mount("https://", adapter)
    assert transport.roster_page("synthetic", after_version=129, after_hash="a" * 64, limit=7) == {"chain": [], "more": False}
    assert adapter.calls[0][0].url.endswith("after_version=129&limit=7&after_hash=" + "a" * 64)
    for values in [{"after_version": True}, {"after_version": 1}, {"after_version": 0, "after_hash": "a" * 64},
                   {"after_version": 2, "after_hash": "../x"}, {"limit": 17}, {"limit": 0}]:
        with pytest.raises(TransportError): transport.roster_page("synthetic", **values)
    assert len(adapter.calls) == 1
    for invalid in [{"chain": [], "more": True}, {"chain": [], "more": 1}, {"chain": [{}] * 17, "more": False}]:
        adapter.body = json.dumps(invalid).encode()
        with pytest.raises(TransportError): transport.roster_page("synthetic")


def test_refresh_roster_scheduling_never_grants_unsigned_authority():
    session = Session()
    progress, installed = [], []
    session.history_cursor = lambda: {"after_version": len(progress), "after_hash": "a" * 64 if progress else None}
    def accept(chain, *, final):
        # Real signatures/anchors are covered by test_hosted_history.
        progress.extend(chain)
        installed.append(final)
    session.accept_page = accept
    transport = HostedTransport("https://relay.test", session)
    adapter = Adapter(b'{"chain":[{}],"more":true}')
    transport.http.mount("https://", adapter)
    assert transport.refresh_roster("synthetic", max_pages=2) is False
    assert len(progress) == 2 and installed == [False, False]
    adapter.body = b'{"chain":[],"more":false}'
    assert transport.refresh_roster("synthetic") is True
    assert installed == [False, False, True]


def test_refresh_first_request_failure_clears_existing_authority():
    session = Session()
    session.active = True
    session.history_cursor = lambda: {"after_version": 2, "after_hash": "a" * 64}
    transport = HostedTransport("https://relay.test", session)
    transport.http.mount("https://", Adapter(status=503))
    with pytest.raises(TransportError): transport.refresh_roster("synthetic")
    assert session.active is False
