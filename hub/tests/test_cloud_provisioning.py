# SPDX-License-Identifier: AGPL-3.0-or-later
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from orion_hub import cloud_provisioning as cloud
from test_acceptance import headers, pair
from test_link import client, hub

LIBRARY = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
ADMIN_TOKEN = 'a' * 40  # Synthetic fixtures, never owner credentials.


@pytest.fixture
def configured(tmp_path, monkeypatch):
    token = tmp_path / 'admin-token'; token.write_text(ADMIN_TOKEN); token.chmod(0o600)
    path = tmp_path / 'seafile.json'
    path.write_text(json.dumps({'schema': 1, 'server': 'http://100.64.1.1:8080', 'admin_token_file': str(token),
        'libraries': [{'id': LIBRARY, 'name': 'Cloud', 'permission': 'rw'}, {'id': OTHER, 'name': 'Shared', 'permission': 'r'}]}))
    path.chmod(0o600)
    monkeypatch.setenv('ORION_SEAFILE_CONFIG', str(path))
    return path


class Remote:
    def __init__(self):
        self.users = {}
        self.calls = []
        self.extra_library = False
        self.fail_disable = False
        self.fail_unshare = False
        self.after_auth = None
        self.bad_created_identity = False

    def __repr__(self):
        return 'Remote(<synthetic private fixtures>)'

    def request(self, method, path, values=None, *, token=None, anonymous=False):
        self.calls.append((method, path, values, token, anonymous))
        if path == '/api/v2.1/admin/users/':
            assert values['is_staff'] == 'false' and values['is_active'] == 'false'
            user = hashlib.sha256(values['email'].encode()).hexdigest()[:32] + '@auth.local'
            row = {'email': user, 'contact_email': values['email'], 'is_staff': False, 'is_active': False,
                   'password': values['password'], 'shares': {}}
            self.users[user] = row
            return {**row, 'email': 'owner@example.invalid'} if self.bad_created_identity else dict(row)
        if path.startswith('/api/v2.1/admin/users/'):
            user = unquote(path.split('/')[-2]); row = self.users[user]
            if method == 'PUT':
                if values['is_active'] == 'false' and self.fail_disable:
                    raise cloud.CloudError()
                row['is_active'] = values['is_active'] == 'true'
            return dict(row)
        if path == '/api/v2.1/admin/shares/':
            if method == 'DELETE':
                if self.fail_unshare:
                    raise cloud.CloudError()
                self.users[values['share_to']]['shares'].pop(values['repo_id'], None)
            else:
                self.users[values['share_to']]['shares'][values['repo_id']] = values['permission']
            return {'success': True}
        if path == '/api2/auth-token/':
            assert anonymous and token is None
            row = next(item for item in self.users.values() if item['contact_email'] == values['username'])
            assert row['is_active'] and values['password'] == row['password']
            if self.after_auth:
                self.after_auth()
            return {'token': hashlib.sha256(row['email'].encode()).hexdigest()[:40]}
        if path == '/api2/repos/':
            row = next(item for item in self.users.values() if hashlib.sha256(item['email'].encode()).hexdigest()[:40] == token)
            libraries = [{'id': identifier, 'permission': permission, 'encrypted': False} for identifier, permission in row['shares'].items()]
            if self.extra_library:
                libraries.append({'id': '33333333-3333-4333-8333-333333333333', 'permission': 'rw'})
            return libraries
        raise AssertionError('Unexpected synthetic request')


@pytest.fixture
def remote(monkeypatch):
    value = Remote()
    monkeypatch.setattr(cloud.API, 'request', lambda self, *args, **kwargs: value.request(*args, **kwargs))
    return value


def test_unconfigured_cloud_has_no_owner_fallback(hub, monkeypatch):
    monkeypatch.delenv('ORION_SEAFILE_CONFIG', raising=False)
    _, device = pair(hub, client(hub))
    assert cloud.status(hub.DB, device) == {'configured': False, 'state': 'not_configured', 'libraries': []}
    with pytest.raises(cloud.CloudError): cloud.provision(hub.DB, device, {})
    assert not cloud._registry_path(hub.DB).exists()


