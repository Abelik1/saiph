# SPDX-License-Identifier: AGPL-3.0-or-later
"""Offline acceptance: real fixture bytes, checksum metadata and synthetic GitHub REST records."""
import copy
import hashlib
import importlib.util
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location('website_downloads', ROOT / 'scripts/public-release/prepare-website-downloads.py')
downloads = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(downloads)
COMMIT = 'b' * 40
REPO = 'synthetic/saiph'


@pytest.fixture
def release_files(tmp_path):
    platforms = {name: name + '.bin' for name in downloads.PLATFORMS}
    directory = tmp_path / 'assets'
    directory.mkdir()
    for name in platforms.values():
        (directory / name).write_bytes(('Synthetic release fixture: ' + name).encode())
    downloads.checksums.record(directory, COMMIT)
    prefix = 'https://github.com/' + REPO + '/releases/download/v1.0/'
    release = {'draft': False, 'tag_name': 'v1.0',
               'html_url': 'https://github.com/' + REPO + '/releases/tag/v1.0',
               'assets': [{'name': p.name, 'state': 'uploaded', 'size': p.stat().st_size,
                           'digest': 'sha256:' + hashlib.sha256(p.read_bytes()).hexdigest(),
                           'browser_download_url': prefix + quote(p.name, safe='')} for p in directory.iterdir()]}
    return directory, platforms, release


def test_verified_bytes_produce_exact_version_links(release_files):
    directory, platforms, release = release_files
    result = downloads.prepare(REPO, release, platforms, directory, COMMIT)
    assert result['release']['sourceCommit'] == COMMIT
    assert result['downloads']['windows'].endswith('/v1.0/windows.bin')
    assert set(result['downloads']) == downloads.PLATFORMS
    assert 'sourceVisibility' not in result  # No publication decision is inferred.


@pytest.mark.parametrize('mutation', ['bytes', 'source', 'sums', 'missing', 'digest', 'size', 'state', 'url', 'draft', 'tag', 'duplicate'])
def test_unverified_or_mismatched_release_fails(release_files, mutation):
    directory, platforms, release = release_files
    source = COMMIT
    if mutation == 'bytes':
        (directory / platforms['windows']).write_bytes(b'tampered')
    elif mutation == 'source':
        source = 'c' * 40
    elif mutation == 'sums':
        (directory / 'SHA256SUMS').write_text('tampered')
    elif mutation == 'missing':
        release['assets'].pop()
    elif mutation == 'draft':
        release['draft'] = True
    elif mutation == 'tag':
        release['tag_name'] = 'latest'
    elif mutation == 'duplicate':
        release['assets'].append(copy.deepcopy(release['assets'][0]))
    else:
        key, value = {'digest': ('digest', 'sha256:' + '0' * 64), 'size': ('size', 0),
                      'state': ('state', 'new'), 'url': ('browser_download_url', 'https://github.com/other/release')}[mutation]
        release['assets'][0][key] = value
    with pytest.raises(ValueError):
        downloads.prepare(REPO, release, platforms, directory, source)


@pytest.mark.parametrize('name', ['../outside.bin', 'folder/file.bin', 'C:\u005cfile.bin', '..', ' bad.bin', 'bad\n.bin'])
def test_platform_paths_rejected_before_checksum_or_file_reads(release_files, monkeypatch, name):
    directory, platforms, release = release_files
    platforms['windows'] = name
    def forbidden(*args):
        pytest.fail('Must reject unsafe platform paths before inspecting files')
    monkeypatch.setattr(downloads.checksums, 'verify', forbidden)
    with pytest.raises(ValueError):
        downloads.prepare(REPO, release, platforms, directory, COMMIT)


def test_unrecorded_platform_cannot_be_read(release_files):
    directory, platforms, release = release_files
    platforms['windows'] = 'not-recorded.bin'
    with pytest.raises(ValueError, match='absent'):
        downloads.prepare(REPO, release, platforms, directory, COMMIT)
