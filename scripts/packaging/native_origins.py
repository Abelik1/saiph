# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check native build inputs against explicit interpreter and platform roots.

Reports describe local build origins, not licence approval or upstream signatures.
Never import or execute the collected application to inspect it.
"""
from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path, PurePosixPath
import sys


def windows_native_environment(environment, prefix=None, base_prefix=None):
    """Keep developer PATH tools out of PyInstaller's Windows DLL search."""
    result = dict(environment)
    prefix = Path(prefix or sys.prefix).resolve()
    base_prefix = Path(base_prefix or sys.base_prefix).resolve()
    system = Path(result.get('SystemRoot', result.get('WINDIR', 'C:/Windows'))).resolve()
    directories = [base_prefix / 'DLLs', base_prefix, prefix / 'Scripts', system / 'System32']
    result['PATH'] = os.pathsep.join(dict.fromkeys(map(str, directories)))
    result.pop('PYTHONPATH', None)
    result.pop('PYTHONHOME', None)
    return result, [prefix, base_prefix, system / 'System32', system / 'WinSxS']


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def native_entries(value):
    if isinstance(value, (tuple, list)):
        if len(value) == 3 and value[2] in ('BINARY', 'EXTENSION'):
            if not isinstance(value[0], str) or not isinstance(value[1], str):
                raise ValueError('Malformed native Analysis entry')
            yield value
        else:
            for child in value:
                yield from native_entries(child)


def audit_analysis(analysis, bundle, trusted_roots, project_inputs=None):
    """Reject ambient native inputs and changed/extra collected native files."""
    bundle = Path(bundle).resolve(strict=True)
    roots = [Path(root).resolve(strict=True) for root in trusted_roots if Path(root).is_dir()]
    if not roots:
        raise ValueError('Native input audit requires explicit trusted roots')
    entries = list(native_entries(ast.literal_eval(Path(analysis).read_text(encoding='utf-8'))))
    if not entries:
        raise ValueError('Native Analysis has no auditable binary entries')
    records = {}
    for relative, source_name, kind in entries:
        relative = relative.replace('\\', '/')
        path = PurePosixPath(relative)
        if (not relative or path.is_absolute() or ':' in relative
                or any(part in ('', '.', '..') for part in relative.split('/'))):
            raise ValueError('Unsafe native bundle path')
        source = Path(source_name).resolve(strict=True)
        project = (project_inputs or {}).get(relative)
        project_match = project is not None and source == Path(project).resolve(strict=True)
        if not source.is_file() or not (project_match or any(source.is_relative_to(root) for root in roots)):
            raise ValueError('Native dependency originates outside trusted build roots: ' + relative)
        target = bundle / '_internal' / relative
        if (target.is_symlink() or not target.resolve(strict=True).is_relative_to(bundle)
                or digest(target) != digest(source)):
            raise ValueError('Collected native dependency differs from its audited input: ' + relative)
        record = {'path': '_internal/' + relative, 'source': str(source), 'kind': kind,
                  'bytes': target.stat().st_size, 'sha256': digest(target)}
        if record['path'] in records and records[record['path']] != record:
            raise ValueError('Conflicting native Analysis entries: ' + relative)
        records[record['path']] = record
    for target in bundle.rglob('*'):
        if not target.is_file():
            continue
        relative = target.relative_to(bundle).as_posix()
        if target.suffix.lower() in {'.exe', '.dll', '.pyd'} and relative != 'Saiph.exe':
            if relative not in records:
                raise ValueError('Collected native file has no audited Analysis input: ' + relative)
    return {'schema': 1, 'format': 'saiph-native-build-origins',
            'trusted_roots': list(map(str, roots)), 'files': list(records.values()),
            'scope': 'Exact local input/collected byte origins. Not a signature, source-build or licence approval.'}
