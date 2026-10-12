# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from types import SimpleNamespace

import pytest

from orion_mini import components


def test_component_status_reuses_existing_installation_without_network_or_account_changes(monkeypatch):
    monkeypatch.setattr(components, 'tailscale_executable', lambda: 'synthetic-tailscale')
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps({'BackendState':'Running','Self':{'Private':'not forwarded'}}))
    monkeypatch.setattr(components, 'run', run)
    manager = components.Components()
    assert manager.poll()['mesh_running']
    assert manager.sign_in('https://mesh.example.test')['mesh_running']
    assert manager.install()['mesh_installed']
    assert len(calls) == 1 and calls[0][1:] == ['status', '--json']
    assert 'Private' not in json.dumps(manager.snapshot())


@pytest.mark.parametrize('url', ['http://login.tailscale.com/a/private', 'https://login.tailscale.com.evil/a/private',
    'https://user:secret@login.tailscale.com/a/private', 'https://evil.example/a/private',
    'https://login.tailscale.com/a/private\n'])
def test_browser_sign_in_url_is_validated_without_exposing_it(url):
    assert not components.auth_url(url, None)


def test_explicit_controller_is_the_only_custom_browser_authority():
    assert components.auth_url('https://login.tailscale.com/a/synthetic', None)
    assert components.auth_url('https://mesh.example.test/register/synthetic', 'https://mesh.example.test')
    assert not components.auth_url('https://login.tailscale.com/a/synthetic', 'https://mesh.example.test')


def test_existing_configured_mesh_is_never_reset_to_invitation_provider(monkeypatch):
    monkeypatch.setattr(components, 'tailscale_executable', lambda: 'synthetic-tailscale')
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        value = {'BackendState':'Stopped'} if command[1] == 'status' else {'ControlURL':'https://existing.example','Persist':{'PrivateNodeKey':'synthetic'}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(value))
    monkeypatch.setattr(components, 'run', run)
    with pytest.raises(ValueError, match='existing network'):
        components.Components().sign_in('https://different.example')
    assert not any('up' in command for command in calls)


@pytest.mark.parametrize('controller', [None, 'https://existing.example'])
def test_stopped_profile_resumes_bare_up_preserving_all_preferences(monkeypatch, controller):
    monkeypatch.setattr(components, 'tailscale_executable', lambda: 'synthetic-tailscale')
    monkeypatch.setattr(components.shutil, 'which', lambda _: 'synthetic-pkexec')
    calls = []
    resumed = False
    def run(command, **kwargs):
        nonlocal resumed
        calls.append(command)
        if command[-1] == 'up':
            resumed = True
            assert kwargs['timeout'] == 125
            value = {}
        elif command[1] == 'status':
            value = {'BackendState': 'Running' if resumed else 'Stopped'}
        else:
            value = {'ControlURL': 'https://existing.example', 'Persist': {'PrivateNodeKey': 'synthetic'},
                     'CorpDNS': False, 'RouteAll': True, 'ExitNodeID': 'preserved-node'}
        return SimpleNamespace(returncode=0, stdout=json.dumps(value))
    monkeypatch.setattr(components, 'run', run)
    monkeypatch.setattr(components.webbrowser, 'open', lambda _: pytest.fail('Resume needs no new login'))
    assert components.Components().sign_in(controller)['mesh_running']
    up = next(command for command in calls if command[-1] == 'up')
    assert up[-2:] == ['synthetic-tailscale', 'up']
    assert not any(argument.startswith('--') for argument in up)


def test_expired_profile_failure_does_not_reset_or_echo_upstream(monkeypatch):
    monkeypatch.setattr(components, 'tailscale_executable', lambda: 'synthetic-tailscale')
    monkeypatch.setattr(components.shutil, 'which', lambda _: 'synthetic-pkexec')
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if command[-1] == 'up':
            return SimpleNamespace(returncode=1, stdout='synthetic private upstream reply')
        value = {'BackendState': 'NeedsLogin'} if command[1] == 'status' else {
            'ControlURL': 'https://existing.example', 'Persist': {'PrivateNodeKey': 'synthetic'}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(value))
    monkeypatch.setattr(components, 'run', run)
    manager = components.Components()
    with pytest.raises(ValueError, match='preferences were preserved') as failure:
        manager.sign_in()
    assert 'synthetic private' not in str(failure.value)
    assert len([command for command in calls if command[-1] == 'up']) == 1
    assert not manager.snapshot()['busy']
