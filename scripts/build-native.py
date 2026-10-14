# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build a native desktop bundle on its target OS; never cross-label executables."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import platform
import subprocess
import sys
import tempfile


def materialize_internal_links(bundle):
    """Convert Linux PyInstaller aliases to files before the strict package audit."""
    bundle = Path(bundle).resolve(strict=True)
    links = []
    for path in bundle.rglob('*'):
        if not path.is_symlink(): continue
        target = path.resolve(strict=True)
        if not target.is_relative_to(bundle) or not target.is_file():
            raise ValueError('Native bundle link points outside its own files')
        links.append((path, target))
    # Validate the entire set before replacing any link. Never remove the target.
    for path, target in links:
        descriptor, name = tempfile.mkstemp(prefix='.orion-materialized-', dir=path.parent)
        os.close(descriptor)
        temporary = Path(name)
        try:
            shutil.copy2(target, temporary)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


# Personal Workspace code and its heavy dependencies; never part of a Link bundle.
LINK_EXCLUDED_MODULES = ('orion_workspace', 'faster_whisper', 'ctranslate2', 'tokenizers', 'transformers', 'torch',
                         'google_auth_oauthlib', 'google.auth')


def workspace_source(parser, profile, source):
    """Validate the add-on checkout: required for Workspace, refused for Link."""
    if profile != 'workspace':
        if source is not None:
            parser.error('--workspace-source is only used with --profile workspace.')
        return None
    if source is None:
        parser.error('--profile workspace needs --workspace-source <orion checkout>; Saiph does not contain the add-on.')
    source = source.resolve()
    for required in ('src/orion_workspace/edition.py', 'skills', 'scripts/dev.py'):
        if not (source / required).exists():
            parser.error(f'{source} is not a Workspace add-on checkout (missing {required}).')
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distpath', default='dist')
    parser.add_argument('--workpath', default='build')
    parser.add_argument('--profile', choices=['link', 'workspace'], default='link',
                        help='Link is the default; personal Workspace is an explicit separate build.')
    parser.add_argument('--workspace-source', type=Path,
                        help='Checkout of the private Workspace add-on (orion_workspace); required for --profile workspace.')
    parser.add_argument('--version', default='0.1.0-unified.2')
    parser.add_argument('--build-number', type=int, default=0, help='Private release sequence; publish builds with increasing numbers.')
    parser.add_argument('--hosted-config', type=Path, help='Explicit public deployment defaults; never contains secrets or enables Hosted')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    hosted_configuration = None
    if args.hosted_config:
        sys.path.insert(0, str(root / 'src'))
        from orion_mini.hosted_distribution import read_configuration
        hosted_configuration = read_configuration(args.hosted_config)
    workspace = workspace_source(parser, args.profile, args.workspace_source)
    sys.path.insert(0, str(root / 'scripts' / 'packaging'))
    from windows_metadata import version_tuple, write_version_resource
    from desktop_names import bundle_name, host_platform
    name = bundle_name(host_platform())
    import re
    if args.build_number < 0 or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?', args.version):
        parser.error('Use a nonnegative build number and explicit semantic version.')
    if platform.machine().lower() not in {'amd64', 'x86_64'} or sys.platform not in {'win32', 'linux'}:
        parser.error('Native desktop preview builds currently support Windows/Linux x86_64 only.')
    if os.name == 'nt':
        try:
            version_tuple(args.version, args.build_number)
        except ValueError as failure:
            parser.error(str(failure))
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    if not npm:
        raise SystemExit('Node/npm is required on the build machine only.')
    environment = dict(os.environ)
    environment['VITE_ORION_PROFILE'] = args.profile
    frontend_output = (root / args.workpath / 'frontend').resolve()
    if workspace:
        # The add-on overlays its Workspace views onto a copy of this checkout's frontend.
        subprocess.run([sys.executable, str(workspace / 'scripts' / 'dev.py'), 'frontend', 'build',
                        '--out-dir', str(frontend_output)], cwd=workspace, env={**environment, 'SAIPH_SOURCE': str(root)},
                       check=True)
    else:
        subprocess.run([npm, '--prefix', 'frontend', 'run', 'build', '--', '--outDir', str(frontend_output)],
                       cwd=root, env=environment, check=True)
    profile_path = (root / args.workpath / 'profile' / 'distribution-profile.json').resolve()
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps({'schema': 1, 'profile': args.profile}), encoding='utf-8')
    release_path = profile_path.with_name('distribution-release.json')
    release_path.write_text(json.dumps({'schema': 1, 'version': args.version, 'build': args.build_number,
        'platform': 'windows-x86_64' if os.name == 'nt' else 'linux-x86_64'}), encoding='utf-8')
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
               '--name', name, '--distpath', args.distpath, '--workpath', args.workpath,
               '--specpath', str((root / args.workpath / 'spec').resolve()),
               '--icon', str(root / 'assets/orion-mini-icon.ico'), '--runtime-hook', str(root / 'scripts/pyi_qt_path.py'),
               '--additional-hooks-dir', str(root / 'scripts/packaging/hooks'), '--paths', str(root / 'src')]
    if workspace:
        # orion_mini.modules imports the add-on by name, so PyInstaller cannot discover it.
        command += ['--paths', str(workspace / 'src'), '--collect-submodules', 'orion_workspace']
    if os.name == 'nt':
        version_resource = profile_path.with_name('windows-version.txt')
        write_version_resource(version_resource, args.version, args.build_number, args.profile)
        command += ['--version-file', str(version_resource)]
    # Orion renders React in WebEngine Widgets and has no QML application.
    # An incidental QtQuick Python dependency otherwise runs the QML hook,
    # collecting every wheel plugin (including unused GPL-only Charts/Graphs).
    # Native WebEngine dependencies such as QtQuick.dll remain discoverable by
    # PyInstaller's binary dependency walk; do not delete those DLLs by hand.
    for module in ('PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets',
                   'PySide6.QtWebEngineQuick', 'PySide6.QtCharts', 'PySide6.QtGraphs',
                   'PySide6.QtDataVisualization', 'PySide6.QtVirtualKeyboard'):
        command += ['--exclude-module', module]
    data = [(str(frontend_output),'frontend/dist'),(str(root / 'assets'),'assets'), (str(profile_path), '.'), (str(release_path), '.')]
    if hosted_configuration is not None:
        defaults = profile_path.with_name('hosted-defaults.json')
        defaults.write_text(json.dumps(hosted_configuration, sort_keys=True) + '\n', encoding='utf-8')
        data.append((str(defaults), '.'))
    if workspace:
        data.append((str(workspace / 'skills'), 'skills'))
    for source, target in data:
        command += ['--add-data', source + os.pathsep + target]
    packages = ['certifi', 'desktop_notifier']
    if workspace:
        packages += ['faster_whisper', 'tokenizers']
    else:
        # Keep Link free of the add-on even when it is installed in this environment.
        for module in [*LINK_EXCLUDED_MODULES, 'pytest']:
            command += ['--exclude-module', module]
    for package in packages:
        command += ['--collect-data', package]
    # Linux slim hosts may lack /usr/share/zoneinfo. PyInstaller's zoneinfo
    # hook enables tzdata only on Windows, so include our declared fallback on
    # both platforms; its upstream hook collects package/resource directories.
    command += ['--hidden-import', 'tzdata', '--hidden-import','desktop_notifier.resources',str(root / 'run_orion_mini.py')]
    if os.name == 'nt':
        from native_origins import windows_native_environment
        environment, trusted_native_roots = windows_native_environment(environment)
    subprocess.run(command, cwd=root, env=environment, check=True)
    if os.name == 'nt':
        from native_origins import audit_analysis
        origins = audit_analysis(root / args.workpath / name / 'Analysis-00.toc',
                                 root / args.distpath / name, trusted_native_roots)
        (profile_path.parent / 'native-build-origins.json').write_text(json.dumps(origins, indent=2) + '\n', encoding='utf-8')
    if sys.platform == 'linux':
        materialize_internal_links(root / args.distpath / name)


if __name__ == '__main__':
    main()
