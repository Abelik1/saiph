# SPDX-License-Identifier: AGPL-3.0-or-later
"""Packaged desktop updates from this computer's own source.

Two feeds: the paired self-hosted mesh Hub, or the signed-in Saiph account on
the Hosted origin packaged into this build (``CloudFeed``; its routes are in
hub/orion_hub/hosted_service.py and docs/DESKTOP_UPDATES.md, not deployed yet). Check and stage
never launch code. Only an explicit install() hands off to the native
installer, waits for this application to exit, and reopens the new build.
"""
from __future__ import annotations

import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import socket
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import zipfile

from . import hub_client
from .storage import read_json, write_json

PLATFORMS = {'windows-x86_64': '.exe', 'linux-x86_64': '.tar.gz'}
PROFILES = {'link', 'workspace'}
MAX_BYTES = 2 * 1024 ** 3
MAX_EXPANDED_BYTES = 8 * 1024 ** 3
# Exact top level of a Linux package written by
# scripts/packaging/build-desktop-distribution.py; install.sh needs every file.
LINUX_DIRECTORIES = frozenset({'app', 'licenses'})
LINUX_FILES = frozenset({'package-manifest.json', 'components.json', 'VERSION', 'SHA256SUMS', 'install.sh',
                         'LINUX_COMPATIBILITY'})
VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?')
HASH = re.compile(r'[a-f0-9]{64}')
_LOCK = threading.RLock()
# What the Saiph account downloads for each platform: the website's installer
# files. Linux's .run is a shell wrapper around the unchanged .tar.gz release.
CLOUD_SUFFIX = {'windows-x86_64': '.exe', 'linux-x86_64': '.run'}
CLOUD_REASONS = {'cloud_manual', 'cloud_unavailable', 'cloud_signed_out', 'cloud_unofficial'}
MAX_NOTES = 4000
_PROGRESS = {'state': 'idle', 'done': 0, 'total': 0}
_PROGRESS_LOCK = threading.Lock()


def progress():
    """The current download for the Updates panel: idle, downloading, verifying, ready or failed."""
    with _PROGRESS_LOCK:
        return dict(_PROGRESS)


def _report(state, done=0, total=0):
    with _PROGRESS_LOCK:
        _PROGRESS.update(state=state, done=done, total=total)


def _build(value, *, current=False):
    if (type(value) is not int or not (0 if current else 1) <= value <= 2 ** 53 - 1):
        raise ValueError('Invalid packaged build number')


def validate_release(value):
    if (not isinstance(value, dict) or set(value) != {'schema', 'platform', 'profile', 'build', 'version', 'sha256', 'bytes'}
            or type(value['schema']) is not int or value['schema'] != 1
            or not isinstance(value['platform'], str) or value['platform'] not in PLATFORMS
            or not isinstance(value['profile'], str) or value['profile'] not in PROFILES
            or not isinstance(value['version'], str) or len(value['version']) > 100 or not VERSION.fullmatch(value['version'])
            or not isinstance(value['sha256'], str) or not HASH.fullmatch(value['sha256'])
            or type(value['bytes']) is not int or not 0 < value['bytes'] <= MAX_BYTES):
        raise ValueError('Invalid desktop release metadata')
    _build(value['build'])
    return dict(value)


