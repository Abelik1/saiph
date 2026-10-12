# SPDX-License-Identifier: AGPL-3.0-or-later
import importlib.util
import json
from pathlib import Path
import pytest

SPEC = importlib.util.spec_from_file_location('beta_downloads', Path(__file__).parents[1] / 'scripts/beta/prepare-downloads.py')
beta = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(beta)
COMMIT = 'a' * 40


@pytest.fixture
def assets(tmp_path):
    folder = tmp_path / 'assets'
    folder.mkdir()
    mapping = dict(windows='Saiph.exe', linux='Saiph.run', android='Saiph.apk',
                   desktop_source='Desktop-source.tar.gz', android_source='Android-source.zip')
    for name in mapping.values():
        (folder / name).write_bytes(b'synthetic fixture only')
    (folder / 'private-build.log').write_text('must never be staged')
    beta.checksums.record(folder, COMMIT)
    return folder, mapping


def test_stages_only_selected_files_and_serves_source_with_installers(assets, tmp_path):
    folder, mapping = assets
    out = tmp_path / 'out'
    manifest = beta.prepare(folder, mapping, COMMIT, 'https://downloads.example.test/beta1/', out)
    assert not (out / 'files/private-build.log').exists()
    verified = beta.checksums.verify(out / 'files', COMMIT)
    assert {i['file'] for i in verified['artifacts']} == set(mapping.values())
    assert manifest['downloads']['windows']['url'].endswith('/beta1/Saiph.exe')
    page = (out / 'portal/index.html').read_text()
    assert 'No compilation' in page and 'Desktop corresponding source' in page
    assert 'private-build.log' not in page
    assert not list((out / 'portal').glob('*.exe'))
    assert json.loads((out / 'portal/vercel.json').read_text())['headers']


def test_explicit_dependency_source_and_notices_are_distributed_without_build_logs(assets, tmp_path):
    folder, mapping = assets
    supporting = ['Qt-source.tar.gz', 'THIRD_PARTY_NOTICES.md']
    for name in supporting:
        (folder / name).write_text('synthetic dependency source/notices')
    beta.checksums.record(folder, COMMIT)
    out = tmp_path / 'out'
    result = beta.prepare(folder, mapping, COMMIT, 'https://downloads.example.test/beta1/', out,
                          supporting_files=supporting)
    assert {item['file'] for item in result['supporting_files']} == set(supporting)
    assert all((out / 'files' / name).is_file() for name in supporting)
    assert not (out / 'files/private-build.log').exists()


@pytest.mark.parametrize('mutation', ['bytes', 'commit', 'missing-source', 'traversal', 'token-url', 'http', 'invite'])
def test_rejects_unverified_or_unsafe_distribution_before_creating_output(assets, tmp_path, mutation):
    folder, mapping = assets
    commit, url, invite = COMMIT, 'https://downloads.example.test/beta1/', ''
    if mutation == 'bytes':
        (folder / mapping['android']).write_bytes(b'changed')
    elif mutation == 'commit':
        commit = 'b' * 40
    elif mutation == 'missing-source':
        mapping.pop('android_source')
    elif mutation == 'traversal':
        mapping['windows'] = '../private.exe'
    elif mutation == 'token-url':
        url += '?token=secret'
    elif mutation == 'http':
        url = url.replace('https:', 'http:')
    elif mutation == 'invite':
        invite = 'https://evil.example.test/invite'
    out = tmp_path / 'out'
    with pytest.raises(ValueError):
        beta.prepare(folder, mapping, commit, url, out, invite)
    assert not out.exists()
