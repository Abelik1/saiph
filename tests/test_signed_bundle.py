# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signed-bundle acceptance with synthetic files; nothing is signed here."""
import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('check_signed_bundle', ROOT / 'scripts/public-release/check-signed-bundle.py')
bundles = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundles)


@pytest.fixture
def pair(tmp_path):
    unsigned = tmp_path / 'unsigned'
    (unsigned / '_internal').mkdir(parents=True)
    (unsigned / 'Saiph.exe').write_bytes(b'MZ synthetic project executable')
    (unsigned / '_internal/Qt6Core.dll').write_bytes(b'MZ upstream dependency keeps its own signature')
    signed = tmp_path / 'signed'
    shutil.copytree(unsigned, signed)
    with (signed / 'Saiph.exe').open('ab') as output:
        output.write(b'synthetic certificate table')
    return unsigned, signed


def test_only_the_project_executable_may_change(pair):
    assert bundles.check(*pair) == {'files': 2, 'signed': ['Saiph.exe']}


def test_unsigned_executable_is_rejected(pair):
    unsigned, signed = pair
    shutil.copyfile(unsigned / 'Saiph.exe', signed / 'Saiph.exe')
    with pytest.raises(ValueError, match='not signed'):
        bundles.check(unsigned, signed)


def test_changed_dependency_is_rejected(pair):
    unsigned, signed = pair
    (signed / '_internal/Qt6Core.dll').write_bytes(b'MZ re-signed or replaced dependency')
    with pytest.raises(ValueError, match='must not change'):
        bundles.check(unsigned, signed)


@pytest.mark.parametrize('change', ['add', 'remove'])
def test_file_set_must_match(pair, change):
    unsigned, signed = pair
    if change == 'add':
        (signed / '_internal/extra.dll').write_bytes(b'MZ')
    else:
        (signed / '_internal/Qt6Core.dll').unlink()
    with pytest.raises(ValueError, match='file set differs'):
        bundles.check(unsigned, signed)