@pytest.mark.parametrize('server', ['https://example.invalid', 'http://127.0.0.1:8080', 'http://100.64.0.1:0',
    'http://@100.64.0.1:8080', 'http://100.64.0.1:8080/?credential=private'])
def test_server_origin_is_only_numeric_mesh_without_supplied_credentials(configured, server):
    raw = json.loads(configured.read_text()); raw['server'] = server; configured.write_text(json.dumps(raw))
    with pytest.raises(cloud.CloudError): cloud.configuration()


def test_supporting_account_is_non_admin_selected_only_and_retry_is_idempotent(hub, configured, remote, caplog):
    _, device = pair(hub, client(hub))
    first = cloud.provision(hub.DB, device, {'libraries': [LIBRARY]})
    again = cloud.provision(hub.DB, device, {'libraries': [LIBRARY]})
    assert first == again and len(remote.users) == 1
    user = next(iter(remote.users.values()))
    assert user['is_staff'] is False and user['is_active'] is True and user['shares'] == {LIBRARY: 'rw'}
    assert first['profile']['user'] == user['contact_email']
    assert first['profile']['libraries'] == [{'id': LIBRARY, 'name': 'Cloud', 'permission': 'rw'}]
    assert ADMIN_TOKEN not in json.dumps(first) and user['password'] not in json.dumps(first)
    assert ADMIN_TOKEN not in caplog.text and user['password'] not in caplog.text
    assert cloud.status(hub.DB, device)['state'] == 'provisioned'


@pytest.mark.parametrize('change',['removed','read_only'])
def test_reconciliation_closes_grants_outside_current_admin_policy_without_reenabling(hub,configured,remote,change):
    _,device=pair(hub,client(hub))
    first=cloud.provision(hub.DB,device,{'libraries':[LIBRARY]})
    raw=json.loads(configured.read_text())
    if change=='removed':raw['libraries']=[item for item in raw['libraries'] if item['id']!=LIBRARY]
    else:raw['libraries'][0]['permission']='r'
    configured.write_text(json.dumps(raw))
    cloud.reconcile(hub.DB)
    old=next(item for item in remote.users.values() if item['contact_email']==first['profile']['user'])
    assert old['is_active'] is False and not old['shares']
    with pytest.raises(cloud.CloudError):cloud.provision(hub.DB,device,{'libraries':[OTHER]})


def test_widened_admin_policy_preserves_existing_read_only_grant(hub,configured,remote):
    _,device=pair(hub,client(hub))
    cloud.provision(hub.DB,device,{'libraries':[OTHER]})
    raw=json.loads(configured.read_text());raw['libraries'][1]['permission']='rw'
    configured.write_text(json.dumps(raw))
    cloud.reconcile(hub.DB)
    assert len(remote.users)==1
    account=next(iter(remote.users.values()))
    assert account['is_active'] is True and account['shares']=={OTHER:'r'}


@pytest.mark.parametrize('body', [{'server': 'http://100.64.0.5:8080'}, {'token': 'a' * 40},
    {'libraries': []}, {'libraries': [LIBRARY, LIBRARY]}, {'libraries': ['33333333-3333-4333-8333-333333333333']}, {'libraries': [{}]}])
def test_clients_cannot_supply_credentials_server_or_unselected_shares(hub, configured, remote, body):
    _, device = pair(hub, client(hub))
    with pytest.raises(cloud.CloudError): cloud.provision(hub.DB, device, body)
    assert not remote.calls


