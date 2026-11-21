# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compatibility forwarding and desktop identity do not expose new browser authority."""
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import urllib.request
import urllib.error

from orion_mini import electron_launcher, paths


def test_source_launch_forwards_without_changing_the_profile(tmp_path, monkeypatch):
    from orion_mini import enrollment, send_files
    calls = []
    monkeypatch.setattr(enrollment, 'forward_local', lambda root, route, body: calls.append((root, route, body)) or True)
    monkeypatch.setattr(enrollment, 'forward_invitation', lambda root, file: calls.append(('invitation', file)) or True)
    monkeypatch.setattr(send_files, 'forward', lambda root, files: calls.append(('files', files)) or True)
    assert electron_launcher.forward_arguments(tmp_path, [])
    assert calls[-1] == (tmp_path, '/v1/window/show', {})
    assert electron_launcher.forward_arguments(tmp_path, ['--open-phone-app', 'org.example.app'])
    assert calls[-1] == (tmp_path, '/v1/phone/app', {'package': 'org.example.app'})
    assert electron_launcher.forward_arguments(tmp_path, ['--enrollment', 'synthetic.orion-enrollment'])
    assert calls[-1] == ('invitation', 'synthetic.orion-enrollment')


def test_desktop_identity_override_is_confined_to_service_children(tmp_path, monkeypatch):
    executable = tmp_path / 'Saiph.exe'
    executable.write_bytes(b'synthetic executable identity')
    monkeypatch.setenv('SAIPH_DESKTOP_EXECUTABLE', str(executable))
    monkeypatch.setenv('SAIPH_DESKTOP_PID', '12345')
    monkeypatch.delenv('SAIPH_ELECTRON_SERVICE', raising=False)
    assert paths.desktop_executable() == Path(sys.executable).resolve()
    assert paths.desktop_pid() == os.getpid()
    monkeypatch.setenv('SAIPH_ELECTRON_SERVICE', '1')
    assert paths.desktop_executable() == executable
    assert paths.desktop_pid() == 12345
    from orion_mini.startup import startup_command
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    source = startup_command()
    assert source.endswith(' -m orion_mini')
    assert 'Saiph.exe' not in source, 'Source startup must launch Python, rather than pass -m to Electron.'


def test_window_forward_api_requires_local_auth_and_empty_body(tmp_path):
    from orion_mini.api import ApiServer
    shown = []
    delivered = threading.Event()
    def show():
        shown.append(True)
        delivered.set()
    workspace = SimpleNamespace(root=tmp_path, settings={'machine': {'name': 'Synthetic desktop'}},
                                plugins=None, request_show_window=show)
    server = ApiServer(workspace, 0)
    info = server.start()
    try:
        token = json.loads((tmp_path / 'api.json').read_text())['token']
        def post(body, *, auth=True, origin=None):
            headers = {'Content-Type': 'application/json'}
            if auth:
                headers['Authorization'] = 'Bearer ' + token
            if origin:
                headers['Origin'] = origin
            request = urllib.request.Request(info['url'] + '/v1/window/show', data=json.dumps(body).encode(), headers=headers)
            try:
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=5) as response:
                    response.read()
                    return response.status
            except urllib.error.HTTPError as error:
                return error.code
        assert post({}, auth=False) == 401
        assert post({}, origin='https://example.invalid') == 403
        assert post({'path': 'unexpected'}) == 400
        assert post({}) == 202
        assert delivered.wait(5), 'The accepted callback must be delivered after the HTTP response.'
        assert shown == [True]
    finally:
        server.stop()