def current():
    """Only immutable native bundle metadata can select an update edition."""
    bundle = getattr(sys, '_MEIPASS', None)
    if not getattr(sys, 'frozen', False) or not isinstance(bundle, str) or not Path(bundle).is_absolute():
        return None
    try:
        folder = Path(bundle)
        for name in ('distribution-profile.json', 'distribution-release.json'):
            if (folder / name).is_symlink() or (folder / name).stat().st_size > 4096:
                return None
        profile = read_json(folder / 'distribution-profile.json')
        release = read_json(folder / 'distribution-release.json')
        if (not isinstance(profile, dict) or set(profile) != {'schema', 'profile'} or type(profile['schema']) is not int
                or profile['schema'] != 1 or profile['profile'] not in PROFILES
                or not isinstance(release, dict) or set(release) != {'schema', 'build', 'version', 'platform'}
                or type(release['schema']) is not int or release['schema'] != 1
                or not isinstance(release['version'], str) or len(release['version']) > 100 or not VERSION.fullmatch(release['version'])):
            return None
        _build(release['build'], current=True)
        actual = ('windows' if sys.platform == 'win32' else 'linux' if sys.platform.startswith('linux') else '')
        if platform.machine().lower() not in {'amd64', 'x86_64'} or release['platform'] != actual + '-x86_64':
            return None
        return {**release, 'profile': profile['profile']}
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _origin(root, config):
    if (not isinstance(config, dict) or config.get('paired') is not True or not isinstance(config.get('device_id'), str)
            or not re.fullmatch(r'dev_[a-f0-9]{32}', config['device_id']) or not (Path(root) / 'hub-device-key.pem').is_file()):
        raise ValueError('Pair this computer before checking packaged updates')
    base = config.get('base_url')
    if not isinstance(base, str):
        raise ValueError('Packaged updates require the configured mesh Hub')
    from .enrollment import mesh_origin
    parsed = urlsplit(base)
    if parsed.hostname == 'pi.orion.internal':
        # Legacy owner profile: resolve once, then pin the mesh IP for both
        # metadata and artifact requests. No second DNS lookup can rebind it.
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 8765, type=socket.SOCK_STREAM)
        networks = (ipaddress.ip_network('100.64.0.0/10'), ipaddress.ip_network('fd7a:115c:a1e0::/48'))
        if not addresses or not all(any(ipaddress.ip_address(row[4][0]) in network for network in networks) for row in addresses):
            raise ValueError('Configured Hub does not resolve only to the mesh')
        address = ipaddress.ip_address(addresses[0][4][0])
        host = '[' + str(address) + ']' if address.version == 6 else str(address)
        if parsed.scheme != 'http' or parsed.username or parsed.password or parsed.path not in {'', '/'} or parsed.query or parsed.fragment:
            raise ValueError('Use the configured mesh HTTP Hub')
        base = f'http://{host}:{parsed.port or 8765}'
    return mesh_origin(base)


