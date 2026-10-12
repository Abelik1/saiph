# SPDX-License-Identifier: AGPL-3.0-or-later
"""Administrator-published native packages, served only to paired mesh devices."""
from __future__ import annotations

import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import struct
import tarfile
from uuid import uuid4
import zipfile

PLATFORMS = {'windows-x86_64': '.exe', 'linux-x86_64': '.tar.gz'}
PROFILES = {'link', 'workspace'}
MAX_BYTES = 2 * 1024 ** 3
VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?')
HASH = re.compile(r'[a-f0-9]{64}')


def validate(value):
    if (not isinstance(value, dict) or set(value) != {'schema', 'platform', 'profile', 'build', 'version', 'sha256', 'bytes'}
            or type(value['schema']) is not int or value['schema'] != 1
            or not isinstance(value['platform'], str) or value['platform'] not in PLATFORMS
            or not isinstance(value['profile'], str) or value['profile'] not in PROFILES
            or type(value['build']) is not int or not 0 < value['build'] <= 2 ** 53 - 1
            or not isinstance(value['version'], str) or len(value['version']) > 100 or not VERSION.fullmatch(value['version'])
            or not isinstance(value['sha256'], str) or not HASH.fullmatch(value['sha256'])
            or type(value['bytes']) is not int or not 0 < value['bytes'] <= MAX_BYTES):
        raise ValueError('Invalid desktop release metadata')
    return dict(value)


def directory(data, platform, profile):
    if platform not in PLATFORMS or profile not in PROFILES:
        raise ValueError('Unsupported desktop package')
    folder = Path(data) / 'desktop-releases' / platform / profile
    if any(path.is_symlink() for path in (folder, folder.parent, folder.parent.parent)):
        raise ValueError('Unsafe desktop release directory')
    return folder


def latest(data, platform, profile):
    path = directory(data, platform, profile) / 'latest.json'
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size > 4096:
        raise ValueError('Invalid desktop release metadata')
    value = validate(json.loads(path.read_text(encoding='utf-8')))
    if (value['platform'], value['profile']) != (platform, profile):
        raise ValueError('Mismatched desktop release metadata')
    return value


def _json(raw):
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError('Package metadata is too large')
    return json.loads(raw)


def inspect_package(path, release):
    """The package must actually carry this edition, platform and build."""
    if release['platform'] == 'windows-x86_64':
        with path.open('rb') as source:
            header = source.read(64)
            if len(header) != 64 or header[:2] != b'MZ':
                raise ValueError('Expected a Windows native installer')
            offset = struct.unpack_from('<I', header, 60)[0]
            if not 64 <= offset <= 4 * 1024 * 1024:
                raise ValueError('Expected a Windows native installer')
            source.seek(offset)
            if source.read(6) != b'PE\0\0\x64\x86':
                raise ValueError('Expected an x86-64 Windows installer')
            source.seek(-16, 2)
            footer = source.read(16)
            if footer[8:] != b'ORIONZIP' or not 0 < struct.unpack('<Q', footer[:8])[0] < path.stat().st_size - 16:
                raise ValueError('Expected a Saiph native installer')
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) > 100000 or len(set(names)) != len(names):
                raise ValueError('Invalid package members')
            def read(name):
                info = archive.getinfo(name)
                if info.file_size > 32 * 1024 * 1024:
                    raise ValueError('Package metadata is too large')
                return _json(archive.read(name))
            package = read('package-manifest.json')
            profile = read('app/_internal/distribution-profile.json')
            current = read('app/_internal/distribution-release.json')
    else:
        with path.open('rb') as source:
            if source.read(2) != b'\x1f\x8b':
                raise ValueError('Expected a Linux package archive')
        required = {'orion/package-manifest.json', 'orion/app/_internal/distribution-profile.json',
                    'orion/app/_internal/distribution-release.json', 'orion/app/OrionMini'}
        found = {}
        with tarfile.open(path, 'r:gz') as archive:
            for index, item in enumerate(archive):
                if index >= 100000:
                    raise ValueError('Too many package members')
                if item.name not in required:
                    continue
                if not item.isfile() or item.name in found or item.size > 32 * 1024 * 1024:
                    raise ValueError('Invalid package metadata member')
                source = archive.extractfile(item)
                if item.name.endswith('/OrionMini'):
                    header = source.read(20)
                    if len(header) < 20 or header[:6] != b'\x7fELF\x02\x01' or header[18:20] != b'\x3e\0':
                        raise ValueError('Expected an x86-64 Linux executable')
                    found[item.name] = True
                else:
                    found[item.name] = _json(source.read())
        if set(found) != required:
            raise ValueError('Missing package metadata')
        package = found['orion/package-manifest.json']
        profile = found['orion/app/_internal/distribution-profile.json']
        current = found['orion/app/_internal/distribution-release.json']
    if (not isinstance(package, dict) or package.get('format') != 'orion-desktop-package'
            or type(package.get('schema')) is not int or package['schema'] != 1
            or any(package.get(key) != release[key] for key in ('platform', 'profile', 'version'))
            or not isinstance(profile, dict) or profile != {'schema': 1, 'profile': release['profile']} or type(profile.get('schema')) is not int
            or not isinstance(current, dict) or current != {key: release[key] for key in ('schema', 'build', 'version', 'platform')}
            or type(current.get('schema')) is not int or type(current.get('build')) is not int):
        raise ValueError('Installer does not match the published desktop build')


