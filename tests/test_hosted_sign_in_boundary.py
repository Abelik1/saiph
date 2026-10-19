# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sign-in boundaries exercised with real offline cryptography."""
import base64
import time
from uuid import uuid4
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from orion_hub.hosted import stable
from orion_hub.hosted_auth import ServiceAuth0Config
from orion_hub.hosted_service import AccountRegistry, SharedHosted
from orion_hub.security import canonical
from orion_mini.hosted_runtime import HostedError
from orion_mini.hosted_login import TokenGrant


@pytest.fixture
def enrolled(tmp_path):
    from test_hosted_runtime import SyntheticProtection, CONFIG, workspace
    from orion_mini.hosted_runtime import HostedController
    from orion_mini.hosted_transport import HostedTransport, TransportError
    from orion_mini.hosted_session import SealedSession
    from orion_mini.hosted_crypto import generate_recipient
    from orion_mini.hosted_approval import trust_root_code, make_request_code

    identity = {'issuer': CONFIG['issuer'], 'subject': 'auth0|synthetic-review'}
    auth = ServiceAuth0Config(CONFIG['issuer'], CONFIG['audience'], (CONFIG['client_id'],))
    registry = AccountRegistry(tmp_path / 'server', auth)
    registry.admit(identity['subject'], expires_at=int(time.time()) + 3600)
    class Tokens:
        def principal(self, request):
            assert request.headers['authorization'] == 'Bearer synthetic-access'
            return identity
    client = TestClient(SharedHosted(registry, tokens=Tokens()))

    class OfflineTransport(HostedTransport):
        def _call(self, method, path, *, token=None, value=None):
            raw = stable(value) if value is not None else b''
            if token:
                headers = {'Authorization': 'Bearer ' + token}
            else:
                timestamp, nonce = str(int(time.time())), str(uuid4())
                signature = self.session.signing.sign(canonical(method, path, timestamp, nonce, raw), ec.ECDSA(hashes.SHA256()))
                headers = {'X-Orion-Device-Id': self.session.device, 'X-Orion-Timestamp': timestamp,
                           'X-Orion-Nonce': nonce, 'X-Orion-Signature': base64.b64encode(signature).decode()}
            response = client.request(method, path, headers=headers, content=raw)
            if response.status_code != 200:
                raise TransportError(response.status_code)
            return response.json()

    controller = HostedController(workspace(tmp_path / 'desktop'), protection=SyntheticProtection(), transport_factory=OfflineTransport)
    controller.transfers.background = False  # Tests run queued file sends with run_due().
    controller.lan_addresses = lambda: []  # Saiph Cloud only, whatever network the test machine is on.
    controller.configure(CONFIG)
    controller.set_enabled(True)
    controller._account()._accept(TokenGrant('synthetic-access', time.time() + 3600, None))
    root = trust_root_code(controller.setup_root()['code'], trusted_out_of_band=True)
    signing, encryption, device = ec.generate_private_key(ec.SECP256R1()), generate_recipient(), 'dev_' + uuid4().hex
    controller.approve(make_request_code(root, device, signing, encryption), 'Synthetic phone', True)
    phone = SealedSession(tmp_path / 'phone.sqlite3', root.deployment_id, root.signing_key, device, signing, encryption)
    phone.accept_chain(controller.transport.rosters('synthetic-access'))
    phone_transport = OfflineTransport(CONFIG['service_url'], phone)

    source = tmp_path / 'synthetic.txt'
    source.write_bytes(b'Synthetic attachment')
    yield controller, phone, phone_transport, device, source
    controller.stop()
    client.close()


def test_expiry_deactivates_session_and_clears_queued_actions(enrolled):
    controller, phone, transport, device, source = enrolled
    controller._offers['synthetic-offer'] = object()
    controller._outgoing_clipboard = 'Synthetic queued clipboard'
    old_session = controller.session
    controller.account._expires_at = time.time() - 1
    controller.step()
    assert controller.status == 'sign_in_required'
    assert controller.session is controller.transport is controller.mailbox is None
    assert controller._offers == {} and controller._outgoing_clipboard is None
    from orion_mini.hosted_session import EnvelopeError
    with pytest.raises(EnvelopeError):
        old_session.current()
    with pytest.raises(HostedError):
        controller.send_file(str(source), device)
    assert transport._call('GET', '/v1/sealed/events')['events'] == []


@pytest.mark.parametrize('action', ['send', 'save', 'dismiss'])
def test_action_checks_expiry_without_waiting_for_worker(enrolled, action):
    controller, phone, transport, device, source = enrolled
    controller.account._expires_at = time.time() - 1
    with pytest.raises(HostedError):
        if action == 'send':
            controller.send_file(str(source), device)
        elif action == 'save':
            controller.save_offer('synthetic-offer')
        else:
            controller.dismiss_notification('synthetic-notification')
    assert controller.session is None
    assert transport._call('GET', '/v1/sealed/events')['events'] == []


def test_expiry_during_encryption_removes_staged_ciphertext(enrolled, monkeypatch):
    from orion_mini import hosted_files
    controller, phone, transport, device, source = enrolled
    original = hosted_files.prepare_attachment
    def expire(*args, **kwargs):
        prepared = original(*args, **kwargs)
        controller.account._expires_at = time.time() - 1
        return prepared
    monkeypatch.setattr(hosted_files, 'prepare_attachment', expire)
    queued = controller.send_file(str(source), device)
    controller.transfers.run_due()
    [row] = [row for row in controller.transfers.snapshot() if row['id'] == queued['id']]
    assert row['state'] == 'failed' and 'Sign in' in row['error']
    assert list((controller.folder/'outgoing').iterdir()) == []
    assert transport._call('GET', '/v1/sealed/events')['events'] == []


def test_reauthentication_restores_real_encrypted_file_transfer(enrolled):
    import io
    from orion_mini.hosted_files import _manifest, DOMAIN, CHUNK_BYTES
    from orion_mini.hosted_crypto import canonical as encryption_context
    controller, phone, transport, device, source = enrolled
    controller.account._expires_at = time.time() - 1
    controller.step()
    controller.account._accept(TokenGrant('synthetic-access', time.time()+3600, None))
    controller.step()
    queued = controller.send_file(str(source), device)
    assert queued['queued'] and queued['name'] == source.name
    assert controller.transfers.run_due() is None
    assert [row['state'] for row in controller.transfers.snapshot()] == ['sent']
    envelope = transport._call('GET', '/v1/sealed/events')['events'][0]
    payload, primitive = _manifest(phone, envelope)
    ciphertext = b''.join(transport.download_blob_chunk(payload['blob']['id'], index)
                          for index in range((payload['ciphertext_size']+CHUNK_BYTES-1)//CHUNK_BYTES))
    with primitive.new_decrypting_stream(io.BytesIO(ciphertext), DOMAIN+encryption_context(payload['blob'])) as decrypted:
        assert decrypted.read() == source.read_bytes()