def _private_directory(root):
    folder = Path(root) / 'package-updates'
    if folder.is_symlink():
        raise ValueError('Unsafe update staging directory')
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == 'nt':
        user = getpass.getuser()
        secured = subprocess.run(['icacls', str(folder), '/inheritance:r', '/grant:r', user + ':(OI)(CI)(F)'],
                                 capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        if secured.returncode:
            raise ValueError('Private update staging permissions are unavailable')
    else:
        folder.chmod(0o700)
    return folder


def _remember(folder, config, release, *, source=None):
    """Refuse a feed that later offers an older build, or different bytes under the same number."""
    source = source or config['base_url'].rstrip('/') + '\0' + config['device_id']
    identity = hashlib.sha256((source + '\0' + release['platform'] + '\0' + release['profile']).encode()).hexdigest()
    path = folder / (identity + '.seen.json')
    if path.is_symlink():
        raise ValueError('Unsafe update history')
    if path.exists() and path.stat().st_size > 4096:
        raise ValueError('Invalid update history')
    previous = read_json(path, None)
    if previous is not None:
        if (not isinstance(previous, dict) or set(previous) != {'build', 'sha256'} or type(previous['build']) is not int
                or not isinstance(previous['sha256'], str) or not HASH.fullmatch(previous['sha256'])):
            raise ValueError('Invalid update history')
        if release['build'] < previous['build'] or (release['build'] == previous['build'] and release['sha256'] != previous['sha256']):
            raise ValueError('The update source offered an older or conflicting desktop release')
    write_json(path, {key: release[key] for key in ('build', 'sha256')})


class CloudFeed:
    """The Saiph account's desktop releases: only this build's packaged HTTPS origin, with
    the signed-in account's token. No environment proxy, redirect, cookie or supplied URL."""

    def __init__(self, origin, token, *, http=None):
        parsed = urlsplit(origin) if isinstance(origin, str) else None
        if (parsed is None or parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.port not in (None, 443)
                or not isinstance(token, str) or not 0 < len(token) <= 16384 or any(ord(c) < 33 or ord(c) > 126 for c in token)):
            raise ValueError('Invalid Saiph account update source')
        self.origin, self.token = origin.rstrip('/'), token
        if http is None:
            import requests
            http = requests.Session()
            http.trust_env = False
        self.http = http

    @property
    def source(self):
        return 'cloud\0' + self.origin

    def release(self, platform):
        """The description's bytes, None when nothing is published, or a reason code."""
        response = self.http.get(f'{self.origin}/v1/app/desktop/{platform}/release', timeout=(5, 15), allow_redirects=False,
                                 stream=True, headers={'Accept': 'application/json', 'Authorization': 'Bearer ' + self.token})
        with response:
            if response.status_code == 204:
                return None
            if response.status_code in (401, 403):
                return 'cloud_signed_out'
            if response.status_code == 404:
                return 'cloud_unavailable'
            if response.status_code != 200:
                raise ValueError('Desktop update check failed')
            return _bounded(response, 16384)

    def download(self, platform):
        """A fresh five-minute ticket, then the file it names; the ticket is the only credential sent."""
        response = self.http.post(f'{self.origin}/v1/app/desktop/{platform}/download', data=b'{}', timeout=(5, 15),
                                  allow_redirects=False, stream=True,
                                  headers={'Accept': 'application/json', 'Content-Type': 'application/json',
                                           'Authorization': 'Bearer ' + self.token})
        with response:
            if response.status_code != 200:
                raise ValueError('Desktop download unavailable')
            ticket = _strict_json(_bounded(response, 1024))
        if (not isinstance(ticket, dict) or set(ticket) != {'ticket'} or not isinstance(ticket['ticket'], str)
                or not re.fullmatch(r'[A-Za-z0-9_-]{43}', ticket['ticket'])):
            raise ValueError('Invalid download ticket')
        return self.http.get(f"{self.origin}/v1/download/{ticket['ticket']}", timeout=(5, 60), allow_redirects=False,
                             stream=True, headers={'Accept-Encoding': 'identity'})


def _bounded(response, limit):
    data = bytearray()
    for part in response.iter_content(4096):
        data.extend(part)
        if len(data) > limit:
            raise ValueError('Update description is too large')
    return bytes(data)


def _strict_json(raw):
    def pairs(items):
        if len({key for key, _ in items}) != len(items):
            raise ValueError('Repeated key')
        return dict(items)

    def constant(_):
        raise ValueError('Invalid number')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)


