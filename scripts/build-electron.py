# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build Link's Electron shell and frozen Python service on the actual target OS."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distpath', type=Path, default=Path('dist'))
    parser.add_argument('--workpath', type=Path, default=Path('build'))
    parser.add_argument('--profile', choices=['link'], default='link')
    parser.add_argument('--version', default='0.1.0-unified.2')
    parser.add_argument('--build-number', type=int, default=0)
    parser.add_argument('--hosted-config', type=Path)
    args = parser.parse_args(argv)
    if platform.machine().lower() not in {'amd64', 'x86_64'} or sys.platform not in {'win32', 'linux'}:
        parser.error('Build Electron on the actual supported Windows/Linux x86_64 target.')
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?', args.version) or args.build_number < 0:
        parser.error('Choose an explicit semantic version and nonnegative build number.')
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'scripts/packaging'))
    from desktop_names import bundle_name, host_platform
    from windows_metadata import write_version_resource
    work = (root / args.workpath / 'electron').resolve()
    work.mkdir(parents=True, exist_ok=True)
    source = work / 'source'
    if source.exists():
        raise ValueError('Choose a fresh --workpath for this Electron build; existing work was preserved.')
    destination = (root / args.distpath / bundle_name(host_platform())).resolve()
    if destination.exists():
        raise ValueError('Choose a fresh --distpath; the existing application folder was preserved.')
    source.mkdir()
    temporary = work / 'tmp'
    temporary.mkdir()
    environment = {**os.environ, 'TEMP': str(temporary), 'TMP': str(temporary), 'TMPDIR': str(temporary),
                   'PYTHONDONTWRITEBYTECODE': '1', 'VITE_ORION_PROFILE': 'link',
                   'PYINSTALLER_CONFIG_DIR': str(work / 'pyinstaller-cache'),
                   'electron_config_cache': str(work / 'electron-cache')}
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    node = shutil.which('node')
    if not npm or not node:
        raise ValueError('Node 24 and the locked desktop/frontend dependencies are required.')
    frontend = work / 'frontend'
    subprocess.run([npm, '--prefix', 'frontend', 'run', 'build', '--', '--outDir', str(frontend)], cwd=root, env=environment, check=True)
    subprocess.run([npm, '--prefix', 'desktop', 'run', 'build'], cwd=root, env=environment, check=True)
    for file in (root / 'desktop/dist').glob('*.cjs'):
        if not file.name.endswith('.test.cjs'):
            (source / 'dist').mkdir(exist_ok=True)
            shutil.copyfile(file, source / 'dist' / file.name)
    (source / 'package.json').write_text(json.dumps({'name': 'saiph-desktop', 'version': args.version,
        'main': 'dist/main.cjs', 'license': 'AGPL-3.0-or-later', 'private': True}), encoding='utf-8')
    shutil.copytree(frontend, source / 'frontend')
    metadata = work / 'metadata'
    metadata.mkdir()
    release = {'schema': 1, 'version': args.version, 'build': args.build_number, 'platform': host_platform()}
    (metadata / 'distribution-profile.json').write_text(json.dumps({'schema': 1, 'profile': 'link'}), encoding='utf-8')
    (metadata / 'distribution-release.json').write_text(json.dumps(release), encoding='utf-8')
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--console',
        '--name', 'SaiphService', '--distpath', str(work / 'python-dist'), '--workpath', str(work / 'python-build'),
        '--specpath', str(work / 'spec'), '--paths', str(root / 'src')]
    data = [(metadata / 'distribution-profile.json', '.'), (metadata / 'distribution-release.json', '.'), (root / 'assets', 'assets'),
            (root / 'tests/fixtures/electron-phone.json', 'test-fixtures')]
    if args.hosted_config:
        from orion_mini.hosted_distribution import read_configuration
        defaults = metadata / 'hosted-defaults.json'
        defaults.write_text(json.dumps(read_configuration(args.hosted_config)), encoding='utf-8')
        data.append((defaults, '.'))
    camera = work / 'camera'
    if os.name == 'nt':
        subprocess.run([sys.executable, str(root / 'native/camera/build.py'), '--output', str(camera)], cwd=root, env=environment, check=True)
        for leaf in ('SaiphCamera64.dll', 'SaiphCamera32.dll'):
            command += ['--add-binary', str(camera / leaf) + os.pathsep + 'camera']
        for leaf in ('LICENSE.UnityCapture.txt', 'camera-build.json'):
            data.append((camera / leaf, 'camera'))
        version_file = metadata / 'windows-version.txt'
        write_version_resource(version_file, args.version, args.build_number, 'link')
        command += ['--version-file', str(version_file)]
    for file, target in data:
        command += ['--add-data', str(file) + os.pathsep + target]
    for package in ('certifi', 'desktop_notifier'):
        command += ['--collect-data', package]
    for module in ('PySide6', 'shiboken6', 'orion_mini.app', 'orion_mini.desktop_bridge', 'orion_mini.dashboard_view',
        'orion_mini.widget_view', 'orion_mini.phone_screen_window', 'orion_workspace', 'pytest',
        'faster_whisper', 'ctranslate2', 'tokenizers', 'transformers', 'torch', 'google_auth_oauthlib', 'google.auth'):
        command += ['--exclude-module', module]
    command += ['--hidden-import', 'tzdata', '--hidden-import', 'desktop_notifier.resources', str(root / 'run_electron_service.py')]
    if os.name == 'nt':
        from native_origins import windows_native_environment
        environment, trusted = windows_native_environment(environment)
    subprocess.run(command, cwd=root, env=environment, check=True)
    subprocess.run([node, str(root / 'scripts/package-electron.cjs'), str(source), str(work / 'electron-dist'),
        args.version, str(args.build_number), str(root / 'assets/orion-mini-icon.ico'), str(work / 'electron-cache')], cwd=root, env=environment, check=True)
    packaged = json.loads((work / 'electron-dist/packager-result.json').read_text(encoding='utf-8'))
    folder = Path(packaged['directories'][0]).resolve(strict=True)
    if not folder.is_relative_to(work):
        raise ValueError('Packager output escaped its build directory.')
    service = folder / 'resources/service'
    shutil.copytree(work / 'python-dist/SaiphService', service)
    compatibility = folder / '_internal'
    compatibility.mkdir()
    for name in ('distribution-profile.json', 'distribution-release.json'):
        shutil.copyfile(metadata / name, compatibility / name)
    shutil.copytree(root / 'assets', compatibility / 'assets')
    shutil.copytree(frontend, compatibility / 'frontend/dist')
    if camera.exists():
        (compatibility / 'camera').mkdir()
        for leaf in ('SaiphCamera64.dll', 'SaiphCamera32.dll', 'LICENSE.UnityCapture.txt', 'camera-build.json'):
            shutil.copyfile(camera / leaf, compatibility / 'camera' / leaf)
    marker = {'schema': 1, 'runtime': 'electron', 'electron_version': packaged['electronVersion'],
        'service': 'resources/service/' + ('SaiphService.exe' if os.name == 'nt' else 'SaiphService'),
        'frontend': 'resources/app/frontend'}
    (compatibility / 'desktop-runtime.json').write_text(json.dumps(marker), encoding='utf-8')
    originals = root / 'desktop/node_modules/electron/dist'
    provenance = []
    for native in folder.iterdir():
        if native.is_file():
            original = originals / native.name
            if original.is_file() and digest(native) == digest(original):
                provenance.append({'path': native.name, 'sha256': digest(native), 'source': 'pinned-electron-runtime'})
    (compatibility / 'electron-runtime-provenance.json').write_text(json.dumps({'schema': 1,
        'electron_version': packaged['electronVersion'], 'native_files': provenance,
        'source': 'https://github.com/electron/electron/releases/tag/v' + packaged['electronVersion'],
        'scope': 'Exact runtime byte matches; the application executable is renamed and stamped by Electron Packager.'}), encoding='utf-8')
    if os.name == 'nt':
        from native_origins import audit_analysis
        receipt = audit_analysis(work / 'python-build/SaiphService/Analysis-00.toc', service, trusted,
            {f'camera/{leaf}': camera / leaf for leaf in ('SaiphCamera64.dll', 'SaiphCamera32.dll')}, entrypoint='SaiphService.exe')
        (metadata / 'native-build-origins.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    if sys.platform == 'linux':
        from importlib.util import spec_from_file_location, module_from_spec
        spec = spec_from_file_location('legacy_build', root / 'scripts/build-native.py')
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        module.materialize_internal_links(folder)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(folder), str(destination))
    print(json.dumps({'bundle': str(destination), 'analysis': str(work / 'python-build/SaiphService/Analysis-00.toc'),
                      'platform': host_platform(), 'runtime': 'electron', 'signed': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
