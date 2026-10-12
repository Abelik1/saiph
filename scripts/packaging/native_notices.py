# SPDX-License-Identifier: AGPL-3.0-or-later
"""Offline native inventory and exact-version upstream source provenance.

Inventory is evidence, not a statement that all distribution obligations are met.
Only pre-fetched versioned notices are copied; packaging never downloads code.
"""
from __future__ import annotations

import hashlib
import base64
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import ssl
import sys
import sysconfig

HERE = Path(__file__).resolve().parent
UNUSED_QT = ('Qt6Charts', 'Qt6DataVisualization', 'Qt6Graphs', 'Qt6VirtualKeyboard')
PYWINRT_DISTRIBUTIONS = {
    'winrt-runtime', 'winrt-windows-applicationmodel-core',
    'winrt-windows-data-xml-dom', 'winrt-windows-foundation',
    'winrt-windows-foundation-collections', 'winrt-windows-ui-notifications',
}
QT_DISTRIBUTIONS = {'pyside6', 'pyside6-essentials', 'pyside6-addons', 'shiboken6'}
REVIEWED_QT_VERSIONS = {'6.8.3', '6.11.2'}


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as source:
        while block := source.read(1024 * 1024): result.update(block)
    return result.hexdigest()


def retained_notice_bytes(path):
    """Git's Windows checkout may transport retained UTF-8 notices as CRLF."""
    return Path(path).read_bytes().replace(b'\r\n', b'\n')


def fallback_python_notice(distribution, destination):
    """Supply a retained upstream notice only for a reviewed exact wheel version."""
    name = re.sub(r'[-_.]+', '-', distribution.metadata['Name'].lower())
    if name in QT_DISTRIBUTIONS and distribution.version in REVIEWED_QT_VERSIONS:
        version = distribution.version
        cache = HERE / 'notices' / ('qt-' + version)
        retained = json.loads((cache / 'RETAINED_SOURCE.txt').read_text(encoding='utf-8'))
        upstream = json.loads((cache / 'UPSTREAM_NOTICES.txt').read_text(encoding='utf-8'))
        attribution = 'pyside-setup-everywhere-src-' + version + '-ATTRIBUTIONS.txt'
        pyside_archive = 'pyside-setup-everywhere-src-' + version + '.tar.xz'
        if (retained.get('version') != version or retained.get('complete') is not True
                or not any(item.get('archive') == pyside_archive and item.get('attribution_file') == attribution
                           for item in retained.get('archives', []))):
            raise ValueError('Retained Qt notice evidence must match the complete exact version')
        license_names = set()
        sources = []
        for item in upstream.get('files', []):
            filename = item['file']
            if not re.fullmatch(r'(?:L?GPL)-[0-9.]+-(?:only|or-later)\.txt', filename):
                raise ValueError('Unexpected retained Qt licence notice path')
            source = cache / filename
            if hashlib.sha256(retained_notice_bytes(source)).hexdigest() != item['sha256']:
                raise ValueError('Retained Qt notice hash does not match its provenance')
            license_names.add(filename)
            sources.append(source)
        if not {'LGPL-3.0-only.txt', 'GPL-3.0-only.txt'} <= license_names:
            raise ValueError('Retained Qt notices lack required LGPL/GPL texts')
        attribution_path = cache / attribution
        if not attribution_path.is_file() or not attribution_path.stat().st_size:
            raise ValueError('Retained PySide attribution notice is missing')
        sources += [attribution_path, cache / 'RETAINED_SOURCE.txt', cache / 'UPSTREAM_NOTICES.txt']
        target_directory = Path(destination) / ('qt-' + version)
        target_directory.mkdir(parents=True, exist_ok=True)
        for source in sources:
            (target_directory / source.name).write_bytes(retained_notice_bytes(source))
        # These upstream texts fill missing wheel notices only. Matching wheel
        # build options, applicable grants and replacement remain release review.
        return [(target_directory / source.name).relative_to(destination).as_posix() for source in sources]
    if name not in PYWINRT_DISTRIBUTIONS or distribution.version != '3.2.1':
        return []
    cache = HERE / 'notices/pywinrt-3.2.1'
    source = cache / 'LICENSE.txt'
    provenance = json.loads((cache / 'PROVENANCE.json').read_text(encoding='utf-8'))
    if hashlib.sha256(retained_notice_bytes(source)).hexdigest() != provenance['sha256']:
        raise ValueError('Retained PyWinRT notice hash does not match its provenance')
    target = Path(destination) / name / 'LICENSE-upstream.txt'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(retained_notice_bytes(source))
    shutil.copyfile(cache / 'PROVENANCE.json', target.parent / 'PROVENANCE.json')
    return [target.relative_to(destination).as_posix()]


