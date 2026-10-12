# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthetic Seafile profiles; no running client, network or owner data."""
import configparser
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import stat

import pytest

from orion_mini import cloud_client as cloud


LIBRARY = '1f9d8ae2-11cf-4d07-b359-653b1a0b2a12'
OTHER = '2f9d8ae2-11cf-4d07-b359-653b1a0b2a12'
TOKEN = '0123456789abcdef' * 3


@pytest.fixture
def setup(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    executable = tmp_path / 'seaf-cli'
    executable.touch()
    # Exercise file content and preparation independently of Windows ACL tools.
    monkeypatch.setattr(cloud, '_restrict_windows', lambda path: None)
    client = cloud.SeafileClient(home=home, private_root=home / 'private',
                                executable=executable, platform='linux')
    folder = home / 'Cloud'
    folder.mkdir()
    profile = cloud.CloudProfile('http://100.64.0.2:8080', 'device@example.invalid', TOKEN, LIBRARY)
    return client, folder, profile


def existing(client, folder=None, library=LIBRARY, server='http://100.64.0.2:8080'):
    config = client.profile_dirs[0]
    config.mkdir()
    data = client.home / 'data'
    data.mkdir()
    (config / 'seafile.ini').write_text(str(data), encoding='utf-8')
    with closing(sqlite3.connect(data / 'repo.db')) as connection, connection:
        connection.execute('CREATE TABLE Repo (repo_id TEXT PRIMARY KEY)')
        connection.execute('CREATE TABLE RepoProperty (repo_id TEXT, key TEXT, value TEXT)')
        if folder:
            connection.execute('INSERT INTO Repo VALUES (?)', (library,))
            connection.executemany('INSERT INTO RepoProperty VALUES (?, ?, ?)',
                                   [(library, 'worktree', str(folder)), (library, 'server-url', server)])
        connection.execute('CREATE TABLE SecretAccount (token TEXT)')
        connection.execute('INSERT INTO SecretAccount VALUES (?)', (TOKEN,))
    return config, data


@pytest.mark.parametrize('origin', ['https://example.com', 'http://127.0.0.1',
    'http://100.64.0.2/path', 'http://u:p@100.64.0.2', 'http://100.64.0.2?x=1',
    'http://100.64.0.2:0', 'http://100.64.0.2\n', 'http://[fd7a:115c:a1e0::2%25x]'])
def test_only_numeric_mesh_origins(origin):
    with pytest.raises(ValueError, match='numeric mesh'):
        cloud.server_origin(origin)


def test_ipv6_and_default_ports():
    assert cloud.server_origin('https://[fd7a:115c:a1e0::2]') == 'https://[fd7a:115c:a1e0::2]:443'
    assert cloud.server_origin('http://100.64.0.2/') == 'http://100.64.0.2:80'


def test_status_is_read_only_and_does_not_expose_secrets(setup, monkeypatch):
    client, folder, _ = setup
    config, data = existing(client, folder)
    before = {p: p.read_bytes() for p in (config / 'seafile.ini', data / 'repo.db')}
    monkeypatch.setattr(cloud.subprocess, 'run', lambda *a, **k: pytest.fail('No process allowed'))
    result = client.detect().safe()
    assert result == {'installed': True, 'profile_present': True, 'inspection_complete': True,
                      'prepared': False, 'selected_libraries': 1, 'state': 'existing_profile'}
    assert all(p.read_bytes() == content for p, content in before.items())
    assert TOKEN not in str(result) and LIBRARY not in str(result) and str(folder) not in str(result)
    assert not (data / 'repo.db-wal').exists()


def test_gui_prepares_first_use_login_not_sync(setup):
    client, folder, profile = setup
    result = client.provision(profile, folder, consent=True)
    assert result.safe() == {'state': 'prepared', 'needs_library_link': True}
    assert result.command == ()
    config = configparser.ConfigParser()
    config.read(result.credential_file)
    assert config['preconfigure']['PreconfigureUserToken'] == TOKEN
    assert config['preconfigure']['PreconfigureServerAddr'] == profile.server
    assert not (folder / 'account.ini').exists()
    assert TOKEN not in repr(result) and TOKEN not in repr(profile)
    if os.name != 'nt':
        assert stat.S_IMODE(result.credential_file.stat().st_mode) == 0o600


def test_legacy_cli_preparation_refuses_unproven_token_support(setup):
    client, folder, profile = setup
    config, _ = existing(client)
    with pytest.raises(ValueError, match='CLI account-file preparation is unsupported'):
        client.provision(profile, folder, consent=True, mode='cli',
                         config_dir=config, supports_private_config=True)
    assert not client.private_root.exists()


def test_existing_binding_is_idempotent(setup):
    client, folder, profile = setup
    existing(client, folder)
    assert client.provision(profile, folder, consent=True).safe() == {
        'state': 'existing_binding', 'needs_library_link': False}
    assert not client.private_root.exists()


@pytest.mark.parametrize('reason', ['folder', 'server', 'overlap', 'existing_login'])
def test_existing_profile_is_preserved(setup, reason):
    client, folder, profile = setup
    selected = folder
    library = LIBRARY
    server = profile.server
    if reason == 'folder':
        selected = client.home / 'other'
    elif reason == 'server':
        server = 'http://100.64.0.9:8080'
    elif reason == 'overlap':
        library = OTHER
    elif reason == 'existing_login':
        selected = None
    _, data = existing(client, selected, library, server)
    before = (data / 'repo.db').read_bytes()
    with pytest.raises(ValueError):
        client.provision(profile, folder, consent=True)
    assert (data / 'repo.db').read_bytes() == before
    assert not client.private_root.exists()


def test_live_wal_profile_refuses_preparation(setup):
    client, folder, profile = setup
    _, data = existing(client)
    (data / 'repo.db-wal').write_bytes(b'active')
    assert not client.detect().safe()['inspection_complete']
    with pytest.raises(ValueError, match='inspection'):
        client.provision(profile, folder, consent=True)


def test_broken_profile_preserved(setup):
    client, folder, profile = setup
    client.profile_dirs[0].mkdir()
    with pytest.raises(ValueError, match='inspection'):
        client.provision(profile, folder, consent=True)


def test_existing_preconfiguration_never_overwritten(setup):
    client, folder, profile = setup
    client.preconfiguration.write_text('owner settings', encoding='utf-8')
    with pytest.raises(ValueError, match='Preserve'):
        client.provision(profile, folder, consent=True)
    assert client.preconfiguration.read_text() == 'owner settings'


def test_cli_preserves_unrelated_binding(setup):
    client, folder, profile = setup
    other = client.home / 'other-library'
    other.mkdir()
    config, data = existing(client, other, OTHER)
    before = (data / 'repo.db').read_bytes()
    with pytest.raises(ValueError, match='existing profiles are preserved'):
        client.provision(profile, folder, consent=True, mode='cli',
                         config_dir=config, supports_private_config=True)
    assert (data / 'repo.db').read_bytes() == before
    assert not client.private_root.exists()


def test_credentials_cannot_land_inside_another_library(setup):
    client, folder, profile = setup
    other = client.home / 'other-library'
    other.mkdir()
    config, _ = existing(client, other, OTHER)
    client.private_root = other / 'private'
    with pytest.raises(ValueError, match='unsupported'):
        client.provision(profile, folder, consent=True, mode='cli',
                         config_dir=config, supports_private_config=True)
    assert not client.private_root.exists()


def test_existing_private_root_never_taken_over(setup):
    client, folder, profile = setup
    client.private_root.mkdir()
    saved = client.private_root / 'account.ini'
    saved.write_text('owner configuration', encoding='utf-8')
    with pytest.raises(ValueError, match='Existing profiles are unchanged'):
        client.provision(profile, folder, consent=True)
    assert saved.read_text() == 'owner configuration'
    assert not client.preconfiguration.exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows ACL ordering')
def test_windows_acl_is_restricted_before_token_write(tmp_path, monkeypatch):
    target = tmp_path / 'credentials.ini'
    secured = []
    def secure(path):
        assert path.read_bytes() == b''
        secured.append(path)
    monkeypatch.setattr(cloud, '_restrict_windows', secure)
    cloud._private_write(target, TOKEN)
    assert secured == [target]
    assert target.read_text() == TOKEN


@pytest.mark.parametrize('change', ['no_consent', 'missing_executable', 'unknown_mode', 'unverified_cli', 'private_in_sync'])
def test_invalid_preparation_does_not_write(setup, change):
    client, folder, profile = setup
    kwargs = {'consent': True}
    if change == 'no_consent':
        kwargs = {}
    elif change == 'missing_executable':
        client.executable.unlink()
    elif change == 'unknown_mode':
        kwargs['mode'] = 'other'
    elif change == 'unverified_cli':
        kwargs['mode'] = 'cli'
    elif change == 'private_in_sync':
        client.private_root = folder / 'private'
    with pytest.raises(ValueError):
        client.provision(profile, folder, **kwargs)
    assert not client.private_root.exists()


def test_failure_after_acl_does_not_leave_credentials(setup, monkeypatch):
    client, folder, profile = setup
    def fail(*args):
        raise OSError('private fixture failure')
    monkeypatch.setattr(cloud, '_private_write', fail)
    with pytest.raises(ValueError, match='Existing profiles are unchanged'):
        client.provision(profile, folder, consent=True)
    assert not client.private_root.exists()
    assert not client.preconfiguration.exists()


def test_public_status_wrapper_is_safe(setup, monkeypatch):
    client, _, _ = setup
    monkeypatch.setattr(cloud.SeafileClient, '_find_executable', lambda self: client.executable)
    result = cloud.status(client.private_root, home=client.home)
    assert result['state'] == 'not_detected'
    assert set(result) == {'installed', 'profile_present', 'inspection_complete', 'prepared', 'selected_libraries', 'state', 'management_available', 'service_state'}


@pytest.mark.parametrize('user,token,library,scope', [
    ('line\nbreak', TOKEN, LIBRARY, 'account'),
    ('device@example.invalid', 'secret\nkey', LIBRARY, 'account'),
    ('device@example.invalid', TOKEN, 'invalid', 'account'),
    ('device@example.invalid', TOKEN, LIBRARY, 'library'),
])
def test_profile_validation_never_echoes_input(user, token, library, scope):
    with pytest.raises(ValueError) as failure:
        cloud.CloudProfile('http://100.64.0.2', user, token, library, scope)
    assert token not in str(failure.value)


@pytest.mark.skipif(os.name == 'nt', reason='Unix symlink fixture')
def test_redirected_profile_refused(setup):
    client, folder, profile = setup
    target = client.home / 'real-profile'
    target.mkdir()
    client.profile_dirs[0].symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match='inspection'):
        client.provision(profile, folder, consent=True)