def test_devices_have_distinct_supporting_accounts_and_selection_change_disables_previous(hub, configured, remote):
    _, one = pair(hub, client(hub)); _, two = pair(hub, client(hub))
    first = cloud.provision(hub.DB, one, {'libraries': [LIBRARY]})
    second = cloud.provision(hub.DB, two, {'libraries': [OTHER]})
    assert first['profile']['user'] != second['profile']['user'] and first['profile']['token'] != second['profile']['token']
    cloud.provision(hub.DB, one, {'libraries': [OTHER]})
    old = next(item for item in remote.users.values() if item['contact_email'] == first['profile']['user'])
    assert not old['is_active'] and not old['shares']
    assert sum(item['is_active'] for item in remote.users.values()) == 2


def test_extra_visible_library_fails_closed_and_can_retry_after_repair(hub, configured, remote):
    _, device = pair(hub, client(hub)); remote.extra_library = True
    with pytest.raises(cloud.CloudError): cloud.provision(hub.DB, device, {'libraries': [LIBRARY]})
    assert all(not item['is_active'] for item in remote.users.values())
    remote.extra_library = False
    assert cloud.provision(hub.DB, device, {'libraries': [LIBRARY]})['profile']['libraries'][0]['id'] == LIBRARY
    assert len(remote.users) == 2 and sum(item['is_active'] for item in remote.users.values()) == 1


def test_unexpected_created_identity_never_adopts_or_changes_an_owner_account(hub, configured, remote):
    _, device = pair(hub, client(hub)); remote.bad_created_identity = True
    with pytest.raises(cloud.CloudError): cloud.provision(hub.DB, device, {})
    assert all(item['is_active'] is False for item in remote.users.values())
    assert not any('owner' in call[1] for call in remote.calls)


def test_pairing_removed_during_provision_does_not_return_a_usable_token(hub, configured, remote):
    _, device = pair(hub, client(hub))
    remote.after_auth = lambda: hub.DB.execute('DELETE FROM devices WHERE id=?', (device,))
    with pytest.raises(cloud.CloudError): cloud.provision(hub.DB, device, {})
    assert all(not item['is_active'] for item in remote.users.values())


def test_cloud_registry_does_not_hold_hub_database_write_lock(hub, configured, remote):
    _, device = pair(hub, client(hub))
    remote.after_auth = lambda: hub.DB.execute('UPDATE devices SET name=? WHERE id=?', ('synthetic changed name', device))
    cloud.provision(hub.DB, device, {})
    assert hub.DB.row('SELECT name FROM devices WHERE id=?', (device,))['name'] == 'synthetic changed name'


def test_revocation_disables_cloud_before_pairing_removal_and_never_reenables(hub, configured, remote):
    _, device = pair(hub, client(hub))
    cloud.provision(hub.DB, device, {})
    cloud.revoke(hub.DB, device)
    assert all(not item['is_active'] for item in remote.users.values())
    assert all(not item['shares'] for item in remote.users.values())
    assert hub.DB.row('SELECT id FROM devices WHERE id=?', (device,))
    with pytest.raises(cloud.CloudError): cloud.provision(hub.DB, device, {})
    assert all(not item['is_active'] for item in remote.users.values())


def test_owner_cli_revokes_hub_even_when_seafile_is_offline(hub, configured, remote, monkeypatch, capsys):
    from orion_hub import cli
    _, device = pair(hub, client(hub)); cloud.provision(hub.DB, device, {})
    remote.fail_disable = True
    monkeypatch.setattr(sys, 'argv', ['orion-server', 'revoke', device])
    monkeypatch.setattr(cli.phone_backup, 'revoke', lambda db, identifier: db.execute('DELETE FROM devices WHERE id=?', (identifier,)))
    cli.main()
    assert hub.DB.row('SELECT id FROM devices WHERE id=?', (device,)) is None
    assert 'Cloud access cleanup is pending' in capsys.readouterr().out
    with cloud.registry(hub.DB) as connection:
        assert connection.execute('SELECT state FROM accounts WHERE device_id=?', (device,)).fetchone()['state'] == 'revoking'
    remote.fail_disable = False
    cloud.reconcile(hub.DB)
    assert all(not item['is_active'] and not item['shares'] for item in remote.users.values())


