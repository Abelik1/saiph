# SPDX-License-Identifier: AGPL-3.0-or-later
"""The default distribution keeps Link functional without loading personal tools."""
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from orion_mini import hub_client, modules, phone
from orion_mini.link_operations import LinkOperations
from orion_mini.link_service import LinkWorkspace
from orion_mini.storage import read_json, write_json
PERSONAL_FEATURES = {'sleep_plan': True, 'activity_breaks': True, 'calendar': True}
DISABLED_FEATURES = {key: False for key in PERSONAL_FEATURES}

def saved_profile(root):
    settings = {'projects': [{'id': 'retained-project', 'path': 'synthetic-project-path'}], 'selected_project': 'retained-project', 'plugins': ['synthetic-plugin'], 'watched_folders': ['synthetic-watched-folder'], 'machine': {'name': 'Existing computer', 'features': PERSONAL_FEATURES}, 'transcription': {'model': 'small', 'device': 'cpu'}, 'sleep_plan': {'hour': 22, 'minute': 15}, 'cloud': {'path': str(root / 'Cloud'), 'enabled': True, 'recordings': True}, 'ai': {'provider': 'old-provider'}, 'email': {'address': 'old@example.invalid'}}
    connections = {'ai': {'provider': 'saved-provider', 'model': 'saved-model', 'credential_source': 'private-fixture-path'}, 'email': {'address': 'saved@example.invalid'}, 'hub': {'base_url': 'http://100.64.1.2:9876', 'device_id': 'dev_saved', 'paired': True}}
    write_json(root / 'settings.json', settings)
    write_json(root / 'connections.json', connections)
    return (settings, connections)