def test_custom_task_metadata_discovers_original_profile_without_running_script(setup):
    client, folder, _ = setup
    config, data = existing(client, folder)
    root = client.home / 'custom-client'
    root.mkdir()
    # Task metadata is finite and contains no credentials.
    config.rename(root / 'ccnet')
    data.rename(root / 'data')
    (root / 'ccnet/seafile.ini').write_text(str(root / 'data'))
    binary = client.home / 'portable/bin'
    binary.mkdir(parents=True)
    (binary / 'seafile-applet.exe').touch()
    action = {'Execute': str(client.home / 'pythonw.exe'),
              'Arguments': f'"{client.home / "start-seafile-client.py"}" --client-root "{root}" --binary-root "{binary}"'}
    location = cloud._task_location(action)
    client.location = location
    client.executable = location.executable
    client.profile_dirs = (location.config,)
    assert client.detect().safe()['selected_libraries'] == 1
    assert str(root) not in repr(location)


def test_unrecognized_task_action_is_not_executed_or_adopted():
    with pytest.raises(ValueError, match='needs inspection'):
        cloud._task_location({'Execute': 'powershell.exe', 'Arguments': '-Command arbitrary'})


def test_unknown_discovery_is_not_definite_missing_profile(setup):
    client, _, _ = setup
    client.discovery_complete = False
    result = client.detect().safe()
    assert result['state'] == 'inspection_pending' and not result['inspection_complete']


def test_open_sets_exact_profile_before_official_gui_creation(setup, monkeypatch):
    from types import SimpleNamespace
    client, folder, _ = setup
    config, data = existing(client, folder)
    gui = client.executable.with_name('seafile-applet.exe')
    gui.touch()
    client.executable = gui
    calls = []
    monkeypatch.setattr(cloud.subprocess, 'Popen', lambda command, **kwargs: calls.append((command, kwargs)) or SimpleNamespace())
    assert client.open() == {'opened': True}
    command, options = calls[0]
    assert command == [str(gui), '-c', str(config), '-d', str(data)]
    assert options['env']['CCNET_CONF_DIR'] == config.as_posix()
    assert options['env']['SEAFILE_DATA_DIR'] == data.as_posix()
    assert options['stdout'] == cloud.subprocess.DEVNULL
    assert TOKEN not in ' '.join(command)


