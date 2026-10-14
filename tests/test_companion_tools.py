# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path
import os
import pytest

from orion_mini.deskflow import configuration
from orion_mini.companion_tools import tool_path


@pytest.mark.skipif(os.name != 'nt', reason='Windows portable executable discovery')
def test_portable_discovery_requires_upstream_marker_and_prefers_latest(tmp_path, monkeypatch):
    monkeypatch.setattr('orion_mini.companion_tools.shutil.which', lambda _: None)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    root = tmp_path / 'OrionMini/tools/scrcpy'
    for version in ('4.0.0', '5.0.1', '99.0.0'):
        folder = root / version
        folder.mkdir(parents=True)
        (folder / 'adb.exe').write_bytes(b'fixture executable')
        if version != '99.0.0':
            (folder / 'orion-upstream.json').write_text('{}')
    # Hosted runners set both SDK variables; either would win over the portable copy.
    monkeypatch.delenv('ANDROID_HOME', raising=False)
    monkeypatch.delenv('ANDROID_SDK_ROOT', raising=False)
    assert Path(tool_path('adb')).parent.name == '5.0.1'
    assert tool_path('adb', tmp_path / 'missing.exe') is None
    with pytest.raises(ValueError):
        tool_path('arbitrary-command')


def _fake_adb(root):
    adb = root / 'platform-tools' / ('adb.exe' if os.name == 'nt' else 'adb')
    adb.parent.mkdir(parents=True)
    adb.write_bytes(b'fixture executable')
    return adb


def test_installed_app_finds_adb_in_the_default_android_sdk(tmp_path, monkeypatch):
    # An installed Saiph has no SDK of its own; adb is often only in Android Studio's SDK.
    monkeypatch.setattr('orion_mini.companion_tools.shutil.which', lambda _: None)
    monkeypatch.delenv('ANDROID_HOME', raising=False)
    monkeypatch.delenv('ANDROID_SDK_ROOT', raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'no-portable-tools'))
    monkeypatch.setattr('orion_mini.companion_tools.default_sdk_roots', lambda: [str(tmp_path / 'missing'), str(tmp_path / 'Sdk')])
    assert tool_path('adb') is None
    adb = _fake_adb(tmp_path / 'Sdk')
    assert Path(tool_path('adb')) == adb


def test_explicit_android_sdk_root_is_used(tmp_path, monkeypatch):
    monkeypatch.setattr('orion_mini.companion_tools.shutil.which', lambda _: None)
    monkeypatch.delenv('ANDROID_HOME', raising=False)
    monkeypatch.setattr('orion_mini.companion_tools.default_sdk_roots', lambda: [])
    adb = _fake_adb(tmp_path / 'configured')
    monkeypatch.setenv('ANDROID_SDK_ROOT', str(tmp_path / 'configured'))
    assert Path(tool_path('adb')) == adb


def test_deskflow_keeps_mesh_tls_and_clipboard_constraints(tmp_path):
    path = configuration(tmp_path, role='desktop', local='100.64.0.2', certificate=tmp_path / 'Deskflow.pem')
    text = path.read_text()
    assert 'interface=100.64.0.2' in text
    assert 'enableClipboard=false' in text
    assert 'tlsEnabled=true' in text and 'checkPeerFingerprints=true' in text
    assert 'enableEnterCommand=false' in text and 'enableExitCommand=false' in text
    with pytest.raises(ValueError, match='mesh'):
        configuration(tmp_path, local='0.0.0.0')
    with pytest.raises(ValueError, match='certificate'):
        configuration(tmp_path, local='100.64.0.2', certificate='bad\n[security]\ntlsEnabled=false')
