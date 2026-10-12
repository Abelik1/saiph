# SPDX-License-Identifier: AGPL-3.0-or-later
"""Finite Seafile worker: synthetic private directories, no real daemon/account."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys

import pytest

SPEC = importlib.util.spec_from_file_location('linux_cloud_rpc', Path(__file__).parents[1] / 'assets/cloud-rpc-linux.py')
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)

LIBRARY = '28ef9e21-4b47-48bd-9683-2e39113fc730'
TOKEN = 'e' * 40


@pytest.fixture
def clone_request(tmp_path):
    if sys.platform != 'linux':
        pytest.skip('Actual Unix socket/ownership validation requires Linux')
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    folder = tmp_path / 'Cloud'
    folder.mkdir()
    config = private / 'ccnet'
    config.mkdir()
    data = private / 'seafile-data'
    data.mkdir()
    (config / 'seafile.ini').write_text(str(data))
    executable = tmp_path / 'seaf-cli'
    executable.touch()
    (private / 'orion-linux-client.json').write_text(json.dumps({'schema': 1, 'executable': str(executable),
        'folder': str(folder), 'library': LIBRARY, 'state': 'pending'}))
    peer = socket.socket(socket.AF_UNIX)
    peer.bind(str(data / 'seafile.sock'))
    try:
        yield {'action': 'clone', 'private': str(private), 'folder': str(folder), 'library': LIBRARY,
            'server': 'http://100.64.1.3:80', 'info': {'repo_version': 1, 'repo_name': 'Synthetic library',
                'token': TOKEN, 'email': 'test@example.invalid', 'permission': 'rw'}}
    finally:
        peer.close()


def test_probe_checks_installed_upstream_interface_without_profile_creation():
    class RPC:
        def clone(self, *args):
            pytest.fail('Probe must not clone or connect')
    assert worker.dispatch({'action': 'probe'}, RPC) == 'available'
    with pytest.raises(ValueError):
        worker.dispatch({'action': 'probe'}, object)


def test_clone_uses_only_selected_private_socket_and_upstream_arguments(clone_request):
    calls = []
    class RPC:
        def __init__(self, path):
            calls.append(path)
        def clone(self, *args):
            calls.append(args)
            return LIBRARY
    assert worker.dispatch(clone_request, RPC) == 'link_requested'
    assert calls[0] == str(Path(clone_request['private']) / 'seafile-data/seafile.sock')
    assert calls[1][:5] == (LIBRARY, 1, 'Synthetic library', clone_request['folder'], TOKEN)
    assert calls[1][5:10] == (None, None, 'test@example.invalid', None, 0)
    assert json.loads(calls[1][10]) == {'server_url': clone_request['server'], 'is_readonly': 0}
    assert not (Path(clone_request['private']) / 'account.ini').exists()


@pytest.mark.parametrize('change', ['successful_marker', 'other_library', 'other_folder', 'public_root',
    'redirected_pointer', 'socket_symlink', 'non_socket', 'remote_origin', 'zero_port', 'extra_field', 'encrypted_field', 'bad_token'])
def test_clone_refuses_adoption_redirection_or_unvalidated_metadata(clone_request, change, tmp_path):
    private = Path(clone_request['private'])
    marker_path = private / 'orion-linux-client.json'
    marker = json.loads(marker_path.read_text())
    if change == 'successful_marker':
        marker['state'] = 'link_requested'
    elif change == 'other_library':
        marker['library'] = '11111111-1111-4111-8111-111111111111'
    elif change == 'other_folder':
        marker['folder'] = str(tmp_path)
    elif change == 'public_root':
        private.chmod(0o755)
    elif change == 'redirected_pointer':
        (private / 'ccnet/seafile.ini').write_text(str(tmp_path))
    elif change in {'socket_symlink', 'non_socket'}:
        path = private / 'seafile-data/seafile.sock'
        path.unlink()
        if change == 'socket_symlink':
            path.symlink_to(tmp_path / 'elsewhere')
        else:
            path.touch()
    elif change == 'remote_origin':
        clone_request['server'] = 'https://public.example.invalid'
    elif change == 'zero_port':
        clone_request['server'] = 'http://100.64.1.3:0'
    elif change == 'extra_field':
        clone_request['command'] = 'arbitrary'
    elif change == 'encrypted_field':
        clone_request['info']['password'] = 'unsupported'
    elif change == 'bad_token':
        clone_request['info']['token'] = 'invalid'
    marker_path.write_text(json.dumps(marker))
    class RPC:
        def __init__(self, *args):
            pytest.fail('Invalid request must never connect')
    with pytest.raises((ValueError, OSError)):
        worker.dispatch(clone_request, RPC)