def test_signed_profile_cannot_expand_selected_library(setup):
    _, _, profile = setup
    response = {'profile': {'schema': 1, 'server': profile.server, 'user': profile.user,
                           'token': profile.token, 'token_scope': 'account',
                           'libraries': [{'id': OTHER, 'name': 'Other', 'permission': 'rw'}]}}
    with pytest.raises(ValueError, match='unsupported file sync profile'):
        cloud.paired_profile(response, LIBRARY)
    response['profile']['libraries'][0]['id'] = LIBRARY
    assert cloud.paired_profile(response, LIBRARY).library_id == LIBRARY


@pytest.mark.parametrize('fail_sync', [False, True])
def test_linux_first_use_runs_official_cli_without_secret_arguments(setup, monkeypatch, fail_sync):
    from types import SimpleNamespace
    client, folder, profile = setup
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert TOKEN not in ' '.join(command) and profile.user not in ' '.join(command)
        assert kwargs['stdout'] == cloud.subprocess.DEVNULL
        assert not any(key.lower() == 'http_proxy' for key in kwargs['env'])
        if command[1] == 'init':
            (client.private_root / 'ccnet').mkdir()
            data = client.private_root / 'seafile-data'
            data.mkdir()
            (client.private_root / 'ccnet/seafile.ini').write_text(str(data))
        return SimpleNamespace(returncode=0)
    rpc_calls = []
    def rpc(value):
        rpc_calls.append(value)
        if value['action'] == 'probe':
            assert not client.private_root.exists()
            return 'available'
        assert value['private'] == str(client.private_root) and value['library'] == LIBRARY
        assert value['info']['token'] == TOKEN and 'profile' not in value
        assert not (client.private_root / 'account.ini').exists()
        assert __import__('json').loads((client.private_root/'orion-linux-client.json').read_text())['state'] == 'pending'
        return 'failed' if fail_sync else 'link_requested'
    monkeypatch.setattr(cloud, '_linux_rpc_request', rpc)
    monkeypatch.setattr(cloud, '_linux_daemon_alive', lambda data: data == client.private_root/'seafile-data')
    monkeypatch.setattr(cloud, '_download_info', lambda selected: {'repo_version': 1, 'repo_name': 'Synthetic library',
        'token': TOKEN, 'email': profile.user, 'permission': 'rw'})
    monkeypatch.setenv('HTTP_PROXY', 'http://proxy.example.invalid')
    monkeypatch.setattr(cloud.subprocess, 'run', run)
    if fail_sync:
        with pytest.raises(ValueError, match='Existing profiles were preserved'):
            client.setup(profile, folder)
    else:
        assert client.setup(profile, folder) == {'state': 'link_requested', 'needs_library_link': False}
    assert [command[1] for command, _ in calls] == ['init', 'start'] + (['stop'] if fail_sync else [])
    assert [value['action'] for value in rpc_calls] == ['probe', 'clone']
    assert not (client.private_root / 'account.ini').exists()
    marker = client.private_root / 'orion-linux-client.json'
    assert marker.exists()
    if marker.exists():
        assert TOKEN not in marker.read_text() and profile.user not in marker.read_text()
        assert __import__('json').loads(marker.read_text())['state'] == ('pending' if fail_sync else 'link_requested')


def test_linux_missing_rpc_support_fails_before_initializing_or_fetching_credentials(setup, monkeypatch):
    client, folder, profile = setup
    monkeypatch.setattr(cloud, '_linux_rpc_request', lambda value: 'failed')
    monkeypatch.setattr(cloud, '_download_info', lambda *a: pytest.fail('No account HTTP when unsupported'))
    monkeypatch.setattr(cloud.subprocess, 'run', lambda *a, **k: pytest.fail('No daemon or profile changes'))
    with pytest.raises(ValueError, match='No profile was replaced'):
        client.setup(profile, folder)
    assert not client.private_root.exists()


def test_linux_worker_uses_isolated_system_python_and_secret_stdin(setup, monkeypatch):
    from types import SimpleNamespace
    calls = []
    monkeypatch.setenv('HTTP_PROXY', 'http://synthetic-proxy.invalid')
    monkeypatch.setenv('PYTHONPATH', '/untrusted-import')
    monkeypatch.setattr(cloud.subprocess, 'run', lambda command, **options:
        calls.append((command, options)) or SimpleNamespace(returncode=0, stdout=b'{"state":"link_requested"}'))
    value = {'action': 'clone', 'info': {'token': TOKEN}}
    assert cloud._linux_rpc_request(value) == 'link_requested'
    command, options = calls[0]
    assert command[:2] == ['/usr/bin/python3', '-I'] and Path(command[2]).name == 'cloud-rpc-linux.py'
    assert TOKEN not in str(command) and TOKEN.encode() in options['input']
    assert options['timeout'] == 20 and options['stderr'] == cloud.subprocess.DEVNULL
    assert 'HTTP_PROXY' not in options['env'] and 'PYTHONPATH' not in options['env']


@pytest.mark.parametrize('output', [b'{"state":"synced"}', b'{"state":"failed","token":"secret"}', b'x'*129])
def test_linux_worker_rejects_nonfinite_or_oversize_output(monkeypatch, output):
    from types import SimpleNamespace
    monkeypatch.setattr(cloud.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=output))
    with pytest.raises(ValueError, match='interface is unavailable'):
        cloud._linux_rpc_request({'action': 'probe'})


def _workspace(tmp_path, monkeypatch, state, result=None):
    from types import SimpleNamespace
    from orion_mini.link_service import LinkWorkspace
    workspace = LinkWorkspace(tmp_path / 'orion')
    workspace.settings['hub'] = {'paired': True, 'device_id': 'dev_' + 'a' * 32,
                                 'base_url': 'http://100.64.0.1:8765'}
    calls = []
    client = SimpleNamespace(detect=lambda: state,
                             setup=lambda profile, folder: calls.append((profile, folder)) or result)
    monkeypatch.setattr(workspace, 'cloud_client', lambda: client)
    return workspace, calls


