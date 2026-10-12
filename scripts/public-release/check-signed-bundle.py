#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Accept a provider-signed desktop bundle only if it changed the project executable.

The signing provider returns a copy of the bundle. Every file must be present with
identical bytes except the project-authored executables, which must have grown by
an appended signature. Signature validity is checked later by
verify-windows-signatures.py on the final installer and installed executable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PROJECT_EXECUTABLES = ('OrionMini.exe',)


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def inventory(root: Path) -> dict[str, Path]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f'{root} is not a regular bundle directory')
    files = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError(f'Bundle contains a link: {path.relative_to(root).as_posix()}')
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path
    return files


def check(unsigned: Path, signed: Path, executables=PROJECT_EXECUTABLES) -> dict:
    before, after = inventory(unsigned), inventory(signed)
    missing, added = sorted(before.keys() - after.keys()), sorted(after.keys() - before.keys())
    if missing or added:
        raise ValueError(f'Signed bundle file set differs; missing {missing[:5]}, added {added[:5]}')
    for name in executables:
        if name not in before:
            raise ValueError(f'Project executable {name} is absent')
    changed = []
    for name in sorted(before):
        if name in executables:
            if after[name].stat().st_size <= before[name].stat().st_size or digest(after[name]) == digest(before[name]):
                raise ValueError(f'{name} was not signed')
            changed.append(name)
        elif digest(after[name]) != digest(before[name]):
            raise ValueError(f'Signing changed a file it must not change: {name}')
    return {'files': len(before), 'signed': changed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unsigned', type=Path, required=True)
    parser.add_argument('--signed', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.unsigned, args.signed)))


if __name__ == '__main__':
    main()