def collect_python_runtime_notice(destination):
    """Retain this build interpreter's notice, without claiming binary provenance."""
    candidates = [Path(sys.base_prefix) / 'LICENSE.txt',
                  Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt',
                  Path('/usr/share/doc') / ('python' + '.'.join(map(str, sys.version_info[:2]))) / 'copyright']
    notices = []
    for source in candidates:
        if source.is_file():
            target = Path(destination) / 'python-runtime/LICENSE.txt'
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            notices.append({'path': target.relative_to(destination).as_posix(), 'sha256': digest(target)})
            break
    return {'implementation': sys.implementation.name, 'version': '.'.join(map(str, sys.version_info[:3])),
            'openssl': ssl.OPENSSL_VERSION, 'notices': notices,
            'source_url': 'https://www.python.org/downloads/release/python-' + ''.join(map(str, sys.version_info[:3])) + '/',
            'scope': 'Build interpreter metadata; match packaged native bytes and transitive notices during release review.'}


def audit_qt_modules(bundle):
    """Reject known unused GPL-only modules, including platform naming variants."""
    for path in Path(bundle).rglob('*'):
        if path.is_file() and any(re.search(r'(?:^|lib)' + re.escape(prefix) + r'(?:Qml)?(?:\.|$)', path.name) for prefix in UNUSED_QT):
            raise ValueError('Unused Qt module was bundled; rebuild without QML plugin collection')


def is_native_file(path):
    return path.suffix.lower() in {'.dll', '.pyd', '.exe', '.so'} or '.so.' in path.name


def native_origin_records(binaries):
    """Match actual bytes to all installed native RECORDs and build Python files."""
    wheel_records = {}
    for distribution in importlib.metadata.distributions():
        for item in distribution.files or []:
            if not is_native_file(Path(item)) or not item.hash or item.hash.mode != 'sha256':
                continue
            decoded = base64.urlsafe_b64decode(item.hash.value + '=' * (-len(item.hash.value) % 4))
            if len(decoded) != 32:
                raise ValueError('Installed native wheel RECORD has an invalid SHA256')
            key = (Path(item).name.casefold(), decoded.hex())
            wheel_records.setdefault(key, []).append({
                'distribution': distribution.metadata['Name'], 'version': distribution.version,
                'wheel_path': str(item).replace('\\', '/')})
    interpreter_records = {}
    base = Path(sys.base_prefix)
    directories = {base, base / 'DLLs', Path(sysconfig.get_config_var('DESTSHARED') or base / 'DLLs')}
    library_directory = sysconfig.get_config_var('LIBDIR')
    library_name = sysconfig.get_config_var('LDLIBRARY')
    candidates = [source for directory in directories if directory.is_dir()
                  for source in directory.iterdir() if source.is_file() and is_native_file(source)]
    if library_directory and library_name:
        candidates += list(Path(library_directory).glob(library_name + '*'))
    for source in candidates:
        if not source.is_file() or not is_native_file(source):
            continue
        key = (source.name.casefold(), digest(source))
        # No developer account paths are added to public package inventories.
        relative = source.relative_to(base).as_posix() if source.is_relative_to(base) else source.name
        interpreter_records.setdefault(key, []).append({
            'relative_path': relative, 'implementation': sys.implementation.name,
            'version': '.'.join(map(str, sys.version_info[:3]))})
    for item in binaries:
        key = (Path(item['path']).name.casefold(), item['sha256'])
        item['wheel_record_matches'] = wheel_records.get(key, [])
        item['build_interpreter_matches'] = interpreter_records.get(key, [])
        item['project_generated'] = item['path'] == 'OrionMini.exe'