def test_existing_owner_binding_never_requests_new_account(tmp_path, monkeypatch):
    from orion_mini import hub_client
    folder = tmp_path / 'Cloud'
    folder.mkdir()
    state = cloud.ClientStatus(True, True, True, False,
                               (cloud._Binding(LIBRARY, folder, 'http://100.64.0.2:8080'),))
    workspace, calls = _workspace(tmp_path, monkeypatch, state)
    monkeypatch.setattr(hub_client, 'signed', lambda *a: pytest.fail('Existing binding needs no account provisioning'))
    assert workspace.dispatch('cloud.setup', {'folder': str(folder), 'libraries': [LIBRARY]}) == {
        'state': 'existing_binding', 'needs_library_link': False}
    assert calls == []


def test_new_library_uses_only_paired_hub_profile_and_approved_folder(tmp_path, monkeypatch):
    from orion_mini import hub_client
    folder = tmp_path / 'Cloud'
    folder.mkdir()
    workspace, calls = _workspace(tmp_path, monkeypatch, cloud.ClientStatus(True, False, True, False),
                                  {'state': 'link_requested', 'needs_library_link': False})
    hub_calls = []
    def signed(root, config, path, method, body):
        hub_calls.append((path, method, body))
        return {'profile': {'schema': 1, 'server': 'http://100.64.0.2:8080', 'user': 'device@example.invalid',
                            'token': TOKEN, 'token_scope': 'account',
                            'libraries': [{'id': LIBRARY, 'name': 'Shared', 'permission': 'rw'}]}}
    monkeypatch.setattr(hub_client, 'signed', signed)
    result = workspace.dispatch('cloud.setup', {'folder': str(folder), 'libraries': [LIBRARY]})
    assert result == {'state': 'link_requested', 'needs_library_link': False}
    assert hub_calls == [('/v1/link/cloud/profile', 'POST', {'libraries': [LIBRARY]})]
    assert calls[0][1] == folder and calls[0][0].token == TOKEN
    assert workspace.settings['cloud']['path'] == str(folder)
    assert TOKEN not in str(result)


@pytest.mark.parametrize('selection', [[], [LIBRARY, OTHER], ['invalid']])
def test_setup_rejects_invalid_consent_without_provisioning(tmp_path, monkeypatch, selection):
    from orion_mini import hub_client
    workspace, _ = _workspace(tmp_path, monkeypatch, cloud.ClientStatus(True, False, True, False))
    monkeypatch.setattr(hub_client, 'signed', lambda *a: pytest.fail('No account before valid selection'))
    with pytest.raises(ValueError, match='Choose one shared library'):
        workspace.dispatch('cloud.setup', {'folder': str(tmp_path), 'libraries': selection})


def test_setup_never_overwrites_existing_account(tmp_path, monkeypatch):
    from orion_mini import hub_client
    workspace, _ = _workspace(tmp_path, monkeypatch, cloud.ClientStatus(True, True, True, False))
    monkeypatch.setattr(hub_client, 'signed', lambda *a: pytest.fail('Existing account must be preserved'))
    with pytest.raises(ValueError, match='kept unchanged'):
        workspace.dispatch('cloud.setup', {'folder': str(tmp_path), 'libraries': [LIBRARY]})


def test_cloud_info_never_forwards_credentials_or_raw_server_errors(tmp_path, monkeypatch):
    from orion_mini import hub_client
    workspace, _ = _workspace(tmp_path, monkeypatch, cloud.ClientStatus(True, False, True, False))
    monkeypatch.setattr(hub_client, 'signed', lambda *a: {'configured': True, 'state': 'available',
                        'libraries': [{'id': LIBRARY, 'name': 'Shared', 'permission': 'rw'}], 'token': TOKEN})
    result = workspace.dispatch('cloud.info', {})
    assert TOKEN not in str(result) and set(result) == {'configured', 'state', 'libraries'}
    def failed(*args):
        raise RuntimeError(TOKEN)
    monkeypatch.setattr(hub_client, 'signed', failed)
    with pytest.raises(ValueError) as failure:
        workspace.dispatch('cloud.info', {})
    assert TOKEN not in str(failure.value)


def test_cloud_status_does_not_block_ui_or_start_duplicate_probes(tmp_path, monkeypatch):
    import threading
    import time
    from orion_mini.link_service import LinkWorkspace
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def slow_status(root):
        calls.append(root)
        started.set()
        assert release.wait(5)
        finished.set()
        return {'installed': True, 'profile_present': True, 'inspection_complete': True,
                'prepared': False, 'selected_libraries': 1, 'state': 'existing_profile'}
    monkeypatch.setattr(cloud, 'status', slow_status)
    workspace = LinkWorkspace(tmp_path)
    result = workspace.cloud_status()
    assert result['state'] == 'inspection_pending'
    assert started.wait(2)
    assert workspace.cloud_status()['state'] == 'inspection_pending'
    assert len(calls) == 1
    release.set()
    assert finished.wait(2)
    deadline = time.monotonic() + 2
    while not getattr(workspace, '_cloud_status_cache', None) and time.monotonic() < deadline:
        time.sleep(0.001)
    assert workspace.cloud_status()['selected_libraries'] == 1
    assert len(calls) == 1


def test_binary_verification_rejects_modified_dependency_before_code_load(tmp_path, monkeypatch):
    import hashlib
    binary = tmp_path / 'bin'
    binary.mkdir()
    for name in ('libsearpc.dll', 'seaf-daemon.exe'):
        (binary / name).write_bytes(b'verified synthetic binary')
    hashes = {name: hashlib.sha256((binary / name).read_bytes()).hexdigest()
              for name in ('libsearpc.dll', 'seaf-daemon.exe')}
    monkeypatch.setattr(cloud, '_WINDOWS_BINARIES', hashes)
    assert cloud._verified_binary(binary) == binary
    (binary / 'libsearpc.dll').write_bytes(b'untrusted replacement')
    with pytest.raises(ValueError, match='verified official'):
        cloud._verified_binary(binary)
    (binary / 'libsearpc.dll').write_bytes(b'verified synthetic binary')
    (binary / 'KERNEL32.dll').touch()
    with pytest.raises(ValueError, match='inspection'):
        cloud._verified_binary(binary)


