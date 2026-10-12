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
    assert packaged_config()['refresh_tokens'] is False
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