def validate_cloud_release(raw):
    """The Saiph account's description: the mesh metadata plus what's new. Returns (release, notes)."""
    try:
        value = _strict_json(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError('Invalid desktop release metadata') from None
    if not isinstance(value, dict) or set(value) != {'schema', 'platform', 'profile', 'build', 'version', 'sha256', 'bytes', 'notes'}:
        raise ValueError('Invalid desktop release metadata')
    notes = value.pop('notes')
    if (not isinstance(notes, str) or len(notes) > MAX_NOTES
            or any((ord(c) < 32 and c != '\n') or ord(c) == 127 or '‪' <= c <= '‮' or '⁦' <= c <= '⁩' for c in notes)):
        raise ValueError('Invalid desktop release notes')
    return validate_release(value), notes.strip()


def _check_cloud(root, installed, feed):
    raw = feed.release(installed['platform'])
    if isinstance(raw, str):
        return {'supported': False, 'available': False, 'current': installed, 'release': None, 'reason': raw}
    release, notes = (None, '') if raw is None else validate_cloud_release(raw)
    if release is not None:
        if any(release[key] != installed[key] for key in ('platform', 'profile')):
            raise ValueError('Saiph account offered another desktop edition or platform')
        if release['build'] > installed['build'] and release['version'] == installed['version']:
            raise ValueError('Desktop update must use a new version directory')
        _remember(_private_directory(root), None, release, source=feed.source)
    # An older or equal build is never offered; install() refuses it again.
    return {'supported': True, 'available': release is not None and release['build'] > installed['build'],
            'current': installed, 'release': release, 'notes': notes, 'source': 'cloud'}


def source_for(workspace):
    """The ``cloud`` argument for this workspace: False for a self-hosted computer, else the
    Saiph account feed or the reason it cannot be asked."""
    if not workspace.hosted_blocks_self_hosted():
        return False
    try:
        controller = workspace.hosted_controller()
    except (ValueError, ImportError):
        return 'cloud_manual'
    return controller.update_feed()


def check(root, config, *, cloud=False):
    """``cloud``: False for the mesh Hub, a CloudFeed for the Saiph account, or a reason
    code (True meaning cloud_manual) when the account cannot be asked."""
    installed = current()
    if installed is None:
        return {'supported': False, 'available': False, 'current': None, 'release': None}
    if isinstance(cloud, CloudFeed):
        with _LOCK:
            return _check_cloud(root, installed, cloud)
    if cloud:
        # Retained mesh pairing is inactive under Saiph Cloud and must never become an update source.
        return {'supported': False, 'available': False, 'current': installed,
                'release': None, 'reason': cloud if cloud in CLOUD_REASONS else 'cloud_manual'}
    with _LOCK:
        origin = _origin(root, config)
        path = f"/v1/link/desktop/releases/{installed['platform']}/{installed['profile']}"
        reply = hub_client.signed(Path(root), {**config, 'base_url': origin}, path)
        if not isinstance(reply, dict) or set(reply) != {'release'}:
            raise ValueError('Invalid desktop update reply')
        release = reply['release']
        if release is not None:
            release = validate_release(release)
            if any(release[key] != installed[key] for key in ('platform', 'profile')):
                raise ValueError('Hub offered another desktop edition or platform')
            if release['build'] > installed['build'] and release['version'] == installed['version']:
                raise ValueError('Desktop update must use a new version directory')
            _remember(_private_directory(root), config, release)
        return {'supported': True, 'available': release is not None and release['build'] > installed['build'],
                'current': installed, 'release': release, 'notes': '', 'source': 'hub'}


def _run_payload(path, release, folder):
    """Check a Linux .run setup file without running it and write out its release archive.

    The file (scripts/packaging/linux-setup.sh) is a filled template followed by the
    unchanged .tar.gz release. Its own --text mode only checks and unpacks that archive
    and runs its install.sh, so the updater does exactly that through the verified
    archive. Returns the archive and the metadata that describes it, for install().
    """
    size = path.stat().st_size
    with path.open('rb') as source:
        head = source.read(65536)
    if not head.startswith(b'#!/bin/sh\n# SPDX-License-Identifier: AGPL-3.0-or-later\n# Saiph '):
        raise ValueError('Expected a Saiph Linux setup file')

    def field(name, pattern):
        found = re.findall(rb'^' + name + rb"='(" + pattern + rb")'$", head, re.M)
        if len(found) != 1:
            raise ValueError('Invalid Saiph Linux setup file')
        return found[0].decode('ascii')
    version = field(rb'version', rb'[0-9A-Za-z.-]{1,100}')
    archive = field(rb'archive_name', rb'Saiph-[A-Za-z]+-[0-9A-Za-z.-]{1,100}-linux-x86_64\.tar\.gz')
    payload_bytes = int(field(rb'payload_bytes', rb'[1-9][0-9]{0,11}'))
    payload_sha256 = field(rb'payload_sha256', rb'[a-f0-9]{64}')
    if version != release['version'] or not archive.endswith('-' + version + '-linux-x86_64.tar.gz') or not payload_bytes < size:
        raise ValueError('Linux setup file does not match the offered desktop build')
    staged = dict(release, sha256=payload_sha256, bytes=payload_bytes)
    target = folder / (payload_sha256 + PLATFORMS['linux-x86_64'])
    digest = hashlib.sha256()
    with path.open('rb') as source, target.open('xb') as output:
        target.chmod(0o600)
        source.seek(size - payload_bytes)
        while chunk := source.read(1024 * 1024):
            digest.update(chunk); output.write(chunk)
        output.flush(); os.fsync(output.fileno())
    if digest.hexdigest() != payload_sha256:
        raise ValueError('Linux setup file is damaged')
    path.unlink()
    return target, staged


def _package_metadata(path, release):
    if release['platform'] == 'windows-x86_64':
        with path.open('rb') as source:
            header = source.read(64)
            if len(header) != 64 or header[:2] != b'MZ':
                raise ValueError('Expected a Windows native installer')
            offset = struct.unpack_from('<I', header, 60)[0]
            if not 64 <= offset <= 4 * 1024 * 1024:
                raise ValueError('Invalid Windows native installer')
            source.seek(offset)
            if source.read(6) != b'PE\0\0\x64\x86':
                raise ValueError('Expected an x86-64 Windows installer')
            source.seek(-16, 2); footer = source.read(16)
            if footer[8:] != b'ORIONZIP' or not 0 < struct.unpack('<Q', footer[:8])[0] < path.stat().st_size - 16:
                raise ValueError('Expected a Saiph native installer')
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) > 100000 or len(set(names)) != len(names):
                raise ValueError('Invalid package members')
            def read(name):
                if archive.getinfo(name).file_size > 32 * 1024 * 1024:
                    raise ValueError('Package metadata is too large')
                return json.loads(archive.read(name))
            package = read('package-manifest.json')
            profile = read('app/_internal/distribution-profile.json')
            build = read('app/_internal/distribution-release.json')
    else:
        required = {'orion/package-manifest.json', 'orion/app/_internal/distribution-profile.json',
                    'orion/app/_internal/distribution-release.json', 'orion/app/saiph'}
        found = {}; names = set(); total = 0
        with tarfile.open(path, 'r:gz') as archive:
            for count, item in enumerate(archive):
                _member(item)
                total += item.size
                if count >= 100000 or total > MAX_EXPANDED_BYTES or item.name in names:
                    raise ValueError('Linux package exceeds extraction bounds')
                names.add(item.name)
                if item.name not in required:
                    continue
                if item.name in found or not item.isfile() or item.size > 32 * 1024 * 1024:
                    raise ValueError('Invalid package metadata')
                source = archive.extractfile(item)
                if item.name.endswith('/saiph'):
                    header = source.read(20)
                    if len(header) < 20 or header[:6] != b'\x7fELF\x02\x01' or header[18:20] != b'\x3e\0':
                        raise ValueError('Expected an x86-64 Linux executable')
                    found[item.name] = True
                else:
                    found[item.name] = json.loads(source.read())
        if set(found) != required:
            raise ValueError('Incomplete Linux native package')
        package = found['orion/package-manifest.json']
        profile = found['orion/app/_internal/distribution-profile.json']
        build = found['orion/app/_internal/distribution-release.json']
    if (not isinstance(package, dict) or package.get('format') != 'orion-desktop-package'
            or type(package.get('schema')) is not int or package['schema'] != 1
            or any(package.get(key) != release[key] for key in ('platform', 'profile', 'version'))
            or not isinstance(profile, dict) or profile != {'schema': 1, 'profile': release['profile']}
            or type(profile.get('schema')) is not int
            or not isinstance(build, dict) or build != {key: release[key] for key in ('schema', 'build', 'version', 'platform')}
            or type(build.get('schema')) is not int or type(build.get('build')) is not int):
        raise ValueError('Installer does not match the offered desktop build')


