# SPDX-License-Identifier: AGPL-3.0-or-later
"""Wrap an existing native PyInstaller bundle; build machines need Python, targets do not."""
from __future__ import annotations
import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from desktop_names import bundle_name, executable, legacy_executable  # noqa: E402
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?$")


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024): result.update(chunk)
    return result.hexdigest()


def safe_path(value):
    if not value or '\\' in value or value.startswith('/') or any(x in value for x in ('\n', '\r', '\0', ':')):
        raise ValueError("Unsafe distribution path")
    if any(part in ('', '.', '..') for part in value.split('/')):
        raise ValueError("Unsafe distribution path")
    return value


def audit_installed_modules(bundle, platform, profile):
    from PyInstaller.archive.readers import CArchiveReader
    entry = bundle / executable(platform)
    archive = CArchiveReader(str(entry)).open_embedded_archive('PYZ.pyz')
    audit_profile_contents(bundle, profile, archive.toc)


def audit_profile_contents(bundle, profile, modules):
    if profile == 'workspace':
        # Without the add-on a Workspace-labelled bundle would quietly start as Link.
        if 'orion_workspace.edition' not in modules:
            raise ValueError('Workspace bundle is missing the orion_workspace add-on')
        if not (bundle / '_internal/skills').is_dir():
            raise ValueError('Workspace bundle is missing its assistant skills')
        return
    forbidden = ('orion_workspace', 'faster_whisper', 'ctranslate2', 'tokenizers', 'transformers', 'torch')
    if any(name == prefix or name.startswith(prefix + '.') for name in modules for prefix in forbidden):
        raise ValueError('Link bundle still includes optional personal Workspace modules')
    if (bundle / '_internal/skills').exists():
        raise ValueError('Link bundle still includes personal assistant skills')
    frontend = bundle / '_internal/frontend/dist/assets'
    if any(path.name.startswith('Workspace-') for path in frontend.glob('*.js')):
        raise ValueError('Link bundle still includes optional personal frontend chunks')


