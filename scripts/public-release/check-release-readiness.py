# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check native package evidence before external release; never sign or publish."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

REVIEW_CHECKS = ('native_notices', 'wheel_provenance', 'qt_replacement', 'supported_runtime')


def package_entries(root):
    """Inspect each directory entry before descending, especially Windows junctions."""
    pending = [Path(root)]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                information = entry.stat(follow_symlinks=False)
                if (stat.S_ISLNK(information.st_mode)
                        or getattr(information, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                        or not (stat.S_ISREG(information.st_mode) or stat.S_ISDIR(information.st_mode))):
                    raise ValueError('Package must contain only regular files and directories without links')
                path = Path(entry.path)
                yield path
                if stat.S_ISDIR(information.st_mode):
                    pending.append(path)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as source:
        while block := source.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def local_file(root, relative):
    if (not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative
            or any(part in {'', '.', '..'} for part in relative.split('/')) or relative.startswith('/')):
        raise ValueError('Unsafe evidence path')
    root = Path(root).resolve()
    target = root / relative
    if any(part.is_symlink() or getattr(part, 'is_junction', lambda: False)() for part in (target, *target.parents) if part != root):
        raise ValueError('Evidence must not use links or junctions')
    if not target.resolve().is_relative_to(root) or not target.is_file():
        raise ValueError('Missing local evidence file: ' + relative)
    return target


def check(package, review_path=None, qt_source_dir=None):
    package = Path(package)
    entries = list(package_entries(package))
    manifest_path = local_file(package, 'package-manifest.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('format') != 'orion-desktop-package' or manifest.get('schema') != 1:
        raise ValueError('Unsupported package manifest')
    platform = manifest.get('platform')
    version = manifest.get('version')
    build = manifest.get('build')
    if (platform not in {'windows-x86_64', 'linux-x86_64'} or not isinstance(version, str)
            or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?', version)
            or type(build) is not int or build < 0):
        raise ValueError('Invalid native package platform/version/build')
    entrypoint = 'app/Saiph.exe' if platform.startswith('windows') else 'app/saiph'
    # Byte copy for updaters installed before the rename (0.1.0-beta.4 and older).
    compatibility = 'app/OrionMini.exe' if platform.startswith('windows') else 'app/OrionMini'
    if manifest.get('entrypoint') != entrypoint:
        raise ValueError('Unexpected native package entrypoint')
    expected = set()
    for item in manifest['files']:
        path = local_file(package, item['path'])
        if item['path'] in expected or path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
            raise ValueError('Package bytes no longer match the manifest: ' + item['path'])
        expected.add(item['path'])
    actual = {p.relative_to(package).as_posix() for p in entries if p.is_file()}
    extras = {'package-manifest.json'}
    checksum_path = package / 'SHA256SUMS'
    if checksum_path.is_file():
        lines = []
        for path in sorted(entries):
            if path.is_file() and path != checksum_path:
                lines.append(digest(path) + '  ' + path.relative_to(package).as_posix())
        if checksum_path.read_text(encoding='utf-8') != '\n'.join(lines) + '\n':
            raise ValueError('Package SHA256SUMS no longer matches final bytes')
        extras.add('SHA256SUMS')
    if actual != expected | extras:
        raise ValueError('Package contains unrecorded or missing files')
    executable = local_file(package, entrypoint)
    with executable.open('rb') as source:
        magic = source.read(4)
    if (platform.startswith('windows') and magic[:2] != b'MZ') or (platform.startswith('linux') and magic != b'\x7fELF'):
        raise ValueError('Native executable does not match package platform')
    if digest(local_file(package, compatibility)) != digest(executable):
        raise ValueError('Compatibility executable must be a byte copy of the entrypoint')
    frozen_release = json.loads(local_file(package, 'app/_internal/distribution-release.json').read_text(encoding='utf-8'))
    frozen_profile = json.loads(local_file(package, 'app/_internal/distribution-profile.json').read_text(encoding='utf-8'))
    if (frozen_release != {'schema': 1, 'version': version, 'build': build, 'platform': platform}
            or frozen_profile != {'schema': 1, 'profile': manifest.get('profile')}):
        raise ValueError('Frozen release/profile metadata does not match the native package')
    inventory = json.loads(local_file(package, 'licenses/inventory.json').read_text(encoding='utf-8'))
    native = json.loads(local_file(package, 'licenses/native-provenance.json').read_text(encoding='utf-8'))
    problems = []
    if manifest.get('profile') != 'link':
        problems.append('Public release must use the reviewed Link profile.')
    local_file(package, 'licenses/Saiph-LICENSE.txt')
    for group in ('python', 'frontend'):
        for item in inventory[group]:
            if not item.get('notices'):
                problems.append('Missing ' + group + ' notice: ' + item['name'])
            for path in item.get('notices', []):
                local_file(package / 'licenses', path)
    if inventory.get('packages_without_shipped_notice'):
        problems.append('Inventory still records packages without shipped notices.')
    runtime = native.get('python_runtime', {})
    if not re.fullmatch(r'3\.(?:1[2-9]|[2-9][0-9])\.[0-9]+', runtime.get('version', '')):
        problems.append('Rebuild with a supported Python release (3.12 or newer); verify its current patch level.')
    if not runtime.get('notices'):
        problems.append('Build interpreter licence notice is missing.')
    for item in runtime.get('notices', []):
        if digest(local_file(package / 'licenses', item['path'])) != item['sha256']:
            problems.append('Build interpreter notice hash changed.')
    retained = native.get('retained_qt_source_evidence') or {}
    qt = native.get('build_environment_versions', {}).get('PySide6_Essentials', '')
    expected_archives = {module + '-everywhere-src-' + qt + '.tar.xz' for module in
                         ('qtbase', 'qtdeclarative', 'qtwebengine', 'qtwebchannel', 'qtpositioning', 'qtshadertools', 'qtsvg')}
    expected_archives.add('pyside-setup-everywhere-src-' + qt + '.tar.xz')
    archives = retained.get('archives', [])
    if (not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', qt) or retained.get('version') != qt
            or not retained.get('complete') or len(archives) != len(expected_archives)
            or {item.get('archive') for item in archives} != expected_archives or not qt_source_dir):
        problems.append('Supply the complete retained matching Qt/PySide source archives.')
    else:
        for archive in archives:
            source = local_file(qt_source_dir, archive['archive'])
            if source.stat().st_size != archive['bytes'] or digest(source) != archive['sha256']:
                problems.append('Matching source archive changed: ' + archive['archive'])
    review = None
    if review_path:
        review_path = Path(review_path)
        review = json.loads(review_path.read_text(encoding='utf-8'))
        if (review.get('schema') != 1 or not str(review.get('reviewer', '')).strip()
                or not str(review.get('reviewed_at', '')).strip()
                or review.get('package_manifest_sha256') != digest(manifest_path)):
            raise ValueError('Review must identify its reviewer, date and exact package manifest hash')
        for name in REVIEW_CHECKS:
            approval = review.get('checks', {}).get(name, {})
            evidence = approval.get('evidence', [])
            if approval.get('result') != 'pass' or not evidence:
                problems.append('Release review needs passing evidence: ' + name)
            for item in evidence:
                if digest(local_file(review_path.parent, item['path'])) != item['sha256']:
                    problems.append('Release review evidence changed: ' + name)
    else:
        problems.extend(inventory.get('unresolved', []))
        problems.extend(native.get('remaining_review', []))
        problems.append('Complete the package-bound native notices, wheel provenance, Qt replacement and runtime review.')
    return {'format': 'saiph-release-readiness', 'schema': 1, 'ready': not problems,
            'package_manifest_sha256': digest(manifest_path), 'problems': problems,
            'scope': 'Native notice/source/review evidence only. Windows signatures, final checksums and clean-machine acceptance are separate gates.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--qt-source-dir', type=Path)
    args = parser.parse_args()
    try:
        result = check(args.package, args.review, args.qt_source_dir)
    except (ValueError, OSError, KeyError, TypeError) as error:
        result = {'ready': False, 'problems': [str(error)]}
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['ready'] else 1)


if __name__ == '__main__':
    main()
