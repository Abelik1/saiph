# SPDX-License-Identifier: AGPL-3.0-or-later
"""Native notices must describe actual bytes and reject unused Qt payloads."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import shutil
import base64
import hashlib
import importlib.metadata

import pytest

SPEC = importlib.util.spec_from_file_location('native_notices', Path(__file__).parents[1] / 'scripts/packaging/native_notices.py')
notices = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notices)


def test_native_origins_cover_other_wheels_and_interpreter_exact_bytes(tmp_path, monkeypatch):
    base = tmp_path / 'python'
    library = base / 'DLLs/libssl.dll'
    library.parent.mkdir(parents=True)
    library.write_bytes(b'build interpreter library')
    wheel_bytes = b'reviewed native wheel content'
    wheel_hash = hashlib.sha256(wheel_bytes).digest()
    item = importlib.metadata.PackagePath('some_other_package/accelerator.pyd')
    item.hash = SimpleNamespace(mode='sha256', value=base64.urlsafe_b64encode(wheel_hash).decode().rstrip('='))
    distribution = SimpleNamespace(metadata={'Name': 'other-native-package'}, version='2.0', files=[item])
    monkeypatch.setattr(notices.importlib.metadata, 'distributions', lambda: [distribution])
    monkeypatch.setattr(notices.sys, 'base_prefix', str(base))
    monkeypatch.setattr(notices.sysconfig, 'get_config_var', lambda name: None)
    binaries = [{'path': '_internal/accelerator.pyd', 'sha256': wheel_hash.hex()},
                {'path': '_internal/libssl.dll', 'sha256': notices.digest(library)},
                {'path': '_internal/tampered/accelerator.pyd', 'sha256': hashlib.sha256(b'changed').hexdigest()},
                {'path': 'OrionMini.exe', 'sha256': hashlib.sha256(b'project launcher').hexdigest()}]
    notices.native_origin_records(binaries)
    assert binaries[0]['wheel_record_matches'] == [{'distribution': 'other-native-package', 'version': '2.0',
                                                    'wheel_path': 'some_other_package/accelerator.pyd'}]
    assert binaries[1]['build_interpreter_matches'][0]['relative_path'] == 'DLLs/libssl.dll'
    assert not binaries[2]['wheel_record_matches'] and not binaries[2]['build_interpreter_matches']
    assert binaries[3]['project_generated'] is True
    assert str(base) not in json.dumps(binaries)


@pytest.mark.parametrize('name', ['Qt6Charts.dll', 'libQt6Graphs.so.6', 'Qt6VirtualKeyboardQml.dll'])
def test_rejects_unused_qt_modules_before_wrapping(tmp_path, name):
    (tmp_path / name).write_bytes(b'synthetic binary')
    with pytest.raises(ValueError, match='Unused Qt module'):
        notices.audit_qt_modules(tmp_path)


def test_inventory_hashes_real_native_bytes_and_keeps_exact_version_notices(tmp_path, monkeypatch):
    bundle = tmp_path / 'bundle'; bundle.mkdir()
    (bundle / 'Qt6Core.dll').write_bytes(b'synthetic shared library')
    (bundle / 'not-native.txt').write_text('excluded from native inventory')
    cache = tmp_path / 'notices/qt-6.8.3'; cache.mkdir(parents=True)
    (cache / 'LGPL-3.0-only.txt').write_text('synthetic test license text')
    (tmp_path / 'REPLACEABLE_LIBRARIES.md').write_text('synthetic replacement instructions')
    monkeypatch.setattr(notices, 'HERE', tmp_path)
    monkeypatch.setattr(notices.importlib.metadata, 'version', lambda name: '6.8.3')
    target = tmp_path / 'output'
    inventory = notices.collect(bundle, target)
    assert [item['path'] for item in inventory['native_files']] == ['Qt6Core.dll']
    assert inventory['native_files'][0]['sha256'] == notices.digest(bundle / 'Qt6Core.dll')
    assert inventory['notice_files'][0]['sha256'] == notices.digest(cache / 'LGPL-3.0-only.txt')
    assert '6.8.3/submodules/qtwebengine-everywhere-src-6.8.3.tar.xz' in inventory['qt_source_archive_candidates'][2]
    assert 'not proof' in inventory['source_status']
    assert json.loads((target / 'native-provenance.json').read_text()) == inventory


def test_rejects_ambiguous_qt_version(tmp_path, monkeypatch):
    monkeypatch.setattr(notices.importlib.metadata, 'version', lambda name: '6.8.3+local')
    with pytest.raises(ValueError, match='exact stable'):
        notices.collect(tmp_path / 'bundle', tmp_path / 'output')


@pytest.mark.parametrize('name', ['winrt-runtime', 'winrt-Windows.UI.Notifications', 'winrt_windows_foundation'])
def test_reviewed_winrt_notice_covers_exact_versions_only(tmp_path, name):
    distribution = SimpleNamespace(metadata={'Name': name}, version='3.2.1')
    paths = notices.fallback_python_notice(distribution, tmp_path)
    assert len(paths) == 1
    assert 'Microsoft Corporation' in (tmp_path / paths[0]).read_text()
    provenance = json.loads((tmp_path / paths[0]).with_name('PROVENANCE.json').read_text())
    assert notices.digest(tmp_path / paths[0]) == provenance['sha256']
    distribution.version = '3.2.2'
    assert notices.fallback_python_notice(distribution, tmp_path) == []
    distribution.version = '3.2.1'
    distribution.metadata['Name'] = 'unreviewed-package'
    assert notices.fallback_python_notice(distribution, tmp_path) == []


def test_retained_notice_tampering_blocks_packaging(tmp_path, monkeypatch):
    cache = tmp_path / 'cache/notices/pywinrt-3.2.1'
    shutil.copytree(notices.HERE / 'notices/pywinrt-3.2.1', cache)
    (cache / 'LICENSE.txt').write_text('altered licence notice')
    monkeypatch.setattr(notices, 'HERE', tmp_path / 'cache')
    with pytest.raises(ValueError, match='notice hash'):
        notices.fallback_python_notice(SimpleNamespace(metadata={'Name': 'winrt-runtime'}, version='3.2.1'), tmp_path / 'out')


@pytest.mark.parametrize('version', ['6.8.3', '6.11.2'])
@pytest.mark.parametrize('name', ['PySide6', 'PySide6_Essentials', 'PySide6_Addons', 'shiboken6'])
def test_reviewed_qt_wheels_receive_real_exact_version_notices(tmp_path, name, version):
    distribution = SimpleNamespace(metadata={'Name': name}, version=version)
    paths = notices.fallback_python_notice(distribution, tmp_path)
    assert 'qt-' + version + '/LGPL-3.0-only.txt' in paths
    assert 'qt-' + version + '/GPL-3.0-only.txt' in paths
    attribution = 'pyside-setup-everywhere-src-' + version + '-ATTRIBUTIONS.txt'
    assert 'qt-' + version + '/' + attribution in paths
    for path in paths:
        assert (tmp_path / path).read_bytes() == notices.retained_notice_bytes(notices.HERE / 'notices' / path)
    assert notices.fallback_python_notice(distribution, tmp_path) == paths


@pytest.mark.parametrize('name,version', [('PySide6', '6.8.4'), ('PySide6', '6.8.3+local'),
                                         ('PySide6-unknown', '6.8.3'), ('shiboken2', '6.11.2')])
def test_qt_notice_fallback_does_not_cover_unreviewed_packages(tmp_path, name, version):
    assert notices.fallback_python_notice(SimpleNamespace(metadata={'Name': name}, version=version), tmp_path) == []
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('damage', ['license_hash', 'missing_license', 'missing_attribution',
                                    'wrong_version', 'incomplete', 'missing_required_text'])
def test_qt_notice_cache_damage_blocks_packaging_before_copy(tmp_path, monkeypatch, damage):
    cache = tmp_path / 'cache/notices/qt-6.8.3'
    shutil.copytree(notices.HERE / 'notices/qt-6.8.3', cache)
    if damage == 'license_hash':
        (cache / 'LGPL-3.0-only.txt').write_text('altered licence')
    elif damage == 'missing_license':
        (cache / 'LGPL-3.0-only.txt').unlink()
    elif damage == 'missing_attribution':
        (cache / 'pyside-setup-everywhere-src-6.8.3-ATTRIBUTIONS.txt').unlink()
    elif damage in {'wrong_version', 'incomplete'}:
        path = cache / 'RETAINED_SOURCE.txt'
        evidence = json.loads(path.read_text())
        evidence['version' if damage == 'wrong_version' else 'complete'] = '6.11.2' if damage == 'wrong_version' else False
        path.write_text(json.dumps(evidence))
    else:
        path = cache / 'UPSTREAM_NOTICES.txt'
        evidence = json.loads(path.read_text())
        evidence['files'] = [item for item in evidence['files'] if item['file'] != 'LGPL-3.0-only.txt']
        path.write_text(json.dumps(evidence))
    monkeypatch.setattr(notices, 'HERE', tmp_path / 'cache')
    output = tmp_path / 'out'
    with pytest.raises((ValueError, OSError)):
        notices.fallback_python_notice(SimpleNamespace(metadata={'Name': 'PySide6'}, version='6.8.3'), output)
    assert not output.exists()


def test_qt_notice_fallback_requires_retained_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(notices, 'HERE', tmp_path / 'absent')
    with pytest.raises(OSError):
        notices.fallback_python_notice(SimpleNamespace(metadata={'Name': 'shiboken6'}, version='6.8.3'), tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_retained_notice_windows_checkout_line_endings_are_canonical(tmp_path, monkeypatch):
    cache = tmp_path / 'cache/notices/pywinrt-3.2.1'
    shutil.copytree(notices.HERE / 'notices/pywinrt-3.2.1', cache)
    expected = notices.retained_notice_bytes(cache / 'LICENSE.txt')
    (cache / 'LICENSE.txt').write_bytes(expected.replace(b'\n', b'\r\n'))
    monkeypatch.setattr(notices, 'HERE', tmp_path / 'cache')
    output = tmp_path / 'output'
    paths = notices.fallback_python_notice(SimpleNamespace(metadata={'Name': 'winrt-runtime'}, version='3.2.1'), output)
    assert (output / paths[0]).read_bytes() == expected


def test_packaged_inventory_fills_reviewed_gap_and_preserves_unknown_gap(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('notice_packaging', Path(__file__).parents[1] / 'scripts/packaging/build-desktop-distribution.py')
    packaging = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packaging)

    class Metadata(dict):
        def get_all(self, key):
            return []

    represented = tmp_path / 'synthetic_module.py'
    represented.write_text('# synthetic represented module')
    distributions = [SimpleNamespace(metadata=Metadata(Name=name, License='MIT'), version=version,
                                     files=[Path('synthetic_module.py')], locate_file=lambda file: tmp_path / file)
                     for name, version in [('winrt-runtime', '3.2.1'), ('winrt-Windows.UI.Notifications', '3.2.2')]]
    monkeypatch.setattr(packaging.importlib.metadata, 'distributions', lambda: distributions)
    analysis = tmp_path / 'analysis.toc'
    analysis.write_text(str(represented))
    output = tmp_path / 'licenses'
    packaging.license_inventory(output, analysis, tmp_path / 'frontend')
    inventory = json.loads((output / 'inventory.json').read_text())
    assert inventory['packages_without_shipped_notice'] == ['winrt-Windows.UI.Notifications']
    assert (output / inventory['python'][0]['notices'][0]).is_file()


@pytest.mark.skipif(__import__('os').name=='nt',reason='Linux native bundle aliases')
def test_materializing_bundle_aliases_refuses_external_targets_before_changes(tmp_path):
    spec=importlib.util.spec_from_file_location('native_build',Path(__file__).parents[1]/'scripts/build-native.py')
    build=importlib.util.module_from_spec(spec);spec.loader.exec_module(build)
    bundle=tmp_path/'bundle';bundle.mkdir()
    source=bundle/'library.so.1';source.write_bytes(b'synthetic native library')
    alias=bundle/'library.so';alias.symlink_to(source.name)
    external=tmp_path/'external';external.write_bytes(b'outside')
    unsafe=bundle/'unsafe.so';unsafe.symlink_to(external)
    with pytest.raises(ValueError):build.materialize_internal_links(bundle)
    assert alias.is_symlink() and unsafe.is_symlink()
    unsafe.unlink();build.materialize_internal_links(bundle)
    assert not alias.is_symlink() and alias.read_bytes()==source.read_bytes()