def audit_bundle(bundle, platform):
    entry = bundle / executable(platform)
    if not entry.is_file(): raise ValueError("Native PyInstaller bundle is missing its executable")
    magic = entry.open('rb').read(4)
    if platform.startswith('windows') and magic[:2] != b'MZ': raise ValueError("Windows packaging requires a PE executable")
    if platform.startswith('linux') and magic != b'\x7fELF': raise ValueError("Linux packaging requires a Linux-built ELF executable")
    profile_file = bundle / '_internal/distribution-profile.json'
    try:
        profile = json.loads(profile_file.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ValueError('Build a native bundle with an explicit Link or Workspace profile first') from None
    if (not isinstance(profile, dict) or set(profile) != {'schema', 'profile'} or type(profile['schema']) is not int
            or profile['schema'] != 1 or profile['profile'] not in {'link', 'workspace'}):
        raise ValueError('Invalid native distribution profile')
    for path in bundle.rglob('*'):
        if path.is_symlink(): raise ValueError("Distribution bundle contains a symbolic link; use a fully materialized bundle")
        if not path.is_file(): continue
        relative = safe_path(path.relative_to(bundle).as_posix())
        name = path.name.lower()
        if name in {'.env', 'google-services.json', 'client-bootstrap.json', 'settings.json', 'connections.json', 'api.json', 'device_key.pem', 'hub-device-key.pem'} or name.endswith(('.jks', '.keystore', '.sqlite', '.sqlite3', '.db', '.pfx', '.p12', '.orion-enrollment')):
            raise ValueError("Distribution contains private state or credential files")
        if path.stat().st_size <= 1024 * 1024:
            content = path.read_bytes()
            # TLS libraries contain NUL-terminated PEM label constants. A PEM
            # credential starts a text line and has a following line break.
            if re.search(rb'(?:^|[\r\n])-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----[ \t]*\r?\n', content):
                raise ValueError("Distribution contains a private key")
    return profile['profile']


def license_inventory(destination, analysis, frontend):
    """Record packages represented in the actual PyInstaller analysis, not every pip tool."""
    lock = frontend / 'package-lock.json'
    if not lock.is_file():
        raise ValueError('Frontend licence inventory requires the source package-lock.json and installed dependencies')
    import importlib.util
    spec = importlib.util.spec_from_file_location('distribution_native_notices', HERE / 'native_notices.py')
    native_notices = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native_notices)
    destination.mkdir(parents=True)
    text = analysis.read_text(encoding='utf-8') if analysis.is_file() else ''
    included = []
    for distribution in importlib.metadata.distributions():
        files = distribution.files or []
        represented = any(str(distribution.locate_file(file)).replace('\\', '\\\\') in text or str(distribution.locate_file(file)) in text for file in files)
        if not represented: continue
        name = distribution.metadata['Name']
        notices = []
        for file in files:
            leaf = Path(str(file)).name.lower()
            if (leaf.startswith(('license', 'copying', 'notice', 'copyright')) and not leaf.endswith(('.pyc', '.py'))):
                source = distribution.locate_file(file)
                if source.is_file():
                    target = destination / re.sub(r'[^A-Za-z0-9_.-]', '_', name) / str(file).replace('/', '__').replace('\\', '__')
                    target.parent.mkdir(exist_ok=True); shutil.copyfile(source, target)
                    notices.append(target.relative_to(destination).as_posix())
        if not notices:
            notices = native_notices.fallback_python_notice(distribution, destination)
        included.append({'name': name, 'version': distribution.version,
                         'license': distribution.metadata.get('License-Expression') or distribution.metadata.get('License'),
                         'project_urls': distribution.metadata.get_all('Project-URL') or [], 'notices': notices})
    npm = []
    if lock.is_file():
        for path, data in json.loads(lock.read_text(encoding='utf-8')).get('packages', {}).items():
            if not path or data.get('dev') is True: continue
            name = path.rsplit('node_modules/', 1)[-1]
            notices = []
            directory = frontend / path
            for source in directory.glob('*'):
                if source.is_file() and source.name.lower().startswith(('license', 'notice', 'copying', 'copyright')):
                    target = destination / ('npm-' + re.sub(r'[^A-Za-z0-9_.-]', '_', name)) / source.name
                    target.parent.mkdir(exist_ok=True); shutil.copyfile(source, target)
                    notices.append(target.relative_to(destination).as_posix())
            npm.append({'name': name, 'version': data.get('version'), 'license': data.get('license'), 'notices': notices,
                        'scope': 'production dependency; individual bundled-use confirmation still required'})
    gaps = [item['name'] for item in included if not item['notices']]
    inventory = {'format': 'orion-distribution-inventory', 'schema': 1, 'python': included, 'frontend': npm,
                 'audit_basis': 'PyInstaller Analysis TOC paths and production npm lock; exact native file manifest accompanies this inventory',
                 'unresolved': ['Native transitive notices and matching-source/relink obligations require review, including Qt WebEngine/Chromium and bundled FFmpeg',
                                'PySide wheel metadata lists LGPL/GPL but some wheels carry only commercial license text; full applicable license texts must be added before external release'],
                 'packages_without_shipped_notice': gaps}
    (destination / 'inventory.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    shutil.copyfile(HERE / 'DISTRIBUTION_NOTICES.md', destination / 'DISTRIBUTION_NOTICES.md')


def prepare(bundle, staging, version, platform, analysis, frontend):
    if not VERSION.fullmatch(version): raise ValueError("Version must be an explicit semantic version")
    profile = audit_bundle(bundle, platform)
    # Run before copying a large bundle. An incidental QML hook must never add
    # unused GPL-only libraries to a private-edition release silently.
    import importlib.util
    spec = importlib.util.spec_from_file_location('orion_native_notices', HERE / 'native_notices.py')
    native_notices = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native_notices)
    native_notices.audit_qt_modules(bundle)
    try:
        release = json.loads((bundle / '_internal/distribution-release.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ValueError('Native bundle is missing its immutable release metadata') from None
    if (not isinstance(release, dict) or set(release) != {'schema', 'platform', 'version', 'build'}
            or type(release['schema']) is not int or release['schema'] != 1 or release['platform'] != platform
            or release['version'] != version or type(release['build']) is not int or release['build'] < 0):
        raise ValueError('Native release metadata does not match the selected package version/platform')
    staging.mkdir(parents=True, exist_ok=False)
    shutil.copytree(bundle, staging / 'app')
    # Installed beta.4 and older updaters, and the deployed Hub, still look for this
    # name. A byte copy made after signing keeps it signed and identical.
    if (staging / 'app' / legacy_executable(platform)).exists():
        raise ValueError('Native bundle already contains the compatibility executable name')
    shutil.copy2(staging / 'app' / executable(platform), staging / 'app' / legacy_executable(platform))
    license_inventory(staging / 'licenses', analysis, frontend)
    native_notices.collect(bundle, staging / 'licenses')
    project_license = HERE.parents[1] / 'LICENSE'
    if project_license.is_file():
        shutil.copyfile(project_license, staging / 'licenses/Saiph-LICENSE.txt')
    shutil.copyfile(HERE / 'components.json', staging / 'components.json')
    files = [{'path': safe_path(p.relative_to(staging).as_posix()), 'bytes': p.stat().st_size, 'sha256': digest(p)}
             for p in sorted(staging.rglob('*')) if p.is_file()]
    manifest = {'format': 'orion-desktop-package', 'schema': 1, 'version': version, 'platform': platform, 'profile': profile, 'build': release['build'],
                'entrypoint': 'app/' + executable(platform),
                'release_state': 'internal-preview', 'license_inventory': 'licenses/inventory.json', 'files': files}
    (staging / 'package-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def aligned_padding(length, alignment=8):
    return -length % alignment


def add_network_relay(staging, compiler):
    """Compile SaiphNetwork.exe beside app/; the installer keeps it at one fixed path.

    Windows Firewall rules name a program path and every release has a new one,
    so Saiph's local listeners go through this relay (src/orion_mini/lan_relay.py).
    """
    relay = staging / 'SaiphNetwork.exe'
    if relay.exists():
        raise ValueError('Staging already contains SaiphNetwork.exe')
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/optimize+', '/platform:x64', '/out:' + str(relay),
                    str(HERE / 'WindowsNetworkRelay.cs')], check=True)
    manifest_path = staging / 'package-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest.setdefault('files', []).append({'path': 'SaiphNetwork.exe', 'bytes': relay.stat().st_size, 'sha256': digest(relay)})
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def build_windows(staging, output, compiler):
    from windows_metadata import write_assembly_metadata
    staging, output, compiler = staging.absolute(), output.absolute(), compiler.absolute()
    stub = output.with_suffix('.stub.exe')
    metadata_path = output.with_suffix('.assembly.cs')
    if any(path.exists() or path.is_symlink() for path in (stub, metadata_path, output.with_suffix('.payload.zip'))):
        raise ValueError('Installer temporary outputs already exist; choose a fresh output directory')
    manifest = add_network_relay(staging, compiler)
    write_assembly_metadata(metadata_path, manifest['version'], manifest['build'], manifest['profile'])
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/optimize+', '/platform:x64', '/out:' + str(stub),
                    '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
                    '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll',
                    '/reference:System.Web.Extensions.dll', str(HERE / 'WindowsSetup.cs'), str(metadata_path)], check=True)
    archive = output.with_suffix('.payload.zip')
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for path in sorted(staging.rglob('*')):
            if path.is_file(): zipped.write(path, path.relative_to(staging).as_posix())
    shutil.copyfile(stub, output)
    with output.open('ab') as executable, archive.open('rb') as source:
        # Authenticode pads to 8 bytes before its certificate table. Align the
        # unsigned file now, ahead of the payload, so the trailer stays directly
        # before any later signature.
        executable.write(b'\0' * aligned_padding(stub.stat().st_size + archive.stat().st_size + 16))
        shutil.copyfileobj(source, executable, length=1024 * 1024)
        executable.write(struct.pack('<Q', archive.stat().st_size) + b'ORIONZIP')
    # Only our generated temporary payload/stub, inside the chosen output directory.
    archive.unlink(); stub.unlink(); metadata_path.unlink()


