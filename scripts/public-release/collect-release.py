#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Gather one platform's packaged desktop files under unique release asset names.

Copies the installer(s) and the package's manifest and dependency inventory from a
build-desktop-distribution.py output directory. Never builds, signs or uploads.
"""
import argparse
from pathlib import Path
import shutil

PLATFORMS = {'windows-x86_64': ('.exe',), 'linux-x86_64': ('.tar.gz', '.run')}


def collect(distribution, platform, version, output, extra=()):
    distribution, output = Path(distribution), Path(output)
    if platform not in PLATFORMS:
        raise ValueError('Unknown platform')
    output.mkdir(parents=True, exist_ok=True)
    for suffix in PLATFORMS[platform]:
        package = distribution / f'Saiph-Link-{version}-{platform}{suffix}'
        if not package.is_file():
            raise ValueError('Missing packaged file ' + package.name)
        shutil.copyfile(package, output / package.name)
    package = distribution / f'package-{version}-{platform}'
    shutil.copyfile(package / 'package-manifest.json', output / f'package-manifest-{platform}.json')
    shutil.copyfile(package / 'licenses/inventory.json', output / f'dependency-inventory-{platform}.json')
    origins = Path('build/electron/metadata/native-build-origins.json')
    if origins.is_file():
        shutil.copyfile(origins, output / f'native-build-origins-{platform}.json')
    for path in map(Path, extra):
        shutil.copyfile(path, output / path.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distribution', type=Path, required=True)
    parser.add_argument('--platform', choices=sorted(PLATFORMS), required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--extra', type=Path, action='append', default=[], help='Additional evidence file to include as is')
    args = parser.parse_args()
    collect(args.distribution, args.platform, args.version, args.output, args.extra)


if __name__ == '__main__':
    main()