def test_changed_cloud_server_never_sends_old_account_updates_to_new_origin(hub, configured, remote):
    _, device = pair(hub, client(hub)); cloud.provision(hub.DB, device, {})
    remote.calls.clear()
    raw = json.loads(configured.read_text()); raw['server'] = 'http://100.64.6.8:8080'; configured.write_text(json.dumps(raw))
    with pytest.raises(cloud.CloudError): cloud.provision(hub.DB, device, {})
    assert not remote.calls


def test_concurrent_profile_requests_create_only_one_supporting_account(hub, configured, remote):
    _, device = pair(hub, client(hub))
    with ThreadPoolExecutor(max_workers=2) as executor:
        replies = list(executor.map(lambda _: cloud.provision(hub.DB, device, {}), range(2)))
    assert replies[0] == replies[1] and len(remote.users) == 1


@pytest.mark.skipif(sys.platform == 'win32', reason='Unix private configuration mode')
def test_group_writable_or_world_accessible_cloud_credentials_are_refused(configured):
    raw = json.loads(configured.read_text()); token = Path(raw['admin_token_file'])
    for mode in (0o660, 0o644, 0o602):
        token.chmod(mode)
        with pytest.raises(cloud.CloudError): cloud.configuration()
    token.chmod(0o640)
    assert cloud.configuration().admin_token == ADMIN_TOKEN


def test_remote_transport_is_bounded_no_proxy_no_redirect_and_fixed_errors(configured, monkeypatch):
    config = cloud.configuration(); supplied = []
    class Reply(io.BytesIO):
        status = 200
    calls = []
    def opening(request, **options):
        calls.append((request, options))
        return Reply(b'{"success":true}')
    def builder(*handlers):
        supplied.extend(handlers)
        return SimpleNamespace(open=opening)
    monkeypatch.setattr(cloud.urllib.request, 'build_opener', builder)
    api = cloud.API(config)
    assert api.request('POST', '/api/v2.1/admin/shares/', {'share_to': 'synthetic'}) == {'success': True}
    assert any(isinstance(item, cloud.urllib.request.ProxyHandler) and item.proxies == {} for item in supplied)
    assert any(isinstance(item, cloud._NoRedirect) for item in supplied)
    assert calls[0][1]['timeout'] == 8
    with pytest.raises(cloud.CloudError):
        cloud._NoRedirect().redirect_request(None, None, 302, '', {}, 'https://untrusted.invalid')
    api.opener = SimpleNamespace(open=lambda *args, **kwargs: Reply(b'PRIVATE_SERVER_RESPONSE_NOT_JSON'))
    with pytest.raises(cloud.CloudError) as error:
        api.request('GET', '/api2/repos/')
    assert 'PRIVATE_SERVER_RESPONSE' not in str(error.value)
    api.opener = SimpleNamespace(open=lambda *args, **kwargs: Reply(b' ' * (cloud.MAX_RESPONSE + 1)))
    with pytest.raises(cloud.CloudError): api.request('GET', '/api2/repos/')


def test_unshare_not_found_is_idempotent_without_ignoring_other_remote_failures(configured, monkeypatch):
    api = cloud.API(cloud.configuration())
    def fail(*args, **kwargs):
        raise urllib.error.HTTPError('http://100.64.0.1', 404, 'PRIVATE_BODY', {}, None)
    api.opener = SimpleNamespace(open=fail)
    assert api.request('DELETE', '/api/v2.1/admin/shares/', {'share_to': 'synthetic'}) == {'success': True}
    with pytest.raises(cloud.CloudError): api.request('GET', '/api2/repos/')


