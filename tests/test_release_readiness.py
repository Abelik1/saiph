# SPDX-License-Identifier: AGPL-3.0-or-later
"""A release review cannot bless missing notices, changed packages or source."""
import importlib.util
from contextlib import nullcontext
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location('release_readiness', Path(__file__).parents[1] / 'scripts/public-release/check-release-readiness.py')
readiness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(readiness)


def fixture(tmp_path, platform='windows-x86_64'):
    package = tmp_path / 'package'
    licenses = package / 'licenses'
    licenses.mkdir(parents=True)
    (licenses / 'Saiph-LICENSE.txt').write_text('Synthetic project licence fixture')
    (licenses / 'python.txt').write_text('Synthetic dependency and runtime notice')
    internal = package / 'app/_internal'
    internal.mkdir(parents=True)
    version = '0.1.0-beta.1'
    (internal / 'distribution-release.json').write_text(json.dumps({'schema': 1, 'version': version, 'build': 0, 'platform': platform}))
    (internal / 'distribution-profile.json').write_text(json.dumps({'schema': 1, 'profile': 'link'}))
    entrypoint = 'app/Saiph.exe' if platform.startswith('windows') else 'app/saiph'
    compatibility = 'app/OrionMini.exe' if platform.startswith('windows') else 'app/OrionMini'
    for name in (entrypoint, compatibility):
        (package / name).write_bytes(b'MZ synthetic test payload' if platform.startswith('windows') else b'\x7fELF synthetic test payload')
    sources = tmp_path / 'sources'
    sources.mkdir()
    archive = sources / 'synthetic-source.tar.xz'
    archive.write_bytes(b'synthetic retained source fixture')
    archive_names = [module + '-everywhere-src-6.11.2.tar.xz' for module in
                     ('qtbase', 'qtdeclarative', 'qtwebengine', 'qtwebchannel', 'qtpositioning', 'qtshadertools', 'qtsvg', 'pyside-setup')]
    archives = []
    for name in archive_names:
        source = sources / name
        source.write_bytes(archive.read_bytes())
        archives.append({'archive': name, 'bytes': source.stat().st_size, 'sha256': readiness.digest(source)})
    inventory = {'python': [{'name': 'synthetic', 'notices': ['python.txt']}], 'frontend': [],
                 'packages_without_shipped_notice': [], 'unresolved': ['Review native notices']}
    native = {'build_environment_versions': {'PySide6_Essentials': '6.11.2'},
              'python_runtime': {'version': '3.12.14', 'notices': [{'path': 'python.txt', 'sha256': readiness.digest(licenses / 'python.txt')}]},
              'retained_qt_source_evidence': {'version': '6.11.2', 'complete': True, 'archives': archives},
              'remaining_review': ['Test actual Qt replacement']}
    (licenses / 'inventory.json').write_text(json.dumps(inventory))
    (licenses / 'native-provenance.json').write_text(json.dumps(native))
    manifest = {'format': 'orion-desktop-package', 'schema': 1, 'profile': 'link',
                'platform': platform, 'version': version, 'build': 0, 'entrypoint': entrypoint,
                'files': [{'path': p.relative_to(package).as_posix(), 'bytes': p.stat().st_size, 'sha256': readiness.digest(p)} for p in package.rglob('*') if p.is_file()]}
    (package / 'package-manifest.json').write_text(json.dumps(manifest))
    evidence = tmp_path / 'review-evidence.txt'
    evidence.write_text('Synthetic review fixture; not evidence for a real release')
    review = {'schema': 1, 'reviewer': 'Synthetic reviewer', 'reviewed_at': '2026-10-10',
              'package_manifest_sha256': readiness.digest(package / 'package-manifest.json'),
              'checks': {name: {'result': 'pass', 'evidence': [{'path': evidence.name, 'sha256': readiness.digest(evidence)}]} for name in readiness.REVIEW_CHECKS}}
    review_path = tmp_path / 'review.json'
    review_path.write_text(json.dumps(review))
    return package, review_path, sources


def test_preview_stays_blocked_without_review_or_retained_source(tmp_path):
    package, _, _ = fixture(tmp_path)
    result = readiness.check(package)
    assert not result['ready']
    assert 'Review native notices' in result['problems']
    assert 'Test actual Qt replacement' in result['problems']


def test_review_binds_actual_package_source_and_evidence_bytes(tmp_path):
    package, review, sources = fixture(tmp_path)
    assert readiness.check(package, review, sources)['ready']
    (sources / 'qtbase-everywhere-src-6.11.2.tar.xz').write_bytes(b'changed')
    assert not readiness.check(package, review, sources)['ready']
    (tmp_path / 'review-evidence.txt').write_text('changed evidence')
    assert any('evidence changed' in p for p in readiness.check(package, review, sources)['problems'])
    (package / 'licenses/python.txt').write_text('changed bundled notice')
    with pytest.raises(ValueError, match='no longer match'):
        readiness.check(package, review, sources)


def test_review_cannot_override_missing_notice_or_unreviewed_check(tmp_path):
    package, review, sources = fixture(tmp_path)
    approval = json.loads(review.read_text())
    approval['checks'].pop('qt_replacement')
    review.write_text(json.dumps(approval))
    assert not readiness.check(package, review, sources)['ready']
    (package / 'unexpected.exe').write_bytes(b'unreviewed')
    with pytest.raises(ValueError, match='unrecorded'):
        readiness.check(package, review, sources)


