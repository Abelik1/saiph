# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import sys
import pytest
from orion_mini.hosted_distribution import read_configuration
from orion_mini.hosted_runtime import packaged_config


def settings():
    return dict(service_url='https://api.synthetic.test', issuer='https://synthetic.eu.auth0.com/',
                audience='https://api.synthetic.invalid', desktop_client_id='SyntheticDesktop', android_client_id='SyntheticAndroid')


def test_bundled_public_defaults_do_not_enable_hosted_or_override_user_configuration(tmp_path, monkeypatch):
    path = tmp_path / 'hosted-defaults.json'
    path.write_text(json.dumps(settings()))
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    assert packaged_config() is None
    monkeypatch.setattr(sys, 'frozen', True)
    assert packaged_config()['client_id'] == 'SyntheticDesktop'
    assert packaged_config()['refresh_tokens'] is True
    assert 'enabled' not in packaged_config()
    from orion_mini.hosted_runtime import HostedController
    controller = object.__new__(HostedController)
    class Workspace: pass
    controller.workspace = Workspace()
    class Identity:
        def exists(self): return False
    controller.identity = Identity()
    controller.workspace.settings = {'hosted':{}}
    assert controller._config()['service_url'] == settings()['service_url']
    controller.workspace.settings = {'hosted':{'service_url':'invalid'}}
    assert controller._config() is None
    assert controller.workspace.settings == {'hosted':{'service_url':'invalid'}}


def test_fresh_link_state_exposes_bundled_settings_without_enabling_or_creating_keys(tmp_path, monkeypatch):
    from orion_mini.link_operations import LinkOperations
    from types import SimpleNamespace

    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    (bundle / 'hosted-defaults.json').write_text(json.dumps(settings()))
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(bundle), raising=False)
    monkeypatch.setattr('orion_mini.link_operations.hosted_available', lambda: True)
    profile = SimpleNamespace(root=tmp_path / 'fresh-profile', settings={})
    profile.hosted_controller = lambda: pytest.fail('No controller or transport before sign-in')
    snapshot = LinkOperations.hosted_state(profile)
    assert snapshot['available'] and snapshot['configured']
    assert snapshot['config']['client_id'] == settings()['desktop_client_id']
    assert snapshot['enabled'] is False and snapshot['identity'] is False
    assert snapshot['account']['status'] == 'signed_out'
    assert profile.settings == {}
    assert not profile.root.exists()


@pytest.mark.parametrize('difference', [None, 'service_url', 'issuer', 'audience', 'client_id', 'disabled', 'hub'])
def test_persistent_session_upgrade_only_matches_enabled_packaged_deployment(tmp_path, monkeypatch, difference):
    from types import SimpleNamespace
    from orion_mini.hosted_distribution import desktop_config
    from orion_mini.hosted_runtime import HostedController
    from orion_mini.storage import Store

    bundled = desktop_config(settings())
    monkeypatch.setattr('orion_mini.hosted_runtime.packaged_config', lambda: bundled)
    original = {**bundled, 'refresh_tokens': False, 'enabled': difference != 'disabled', 'owner_option': 'kept'}
    if difference in ('service_url', 'issuer', 'audience', 'client_id'):
        original[difference] += 'different'
    profile = SimpleNamespace(root=tmp_path, settings={'hosted': original.copy()},
                              store=Store(tmp_path / 'store'))
    if difference == 'hub': profile.settings['hub'] = {'paired': True}
    saves = []
    profile.save = lambda: saves.append(True)
    account = tmp_path / 'hosted' / 'account'
    account.mkdir(parents=True)
    tombstone = account / 'signed-out'
    tombstone.write_bytes(b'signed-out\n')
    identity = tmp_path / 'hosted' / 'identity'
    identity.mkdir()
    retained = identity / 'synthetic-retained-fixture'
    retained.write_bytes(b'ORION-SYNTHETIC-IDENTITY')

    controller = HostedController(profile)
    expected = {**original, 'refresh_tokens': difference is None}
    assert controller.settings == expected
    assert saves == ([True] if difference is None else [])
    assert tombstone.read_bytes() == b'signed-out\n'
    assert retained.read_bytes() == b'ORION-SYNTHETIC-IDENTITY'
    assert controller.account is None and controller.transport is None
    controller._migrate_packaged_session()
    assert saves == ([True] if difference is None else [])


@pytest.mark.parametrize('mutation', ['secret','http','query','issuer','clients','oversize'])
def test_unsafe_build_configuration_fails_closed(tmp_path, monkeypatch, mutation):
    value = settings()
    if mutation == 'secret': value['client_secret'] = 'must-never-be-bundled'
    elif mutation == 'http': value['service_url'] = 'http://api.synthetic.test'
    elif mutation == 'query': value['service_url'] += '?token=hidden'
    elif mutation == 'issuer': value['issuer'] = 'https://synthetic.eu.auth0.com.evil.test/'
    elif mutation == 'clients': value['android_client_id'] = value['desktop_client_id']
    else: value['audience'] += 'x' * 4096
    path = tmp_path / 'hosted-defaults.json'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError): read_configuration(path)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    assert packaged_config() is None
