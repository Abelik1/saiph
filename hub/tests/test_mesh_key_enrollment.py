# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unattended server setup must not disclose keys or replace existing networks."""
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from orion_hub import server_install as installer


def fake_network(monkeypatch, *, state='NeedsLogin', persisted=False):
    calls = []
    monkeypatch.setattr(installer.shutil, 'which', lambda _: 'synthetic-tailscale')
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[1:] == ['status', '--json']: return json.dumps({'BackendState': state})
        if argv[1:] == ['debug', 'prefs']:
            return json.dumps({'ControlURL': 'https://controlplane.tailscale.com', 'Persist': {'saved': True} if persisted else None})
        if argv[1:] == ['ip', '-4']: return '100.64.1.2'
        if argv[1] == 'up':
            key_files = [arg.removeprefix('--auth-key=file:') for arg in argv if arg.startswith('--auth-key=file:')]
            if key_files:
                assert Path(key_files[0]).read_bytes() == b'synthetic-one-use-enrollment-key'
                assert Path(key_files[0]).stat().st_mode & 0o077 == 0
            return ''
        return ''
    monkeypatch.setattr(installer, 'run', run)
    return calls


@pytest.mark.skipif(os.name == 'nt', reason='Actual Unix private runtime directory')
def test_auth_key_uses_ephemeral_private_file_and_no_browser_or_secret_arguments(monkeypatch, capsys, tmp_path):
    # Test the real private-file lifecycle without requiring root access to /run.
    temporary = installer.tempfile.TemporaryDirectory
    monkeypatch.setattr(installer.tempfile, 'TemporaryDirectory',
                        lambda *args, **kwargs: temporary(*args, **{**kwargs, 'dir': tmp_path}))
    calls = fake_network(monkeypatch)
    assert installer.ensure_mesh('ubuntu', 'noble', None, auth_key=b'synthetic-one-use-enrollment-key') == ('100.64.1.2', None)
    up, options = next((argv, options) for argv, options in calls if argv[1] == 'up')
    argument = next(arg for arg in up if arg.startswith('--auth-key=file:'))
    assert not Path(argument.removeprefix('--auth-key=file:')).exists()
    assert 'synthetic-one-use-enrollment-key' not in str(calls)
    assert not options.get('visible') and options['timeout'] == 130
    assert not capsys.readouterr().out


@pytest.mark.parametrize('state,persisted', [('Running', False), ('Stopped', True)])
def test_existing_network_never_consumes_enrollment_key(monkeypatch, state, persisted):
    calls = fake_network(monkeypatch, state=state, persisted=persisted)
    installer.ensure_mesh('ubuntu', 'noble', None, auth_key=b'synthetic-one-use-enrollment-key')
    assert not any('--auth-key=' in part for argv, _ in calls for part in argv)
    ups = [argv for argv, _ in calls if len(argv) > 1 and argv[1] == 'up']
    assert ups == ([['tailscale', 'up']] if state == 'Stopped' else [])


@pytest.mark.skipif(os.name == 'nt', reason='Actual Unix ownership and mode')
def test_private_key_source_is_bounded_root_owned_and_preserved(tmp_path, monkeypatch):
    path = tmp_path / 'network.key'
    path.write_bytes(b'synthetic-one-use-enrollment-key\n'); path.chmod(0o600)
    original_fstat = installer.os.fstat
    def as_root(fd):
        info = original_fstat(fd)
        return SimpleNamespace(st_mode=info.st_mode, st_uid=0, st_size=info.st_size)
    monkeypatch.setattr(installer.os, 'fstat', as_root)
    assert installer.read_mesh_auth_key(path) == b'synthetic-one-use-enrollment-key'
    assert path.exists()
    path.chmod(0o644)
    with pytest.raises(installer.SetupError, match='root-private'): installer.read_mesh_auth_key(path)
    path.chmod(0o600); path.write_bytes(b'x' * 4097)
    with pytest.raises(installer.SetupError): installer.read_mesh_auth_key(path)
    path.write_bytes(b'secret with spaces must never appear in the error')
    with pytest.raises(installer.SetupError, match='unsupported format') as error: installer.read_mesh_auth_key(path)
    assert 'secret with spaces' not in str(error.value)
    path.write_bytes(b'synthetic-one-use-enrollment-key')
    link = tmp_path / 'alias'; link.symlink_to(path)
    with pytest.raises(installer.SetupError, match='root-private'): installer.read_mesh_auth_key(link)
    assert installer.read_mesh_auth_key(None) is None