def test_review_cannot_override_missing_notices_in_a_fresh_package(tmp_path):
    package, review, sources = fixture(tmp_path)
    inventory_path = package / 'licenses/inventory.json'
    inventory = json.loads(inventory_path.read_text())
    inventory['python'][0]['notices'] = []
    inventory_path.write_text(json.dumps(inventory))
    manifest_path = package / 'package-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    for item in manifest['files']:
        if item['path'] == 'licenses/inventory.json':
            item.update(bytes=inventory_path.stat().st_size, sha256=readiness.digest(inventory_path))
    manifest_path.write_text(json.dumps(manifest))
    approval = json.loads(review.read_text())
    approval['package_manifest_sha256'] = readiness.digest(manifest_path)
    review.write_text(json.dumps(approval))
    assert any('Missing python notice' in problem for problem in readiness.check(package, review, sources)['problems'])


def refresh_package_review(package, review):
    manifest_path = package / 'package-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['files'] = [{'path': path.relative_to(package).as_posix(), 'bytes': path.stat().st_size,
                          'sha256': readiness.digest(path)} for path in package.rglob('*')
                         if path.is_file() and path != manifest_path]
    manifest_path.write_text(json.dumps(manifest))
    approval = json.loads(review.read_text())
    approval['package_manifest_sha256'] = readiness.digest(manifest_path)
    review.write_text(json.dumps(approval))


def test_metadata_only_package_cannot_pass_review(tmp_path):
    package, review, sources = fixture(tmp_path)
    (package / 'app/Saiph.exe').unlink()
    refresh_package_review(package, review)
    with pytest.raises(ValueError, match='Missing local evidence file'):
        readiness.check(package, review, sources)


def test_frozen_metadata_cannot_disagree_with_reviewed_package(tmp_path):
    package, review, sources = fixture(tmp_path)
    frozen = package / 'app/_internal/distribution-release.json'
    release = json.loads(frozen.read_text())
    release['version'] = '9.9.9'
    frozen.write_text(json.dumps(release))
    refresh_package_review(package, review)
    with pytest.raises(ValueError, match='Frozen release/profile'):
        readiness.check(package, review, sources)


def test_platform_magic_cannot_be_overridden_by_review(tmp_path):
    package, review, sources = fixture(tmp_path)
    (package / 'app/Saiph.exe').write_bytes(b'\x7fELF wrong platform')
    refresh_package_review(package, review)
    with pytest.raises(ValueError, match='does not match package platform'):
        readiness.check(package, review, sources)


@pytest.mark.parametrize('platform', ['windows-x86_64', 'linux-x86_64'])
def test_compatibility_executable_must_be_a_byte_copy_of_the_entrypoint(tmp_path, platform):
    package, review, sources = fixture(tmp_path, platform)
    compatibility = package / ('app/OrionMini.exe' if platform.startswith('windows') else 'app/OrionMini')
    compatibility.write_bytes(compatibility.read_bytes() + b' altered')
    refresh_package_review(package, review)
    with pytest.raises(ValueError, match='byte copy of the entrypoint'):
        readiness.check(package, review, sources)
    compatibility.unlink()
    refresh_package_review(package, review)
    with pytest.raises(ValueError, match='Missing local evidence file'):
        readiness.check(package, review, sources)


def test_unrecorded_directory_link_is_rejected(tmp_path):
    package, review, sources = fixture(tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        os.symlink(outside, package / 'unrecorded-link', target_is_directory=True)
    except OSError:
        pytest.skip('Directory symlink creation requires system privilege')
    with pytest.raises(ValueError, match='without links'):
        readiness.check(package, review, sources)


@pytest.mark.parametrize('mode,attributes', [(readiness.stat.S_IFDIR, readiness.stat.FILE_ATTRIBUTE_REPARSE_POINT),
                                            (readiness.stat.S_IFIFO, 0)])
def test_reparse_and_special_entries_are_rejected_before_descent(tmp_path, monkeypatch, mode, attributes):
    visited = []
    entry = SimpleNamespace(path=str(tmp_path / 'unrecorded'),
        stat=lambda **kwargs: SimpleNamespace(st_mode=mode, st_file_attributes=attributes))

    def scan(path):
        visited.append(path)
        return nullcontext([entry])

    monkeypatch.setattr(readiness.os, 'scandir', scan)
    with pytest.raises(ValueError, match='without links'):
        list(readiness.package_entries(tmp_path))
    assert visited == [tmp_path]


def test_linux_wrapper_records_installer_files_before_final_checksums(tmp_path, monkeypatch):
    package, review, sources = fixture(tmp_path, platform='linux-x86_64')
    spec = importlib.util.spec_from_file_location('linux_packaging', Path(__file__).parents[1] / 'scripts/packaging/build-desktop-distribution.py')
    packaging = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packaging)
    monkeypatch.setattr(packaging.shutil, 'which', lambda tool: 'synthetic-readelf')
    monkeypatch.setattr(packaging.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(stdout='Name: GLIBC_2.17'))
    manifest_path = package / 'package-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['version'] = '0.1.0-beta.1'
    manifest_path.write_text(json.dumps(manifest))
    packaging.build_linux(package, tmp_path / 'synthetic-linux.tar.gz')
    manifest = json.loads(manifest_path.read_text())
    assert {'install.sh', 'VERSION', 'LINUX_COMPATIBILITY'} <= {item['path'] for item in manifest['files']}
    approval = json.loads(review.read_text())
    approval['package_manifest_sha256'] = readiness.digest(manifest_path)
    review.write_text(json.dumps(approval))
    assert readiness.check(package, review, sources)['ready']
    (package / 'SHA256SUMS').write_text('tampered checksum file')
    with pytest.raises(ValueError, match='SHA256SUMS'):
        readiness.check(package, review, sources)


@pytest.mark.parametrize('path', ['../outside', 'C:/outside', '/outside', 'directory\\file'])
def test_evidence_paths_cannot_escape_review_directory(tmp_path, path):
    with pytest.raises(ValueError, match='Unsafe'):
        readiness.local_file(tmp_path, path)