def test_worker_dispatch_keeps_private_payload_out_of_arguments(setup, monkeypatch):
    from types import SimpleNamespace
    calls = []
    def run(command, **options):
        calls.append((command, options))
        return SimpleNamespace(returncode=0, stdout=b'{"state":"link_requested"}')
    monkeypatch.setattr(cloud.subprocess, 'run', run)
    value = {'action': 'clone', 'profile': {'token': TOKEN}}
    assert cloud._worker_request(value) == 'link_requested'
    assert TOKEN not in str(calls[0][0])
    assert TOKEN.encode() in calls[0][1]['input']
    assert calls[0][1]['stderr'] == cloud.subprocess.DEVNULL
    assert cloud._worker_command()[1:] == ['-m', 'orion_mini.cloud_client', '--cloud-rpc-worker']
    monkeypatch.setattr(cloud.sys, 'frozen', True, raising=False)
    assert cloud._worker_command()[1:] == ['--cloud-rpc-worker']


@pytest.mark.parametrize('output', [b'{"state":"synced"}', b'{"state":"failed","token":"private"}', b'x'*129])
def test_worker_replies_are_finite_and_do_not_echo_native_errors(monkeypatch, output):
    from types import SimpleNamespace
    monkeypatch.setattr(cloud.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=output))
    with pytest.raises(ValueError) as failure:
        cloud._worker_request({'action': 'probe'})
    assert 'private' not in str(failure.value)


@pytest.mark.parametrize('encrypted,email,valid', [('', 'abc@auth.local', True),
    (0, 'device@example.invalid', True), (1, 'device@example.invalid', False),
    ('', 'line\nbreak', False), (True, 'device@example.invalid', False)])
def test_download_info_accepts_official_virtual_identity_and_rejects_encrypted_libraries(setup, monkeypatch, encrypted, email, valid):
    import io
    import json
    from types import SimpleNamespace
    profile = setup[2]
    response = {'repo_id': LIBRARY, 'encrypted': encrypted, 'email': email, 'permission': 'rw',
                'repo_version': 1, 'repo_name': 'Synthetic', 'token': TOKEN}
    calls = []
    def open_request(request, **options):
        calls.append((request, options))
        return io.BytesIO(json.dumps(response).encode())
    monkeypatch.setattr(cloud, 'build_opener', lambda *handlers: SimpleNamespace(open=open_request))
    if valid:
        assert cloud._download_info(profile)['email'] == email
    else:
        with pytest.raises(ValueError):
            cloud._download_info(profile)
    assert calls[0][0].full_url.endswith(f'/api2/repos/{LIBRARY}/download-info/')
    assert TOKEN not in calls[0][0].full_url
    assert calls[0][1]['timeout'] == 10


@pytest.mark.skipif(os.name != 'nt', reason='Windows native adapter mock')
@pytest.mark.parametrize('mode', ['absent', 'conflict', 'probe', 'clone', 'foreign_pid'])
def test_native_rpc_only_mutates_matching_owned_profile_and_frees_transport(setup, monkeypatch, mode):
    import ctypes
    from types import SimpleNamespace
    client, folder, profile = setup
    calls, buffers = [], []
    class Function:
        def __init__(self, callback): self.callback = callback
        def __call__(self, *args): return self.callback(*args)
    def username(buffer, size):
        buffer.value = b'SyntheticUser'
        return 1
    def call(rpc, name, error, count, *args):
        calls.append((name, count.value, args))
        value = ('other-folder' if mode == 'conflict' else str(folder)) if name == b'seafile_get_config' else LIBRARY
        buffers.append(ctypes.create_string_buffer(value.encode()))
        return ctypes.addressof(buffers[-1])
    library = SimpleNamespace(
        searpc_create_named_pipe_client=Function(lambda path: 123),
        searpc_client_with_named_pipe_transport=Function(lambda transport, service: 456),
        searpc_named_pipe_client_connect=Function(lambda transport: -1 if mode == 'absent' else 0),
        searpc_free_client_with_pipe_transport=Function(lambda rpc: calls.append(('freed', rpc))),
        searpc_client_call__string=Function(call))
    glib = SimpleNamespace(g_free=Function(lambda value: None), g_error_free=Function(lambda value: None))
    monkeypatch.setattr(ctypes, 'CDLL', lambda path, **k: glib if Path(path).name == 'glib-2.0-0.dll' else library)
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *a, **k: SimpleNamespace(GetUserNameA=username))
    monkeypatch.setattr(cloud, '_verified_binary', lambda path: path)
    monkeypatch.setattr(cloud, '_pipe_server_pid', lambda transport: 5678 if mode == 'foreign_pid' else 1234)
    binary = client.executable.parent
    monkeypatch.setattr(cloud, '_read_owned', lambda *a, **k: {'binary': str(binary), 'folder': str(folder), 'library': LIBRARY})
    monkeypatch.setattr(cloud, '_download_info', lambda p: {'repo_version': 1, 'repo_name': 'Synthetic',
                                                        'token': TOKEN, 'email': 'abc@auth.local', 'permission': 'r'})
    value = {'action': 'clone' if mode in {'clone', 'foreign_pid'} else 'probe', 'binary': str(binary),
             'folder': str(folder), 'private': str(client.private_root), 'pid': 1234,
             'profile': {'server': profile.server, 'user': profile.user, 'token': TOKEN,
                         'library_id': LIBRARY, 'token_scope': 'account'}}
    assert cloud._native_rpc(value) == {'probe': 'matching', 'clone': 'link_requested', 'foreign_pid': 'conflict'}.get(mode, mode)
    clone = [row for row in calls if row[0] == b'seafile_clone']
    assert bool(clone) == (mode == 'clone')
    if clone:
        assert clone[0][1] == 11
        assert len(clone[0][2]) == 22
        assert clone[0][2][0].value == b'string'
        assert clone[0][2][2].value == b'int'
        assert clone[0][2][9].value == TOKEN.encode()
        assert clone[0][2][15].value == b'abc@auth.local'
        assert b'"is_readonly": 1' in clone[0][2][-1].value
    assert calls[-1] == ('freed', 456)