def _member(item):
    name = item.name
    parts = name.split('/')
    if (not name or '\\' in name or any(ord(c) < 32 for c in name) or ':' in name
            or any(part in {'', '.', '..'} for part in parts) or parts[0] != 'orion'
            or not (item.isfile() or item.isdir()) or item.issparse() or not 0 <= item.size <= MAX_EXPANDED_BYTES
            or (len(parts) > 1 and parts[1] not in LINUX_DIRECTORIES | LINUX_FILES)
            or (len(parts) == 2 and parts[1] in LINUX_FILES and not item.isfile())
            or (len(parts) > 2 and parts[1] not in LINUX_DIRECTORIES)):
        raise ValueError('Unsafe Linux package member')
    return PurePosixPath(name)


def _extract_linux(path, folder):
    target = folder / 'extracted'
    target.mkdir(mode=0o700, exist_ok=False)
    names = set(); total = 0
    with tarfile.open(path, 'r:gz') as archive:
        for item in archive:
            relative = _member(item)
            total += item.size
            if item.name in names or len(names) >= 100000 or total > MAX_EXPANDED_BYTES:
                raise ValueError('Linux package exceeds extraction bounds')
            names.add(item.name)
            destination = target.joinpath(*relative.parts)
            if item.isdir():
                destination.mkdir(mode=0o700, parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with archive.extractfile(item) as source, destination.open('xb') as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                destination.chmod(0o700 if item.mode & 0o111 else 0o600)
    for name in ('install.sh', 'VERSION', 'SHA256SUMS', 'LINUX_COMPATIBILITY', 'package-manifest.json', 'app/saiph'):
        if not (target / 'orion' / name).is_file():
            raise ValueError('Linux package is missing its installer')
    return target / 'orion' / 'install.sh'


def _verify(path, release):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != release['bytes']:
        raise ValueError('Desktop installer size does not match')
    digest = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != release['sha256']:
        raise ValueError('Desktop installer hash does not match')
    _package_metadata(path, release)


def _stream(response, output, release):
    """Copy exactly the published number of bytes, reporting progress, then check the hash."""
    size = 0; digest = hashlib.sha256()
    _report('downloading', 0, release['bytes'])
    while chunk := response.read(min(1024 * 1024, release['bytes'] + 1 - size)):
        size += len(chunk)
        if size > release['bytes']:
            raise ValueError('Desktop download exceeds its declared size')
        digest.update(chunk); output.write(chunk)
        _report('downloading', size, release['bytes'])
    output.flush(); os.fsync(output.fileno())
    _report('verifying', size, release['bytes'])
    if size != release['bytes'] or digest.hexdigest() != release['sha256']:
        raise ValueError('Desktop download is incomplete or damaged')


def _stage_cloud(root, config, release, feed):
    result = check(root, config, cloud=feed)
    if not result.get('available') or result['release'] != release:
        raise ValueError('Desktop release changed; check for updates again')
    folder = Path(tempfile.mkdtemp(prefix='staged-', dir=_private_directory(root)))
    target = folder / (release['sha256'] + CLOUD_SUFFIX[release['platform']])
    try:
        response = feed.download(release['platform'])
        with response, target.open('xb') as output:
            target.chmod(0o600)
            if response.status_code != 200 or response.headers.get('Content-Length') != str(release['bytes']):
                raise ValueError('Desktop download headers do not match')
            response.raw.decode_content = False
            _stream(response.raw, output, release)
        staged = release
        if release['platform'] == 'linux-x86_64':
            target, staged = _run_payload(target, release, folder)
        _package_metadata(target, staged)
        write_json(folder / 'staged.json', staged)
        _report('ready', release['bytes'], release['bytes'])
        return {'staged': True, 'path': str(target), 'release': staged}
    except Exception:
        # Only this function's fresh ignored staging directory; never owner data.
        shutil.rmtree(folder)
        _report('failed')
        raise ValueError('Desktop update could not be verified. Existing application and data were retained.') from None


def stage(root, config, offered, *, cloud=False):
    """Download and verify; never runs anything. ``cloud`` as for check()."""
    release = validate_release(offered)
    with _LOCK:
        if isinstance(cloud, CloudFeed):
            return _stage_cloud(root, config, release, cloud)
        if cloud:
            raise ValueError('Sign in to your Saiph account to download desktop updates.')
        result = check(root, config)
        if not result['available'] or result['release'] != release:
            raise ValueError('Desktop release changed; check for updates again')
        folder = Path(tempfile.mkdtemp(prefix='staged-', dir=_private_directory(root)))
        target = folder / (release['sha256'] + PLATFORMS[release['platform']])
        path = f"/v1/link/desktop/artifacts/{release['platform']}/{release['profile']}/{release['sha256']}"
        request = urllib.request.Request(_origin(root, config) + path,
                                         headers=hub_client.signed_headers(Path(root), config['device_id'], path))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), hub_client._NoRedirect())
        try:
            with opener.open(request, timeout=30) as response, target.open('xb') as output:
                target.chmod(0o600)
                if (response.status != 200 or response.headers.get('Content-Length') != str(release['bytes'])
                        or response.headers.get('X-Orion-SHA256') != release['sha256']):
                    raise ValueError('Desktop download headers do not match')
                _stream(response, output, release)
            _package_metadata(target, release)
            write_json(folder / 'staged.json', release)
            _report('ready', release['bytes'], release['bytes'])
            return {'staged': True, 'path': str(target), 'release': release}
        except (OSError, ValueError, KeyError, urllib.error.URLError, zipfile.BadZipFile, tarfile.TarError):
            # Only this function's fresh ignored staging directory; never owner data.
            shutil.rmtree(folder)
            _report('failed')
            raise ValueError('Desktop update could not be verified. Existing application and data were retained.') from None


