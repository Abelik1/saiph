#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Verify local release bytes against GitHub asset digests; emit website settings only.

Read-only inputs: GitHub REST release JSON, an exact platform-to-filename map,
and a directory containing downloaded assets plus release-source.json/SHA256SUMS.
Does not fetch, build, sign, upload, create a release or publish a repository.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from urllib.parse import quote

SPEC = importlib.util.spec_from_file_location('release_checksums', Path(__file__).with_name('release-checksums.py'))
checksums = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checksums)
PLATFORMS = {'windows', 'linux', 'android', 'server'}


def safe_filename(name):
    return (isinstance(name, str) and bool(name) and name == name.strip()
            and name not in ('.', '..') and not re.search(r'[\x00-\x1f\x7f/\\:]', name))


def file_digest(path):
    before = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('Asset changed during hashing')
    return digest


def prepare(repository, release, platforms, directory, source_commit):
    if not isinstance(source_commit, str) or not re.fullmatch(r'[a-f0-9]{40}', source_commit):
        raise ValueError('Exact full Git source commit required')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Exact GitHub owner/repository required')
    if not isinstance(release, dict) or release.get('draft') is not False:
        raise ValueError('An actual published GitHub release is required')
    tag = release.get('tag_name', '')
    if not isinstance(tag, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', tag) or tag in ('latest', 'HEAD'):
        raise ValueError('A fixed release tag is required')
    root = 'https://github.com/' + repository
    if release.get('html_url') != root + '/releases/tag/' + tag:
        raise ValueError('Release repository/tag does not match')
    if not isinstance(platforms, dict) or set(platforms) != PLATFORMS or any(not safe_filename(v) for v in platforms.values()):
        raise ValueError('Map exactly four platforms to their real filenames')
    if len(set(platforms.values())) != 4:
        raise ValueError('Each platform needs a separate artifact')
    metadata = checksums.verify(Path(directory), source_commit)
    records = {item['file']: item for item in metadata['artifacts']}
    if any(name not in records for name in platforms.values()):
        raise ValueError('Platform artifact is absent from exact source/checksum metadata')
    assets = release.get('assets')
    if not isinstance(assets, list):
        raise ValueError('GitHub asset metadata is required')
    remote = {}
    for asset in assets:
        if not isinstance(asset, dict) or not safe_filename(asset.get('name')) or asset['name'] in remote:
            raise ValueError('Invalid or duplicate GitHub asset')
        remote[asset['name']] = asset
    required = set(platforms.values()) | {'SHA256SUMS', 'release-source.json'}
    # Every file in the local checksum set must also be published with matching bytes.
    required |= set(records)
    prefix = root + '/releases/download/' + tag + '/'
    for name in required:
        if name not in remote:
            raise ValueError('A required versioned asset is missing from the GitHub release')
        asset = remote[name]
        path = Path(directory) / name
        if path.is_symlink() or not path.is_file() or getattr(path, 'is_junction', lambda: False)():
            raise ValueError('Only real regular asset files are allowed')
        if asset.get('state') != 'uploaded' or asset.get('size') != path.stat().st_size or path.stat().st_size == 0:
            raise ValueError('GitHub asset upload state or size does not match')
        digest = file_digest(path)
        if asset.get('digest') != 'sha256:' + digest:
            raise ValueError('GitHub asset digest does not match the actual downloaded bytes')
        if asset.get('browser_download_url') != prefix + quote(name, safe=''):
            raise ValueError('Asset URL does not match the exact versioned release')
    return {'releasesUrl': release['html_url'],
            'downloads': {platform: remote[name]['browser_download_url'] for platform, name in platforms.items()},
            'release': {'tag': tag, 'sourceCommit': source_commit,
                        'checksumsUrl': prefix + 'SHA256SUMS', 'sourceMetadataUrl': prefix + 'release-source.json'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--release-json', type=Path, required=True)
    parser.add_argument('--platform-map', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a fresh output file; existing settings are never overwritten')
    try:
        result = prepare(args.repository, json.loads(args.release_json.read_text(encoding='utf-8')),
                         json.loads(args.platform_map.read_text(encoding='utf-8')), args.artifacts, args.source_commit)
    except (ValueError, KeyError, TypeError, OSError):
        raise SystemExit('Release verification failed; no website configuration written.') from None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as target:
        target.write(json.dumps(result, indent=2) + '\n')
    print('Verified exact local bytes/source metadata and GitHub digests; wrote download settings only.')
    print('Signatures, approved source publication and release acceptance remain separate gates.')


if __name__ == '__main__':
    main()