def invite(root):
    artifact = {'format': 'orion-enrollment', 'version': 1, 'hub': 'http://100.64.1.2:9876', 'code': '01234567', 'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()}
    path = root / 'synthetic.orion-enrollment'
    path.write_text(json.dumps(artifact), encoding='utf-8')
    return path

def test_owner_profile_is_retained_but_personal_work_is_inactive(tmp_path):
    settings, connections = saved_profile(tmp_path)
    workspace = LinkWorkspace(tmp_path)
    personal = {}
    for kind in ('project', 'transcript', 'reminder', 'task', 'job', 'message', 'email'):
        personal[kind] = workspace.store.save(kind, {'id': 'existing', 'status': 'queued', 'fixture': kind})
    workspace.bootstrap()
    workspace.dispatch('settings.save', {'machine': {'name': 'Renamed computer'}, 'close_to_tray': False, 'cloud': {'enabled': False}, 'link': {'clipboard': False}})
    state = workspace.dispatch('state', {})
    assert state['modules'] == {'workspace': {'installed': False, 'enabled': False}}
    assert workspace.settings['machine']['features'] == DISABLED_FEATURES
    for key in ('projects', 'transcripts', 'reminders', 'tasks', 'jobs', 'messages', 'emails', 'plugins'):
        assert state[key] == []
    for attr in ('recordings', 'backups', 'reminders', 'projects', 'providers', 'worker'):
        assert not hasattr(workspace, attr)
    for kind, item in personal.items():
        assert workspace.store.get(kind, 'existing') == item
    persisted = read_json(tmp_path / 'settings.json')
    for key in ('projects', 'selected_project', 'plugins', 'watched_folders', 'transcription', 'sleep_plan'):
        assert persisted[key] == settings[key]
    assert persisted['machine'] == {'name': 'Renamed computer', 'features': PERSONAL_FEATURES}
    assert persisted['cloud']['recordings'] is True
    assert persisted['cloud']['enabled'] is False
    assert read_json(tmp_path / 'connections.json') == connections
    for key, value in connections.items():
        assert persisted[key] == value
    restarted = LinkWorkspace(tmp_path)
    assert restarted.settings['machine']['features'] == DISABLED_FEATURES
    assert restarted.settings['hub'] == connections['hub']

def test_link_never_starts_saved_optional_capture_or_deskflow(tmp_path):
    write_json(tmp_path / 'settings.json', {'link': {'deskflow': {'enabled': True}, 'camera': {'enabled': True}}})
    workspace = LinkWorkspace(tmp_path)
    assert workspace.deskflow.process is None
    assert workspace.camera.status()['running'] is False
    with pytest.raises(ValueError, match='paired'):
        workspace.camera.start('synthetic-device')
    workspace.save()
    assert read_json(tmp_path / 'settings.json')['link']['deskflow']['enabled'] is True

def test_camera_is_optional_in_link_without_personal_workspace(tmp_path):
    workspace = LinkWorkspace(tmp_path)
    assert workspace.settings['link']['camera']['enabled'] is False
    assert not workspace.camera.status()['running']
    workspace.dispatch('settings.save', {'link': {'camera': {'enabled': True, 'quality': '720p', 'facing': 'back'}}})
    workspace.dispatch('settings.save', {'link': {'camera': {'rotation': '90'}}})
    assert workspace.settings['link']['camera'] == {'enabled': True, 'quality': '720p', 'facing': 'back', 'rotation': '90'}
    assert workspace.state()['modules']['workspace']['installed'] is False
    assert not workspace.camera.status()['running']
    with pytest.raises(ValueError):
        workspace.dispatch('camera.start', {'device_id': 'phone'})

def test_cloud_inspection_is_cached_and_returns_a_copy(tmp_path, monkeypatch):
    from orion_mini import cloud_client, link_operations
    inspected = []
    clock = [100]
    monkeypatch.setattr(link_operations.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(cloud_client, 'status', lambda root: inspected.append(root) or {'state': 'not_configured'})
    workspace = LinkWorkspace(tmp_path)
    workspace.cloud_status()
    # Inspection runs on a worker. Wait for its lock instead of depending on
    # the scheduler completing it between two consecutive UI snapshots.
    assert workspace._cloud_status_lock.acquire(timeout=5)
    workspace._cloud_status_lock.release()
    expected = {'state': 'not_configured', 'installation_supported': cloud_client.installation_supported()}
    first = workspace.cloud_status()
    assert first == expected
    first['state'] = 'changed'
    assert workspace.cloud_status() == expected
    assert inspected == [tmp_path / 'cloud-client']
    clock[0] += 16
    workspace.cloud_status()
    assert workspace._cloud_status_lock.acquire(timeout=5)
    workspace._cloud_status_lock.release()
    assert len(inspected) == 2
    assert workspace.cloud_status() == expected


def test_cloud_component_installation_is_explicit_finite_and_invalidates_status(tmp_path, monkeypatch):
    from types import SimpleNamespace
    workspace = LinkWorkspace(tmp_path)
    installed = []
    monkeypatch.setattr(workspace, 'cloud_client', lambda: SimpleNamespace(install=lambda **args: installed.append(args) or {'installed': True, 'existing_preserved': False}))
    workspace._cloud_status_cache = (100, {'installed': False})
    with pytest.raises(ValueError):
        workspace.dispatch('cloud.client.install', {'url': 'https://untrusted.invalid'})
    assert not installed
    assert workspace.dispatch('cloud.client.install', {}) == {'installed': True, 'existing_preserved': False}
    assert installed == [{'consent': True}] and workspace._cloud_status_cache is None

def test_cloud_changes_are_serialized_without_blocking_state_or_losing_lock_after_failure(tmp_path, monkeypatch):
    import threading
    from types import SimpleNamespace
    Workspace = LinkWorkspace
    workspace = Workspace(tmp_path)
    entered, release = (threading.Event(), threading.Event())
    calls = []

    def install(**kwargs):
        calls.append(kwargs)
        entered.set()
        assert release.wait(5)
        raise ValueError('synthetic install failure')
    monkeypatch.setattr(workspace, 'cloud_client', lambda: SimpleNamespace(install=install))
    failures = []

    def action():
        try:
            workspace.dispatch('cloud.client.install', {})
        except ValueError as error:
            failures.append(str(error))
    worker = threading.Thread(target=action)
    worker.start()
    try:
        assert entered.wait(5)
        for method in ('cloud.client.install', 'cloud.setup'):
            with pytest.raises(ValueError, match='already running'):
                workspace.dispatch(method, {})
        assert workspace.dispatch('state', {})['settings']
        assert len(calls) == 1
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive() and failures == ['synthetic install failure']
    monkeypatch.setattr(workspace, 'cloud_client', lambda: SimpleNamespace(install=lambda **k: {'installed': True}))
    assert workspace.dispatch('cloud.client.install', {}) == {'installed': True}

@pytest.mark.parametrize(('method', 'args'), [('projects.add', {'path': 'synthetic'}), ('jobs.run', {}), ('transcription.start', {}), ('plugins.run', {}), ('calendar.sync', {}), ('google.sign_in', {}), ('settings.save', {'projects': []}), ('settings.save', {'plugins': []}), ('settings.save', {'transcription': {'model': 'large'}}), ('settings.save', {'machine': {'name': 'Computer', 'features': PERSONAL_FEATURES}}), ('settings.save', {'cloud': {'recordings': True}}), ('settings.save', {'hub': {'paired': True, 'device_id': 'untrusted'}})])
def test_personal_commands_cannot_activate_from_link(tmp_path, method, args):
    settings, connections = saved_profile(tmp_path)
    workspace = LinkWorkspace(tmp_path)
    with pytest.raises(ValueError):
        workspace.dispatch(method, args)
    assert read_json(tmp_path / 'settings.json') == settings
    assert read_json(tmp_path / 'connections.json') == connections
    assert workspace.settings['machine']['features'] == DISABLED_FEATURES

@pytest.mark.parametrize('machine', [None, [], 'Computer', {'name': 12}, {'name': ''}, {'name': 'x' * 41}, {'name': 'Computer', 'unexpected': True}])
def test_invalid_machine_setting_is_rejected_without_write(tmp_path, machine):
    workspace = LinkWorkspace(tmp_path)
    with pytest.raises(ValueError):
        workspace.dispatch('settings.save', {'machine': machine})
    assert not (tmp_path / 'settings.json').exists()

def test_link_enrollment_uses_existing_pairing_and_hides_claim_errors(tmp_path, monkeypatch, caplog):
    workspace = LinkWorkspace(tmp_path)
    assert isinstance(workspace, LinkOperations)
    status = workspace.dispatch('enrollment.import', {'path': str(invite(tmp_path))})
    assert '01234567' not in json.dumps(workspace.state())
    calls = []

    def pair(root, origin, code, name):
        calls.append((root, origin, code, name))
        if len(calls) == 1:
            raise RuntimeError('synthetic private response 01234567')
        return {'base_url': origin, 'device_id': 'dev_friend', 'paired': True}
    monkeypatch.setattr(hub_client, 'pair', pair)
    with pytest.raises(RuntimeError) as error:
        workspace.dispatch('enrollment.approve', {'id': status['id']})
    assert '01234567' not in str(error.value) and 'private response' not in str(error.value)
    assert workspace.enrollment_approved == status['id'] and (not workspace.settings['hub']['paired'])
    assert workspace.complete_enrollment(status['id']) == {'ok': True}
    assert calls[-1][:3] == (tmp_path, 'http://100.64.1.2:9876', '01234567')
    assert not workspace.invitations.status()['ready']
    restarted = LinkWorkspace(tmp_path)
    assert restarted.settings['hub']['device_id'] == 'dev_friend'
    assert '01234567' not in json.dumps(restarted.state()) and '01234567' not in caplog.text
    status = restarted.dispatch('enrollment.import', {'path': str(invite(tmp_path))})
    with pytest.raises(ValueError):
        restarted.dispatch('enrollment.approve', {'id': status['id']})
    assert len(calls) == 2

def test_phone_supervisor_runs_without_personal_services_on_existing_profile(tmp_path, monkeypatch):
    saved_profile(tmp_path)
    workspace = LinkWorkspace(tmp_path)
    retained = workspace.store.save('job', {'id': 'retained-job', 'status': 'queued'})
    runtime = phone.PhoneRuntime(workspace, notifier_factory=lambda _: None, worker_factory=lambda: None)
    calls = []
    monkeypatch.delenv('ORION_MINI_TEST', raising=False)

    def poll():
        calls.append('components')
        runtime.stop_requested.set()
    monkeypatch.setattr(workspace.components, 'poll', poll)
    # A self-hosted invitation is waiting, so the mesh client is checked.
    monkeypatch.setattr(workspace.invitations, 'status', lambda: {'ready': True, 'id': 'invite', 'expires_at': None, 'custom_mesh': False})
    asyncio.run(asyncio.wait_for(runtime.run(), timeout=5))
    assert 'components' in calls and workspace.deskflow.process is None
    assert workspace.store.get('job', retained['id']) == retained
    assert not workspace.store.all('focus_plan')
    assert not workspace.phone.connected

def test_mesh_client_is_not_checked_without_a_self_hosted_invitation(tmp_path, monkeypatch):
    workspace = LinkWorkspace(tmp_path)
    runtime = phone.PhoneRuntime(workspace, notifier_factory=lambda _: None, worker_factory=lambda: None)
    calls = []
    monkeypatch.delenv('ORION_MINI_TEST', raising=False)
    monkeypatch.setattr(workspace.components, 'poll', lambda: calls.append('components'))

    async def briefly():
        asyncio.get_running_loop().call_later(0.5, runtime.stop_requested.set)
        await runtime.run()
    asyncio.run(asyncio.wait_for(briefly(), timeout=10))
    assert calls == []  # Saiph account users are never checked for Tailscale.

def test_link_does_not_issue_personal_agent_grants(tmp_path, monkeypatch):
    workspace = LinkWorkspace(tmp_path)
    runtime = phone.PhoneRuntime(workspace, notifier_factory=lambda _: None, worker_factory=lambda: None)
    paths = []

    def signed(root, mesh, path):
        paths.append(path)
        return {'focus': None}
    monkeypatch.setattr(phone, 'signed', signed)

    def forbidden(*args):
        pytest.fail('Default Link must not issue personal assistant grants')
    monkeypatch.setattr(phone, 'ensure_grants', forbidden)
    assert asyncio.run(runtime.refresh_auxiliary({'base_url': 'http://100.64.1.2:9876'}))
    assert paths == ['/v1/link/continuity']

def test_link_import_and_state_are_isolated_in_fresh_interpreter(tmp_path):
    saved_profile(tmp_path)
    code = "\nimport importlib.abc\nimport json\nimport sys\nfrom pathlib import Path\nforbidden = ('orion_mini.service', 'orion_mini.projects', 'orion_mini.providers',\n             'orion_mini.worker', 'orion_mini.calendar_service', 'orion_mini.google_account',\n             'orion_mini.reminders', 'orion_mini.plugins', 'orion_mini.library',\n             'google', 'faster_whisper', 'ctranslate2', 'torch')\nclass Guard(importlib.abc.MetaPathFinder):\n    def find_spec(self, fullname, path=None, target=None):\n        if any(fullname == name or fullname.startswith(name + '.') for name in forbidden):\n            raise AssertionError('Personal module imported: ' + fullname)\nsys.meta_path.insert(0, Guard())\nfrom orion_mini.link_service import LinkWorkspace\nstate = LinkWorkspace(Path(sys.argv[1])).state()\nassert state['modules']['workspace']['installed'] is False\nassert state['jobs'] == [] and state['projects'] == []\nassert not any(name == prefix or name.startswith(prefix + '.')\n               for name in sys.modules for prefix in forbidden)\nprint('isolated-link-state-ok')\n"
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)], env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'isolated-link-state-ok'