def status(root):
    try:
        path = Path(root) / 'package-updates' / 'update-status.json'
        if path.is_symlink() or path.exists() and path.stat().st_size > 4096:
            raise ValueError()
        value = read_json(path, {'state': 'idle', 'code': ''})
    except (OSError, ValueError):
        return {'state': 'failed', 'code': 'install_failed'}
    allowed = {'', 'close_timeout', 'damaged_package', 'installer_failed', 'missing_release', 'install_failed', 'handoff_failed'}
    if (not isinstance(value, dict) or set(value) != {'state', 'code'}
            or not isinstance(value['state'], str) or value['state'] not in {'idle', 'waiting', 'completed', 'failed'}
            or not isinstance(value['code'], str) or value['code'] not in allowed):
        return {'state': 'failed', 'code': 'install_failed'}
    return value


WINDOWS_HANDOFF = r'''param([int]$AppPid,[string]$Package,[string]$Digest,[string]$NextExe,[string]$OldExe,[string]$StatusFile,[ValidateRange(1,120)][int]$WaitSeconds=120)
$ErrorActionPreference='Stop'
$oldExited=$false
function Report([string]$state,[string]$code) {
  $temporary=$StatusFile+'.'+[Guid]::NewGuid().ToString('N')+'.tmp'
  @{state=$state;code=$code} | ConvertTo-Json -Compress | Set-Content -LiteralPath $temporary -Encoding UTF8
  Move-Item -LiteralPath $temporary -Destination $StatusFile -Force
}
function ReopenOld {
  if ($oldExited -and (Test-Path -LiteralPath $OldExe -PathType Leaf)) { Start-Process -FilePath $OldExe }
}
try {
  $p=Get-Process -Id $AppPid -ErrorAction SilentlyContinue
  if ($p) {
    try { Wait-Process -Id $AppPid -Timeout $WaitSeconds -ErrorAction Stop }
    catch { Report 'failed' 'close_timeout'; exit 2 }
  }
  $oldExited=$true
  $source=[IO.File]::OpenRead($Package)
  $sha=[Security.Cryptography.SHA256]::Create()
  try { $actual=[BitConverter]::ToString($sha.ComputeHash($source)).Replace('-','').ToLowerInvariant() }
  finally { $source.Dispose(); $sha.Dispose() }
  if ($actual -ne $Digest) {
    Report 'failed' 'damaged_package'; ReopenOld; exit 3
  }
  $p=Start-Process -FilePath $Package -ArgumentList @('--silent','--no-launch') -Wait -PassThru -WindowStyle Hidden
  if ($p.ExitCode -ne 0) { Report 'failed' 'installer_failed'; ReopenOld; exit 4 }
  if (Test-Path -LiteralPath $NextExe -PathType Leaf) {
    Report 'completed' ''; Start-Process -FilePath $NextExe
  } else { Report 'failed' 'missing_release'; ReopenOld; exit 5 }
} catch {
  try { Report 'failed' 'install_failed' } catch { }
  try { ReopenOld } catch { }
  exit 6
}
'''