def test_failed_revocation_remains_pending_and_reconciliation_retries(hub, configured, remote):
    _, device = pair(hub, client(hub)); cloud.provision(hub.DB, device, {})
    remote.fail_disable = True
    with pytest.raises(cloud.CloudError): cloud.revoke(hub.DB, device)
    with pytest.raises(cloud.CloudError): cloud.provision(hub.DB, device, {})
    with cloud.registry(hub.DB) as connection:
        assert connection.execute('SELECT state FROM accounts WHERE device_id=?', (device,)).fetchone()['state'] == 'revoking'
    remote.fail_disable = False; cloud.reconcile(hub.DB)
    assert all(not item['is_active'] for item in remote.users.values())


def test_reconcile_closes_accounts_for_out_of_band_deleted_pairing(hub, configured, remote):
    _, device = pair(hub, client(hub)); cloud.provision(hub.DB, device, {})
    hub.DB.execute('DELETE FROM devices WHERE id=?', (device,))
    cloud.reconcile(hub.DB)
    assert all(not item['is_active'] for item in remote.users.values())


def test_failed_unshare_keeps_revocation_pending_until_shares_are_removed(hub, configured, remote):
    _, device = pair(hub, client(hub)); cloud.provision(hub.DB, device, {})
    remote.fail_unshare = True
    with pytest.raises(cloud.CloudError): cloud.revoke(hub.DB, device)
    assert all(not item['is_active'] and item['shares'] for item in remote.users.values())
    with cloud.registry(hub.DB) as connection:
        assert connection.execute('SELECT state FROM accounts WHERE device_id=?', (device,)).fetchone()['state'] == 'revoking'
    with pytest.raises(cloud.CloudError): cloud.provision(hub.DB, device, {})
    remote.fail_unshare = False; cloud.reconcile(hub.DB)
    assert all(not item['is_active'] and not item['shares'] for item in remote.users.values())


def test_one_failed_cleanup_does_not_starve_other_pending_devices(hub, configured, remote, monkeypatch):
    devices = [pair(hub, client(hub))[1] for _ in range(2)]
    for device in devices:
        cloud.provision(hub.DB, device, {})
        cloud.queue_revoke(hub.DB, device)
    original = cloud.revoke
    def revoke(db, device, **options):
        if device == devices[0]:
            raise cloud.CloudError()
        return original(db, device, **options)
    monkeypatch.setattr(cloud, 'revoke', revoke)
    with pytest.raises(cloud.CloudError): cloud.reconcile(hub.DB)
    with cloud.registry(hub.DB) as connection:
        states = {row['device_id']: row['state'] for row in connection.execute('SELECT device_id,state FROM accounts')}
    assert states == {devices[0]: 'revoking', devices[1]: 'revoked'}


def test_routes_require_existing_signature_actual_mesh_and_reject_browser_and_delegate(hub, configured, remote):
    c = client(hub); key, device = pair(hub, c)
    for method, path, raw in [('GET', '/v1/link/cloud', b''), ('POST', '/v1/link/cloud/profile', b'{}')]:
        assert c.request(method, path, content=raw).status_code == 401
        assert c.request(method, path, content=raw, headers={'Authorization': 'Bearer synthetic-delegate'}).status_code == 401
        auth = headers(key, device, method, path, raw)
        assert c.request(method, path, content=raw, headers={**auth, 'Origin': 'https://untrusted.invalid'}).status_code == 403
        c.cookies.set('orion_session', 'synthetic-browser')
        assert c.request(method, path, content=raw, headers=headers(key, device, method, path, raw)).status_code == 403
        c.cookies.clear()
        public = TestClient(hub.app, base_url='http://127.0.0.1:8765', client=('100.64.0.2', 9))
        assert public.request(method, path, content=raw, headers=headers(key, device, method, path, raw)).status_code == 403
    path = '/v1/link/cloud/profile'; auth = headers(key, device, 'POST', path, b'{}')
    response = c.post(path, content=b'{}', headers=auth)
    assert response.status_code == 200 and ADMIN_TOKEN not in response.text
    assert response.headers['cache-control'] == 'no-store'
    assert c.post(path, content=b'{}', headers=auth).status_code == 409