def publish(data, source, platform, profile, build, version):
    folder = directory(data, platform, profile)
    metadata = validate(dict(schema=1, platform=platform, profile=profile, build=build,
                             version=version, sha256='0' * 64, bytes=1))
    source = Path(source)
    if source.is_symlink() or not source.is_file() or not 0 < source.stat().st_size <= MAX_BYTES:
        raise ValueError('Choose a bounded regular native installer')
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / (uuid4().hex + '.staging')
    pointer = folder / (uuid4().hex + '.json.staging')
    try:
        digest = hashlib.sha256(); size = 0
        with source.open('rb') as incoming, temporary.open('xb') as output:
            os.chmod(temporary, 0o600)
            while chunk := incoming.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError('Desktop package is too large')
                digest.update(chunk); output.write(chunk)
            output.flush(); os.fsync(output.fileno())
        metadata.update(sha256=digest.hexdigest(), bytes=size)
        validate(metadata)
        try:
            inspect_package(temporary, metadata)
        except (KeyError, zipfile.BadZipFile, tarfile.TarError, struct.error, EOFError):
            raise ValueError('Invalid native desktop installer') from None
        # SQLite serializes publishers across threads/processes and releases on
        # a crash. The atomic pointer never exposes an incomplete artifact.
        with closing(sqlite3.connect(folder / 'publish-lock.sqlite3', timeout=10)) as lock:
            lock.execute('BEGIN IMMEDIATE')
            previous = latest(data, platform, profile)
            if previous and build <= previous['build']:
                raise ValueError('Desktop build is not newer than the published release')
            # Native installers own immutable directories by version. A higher
            # numeric build must not reuse any previously activated directory.
            lock.execute('CREATE TABLE IF NOT EXISTS versions (version TEXT PRIMARY KEY, build INTEGER NOT NULL, sha256 TEXT NOT NULL)')
            if previous:
                lock.execute('INSERT OR IGNORE INTO versions VALUES (?,?,?)',
                             (previous['version'], previous['build'], previous['sha256']))
            if lock.execute('SELECT 1 FROM versions WHERE version=?', (version,)).fetchone():
                raise ValueError('Desktop version has already been published; use a new version and build number')
            lock.execute('INSERT INTO versions VALUES (?,?,?)', (version, build, metadata['sha256']))
            target = folder / (metadata['sha256'] + PLATFORMS[platform])
            if not target.exists() and not target.is_symlink():
                # All publications hold the same cross-process SQLite write
                # lock. Rename the complete file without replacing old content.
                os.rename(temporary, target)
            else:
                # Recover a fully written artifact left before pointer activation.
                existing, existing_size = open_artifact(data, platform, profile, metadata['sha256'])
                with existing:
                    previous_digest = hashlib.sha256()
                    while chunk := existing.read(1024 * 1024):
                        previous_digest.update(chunk)
                if existing_size != size or previous_digest.hexdigest() != metadata['sha256']:
                    raise ValueError('Existing desktop artifact is damaged')
            os.chmod(target, 0o400)
            _sync_directory(folder)
            with pointer.open('x', encoding='utf-8') as output:
                json.dump(metadata, output); output.flush(); os.fsync(output.fileno())
            os.replace(pointer, folder / 'latest.json')
            _sync_directory(folder)
            lock.commit()
        return metadata
    finally:
        temporary.unlink(missing_ok=True)
        pointer.unlink(missing_ok=True)


def _sync_directory(folder):
    if os.name != 'nt':
        descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def open_artifact(data, platform, profile, digest):
    if not isinstance(digest, str) or not HASH.fullmatch(digest):
        raise ValueError('Invalid desktop artifact digest')
    path = directory(data, platform, profile) / (digest + PLATFORMS[platform])
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BYTES:
            raise ValueError('Invalid desktop artifact')
        return os.fdopen(descriptor, 'rb'), info.st_size
    except BaseException:
        os.close(descriptor)
        raise