def build_linux(staging, output):
    # Record actual versioned ELF requirements, including embedded Python and
    # native dependencies. Building on a recent host can raise the baseline.
    if not shutil.which('readelf'):
        raise ValueError('Linux packaging requires readelf (binutils) to record the supported glibc baseline')
    versions = set()
    for path in (staging / 'app').rglob('*'):
        if not path.is_file():
            continue
        with path.open('rb') as source:
            elf = source.read(4) == b'\x7fELF'
        if not elf:
            continue
        result = subprocess.run(['readelf', '--version-info', str(path)], capture_output=True, text=True, check=True)
        versions.update(tuple(map(int, value.split('.'))) for value in re.findall(r'Name: GLIBC_([0-9]+\.[0-9]+)\b', result.stdout))
    if not versions:
        raise ValueError('Linux native bundle has no verifiable glibc requirement')
    minimum_glibc = '.'.join(map(str, max(versions)))
    (staging / 'LINUX_COMPATIBILITY').write_text('linux-x86_64 glibc ' + minimum_glibc + '\n', encoding='utf-8')
    shutil.copyfile(HERE / 'install-linux.sh', staging / 'install.sh')
    (staging / 'install.sh').chmod(0o755)
    version = json.loads((staging / 'package-manifest.json').read_text(encoding='utf-8'))['version']
    (staging / 'VERSION').write_text(version + '\n', encoding='utf-8')
    manifest_path = staging / 'package-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['files'] = [{'path': safe_path(path.relative_to(staging).as_posix()),
                          'bytes': path.stat().st_size, 'sha256': digest(path)}
                         for path in sorted(staging.rglob('*')) if path.is_file()
                         and path != manifest_path and path != staging / 'SHA256SUMS']
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    checksums = '\n'.join(digest(p) + '  ' + p.relative_to(staging).as_posix() for p in sorted(staging.rglob('*')) if p.is_file()) + '\n'
    (staging / 'SHA256SUMS').write_text(checksums, encoding='utf-8')
    with tarfile.open(output, 'w:gz') as archive: archive.add(staging, arcname='orion')


