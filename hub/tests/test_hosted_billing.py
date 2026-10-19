# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signed paid-grant pushes from the account website (docs/PAID_HOSTED.md)."""
import base64
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import HTTPException
from fastapi.testclient import TestClient

from orion_hub.hosted_auth import AccessTokens, ServiceAuth0Config
from orion_hub.hosted_billing import CONTEXT, HORIZON, BillingGrants
from orion_hub.hosted_service import AccountRegistry, SharedHosted

ISSUER = 'https://synthetic.eu.auth0.com/'


def b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def public(key):
    return b64url(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


@pytest.fixture
def hosted(tmp_path):
    auth = ServiceAuth0Config(ISSUER, 'https://saiph.example.test/api', ('desktop', 'android'))
    authority = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    resolver = dict(key_resolver=lambda kid: authority.public_key())
    tokens = AccessTokens(auth, **resolver)
    web_tokens = AccessTokens(ServiceAuth0Config(auth.issuer, auth.audience, ('website',)), **resolver)
    signer = Ed25519PrivateKey.generate()
    billing = BillingGrants('sandbox', {'test-1': public(signer)})
    registry = AccountRegistry(tmp_path / 'shared', auth)
    client = TestClient(SharedHosted(registry, tokens=tokens, web_tokens=web_tokens, billing=billing, cache_size=1))

    def token(subject, azp='desktop'):
        claims = dict(iss=ISSUER, aud=auth.audience, azp=azp, sub=subject, iat=int(time.time()), exp=int(time.time()) + 300)
        return {'Authorization': 'Bearer ' + jwt.encode(claims, authority, algorithm='RS256', headers={'kid': 'synthetic'})}

    def push(subject='auth0|payer', grant='stripe:sub_alpha', until=None, sequence=1, *, key=signer, key_id='test-1',
             livemode=False, timestamp=None, extra=None, headers=None, raw=None, tamper=None):
        value = dict(issuer=ISSUER, subject=subject, grant=grant,
                     until=int(time.time()) + 30 * 86400 if until is None else until, sequence=sequence, livemode=livemode)
        value.update(extra or {})
        body = raw if raw is not None else json.dumps(value, separators=(',', ':')).encode()
        t = str(int(time.time()) if timestamp is None else timestamp)
        signature = b64url(key.sign(CONTEXT + t.encode() + b'.' + body))
        sent = {'Saiph-Billing-Signature': f't={t},k={key_id},v1={signature}', 'Content-Type': 'application/json'}
        sent.update(headers or {})
        return client.post('/v1/billing/grant', content=tamper if tamper is not None else body, headers=sent)

    def access(subject='auth0|payer'):
        return client.get('/v1/billing/access', headers=token(subject, 'website')).json()

    return dict(registry=registry, client=client, token=token, push=push, access=access, signer=signer)


def test_signed_push_grants_access_like_a_beta_code(hosted):
    assert hosted['client'].get('/v1/account', headers=hosted['token']('auth0|payer')).status_code == 403
    until = int(time.time()) + 30 * 86400
    response = hosted['push'](until=until)
    assert response.status_code == 200 and response.json() == {'applied': True}
    assert hosted['access']() == {'entitled': True, 'until': until, 'kinds': ['paid']}
    # The unchanged beta status endpoint reports paid access with its existing shape.
    beta = hosted['client'].get('/v1/beta/access', headers=hosted['token']('auth0|payer', 'website')).json()
    assert beta == {'entitled': True, 'until': until}
    assert hosted['client'].get('/v1/account', headers=hosted['token']('auth0|payer')).status_code == 200
    account = hosted['registry'].principal({'issuer': ISSUER, 'subject': 'auth0|payer'})
    hosted['registry'].claim_devices(account['id'], ['dev_' + 'a' * 32])
    assert hosted['registry'].device('dev_' + 'a' * 32)['id'] == account['id']


def test_ending_paid_access_blocks_bearer_and_device_routes(hosted):
    hosted['push'](sequence=1)
    account = hosted['registry'].principal({'issuer': ISSUER, 'subject': 'auth0|payer'})
    hosted['registry'].claim_devices(account['id'], ['dev_' + 'b' * 32])
    assert hosted['push'](until=0, sequence=2).json() == {'applied': True}
    assert hosted['access']() == {'entitled': False, 'until': None, 'kinds': []}
    assert hosted['client'].get('/v1/account', headers=hosted['token']('auth0|payer')).status_code == 403
    with pytest.raises(HTTPException) as denied:
        hosted['registry'].device('dev_' + 'b' * 32)
    assert denied.value.status_code == 403
    # A later renewal (higher sequence) restores access without a new account.
    assert hosted['push'](sequence=3).json() == {'applied': True}
    assert hosted['registry'].principal({'issuer': ISSUER, 'subject': 'auth0|payer'})['id'] == account['id']


def test_beta_and_paid_grants_are_independent(hosted):
    registry = hosted['registry']
    code = registry.issue_code(int(time.time()) + 7 * 86400)
    identity = {'issuer': ISSUER, 'subject': 'auth0|payer'}
    registry.redeem(identity, code)
    hosted['push'](sequence=1)
    assert hosted['access']()['kinds'] == ['beta', 'paid']
    hosted['push'](until=0, sequence=2)
    assert hosted['access']()['kinds'] == ['beta'], 'ending paid access leaves the beta grant'
    hosted['push'](sequence=3)
    import hashlib
    registry.revoke_code(hashlib.sha256(code.encode()).hexdigest())
    assert hosted['access']()['kinds'] == ['paid'], 'revoking a beta code leaves paid access'


def test_duplicates_and_out_of_order_pushes_cannot_undo_newer_state(hosted):
    later = int(time.time()) + 20 * 86400
    assert hosted['push'](until=0, sequence=5).json() == {'applied': True}
    assert hosted['push'](until=later, sequence=4).json() == {'applied': False}, 'late older push ignored'
    assert hosted['push'](until=later, sequence=5).json() == {'applied': False}, 'same sequence ignored'
    assert hosted['access']()['entitled'] is False
    assert hosted['push'](until=later, sequence=6).json() == {'applied': True}
    assert hosted['access']()['until'] == later


def test_subscription_stays_bound_to_its_first_account(hosted):
    hosted['push'](subject='auth0|payer', sequence=1)
    assert hosted['push'](subject='auth0|intruder', sequence=2).status_code == 409
    assert hosted['access']('auth0|intruder')['entitled'] is False
    assert hosted['access']('auth0|payer')['entitled'] is True


def test_suspension_overrides_paid_access(hosted):
    hosted['push'](sequence=1)
    account = hosted['registry'].principal({'issuer': ISSUER, 'subject': 'auth0|payer'})
    hosted['registry'].set_active(account['id'], False)
    assert hosted['push'](sequence=2).json() == {'applied': True}, 'grant recorded, account stays suspended'
    assert hosted['client'].get('/v1/account', headers=hosted['token']('auth0|payer')).status_code == 403
    assert hosted['access']()['entitled'] is False
    grants = hosted['registry'].grants(account['id'])
    assert grants['active'] is False and [g['kind'] for g in grants['grants']] == ['paid']


@pytest.mark.parametrize('case', [
    'unknown_key', 'wrong_key', 'stale', 'future', 'tampered', 'extra_field', 'beyond_horizon', 'livemode',
    'bad_grant', 'negative_until', 'zero_sequence', 'float_until', 'duplicate_key', 'wrong_issuer', 'oversized',
])
def test_rejected_pushes_change_nothing(hosted, case):
    push, now = hosted['push'], int(time.time())
    response = {
        'unknown_key': lambda: push(key_id='test-2'),
        'wrong_key': lambda: push(key=Ed25519PrivateKey.generate()),
        'stale': lambda: push(timestamp=now - 301),
        'future': lambda: push(timestamp=now + 301),
        'tampered': lambda: push(tamper=json.dumps(dict(issuer=ISSUER, subject='auth0|payer', grant='stripe:sub_alpha',
                                                         until=now + 40 * 86400, sequence=1, livemode=False)).encode()),
        'extra_field': lambda: push(extra={'admin': True}),
        'beyond_horizon': lambda: push(until=now + HORIZON + 60),
        'livemode': lambda: push(livemode=True),
        'bad_grant': lambda: push(grant='beta:abc'),
        'negative_until': lambda: push(until=-1),
        'zero_sequence': lambda: push(sequence=0),
        'float_until': lambda: push(raw=json.dumps(dict(issuer=ISSUER, subject='auth0|payer', grant='stripe:sub_alpha',
                                                        until=1.5, sequence=1, livemode=False)).encode()),
        'duplicate_key': lambda: push(raw=('{"issuer":"%s","subject":"auth0|payer","subject":"auth0|other","grant":"stripe:sub_alpha",'
                                           '"until":%d,"sequence":1,"livemode":false}' % (ISSUER, now + 60)).encode()),
        'wrong_issuer': lambda: push(raw=json.dumps(dict(issuer='https://other.auth0.com/', subject='auth0|payer',
                                                         grant='stripe:sub_alpha', until=now + 60, sequence=1, livemode=False)).encode()),
        'oversized': lambda: push(subject='auth0|' + 'x' * 2100),
    }[case]
    result = response()
    assert result.status_code in (400, 401, 403, 413), (case, result.status_code)
    assert hosted['access']()['entitled'] is False, case


@pytest.mark.parametrize('headers', [
    {'Origin': 'https://account.saiph.test'}, {'Cookie': 'session=1'}, {'Authorization': 'Bearer x'},
])
def test_browser_style_requests_are_refused(hosted, headers):
    assert hosted['push'](headers=headers).status_code == 403
    assert hosted['access']()['entitled'] is False


def test_query_string_and_methods_are_refused(hosted):
    client = hosted['client']
    assert client.get('/v1/billing/grant').status_code == 404
    signed = hosted['push']().request
    assert client.post('/v1/billing/grant?x=1', content=signed.content, headers=dict(signed.headers)).status_code == 403


def test_endpoint_absent_without_billing_configuration(tmp_path):
    auth = ServiceAuth0Config(ISSUER, 'https://saiph.example.test/api', ('desktop',))
    client = TestClient(SharedHosted(AccountRegistry(tmp_path / 'shared', auth), cache_size=1))
    assert client.post('/v1/billing/grant', content=b'{}', headers={'Saiph-Billing-Signature': 't=1,k=a,v1=a'}).status_code == 404


def test_native_tokens_cannot_read_billing_access(hosted):
    hosted['push']()
    response = hosted['client'].get('/v1/billing/access', headers=hosted['token']('auth0|payer', 'desktop'))
    assert response.status_code == 401


def test_environment_configuration_needs_both_values():
    key = public(Ed25519PrivateKey.generate())
    assert BillingGrants.from_environment({}) is None
    grants = BillingGrants.from_environment({'ORION_BILLING_GRANTS': 'live', 'ORION_BILLING_GRANT_KEYS': 'live-1:' + key})
    assert grants.livemode is True and set(grants.keys) == {'live-1'}
    for env in ({'ORION_BILLING_GRANTS': 'sandbox'}, {'ORION_BILLING_GRANT_KEYS': 'a:' + key},
                {'ORION_BILLING_GRANTS': 'prod', 'ORION_BILLING_GRANT_KEYS': 'a:' + key},
                {'ORION_BILLING_GRANTS': 'sandbox', 'ORION_BILLING_GRANT_KEYS': 'a:' + key + ',a:' + key},
                {'ORION_BILLING_GRANTS': 'sandbox', 'ORION_BILLING_GRANT_KEYS': 'a:short'},
                {'ORION_BILLING_GRANTS': 'sandbox', 'ORION_BILLING_GRANT_KEYS': 'Bad_ID:' + key}):
        with pytest.raises(ValueError):
            BillingGrants.from_environment(env)


def test_signature_made_by_the_account_website_verifies():
    # Synthetic vector produced by Node's crypto.sign (Ed25519) in the website's
    # format; mirrored in account-web/tests/billing-grant.test.mjs. Public key only.
    grants = BillingGrants('sandbox', {'vector': '6CcCelNP-UKWH3Wu9MYqSrEKEUHWx9i_N5VsLGNA4Ko'})
    body = (b'{"issuer":"https://synthetic.eu.auth0.com/","subject":"auth0|vector","grant":"stripe:sub_vector1",'
            b'"until":1800003600,"sequence":7,"livemode":false}')
    header = 't=1800000000,k=vector,v1=0MvIjdn3EDTLi0yD1awAFg6GHZI1-G5EY0nmv9h75DP9NJg4q6KwU6L_Cfgq2ZrYlURT8R5sjddttb1UY2jDAg'
    value = grants.verify(header, body, now=1800000000)
    assert value['grant'] == 'stripe:sub_vector1' and value['sequence'] == 7
    with pytest.raises(HTTPException):
        grants.verify(header, body.replace(b'"sequence":7', b'"sequence":8'), now=1800000000)


TRIAL = 'trial:' + 'a' * 32


def test_trial_grant_admits_like_a_subscription_and_reports_its_end(hosted):
    end = int(time.time()) + 14 * 86400
    assert hosted['push'](grant=TRIAL, until=end).json() == {'applied': True}
    assert hosted['access']() == {'entitled': True, 'until': end, 'kinds': ['trial'], 'trial_until': end}
    assert hosted['client'].get('/v1/account', headers=hosted['token']('auth0|payer')).status_code == 200
    account = hosted['registry'].principal({'issuer': ISSUER, 'subject': 'auth0|payer'})
    hosted['registry'].claim_devices(account['id'], ['dev_' + 'c' * 32])
    assert hosted['registry'].device('dev_' + 'c' * 32)['id'] == account['id']
    assert [g['kind'] for g in hosted['registry'].grants(account['id'])['grants']] == ['trial']


def test_trial_expiry_blocks_access_without_deleting_anything_and_a_subscription_restores_it(hosted):
    registry, now = hosted['registry'], int(time.time())
    hosted['push'](grant=TRIAL, until=now + 14 * 86400)
    account = registry.principal({'issuer': ISSUER, 'subject': 'auth0|payer'})
    registry.claim_devices(account['id'], ['dev_' + 'd' * 32])
    assert hosted['client'].get('/v1/account', headers=hosted['token']('auth0|payer')).status_code == 200
    workspace = registry.config(account).database
    # Fourteen days pass (the stored end moves into the past): the trial runs out
    # by itself, with no push from the website.
    end = now - 60
    with registry.connect() as db:
        db.execute("UPDATE access_grants SET expires_at=? WHERE kind='trial'", (end,))
    assert hosted['client'].get('/v1/account', headers=hosted['token']('auth0|payer')).status_code == 403
    with pytest.raises(HTTPException) as denied:
        registry.device('dev_' + 'd' * 32)
    assert denied.value.status_code == 403
    assert hosted['access']() == {'entitled': False, 'until': None, 'kinds': [], 'trial_until': end}
    # Non-destructive: the account, its device binding and workspace are kept.
    assert workspace.is_file()
    with registry.connect() as db:
        assert db.execute('SELECT account FROM devices WHERE id=?', ('dev_' + 'd' * 32,)).fetchone()[0] == account['id']
    # Subscribing pushes a paid grant; the same account and devices work again.
    assert hosted['push'](sequence=2).json() == {'applied': True}
    assert registry.principal({'issuer': ISSUER, 'subject': 'auth0|payer'})['id'] == account['id']
    assert registry.device('dev_' + 'd' * 32)['id'] == account['id']
    assert hosted['access']()['kinds'] == ['paid'] and hosted['access']()['trial_until'] == end


def test_one_trial_per_account_and_a_trial_stays_with_its_first_account(hosted):
    hosted['push'](grant=TRIAL, sequence=1)
    assert hosted['push'](grant='trial:' + 'b' * 32, sequence=2).status_code == 409, 'a second trial for the same account'
    assert hosted['access']()['kinds'] == ['trial']
    assert hosted['push'](subject='auth0|other', grant=TRIAL, sequence=3).status_code == 409, 'the same trial for another account'
    assert hosted['access']('auth0|other')['entitled'] is False
    # The website may still end or re-deliver its own trial.
    assert hosted['push'](grant=TRIAL, until=0, sequence=4).json() == {'applied': True}
    assert hosted['access']() == {'entitled': False, 'until': None, 'kinds': []}, 'an ended (0) trial has no end date to show'


def test_trial_pushes_are_limited_to_thirty_days_and_a_strict_reference(hosted):
    now = int(time.time())
    for grant, until in ((TRIAL, now + 32 * 86400), ('trial:' + 'A' * 32, now + 86400), ('trial:' + 'a' * 31, now + 86400),
                         ('trial:auth0|payer', now + 86400)):
        assert hosted['push'](grant=grant, until=until).status_code == 400, grant
    assert hosted['access']()['entitled'] is False
    assert hosted['push'](grant=TRIAL, until=now + 30 * 86400).status_code == 200


def test_accounts_without_a_trial_keep_the_original_access_shape(hosted):
    hosted['push']()
    assert set(hosted['access']()) == {'entitled', 'until', 'kinds'}
    code = hosted['registry'].issue_code(int(time.time()) + 86400)
    hosted['registry'].redeem({'issuer': ISSUER, 'subject': 'auth0|tester'}, code)
    assert set(hosted['access']('auth0|tester')) == {'entitled', 'until', 'kinds'}


def test_apps_read_their_own_access_with_native_tokens_even_without_a_grant(hosted):
    client, token = hosted['client'], hosted['token']
    assert client.get('/v1/access', headers=token('auth0|newcomer')).json() == {'entitled': False, 'until': None, 'kinds': []}
    end = int(time.time()) + 3 * 86400
    hosted['push'](subject='auth0|newcomer', grant=TRIAL, until=end)
    assert client.get('/v1/access', headers=token('auth0|newcomer', 'android')).json() == {
        'entitled': True, 'until': end, 'kinds': ['trial'], 'trial_until': end}
    assert client.get('/v1/access').status_code == 401
    assert client.get('/v1/access', headers=token('auth0|newcomer', 'website')).status_code == 401, 'web tokens are not app tokens'
    assert client.get('/v1/access?x=1', headers=token('auth0|newcomer')).status_code == 403
    assert client.get('/v1/access', headers={**token('auth0|newcomer'), 'Origin': 'https://evil.test'}).status_code == 403
    assert client.post('/v1/access', headers=token('auth0|newcomer')).status_code == 404
    # Reading access never creates an account or a grant.
    with hosted['registry'].connect() as db:
        assert db.execute("SELECT count(*) FROM accounts WHERE subject='auth0|stranger'").fetchone()[0] == 0
    client.get('/v1/access', headers=token('auth0|stranger'))
    with hosted['registry'].connect() as db:
        assert db.execute("SELECT count(*) FROM accounts WHERE subject='auth0|stranger'").fetchone()[0] == 0
