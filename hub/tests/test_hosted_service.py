# SPDX-License-Identifier: AGPL-3.0-or-later
"""Two real JWT identities, root approvals, encrypted mailboxes and hostile access."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import time
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient

from orion_hub.hosted import stable
from orion_hub.hosted_auth import AccessTokens, ServiceAuth0Config
from orion_hub.hosted_service import AccountRegistry, SharedHosted
from orion_hub.hosted_service_server import configuration
from orion_hub.security import canonical
from orion_mini.hosted_crypto import generate_recipient
from orion_mini.hosted_session import SealedSession, enrollment, public_signing_key, sign_roster


def signed(device, path, method='GET', value=None, *, nonce=None):
    raw = stable(value) if value is not None else b''
    timestamp, nonce = str(int(time.time())), nonce or str(uuid4())
    proof = device['sign'].sign(canonical(method, path, timestamp, nonce, raw), ec.ECDSA(hashes.SHA256()))
    return {'X-Orion-Device-Id': device['id'], 'X-Orion-Timestamp': timestamp,
            'X-Orion-Nonce': nonce, 'X-Orion-Signature': base64.b64encode(proof).decode()}


def send(client, device, method, path, value=None, **kwargs):
    return client.request(method, path, headers=signed(device, path, method, value),
                          content=stable(value) if value is not None else None, **kwargs)


@pytest.fixture
def service(tmp_path):
    auth = ServiceAuth0Config('https://synthetic.eu.auth0.com/', 'https://saiph.example.test/api', ('desktop', 'android'))
    authority = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tokens = AccessTokens(auth, key_resolver=lambda kid: authority.public_key())
    registry = AccountRegistry(tmp_path / 'shared', auth)
    app = SharedHosted(registry, tokens=tokens, cache_size=1)
    client = TestClient(app)

    def token(subject, **overrides):
        claims = dict(iss=auth.issuer, aud=auth.audience, azp='desktop', sub=subject,
                      iat=int(time.time()), exp=int(time.time()) + 300)
        claims.update(overrides)
        return {'Authorization': 'Bearer ' + jwt.encode(claims, authority, algorithm='RS256', headers={'kid': 'synthetic'})}

    def account(subject):
        deployment = registry.admit(subject, expires_at=int(time.time()) + 3600)
        headers = token(subject)
        assert client.get('/v1/account', headers=headers).json()['deployment_id'] == deployment
        devices, members, entries = [], [], []
        for _ in range(2):
            device = dict(id='dev_' + uuid4().hex, sign=ec.generate_private_key(ec.SECP256R1()), enc=generate_recipient())
            value = enrollment(deployment, device['id'], device['sign'], device['enc'])
            assert client.post('/v1/devices/requests', headers=headers, json=value).status_code == 200
            devices.append(device)
            members.append(value['device'])
            roster = dict(deployment_id=deployment, version=len(entries) + 1,
                          previous_hash=hashlib.sha256(stable(entries[-1]['roster'])).hexdigest() if entries else None,
                          expires_at=int(time.time()) + 3600, members=sorted(members, key=lambda m: m['id']))
            proposal = sign_roster(roster, devices[0]['sign'])
            response = client.post('/v1/devices/rosters', headers=headers, json=proposal)
            assert response.status_code == 200, response.text
            entries.append(proposal)
        pin = public_signing_key(devices[0]['sign'].public_key())
        for device in devices:
            device['session'] = SealedSession(tmp_path / (device['id'] + '.sqlite3'), deployment, pin,
                                             device['id'], device['sign'], device['enc'])
            device['session'].accept_chain(entries)
        return dict(id=deployment, headers=headers, devices=devices, entries=entries)

    return dict(auth=auth, registry=registry, app=app, client=client, token=token,
                accounts=[account('auth0|alice'), account('auth0|bob')], tokens=tokens, authority=authority)


def test_one_origin_isolates_tokens_rosters_and_encrypted_content(service):
    client = service['client']
    alice, bob = service['accounts']
    assert alice['id'] != bob['id']
    for own, other in ((alice, bob), (bob, alice)):
        response = client.get('/v1/devices/rosters', headers=own['headers'])
        assert response.json()['chain'] == own['entries']
        # Knowing another account's deployment ID never selects its workspace.
        response = client.post('/v1/devices/rosters', headers=own['headers'], json=other['entries'][-1])
        assert response.status_code in (400, 409)
        source, target = own['devices']
        envelope = source['session'].encrypt(target['id'], {'text': 'synthetic ' + own['id']})
        assert send(client, source, 'POST', '/v1/sealed/events', envelope).status_code == 200
        events = send(client, target, 'GET', '/v1/sealed/events').json()['events']
        assert len(events) == 1 and events[0]['header']['deployment_id'] == own['id']
        assert target['session'].receive(events[0])['text'] == 'synthetic ' + own['id']
        foreign_events = send(client, other['devices'][1], 'GET', '/v1/sealed/events').json()['events']
        assert all(e['header']['deployment_id'] == other['id'] for e in foreign_events)
        assert client.get('/v1/sealed/events', headers=own['headers']).status_code == 403


@pytest.mark.parametrize('claim,value', [('iss', 'https://wrong.example.test/'), ('aud', 'wrong'),
    ('azp', 'web-client'), ('exp', 1), ('sub', ''), ('sub', 'x' * 257)])
def test_invalid_provider_claims_cannot_reach_any_workspace(service, claim, value):
    response = service['client'].get('/v1/account', headers=service['token']('auth0|alice', **{claim: value}))
    assert response.status_code == 401


def test_unknown_login_and_signed_id_spoofing_do_not_create_accounts(service):
    client = service['client']
    assert client.get('/v1/account', headers=service['token']('auth0|uninvited')).status_code == 403
    alice, bob = service['accounts']
    headers = signed(alice['devices'][1], '/v1/sealed/events')
    headers['X-Orion-Device-Id'] = bob['devices'][1]['id']
    assert client.get('/v1/sealed/events', headers=headers).status_code == 403
    with service['registry'].connect() as db:
        assert db.execute('SELECT count(*) FROM accounts').fetchone()[0] == 2


def test_duplicate_device_cannot_be_admitted_into_another_account(service):
    client = service['client']
    alice, bob = service['accounts']
    device = alice['devices'][1]
    candidate = enrollment(bob['id'], device['id'], device['sign'], device['enc'])
    assert client.post('/v1/devices/requests', headers=bob['headers'], json=candidate).status_code == 200
    head = bob['entries'][-1]['roster']
    roster = {**head, 'version': head['version'] + 1, 'previous_hash': hashlib.sha256(stable(head)).hexdigest(),
              'members': sorted(head['members'] + [candidate['device']], key=lambda m: m['id'])}
    response = client.post('/v1/devices/rosters', headers=bob['headers'], json=sign_roster(roster, bob['devices'][0]['sign']))
    assert response.status_code == 409
    assert client.get('/v1/devices/rosters', headers=bob['headers']).json()['chain'] == bob['entries']
    assert service['registry'].device(device['id'])['id'] == alice['id']


def test_ciphertext_blob_ids_are_scoped_to_account(service):
    client = service['client']
    identifier = str(uuid4())
    for index, own in enumerate(service['accounts']):
        source, target = own['devices']
        raw = ('synthetic ciphertext ' + str(index)).encode()
        descriptor = dict(id=identifier, target=target['id'], roster_version=2,
                          roster_hash=hashlib.sha256(stable(own['entries'][-1]['roster'])).hexdigest(),
                          expires_at=int(time.time()) + 200, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        assert send(client, source, 'POST', '/v1/sealed/blobs', descriptor).status_code == 200
        chunk = '/v1/sealed/blobs/' + identifier + '/chunks/0'
        assert send(client, source, 'POST', chunk, {'data': base64.b64encode(raw).decode()}).status_code == 200
        assert send(client, source, 'POST', '/v1/sealed/blobs/' + identifier + '/complete', {}).status_code == 200
        assert base64.b64decode(send(client, target, 'GET', chunk).json()['data']) == raw
    # Reading the colliding blob as Alice still yields Alice's bytes.
    alice = service['accounts'][0]
    response = send(client, alice['devices'][1], 'GET', '/v1/sealed/blobs/' + identifier + '/chunks/0')
    assert base64.b64decode(response.json()['data']) == b'synthetic ciphertext 0'


def test_suspend_blocks_token_and_device_routes_without_affecting_other_account(service):
    alice, bob = service['accounts']
    registry, client = service['registry'], service['client']
    registry.set_active(alice['id'], False)
    assert client.get('/v1/account', headers=alice['headers']).status_code == 403
    assert send(client, alice['devices'][1], 'GET', '/v1/sealed/events').status_code == 403
    assert client.get('/v1/account', headers=bob['headers']).status_code == 200
    assert send(client, bob['devices'][1], 'GET', '/v1/sealed/events').status_code == 200
    registry.set_active(alice['id'], True)
    assert send(client, alice['devices'][1], 'GET', '/v1/sealed/events').status_code == 200


def test_registry_restart_and_concurrent_admission_preserve_identity(service):
    registry = AccountRegistry(service['registry'].directory, service['auth'])
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda subject: registry.admit(subject, expires_at=int(time.time()) + 3600), ['auth0|alice'] * 8))
    assert set(ids) == {service['accounts'][0]['id']}
    client = TestClient(SharedHosted(registry, tokens=service['tokens']))
    assert client.get('/v1/account', headers=service['accounts'][0]['headers']).json()['deployment_id'] == ids[0]
    assert send(client, service['accounts'][0]['devices'][1], 'GET', '/v1/sealed/events').status_code == 200
    changed = ServiceAuth0Config(service['auth'].issuer, 'other-audience', service['auth'].client_ids)
    with pytest.raises(ValueError):
        AccountRegistry(registry.directory, changed)


def test_shared_runner_is_separately_disabled_and_loopback_state_is_required(tmp_path):
    env = dict(ORION_HOSTED_SHARED='1', ORION_AUTH0_ISSUER='https://synthetic.eu.auth0.com/',
               ORION_AUTH0_AUDIENCE='synthetic-api', ORION_AUTH0_NATIVE_CLIENT_IDS='desktop,android',
               ORION_HOSTED_STATE=str(tmp_path))
    assert configuration(env)[0] == tmp_path
    for key in env:
        with pytest.raises(ValueError):
            configuration({k: v for k, v in env.items() if k != key})


def identity(service, subject='auth0|friend'):
    return dict(issuer=service['auth'].issuer, subject=subject)


def test_beta_code_single_use_hash_only_restart_and_idempotent_retry(service):
    registry = service['registry']
    until = int(time.time()) + 1800
    code = registry.issue_code(until)
    digest = hashlib.sha256(code.encode()).hexdigest()
    assert code.startswith('SAIPH-') and len(code) == 38
    with registry.connect() as db:
        assert db.execute('SELECT digest FROM beta_codes').fetchone()[0] == digest
    assert code.encode() not in registry.path.read_bytes()
    restarted = AccountRegistry(registry.directory, service['auth'])
    assert restarted.redeem(identity(service), code) == {'entitled': True, 'until': until}
    assert restarted.redeem(identity(service), code)['entitled']
    with pytest.raises(HTTPException) as error:
        restarted.redeem(identity(service, 'auth0|thief'), code)
    assert error.value.status_code == 403
    with registry.connect() as db:
        assert db.execute('SELECT count(*) FROM accounts').fetchone()[0] == 3
    client = service['client']
    assert client.get('/v1/account', headers=service['token']('auth0|friend')).status_code == 200
    assert client.get('/v1/account', headers=service['token']('auth0|thief')).status_code == 403


def test_concurrent_redemption_has_one_owner(service):
    registry = service['registry']
    code = registry.issue_code(int(time.time()) + 1800)
    def attempt(subject):
        try:
            registry.redeem(identity(service, subject), code)
            return subject
        except HTTPException as error:
            assert error.status_code == 403
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, ['auth0|racer' + str(i) for i in range(4)]))
    assert sum(result is not None for result in results) == 1
    with registry.connect() as db:
        assert db.execute('SELECT count(*) FROM accounts').fetchone()[0] == 3


@pytest.mark.parametrize('cause', ['expiry', 'revocation'])
def test_entitlement_removal_blocks_cached_account_and_device_routes(service, cause):
    registry, client = service['registry'], service['client']
    alice, bob = service['accounts']
    code = registry.issue_code(int(time.time()) + 1800)
    registry.redeem(identity(service, 'auth0|alice'), code)
    # Remove Alice's synthetic administrative grant so beta access is the only grant.
    with registry.connect() as db:
        db.execute("DELETE FROM access_grants WHERE account=? AND kind='admin'", (alice['id'],))
    assert send(client, alice['devices'][1], 'GET', '/v1/sealed/events').status_code == 200
    if cause == 'revocation':
        registry.revoke_code(hashlib.sha256(code.encode()).hexdigest())
    else:
        with registry.connect() as db:
            db.execute('UPDATE access_grants SET expires_at=1 WHERE account=?', (alice['id'],))
            db.execute('UPDATE beta_codes SET expires_at=1')
    assert registry.status(identity(service, 'auth0|alice')) == {'entitled': False, 'until': None}
    assert client.get('/v1/account', headers=alice['headers']).status_code == 403
    assert send(client, alice['devices'][1], 'GET', '/v1/sealed/events').status_code == 403
    assert client.get('/v1/account', headers=bob['headers']).status_code == 200
    with pytest.raises(HTTPException):
        registry.claim_devices(alice['id'], ['dev_' + uuid4().hex])
    with pytest.raises(HTTPException):
        registry.redeem(identity(service, 'auth0|alice'), code)


@pytest.mark.parametrize('cause', ['invalid', 'expired', 'revoked', 'suspended'])
def test_failed_code_cannot_create_or_reactivate_account(service, cause):
    registry = service['registry']
    code = registry.issue_code(int(time.time()) + 1800)
    who = identity(service)
    if cause == 'invalid':
        code = 'SAIPH-' + 'x' * 32
    elif cause == 'expired':
        with registry.connect() as db:
            db.execute('UPDATE beta_codes SET expires_at=1')
    elif cause == 'revoked':
        registry.revoke_code(hashlib.sha256(code.encode()).hexdigest())
    else:
        who = identity(service, 'auth0|alice')
        registry.set_active(service['accounts'][0]['id'], False)
    with pytest.raises(HTTPException) as error:
        registry.redeem(who, code)
    assert error.value.status_code == 403
    with registry.connect() as db:
        assert db.execute('SELECT count(*) FROM accounts').fetchone()[0] == 2
        assert db.execute('SELECT redeemed_by FROM beta_codes').fetchone()[0] is None


def test_beta_bruteforce_accounting_commits_failures_and_expires(service):
    registry = service['registry']
    for _ in range(5):
        with pytest.raises(HTTPException) as error:
            registry.redeem(identity(service), 'bad')
        assert error.value.status_code == 403
    code = registry.issue_code(int(time.time()) + 1800)
    with pytest.raises(HTTPException) as error:
        registry.redeem(identity(service), code)
    assert error.value.status_code == 429
    with registry.connect() as db:
        assert db.execute('SELECT count(*) FROM beta_attempts').fetchone()[0] == 5
        db.execute('UPDATE beta_attempts SET attempted_at=1')
    assert registry.redeem(identity(service), code)['entitled']
    with registry.connect() as db:
        db.executemany('INSERT INTO beta_attempts VALUES(?,?)', [('synthetic', int(time.time()))] * 999)
    with pytest.raises(HTTPException) as error:
        registry.redeem(identity(service, 'auth0|other'), code)
    assert error.value.status_code == 429


def test_other_accounts_failures_cannot_lock_out_a_valid_code(service):
    registry = service['registry']
    with registry.connect() as db:
        db.executemany('INSERT INTO beta_attempts VALUES(?,?)',
                       [(f'synthetic-{n}', int(time.time())) for n in range(1000)])
    with pytest.raises(HTTPException) as error:
        registry.redeem(identity(service, 'auth0|guesser'), 'SAIPH-' + 'A' * 32)
    assert error.value.status_code == 429
    code = registry.issue_code(int(time.time()) + 1800)
    assert registry.redeem(identity(service, 'auth0|friend'), code)['entitled']
    for _ in range(4):
        with pytest.raises(HTTPException):
            registry.redeem(identity(service, 'auth0|guesser'), 'SAIPH-' + 'A' * 32)
    with pytest.raises(HTTPException) as error:
        registry.redeem(identity(service, 'auth0|guesser'), registry.issue_code(int(time.time()) + 1800))
    assert error.value.status_code == 429


def test_web_redemption_and_native_device_authorization_stay_separate(service):
    auth = service['auth']
    web_tokens = AccessTokens(ServiceAuth0Config(auth.issuer, auth.audience, ('web-client',)),
                              key_resolver=lambda kid: service['authority'].public_key())
    app = SharedHosted(service['registry'], tokens=service['tokens'], web_tokens=web_tokens)
    client = TestClient(app)
    headers = service['token']('auth0|friend', azp='web-client')
    code = service['registry'].issue_code(int(time.time()) + 1800)
    assert client.get('/v1/beta/access', headers=headers).json() == {'entitled': False, 'until': None}
    assert client.post('/v1/beta/redeem', headers=headers, json={'code':code}).status_code == 200
    assert client.get('/v1/beta/access', headers=headers).json()['entitled']
    assert client.post('/v1/beta/redeem', headers={**headers, 'Origin':'https://evil.test'}, json={'code':code}).status_code == 403
    assert client.post('/v1/beta/redeem', headers=headers, json={'code':code, 'subject':'auth0|bob'}).status_code == 400
    assert client.get('/v1/beta/access?subject=auth0|bob', headers=headers).status_code == 403
    assert client.get('/v1/beta/redeem', headers=headers).status_code == 405
    assert service['client'].get('/v1/beta/access', headers=headers).status_code == 404
    assert client.get('/v1/beta/access', headers=service['token']('auth0|friend')).status_code == 401
    assert client.get('/v1/account', headers=service['token']('auth0|friend', azp='web-client')).status_code == 401


@pytest.mark.parametrize('until', [1, True, 'tomorrow', 2**53])
def test_invitation_requires_bounded_expiry(service, until):
    with pytest.raises(ValueError):
        service['registry'].issue_code(until)