def build_linux_setup(archive, output):
    """Prefix the finished, unchanged release archive with the no-terminal setup script.

    The archive bytes are appended verbatim, so its manifests, audits, notices and
    install.sh are exactly those already produced for the .tar.gz release.
    """
    match = re.fullmatch(r'Saiph-[A-Za-z]+-(.+)-linux-x86_64\.tar\.gz', archive.name)
    if not match or not VERSION.fullmatch(match.group(1)):
        raise ValueError('Linux setup requires a finished Saiph Linux release archive')
    if output.exists() or output.is_symlink():
        raise ValueError('Setup output already exists; choose a fresh build/version directory')
    payload_bytes, payload_sha256 = archive.stat().st_size, digest(archive)
    if not payload_bytes:
        raise ValueError('Linux release archive is empty')
    # Text mode normalizes a Windows checkout's line endings to LF for sh.
    header = (HERE / 'linux-setup.sh').read_text(encoding='utf-8')
    for name, value in {'VERSION': match.group(1), 'ARCHIVE': archive.name,
                        'PAYLOAD_BYTES': str(payload_bytes), 'PAYLOAD_SHA256': payload_sha256}.items():
        header = header.replace('@' + name + '@', value)
    if re.search(r'@[A-Z_]+@', header) or not header.endswith('\n'):
        raise ValueError('Linux setup template was not completely filled')
    with output.open('xb') as target, archive.open('rb') as source:
        target.write(header.encode('utf-8'))
        shutil.copyfileobj(source, target, length=1024 * 1024)
    output.chmod(0o755)
    if digest(archive) != payload_sha256:
        output.unlink()
        raise ValueError('Linux release archive changed while building setup')
    return {'artifact': str(output), 'bytes': output.stat().st_size, 'sha256': digest(output),
            'payload': archive.name, 'payload_sha256': payload_sha256}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, help='Native PyInstaller bundle (default dist/Saiph, or dist/saiph on Linux)')
    parser.add_argument('--version', required=True)
    parser.add_argument('--platform', choices=['windows-x86_64', 'linux-x86_64'], required=True)
    parser.add_argument('--output', type=Path, default=Path('test-artifacts/distribution'))
    parser.add_argument('--analysis', type=Path, help='PyInstaller Analysis TOC (default build/<bundle name>/Analysis-00.toc)')
    parser.add_argument('--frontend', type=Path, default=Path('frontend'))
    parser.add_argument('--linux-setup', action='store_true',
                        help='Also write a self-extracting .run setup around the unchanged Linux .tar.gz')
    parser.add_argument('--compiler', type=Path, default=Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    args = parser.parse_args()
    if args.linux_setup and not args.platform.startswith('linux'):
        parser.error('--linux-setup is only available for Linux packages')
    args.bundle = args.bundle or Path('dist') / bundle_name(args.platform)
    args.analysis = args.analysis or Path('build') / bundle_name(args.platform) / 'Analysis-00.toc'
    profile = audit_bundle(args.bundle, args.platform)
    audit_installed_modules(args.bundle, args.platform, profile)
    args.output.mkdir(parents=True, exist_ok=True)
    staging = args.output / ('package-' + args.version + '-' + args.platform)
    manifest = prepare(args.bundle, staging, args.version, args.platform, args.analysis, args.frontend)
    output = args.output / ('Saiph-' + manifest['profile'].title() + '-' + args.version + '-' + args.platform + ('.exe' if args.platform.startswith('windows') else '.tar.gz'))
    setup = output.with_name(output.name[:-len('.tar.gz')] + '.run') if args.linux_setup else None
    if output.exists() or (setup and (setup.exists() or setup.is_symlink())):
        raise ValueError('Output already exists; choose a fresh build/version directory')
    if args.platform.startswith('windows'): build_windows(staging, output, args.compiler)
    else: build_linux(staging, output)
    result = {'artifact': str(output), 'bytes': output.stat().st_size, 'sha256': digest(output),
              'files': len(manifest['files']), 'release_state': 'internal-preview'}
    if setup:
        result['setup'] = build_linux_setup(output, setup)
    print(json.dumps(result))


if __name__ == '__main__': main()