LINUX_HANDOFF = r'''#!/bin/sh
set -eu
pid=$1; package=$2; digest=$3; installer=$4; next=$5; old=$6; status=$7
exited=0; completed=0; code=install_failed
report() {
  temporary="$status.$$.tmp"
  printf '{"state":"%s","code":"%s"}\n' "$1" "$2" > "$temporary"
  mv -f -- "$temporary" "$status"
}
recover() {
  if [ "$completed" != 1 ]; then
    report failed "$code"
    if [ "$exited" = 1 ] && [ -f "$old" ]; then "$old" >/dev/null 2>&1 & fi
  fi
}
trap recover EXIT
attempt=0
while kill -0 "$pid" 2>/dev/null; do
  attempt=$((attempt+1)); [ "$attempt" -lt 120 ] || { code=close_timeout; exit 2; }; sleep 1
done
exited=1
actual=$(sha256sum -- "$package"); actual=${actual%% *}
[ "$actual" = "$digest" ] || { code=damaged_package; exit 3; }
if ! /bin/sh "$installer" >/dev/null 2>&1; then code=installer_failed; exit 4; fi
[ -f "$next" ] || { code=missing_release; exit 5; }
report completed ''; code=install_failed
exec "$next"
'''


def _running_executable(folder, *names):
    """This process's installed executable: its name, or the pre-rename compatibility copy
    that older updaters relaunch. Portable and source copies match neither."""
    running = Path(sys.executable).resolve()
    return next((folder / name for name in names if running == (folder / name).resolve()), None)