@pytest.mark.parametrize('initial', ['absent', 'conflict', 'matching', 'failed'])
def test_windows_setup_preserves_owner_and_initializes_only_after_absent_probe(setup, monkeypatch, initial):
    import json
    from types import SimpleNamespace
    client, folder, profile = setup
    client.platform = 'win32'
    monkeypatch.setattr(cloud, '_verified_binary', lambda path: path)
    calls = []
    results = iter([initial, 'matching', 'link_requested'])
    def request(value, **options):
        calls.append(dict(value))
        return next(results)
    monkeypatch.setattr(cloud, '_worker_request', request)
    started = []
    monkeypatch.setattr(cloud, '_start_owned', lambda *a: started.append(a) or SimpleNamespace(poll=lambda: None, pid=1234))
    if initial != 'absent':
        with pytest.raises(ValueError, match='preserved'):
            client.setup(profile, folder)
        assert not client.private_root.exists() and not started
    else:
        assert client.setup(profile, folder) == {'state': 'link_requested', 'needs_library_link': False}
        marker = json.loads((client.private_root / 'orion-client.json').read_text())
        assert marker['state'] == 'link_requested' and TOKEN not in str(marker)
        assert not client.preconfiguration.exists()
        assert calls[-1]['profile']['token'] == TOKEN
        assert cloud._read_owned(client.private_root)['library'] == LIBRARY


def test_supervisor_is_throttled_and_never_starts_for_conflicting_owner(setup, monkeypatch):
    import json
    from types import SimpleNamespace
    client, folder, _ = setup
    client.private_root.mkdir()
    (client.private_root / 'orion-client.json').write_text('{}')
    supervisor = cloud.CloudSupervisor(client.private_root)
    marker = {'binary': str(client.executable.parent), 'folder': str(folder)}
    monkeypatch.setattr(cloud.sys, 'platform', 'win32')
    monkeypatch.setattr(cloud, '_read_owned', lambda root: marker)
    starts, probes = [], []
    monkeypatch.setattr(cloud, '_start_owned', lambda *a: starts.append(a) or SimpleNamespace(poll=lambda: None))
    monkeypatch.setattr(cloud, '_worker_request', lambda *a, **k: probes.append(a) or 'conflict')
    # Run scheduled background work immediately for a deterministic lifecycle test.
    monkeypatch.setattr(cloud.threading, 'Thread', lambda target, **k: SimpleNamespace(start=target))
    supervisor.poll(); supervisor.poll()
    assert len(probes) == 1 and not starts
    supervisor.next_probe = 0
    monkeypatch.setattr(cloud, '_worker_request', lambda *a, **k: 'absent')
    supervisor.poll()
    assert len(starts) == 1
    supervisor.next_probe = 0
    supervisor.poll()
    assert len(starts) == 1  # still-running owned handle prevents duplicate launch
    supervisor.stop(); supervisor.next_probe = 0
    supervisor.poll()
    assert len(starts) == 1


@pytest.mark.parametrize('bad', ['repo_id', 'size', 'redirect'])
def test_download_metadata_rejects_other_library_oversize_and_redirect(setup, monkeypatch, bad):
    import io
    import json
    from types import SimpleNamespace
    response = {'repo_id': OTHER if bad == 'repo_id' else LIBRARY, 'encrypted': '',
                'repo_name': 'Synthetic', 'repo_version': 1, 'email': 'virtual@auth.local',
                'permission': 'rw', 'token': TOKEN}
    class Reply(io.BytesIO):
        pass
    content = b'x' * 16385 if bad == 'size' else json.dumps(response).encode()
    def open_request(*args, **kwargs):
        if bad == 'redirect':
            cloud._NoRedirect().redirect_request(None, None, None, None, None, None)
        return Reply(content)
    monkeypatch.setattr(cloud, 'build_opener', lambda *h: SimpleNamespace(open=open_request))
    with pytest.raises(ValueError):
        cloud._download_info(setup[2])


def test_failed_clone_stops_only_new_owned_daemon_and_never_supervises_pending_profile(setup, monkeypatch):
    import json
    from types import SimpleNamespace
    client, folder, profile = setup
    client.platform = 'win32'
    monkeypatch.setattr(cloud, '_verified_binary', lambda path: path)
    replies = iter(['absent', 'matching', 'failed'])
    monkeypatch.setattr(cloud, '_worker_request', lambda *a, **k: next(replies))
    stopped = []
    process = SimpleNamespace(poll=lambda: None, pid=1234, terminate=lambda: stopped.append('terminate'),
                              wait=lambda **k: stopped.append('wait'))
    monkeypatch.setattr(cloud, '_start_owned', lambda *a: process)
    with pytest.raises(ValueError, match='preserved'):
        client.setup(profile, folder)
    assert stopped == ['terminate', 'wait']
    marker = json.loads((client.private_root / 'orion-client.json').read_text())
    assert marker['state'] == 'pending' and TOKEN not in str(marker)
    with pytest.raises(ValueError, match='inspection'):
        cloud._read_owned(client.private_root)


@pytest.mark.skipif(os.name != 'nt', reason='Windows finite worker dispatch')
@pytest.mark.parametrize('payload', [b'{"action":"arbitrary"}', b'x' * 16385,
                                   b'{"action":"probe","binary":"x","folder":"x","extra":1}'])
def test_worker_main_rejects_extra_actions_and_bounds_stdin_without_native_load(monkeypatch, payload):
    import io
    outgoing = io.BytesIO()
    monkeypatch.setattr(cloud, '_worker_stream', lambda number: (io.BytesIO(payload) if number == 0 else outgoing, False))
    monkeypatch.setattr(cloud, '_native_rpc', lambda value: pytest.fail('Invalid requests never load native code'))
    assert cloud.rpc_worker_main() == 0
    assert outgoing.getvalue() == b'{"state": "failed"}'


@pytest.mark.parametrize('signature_ok', [False, True])
def test_component_install_verifies_before_extraction_and_preserves_profiles(setup, monkeypatch, signature_ok):
    from types import SimpleNamespace
    client, folder, _ = setup
    client.platform = 'win32'
    # This Windows adapter is intentionally mocked on Linux too; the host's
    # subprocess module has no Windows process-creation constant there.
    monkeypatch.setattr(cloud.subprocess, 'CREATE_NO_WINDOW', 0x08000000, raising=False)
    client.executable.unlink()
    calls = []
    def download(path):
        calls.append('download')
        path.write_bytes(b'synthetic signed MSI')
    def signature(path):
        calls.append('signature')
        if not signature_ok:
            raise ValueError('Synthetic untrusted signature')
    def extract(command, **options):
        calls.append('extract')
        assert command[1] == '/a' and TOKEN not in str(command)
        root = Path(next(v for v in command if v.startswith('TARGETDIR='))[10:])
        (root / 'PFiles/Seafile/bin').mkdir(parents=True)
        (root / 'PFiles/Seafile/bin/seafile-applet.exe').touch()
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(cloud, '_download_installer', download)
    monkeypatch.setattr(cloud, '_verify_installer_signature', signature)
    monkeypatch.setattr(cloud.subprocess, 'run', extract)
    monkeypatch.setattr(cloud, '_verified_binary', lambda path: path)
    if signature_ok:
        assert client.install(consent=True) == {'installed': True, 'existing_preserved': False}
        assert calls == ['download', 'signature', 'extract']
        assert client.executable.is_file()
    else:
        with pytest.raises(ValueError, match='preserved'):
            client.install(consent=True)
        assert calls == ['download', 'signature']
        assert not (client.private_root.parent / 'tools/seafile/9.0.21').exists()
    assert not client.private_root.exists() and folder.is_dir()


