# SPDX-License-Identifier: AGPL-3.0-or-later
"""Exercise release identity gates with synthetic files; never launch the application."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


metadata = load('windows_metadata_tested', 'scripts/packaging/windows_metadata.py')
signatures = load('windows_signatures_tested', 'scripts/public-release/verify-windows-signatures.py')


def test_metadata_preserves_semver_and_internal_filename(tmp_path):
    resource, assembly = tmp_path / 'version.txt', tmp_path / 'assembly.cs'
    metadata.write_version_resource(resource, '1.2.3-beta.4', 9, 'link')
    metadata.write_assembly_metadata(assembly, '1.2.3-beta.4', 9, 'link')
    text = resource.read_text()
    assert "filevers=(1, 2, 3, 9)" in text
    assert "StringStruct('ProductName', 'Saiph')" in text
    assert "StringStruct('OriginalFilename', 'OrionMini.exe')" in text
    assert "StringStruct('ProductVersion', '1.2.3-beta.4')" in text
    assert 'AssemblyFileVersion("1.2.3.9")' in assembly.read_text()
    assert 'AssemblyInformationalVersion("1.2.3-beta.4")' in assembly.read_text()


@pytest.mark.parametrize('version,build', [('65536.0.0', 0), ('1.2.3', 65536), ('1.2.3', -1),
                                          ('1.2.3', True), ('1.2.3"injection', 0)])
def test_windows_metadata_rejects_unrepresentable_versions(version, build):
    with pytest.raises(ValueError):
        metadata.version_tuple(version, build)


@pytest.fixture
def signature_probe(tmp_path, monkeypatch):
    installer, executable = tmp_path / 'setup.exe', tmp_path / 'OrionMini.exe'
    installer.write_bytes(b'synthetic installer')
    executable.write_bytes(b'synthetic app')
    state = {'status': 'Valid', 'type': 'Authenticode', 'publisher': 'CN=Approved publisher',
             'certificate_sha256': 'a' * 64, 'timestamped': True, 'product': 'Saiph', 'version': '1.2.3-beta.4'}
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == 'powershell.exe':
            assert Path(kwargs['env']['SAIPH_SIGNATURE_PATH']).is_file()
            return subprocess.CompletedProcess(command, 0, json.dumps(state), '')
        return subprocess.CompletedProcess(command, 0, '', '')

    monkeypatch.setattr(signatures.subprocess, 'run', run)
    return installer, executable, state, calls


def invoke(probe, output):
    installer, executable, _, _ = probe
    return signatures.verify(installer, executable, 'CN=Approved publisher', 'a' * 64,
                             '1.2.3-beta.4', 'verified-sdk/signtool.exe', output)


def test_signature_receipt_tracks_verified_bytes(signature_probe, tmp_path):
    output = tmp_path / 'signature-receipt.json'
    result = invoke(signature_probe, output)
    assert result == json.loads(output.read_text())
    assert len(result['artifacts']) == 2
    assert all(call[1:6] == ['verify', '/pa', '/all', '/v', '/tw']
               for call in signature_probe[3] if call[0] != 'powershell.exe')


@pytest.mark.parametrize('field,value', [('status', 'NotSigned'), ('type', 'Catalog'),
    ('publisher', 'CN=Other publisher'), ('certificate_sha256', 'b' * 64),
    ('timestamped', False), ('product', 'Orion'), ('version', '1.2.2')])
def test_signature_gate_rejects_wrong_identity_or_missing_signature(signature_probe, tmp_path, field, value):
    signature_probe[2][field] = value
    output = tmp_path / 'signature-receipt.json'
    with pytest.raises(ValueError):
        invoke(signature_probe, output)
    assert not output.exists()


def test_signtool_warning_is_a_failed_release(signature_probe, tmp_path, monkeypatch):
    original = signatures.subprocess.run

    def warning(command, **kwargs):
        if command[0] != 'powershell.exe':
            raise subprocess.CalledProcessError(2, command)
        return original(command, **kwargs)

    monkeypatch.setattr(signatures.subprocess, 'run', warning)
    with pytest.raises(subprocess.CalledProcessError):
        invoke(signature_probe, tmp_path / 'receipt.json')


def test_changed_bytes_cannot_receive_receipt(signature_probe, tmp_path, monkeypatch):
    original = signatures.subprocess.run

    def mutation(command, **kwargs):
        result = original(command, **kwargs)
        if command[0] != 'powershell.exe':
            signature_probe[0].write_bytes(b'mutated during verification')
        return result

    monkeypatch.setattr(signatures.subprocess, 'run', mutation)
    with pytest.raises(ValueError, match='changed during'):
        invoke(signature_probe, tmp_path / 'receipt.json')


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows resource compiler and metadata API')
def test_compiled_installer_has_consistent_product_metadata_without_execution(tmp_path):
    compiler = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.is_file():
        pytest.skip('Windows Framework compiler absent')
    packaging = load('windows_packaging_metadata_tested', 'scripts/packaging/build-desktop-distribution.py')
    staging = tmp_path / 'staging'
    staging.mkdir()
    (staging / 'package-manifest.json').write_text(json.dumps({'version': '1.2.3-beta.4', 'build': 9, 'profile': 'link'}))
    output = tmp_path / 'Saiph-Link-1.2.3-beta.4-windows-x86_64.exe'
    packaging.build_windows(staging, output, compiler)
    environment = dict(os.environ, SAIPH_METADATA_PATH=str(output))
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
        '$v = (Get-Item -LiteralPath $env:SAIPH_METADATA_PATH).VersionInfo; '
        '@{product=$v.ProductName; version=$v.ProductVersion; file=$v.FileVersion} | ConvertTo-Json -Compress'],
        env=environment, check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == {'product': 'Saiph', 'version': '1.2.3-beta.4', 'file': '1.2.3.9'}
    assert not output.with_suffix('.assembly.cs').exists()
    assert not output.with_suffix('.stub.exe').exists()