def collect(bundle, destination):
    bundle, destination = Path(bundle), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    audit_qt_modules(bundle)
    binaries = []
    for path in sorted(bundle.rglob('*')):
        if path.is_file() and is_native_file(path):
            binaries.append({'path': path.relative_to(bundle).as_posix(), 'bytes': path.stat().st_size, 'sha256': digest(path)})
    versions = {}
    for name in ('PySide6', 'PySide6_Essentials', 'PySide6_Addons', 'shiboken6', 'cryptography', 'cffi', 'PyInstaller'):
        try: versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: pass
    native_origin_records(binaries)
    qt = versions.get('PySide6_Essentials')
    if qt and not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', qt):
        raise ValueError('Qt source provenance requires an exact stable package version')
    copied = []
    retained = None
    source_links = []
    if qt:
        cache = HERE / 'notices' / ('qt-' + qt)
        if cache.is_dir():
            for source in sorted(cache.glob('*.txt')):
                target = destination / ('qt-' + qt) / source.name
                target.parent.mkdir(exist_ok=True)
                target.write_bytes(retained_notice_bytes(source))
                copied.append({'path': target.relative_to(destination).as_posix(), 'sha256': digest(target)})
            evidence = cache / 'RETAINED_SOURCE.txt'
            if evidence.is_file(): retained = json.loads(evidence.read_text(encoding='utf-8'))
        major_minor = '.'.join(qt.split('.')[:2])
        source_links = [
            f'https://download.qt.io/archive/qt/{major_minor}/{qt}/submodules/{module}-everywhere-src-{qt}.tar.xz'
            for module in ('qtbase', 'qtdeclarative', 'qtwebengine', 'qtwebchannel', 'qtpositioning', 'qtshadertools', 'qtsvg')
        ]
        source_links.append(f'https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{qt}-src/pyside-setup-everywhere-src-{qt}.tar.xz')
    inventory = {
        'format': 'orion-native-provenance', 'schema': 1,
        'build_environment_versions': versions,
        'native_files': binaries,
        'unmatched_native_files': [item['path'] for item in binaries if not (
            item['wheel_record_matches'] or item['build_interpreter_matches'] or item['project_generated'])],
        'origin_scope': 'Exact installed wheel RECORD and build-interpreter byte matches; these do not independently verify wheel downloads, build options, platform grants or replacement acceptance. The project launcher is generated output, not an upstream wheel.',
        'notice_files': copied,
        'python_runtime': collect_python_runtime_notice(destination),
        'retained_qt_source_evidence': retained,
        'qt_source_archive_candidates': source_links,
        'source_status': 'Retained evidence records official verified source archives when present; URLs alone are not proof of retention, wheel build options or replacement verification.',
        'remaining_review': [
            'Review native files without exact wheel RECORD matches and retain wheel build options/patch provenance; environment versions alone do not establish a match.',
            'Transfer matching retained Qt/PySide/Chromium source archives and notices with the private release; confirm wheel-specific build options/patches.',
            'Complete Python, OpenSSL/cryptography, libffi, platform runtime and optional Workspace native dependency notices.',
            'Verify interface-compatible Qt replacement on each supported native platform before external distribution.',
        ],
    }
    (destination / 'native-provenance.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    shutil.copyfile(HERE / 'REPLACEABLE_LIBRARIES.md', destination / 'REPLACEABLE_LIBRARIES.md')
    return inventory