def test_component_install_requires_deliberate_consent_and_never_replaces_existing_client(setup, monkeypatch):
    client, _, _ = setup
    client.platform = 'win32'
    monkeypatch.setattr(cloud, '_download_installer', lambda path: pytest.fail('Existing client/absent consent needs no download'))
    with pytest.raises(ValueError, match='Approve'):
        client.install()
    assert client.install(consent=True) == {'installed': True, 'existing_preserved': True}


@pytest.mark.parametrize('outcome', ['success', 'denied', 'missing', 'timeout'])
def test_linux_component_install_is_os_approved_fixed_and_preserves_profiles(setup, monkeypatch, outcome):
    from types import SimpleNamespace
    client, folder, _ = setup
    client.executable.unlink()
    config = client.profile_dirs[0]
    config.mkdir();sentinel = config / 'keep-owner-profile';sentinel.write_text('synthetic owner state')
    calls = []
    helper = Path(__file__).resolve().parents[1] / 'assets/install-cloud-linux.sh'
    monkeypatch.setattr(cloud, 'linux_install_helper', lambda: helper)
    monkeypatch.setattr(cloud.shutil, 'which', lambda name: '/usr/bin/pkexec' if name == 'pkexec' else None)
    monkeypatch.setattr(cloud, 'installed_linux_cli', lambda: None if outcome == 'missing' else Path('/usr/bin/seaf-cli'))
    monkeypatch.setenv('LD_LIBRARY_PATH', '/frozen/private-libraries')
    monkeypatch.setenv('PYTHONPATH', '/frozen/private-python')
    def install(args, **options):
        calls.append((args, options))
        assert args == ['/usr/bin/pkexec', '/bin/sh', str(helper)]
        assert 'LD_LIBRARY_PATH' not in options['env'] and 'PYTHONPATH' not in options['env']
        assert not options.get('shell') and options['timeout'] == 600
        if outcome == 'timeout':raise cloud.subprocess.TimeoutExpired('private synthetic command', 600)
        return SimpleNamespace(returncode=126 if outcome == 'denied' else 0)
    monkeypatch.setattr(cloud.subprocess, 'run', install)
    if outcome == 'success':
        assert client.install(consent=True) == {'installed': True, 'existing_preserved': False}
        assert client.executable == Path('/usr/bin/seaf-cli')
    else:
        with pytest.raises(ValueError, match='preserved') as error:client.install(consent=True)
        assert 'private synthetic' not in str(error.value)
    assert len(calls) == 1 and sentinel.read_text() == 'synthetic owner state'
    assert not client.private_root.exists() and folder.is_dir()


def test_linux_install_needs_polkit_and_deliberate_consent_and_keeps_existing_client(setup, monkeypatch):
    client, _, _ = setup
    monkeypatch.setattr(cloud.subprocess, 'run', lambda *a, **k: pytest.fail('No install without OS approval'))
    with pytest.raises(ValueError, match='Approve'):client.install()
    assert client.install(consent=True)['existing_preserved']
    client.executable.unlink()
    monkeypatch.setattr(cloud.shutil, 'which', lambda name: None)
    with pytest.raises(ValueError, match='approval'):client.install(consent=True)
    assert not cloud.installation_supported('linux')


def _linux_owned_fixture(setup):
    import json
    client, folder, _ = setup
    client.private_root.mkdir(mode=0o700)
    (client.private_root / 'ccnet').mkdir()
    data = client.private_root / 'seafile-data'
    data.mkdir()
    (client.private_root / 'ccnet/seafile.ini').write_text(str(data))
    marker = {'schema': 1, 'executable': str(client.executable), 'folder': str(folder),
              'library': LIBRARY, 'state': 'link_requested'}
    (client.private_root / 'orion-linux-client.json').write_text(json.dumps(marker))
    return client, data


def test_linux_supervisor_resumes_only_successful_owned_marker_and_stops(setup, monkeypatch):
    from types import SimpleNamespace
    client, _ = _linux_owned_fixture(setup)
    monkeypatch.setattr(cloud.sys, 'platform', 'linux')
    calls = []
    monkeypatch.setattr(cloud, '_resume_linux_owned', lambda root: calls.append(root))
    monkeypatch.setattr(cloud.threading, 'Thread', lambda target, **k: SimpleNamespace(start=target))
    supervisor = cloud.CloudSupervisor(client.private_root)
    supervisor.poll(); supervisor.poll()
    assert calls == [client.private_root]
    supervisor.stop(); supervisor.next_probe = 0; supervisor.poll()
    assert calls == [client.private_root]
    (client.private_root / 'orion-linux-client.json').unlink()
    supervisor = cloud.CloudSupervisor(client.private_root)
    supervisor.poll()
    assert calls == [client.private_root]


@pytest.mark.parametrize('change', ['outside_data', 'pending', 'bad_library', 'missing_executable'])
def test_linux_owned_marker_refuses_redirected_or_incomplete_profile(setup, change):
    import json
    client, _ = _linux_owned_fixture(setup)
    path = client.private_root / 'orion-linux-client.json'
    marker = json.loads(path.read_text())
    if change == 'outside_data':
        (client.private_root / 'ccnet/seafile.ini').write_text(str(client.home))
    elif change == 'pending':
        marker['state'] = 'pending'
    elif change == 'bad_library':
        marker['library'] = 'not-a-library'
    else:
        marker['executable'] = str(client.home / 'missing-seaf-cli')
    path.write_text(json.dumps(marker))
    with pytest.raises((ValueError, FileNotFoundError)):
        cloud._read_linux_owned(client.private_root)