def install(root, staged):
    """Explicit action only. Caller must quit after this returns; no processes are killed."""
    installed = current()
    if (installed is None or not isinstance(staged, dict) or set(staged) != {'staged', 'path', 'release'}
            or staged['staged'] is not True or not isinstance(staged['path'], str)):
        raise ValueError('Stage a packaged update before installing')
    release = validate_release(staged['release'])
    if (any(release[key] != installed[key] for key in ('platform', 'profile')) or release['build'] <= installed['build']
            or release['version'] == installed['version']):
        raise ValueError('This update does not upgrade the installed edition')
    updates = _private_directory(root).resolve()
    path = Path(staged['path'])
    if (not path.is_absolute() or path.is_symlink() or path.parent.is_symlink() or path.parent.parent.resolve() != updates
            or not re.fullmatch(r'staged-[A-Za-z0-9_-]+', path.parent.name)
            or path.name != release['sha256'] + PLATFORMS[release['platform']]
            or (path.parent / 'staged.json').is_symlink()
            or read_json(path.parent / 'staged.json') != release):
        raise ValueError('Choose a verified update staged by this application')
    _verify(path, release)
    environment = {key: value for key, value in os.environ.items() if not key.startswith('_PYI') and key != '_MEIPASS2'}
    if release['platform'] == 'windows-x86_64':
        base = Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'OrionMini'
        expected = _running_executable(base / 'releases' / installed['version'] / 'app', 'Saiph.exe', 'OrionMini.exe')
        if expected is None:
            raise ValueError('This portable build can stage updates; install its native package before using automatic installation')
        helper = path.parent / 'install.ps1'
        with helper.open('x', encoding='utf-8-sig') as output:
            output.write(WINDOWS_HANDOFF)
        command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(helper),
                   '-AppPid', str(os.getpid()), '-Package', str(path), '-Digest', release['sha256'],
                   '-NextExe', str(base / 'releases' / release['version'] / 'app' / 'Saiph.exe'),
                   '-OldExe', str(expected), '-StatusFile', str(updates / 'update-status.json')]
        options = {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        base = Path.home() / '.local/lib/orion'
        expected = _running_executable(base / 'releases' / installed['version'] / 'app', 'saiph', 'OrionMini')
        if expected is None:
            raise ValueError('Install this native package before using automatic installation')
        installer = _extract_linux(path, path.parent)
        helper = path.parent / 'install.sh'
        with helper.open('x', encoding='utf-8') as output:
            output.write(LINUX_HANDOFF)
        helper.chmod(0o700)
        command = ['/bin/sh', str(helper), str(os.getpid()), str(path), release['sha256'], str(installer),
                   str(base / 'releases' / release['version'] / 'app/saiph'), str(expected), str(updates / 'update-status.json')]
        options = {'start_new_session': True}
    write_json(updates / 'update-status.json', {'state': 'waiting', 'code': ''})
    try:
        subprocess.Popen(command, cwd=str(path.parent), env=environment, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
    except OSError:
        write_json(updates / 'update-status.json', {'state': 'failed', 'code': 'handoff_failed'})
        raise ValueError('The update installer could not start. Saiph is still running.') from None
    return {'started': True}