@pytest.mark.parametrize('manifest', [None, {}, {'profile': 'link', 'schema': 1}, {'profile': 'workspace', 'schema': True}, {'profile': 'workspace', 'schema': 1.0}, {'profile': 'workspace', 'schema': '1'}, {'profile': 'workspace', 'schema': 2}, {'profile': 'workspace', 'schema': 1, 'enabled': True}, ['workspace'], 'workspace'])
def test_frozen_defaults_to_link_without_exact_workspace_manifest(tmp_path, monkeypatch, manifest):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    if manifest is not None:
        write_json(tmp_path / 'distribution-profile.json', manifest)
    assert not modules.workspace_installed()


def test_phone_with_unspecified_workspace_edition_does_not_issue_grants(tmp_path, monkeypatch):
    from types import SimpleNamespace
    workspace = SimpleNamespace(root=tmp_path)
    runtime = phone.PhoneRuntime.__new__(phone.PhoneRuntime)
    runtime.workspace = workspace
    runtime.continuity = SimpleNamespace(last_plan=None)
    monkeypatch.setattr(phone, "signed", lambda *args: {})
    monkeypatch.setattr(phone, "ensure_grants", lambda *args: pytest.fail("Missing edition must fail closed"))
    assert asyncio.run(runtime.refresh_auxiliary({"base_url": "https://hub.example.invalid"}))