@pytest.mark.skipif(os.name == 'nt', reason='Upstream daemon lock is a Unix flock')
def test_linux_resume_preserves_locked_pid_file_and_starts_only_unlocked_profile(setup, monkeypatch):
    import fcntl
    import subprocess
    import sys
    client, data = _linux_owned_fixture(setup)
    pidfile = data / 'seaf-daemon.pid'
    pidfile.write_text('synthetic-pid\n')
    calls = []
    monkeypatch.setenv('LD_LIBRARY_PATH', '/frozen-app/libs')
    monkeypatch.setenv('LD_LIBRARY_PATH_ORIG', '/approved/system/libs')
    monkeypatch.setenv('PYTHONPATH', '/frozen-app/python')
    monkeypatch.setenv('HTTP_PROXY', 'http://proxy.example.invalid')
    def run(command, **kwargs):
        calls.append((command, kwargs))
        monkeypatch.setattr(cloud, '_linux_daemon_alive', lambda data: True)
        return type('Result', (), {'returncode': 0})()
    monkeypatch.setattr(cloud.subprocess, 'run', run)
    # A separate process holds the actual lock, just as upstream seaf-daemon.
    with subprocess.Popen([sys.executable, '-c',
            'import fcntl,sys; f=open(sys.argv[1],"r+"); fcntl.flock(f,fcntl.LOCK_EX); print("ready",flush=True); sys.stdin.read()',
            str(pidfile)], stdin=subprocess.PIPE, stdout=subprocess.PIPE) as holder:
        assert holder.stdout.readline().strip() == b'ready'
        cloud._resume_linux_owned(client.private_root)
        assert not calls and pidfile.read_text() == 'synthetic-pid\n'
        holder.communicate(b'', timeout=5)
    cloud._resume_linux_owned(client.private_root)
    assert len(calls) == 1 and calls[0][0] == [str(client.executable), 'start', '-c', str(client.private_root / 'ccnet')]
    environment = calls[0][1]['env']
    assert environment['LD_LIBRARY_PATH'] == '/approved/system/libs'
    assert 'PYTHONPATH' not in environment and 'HTTP_PROXY' not in environment
    assert pidfile.read_text() == 'synthetic-pid\n'


@pytest.mark.skipif(os.name == 'nt', reason='Official daemon uses a Unix socket')
def test_linux_resume_uses_existing_socket_on_cli_without_pid_lock(setup, monkeypatch):
    import socket
    client, data = _linux_owned_fixture(setup)
    monkeypatch.setattr(cloud.subprocess, 'run', lambda *a, **k: pytest.fail('Existing daemon must not be restarted'))
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as daemon:
        daemon.bind(str(data / 'seafile.sock'))
        daemon.listen(2)
        cloud._resume_linux_owned(client.private_root)
    assert not (data / 'seaf-daemon.pid').exists()


def test_unmanaged_profile_health_never_launches_or_inspects_a_daemon(setup, monkeypatch):
    client, folder, _ = setup
    existing(client, folder)
    monkeypatch.setattr(cloud, '_worker_request', lambda *a, **k: pytest.fail('Do not adopt existing owner daemon'))
    monkeypatch.setattr(cloud, '_linux_daemon_alive', lambda *a: pytest.fail('Do not adopt existing owner daemon'))
    assert cloud.owned_service_status(client.private_root, platform='linux') == 'not_managed'
    assert cloud.owned_service_status(client.private_root, platform='win32') == 'not_managed'


@pytest.mark.parametrize('reachable', [True, False])
def test_linux_owned_health_is_read_only_and_contains_no_private_metadata(setup, monkeypatch, reachable):
    client, data = _linux_owned_fixture(setup)
    files = {path:path.read_bytes() for path in client.private_root.rglob('*') if path.is_file()}
    monkeypatch.setattr(cloud.subprocess, 'run', lambda *a, **k: pytest.fail('No CLI/status/init command'))
    monkeypatch.setattr(cloud, '_linux_daemon_alive', lambda path: reachable if path == data else pytest.fail('Wrong profile'))
    result = cloud.owned_service_status(client.private_root, platform='linux')
    assert result == ('reachable' if reachable else 'unavailable')
    assert {path:path.read_bytes() for path in client.private_root.rglob('*') if path.is_file()} == files
    assert LIBRARY not in result and TOKEN not in result and str(client.home) not in result


@pytest.mark.parametrize('result,expected', [('matching','reachable'),('absent','unavailable'),('conflict','needs_attention'),('failed','unavailable'),('timeout','unavailable')])
def test_windows_owned_health_uses_finite_identity_checked_probe(setup, monkeypatch, result, expected):
    client, folder, _ = setup
    client.private_root.mkdir();(client.private_root/'orion-client.json').touch()
    marker={'binary':str(client.home/'binary'),'folder':str(folder)}
    monkeypatch.setattr(cloud, '_read_owned', lambda path: marker if path == client.private_root else pytest.fail('Wrong private profile'))
    calls=[]
    def request(value):
        calls.append(value)
        if result == 'timeout':raise ValueError('synthetic private detail')
        return result
    monkeypatch.setattr(cloud, '_worker_request', request)
    assert cloud.owned_service_status(client.private_root, platform='win32') == expected
    assert calls == [{'action':'probe',**marker}]


def test_malformed_owned_marker_needs_attention_without_fallback(setup, monkeypatch):
    client, _ = _linux_owned_fixture(setup)
    (client.private_root/'orion-linux-client.json').write_text('{"secret":"synthetic-private-detail"}')
    monkeypatch.setattr(cloud, '_linux_daemon_alive', lambda *a: pytest.fail('No fallback profile'))
    assert cloud.owned_service_status(client.private_root, platform='linux') == 'needs_attention'


def test_management_discovery_and_safe_status_do_not_open_cli_or_gui(setup, monkeypatch):
    client, _, _ = setup
    monkeypatch.setattr(cloud, 'SeafileClient', lambda **kwargs: client)
    monkeypatch.setattr(cloud.shutil, 'which', lambda name: None)
    monkeypatch.setattr(cloud.subprocess, 'Popen', lambda *a, **k: pytest.fail('Read-only status must not launch GUI'))
    result=cloud.status(client.private_root)
    assert result['management_available'] is False and result['service_state']=='not_managed'
    assert not client.private_root.exists()
    monkeypatch.setattr(cloud.shutil, 'which', lambda name: '/usr/bin/seafile-applet')
    assert cloud.status(client.private_root)['management_available'] is True
