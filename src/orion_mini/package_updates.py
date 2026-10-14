# SPDX-License-Identifier: AGPL-3.0-or-later
"""Private packaged updates authenticated by the existing paired mesh Hub.

Check and stage never launch code. Only an explicit install() hands off to the
native installer, waits for this application to exit, and reopens the new build.
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


def _remember(folder, config, release):
    identity = hashlib.sha256((config['base_url'].rstrip('/') + '\0' + config['device_id'] + '\0' +
                               release['platform'] + '\0' + release['profile']).encode()).hexdigest()
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
            raise ValueError('Hub offered an older or conflicting desktop release')
    write_json(path, {key: release[key] for key in ('build', 'sha256')})


def check(root, config):
    installed = current()
    if installed is None:
        return {'supported': False, 'available': False, 'current': None, 'release': None}
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
                'current': installed, 'release': release}


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


def stage(root, config, offered):
    release = validate_release(offered)
    with _LOCK:
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
                size = 0; digest = hashlib.sha256()
                while chunk := response.read(min(1024 * 1024, release['bytes'] + 1 - size)):
                    size += len(chunk)
                    if size > release['bytes']:
                        raise ValueError('Desktop download exceeds its declared size')
                    digest.update(chunk); output.write(chunk)
                output.flush(); os.fsync(output.fileno())
                if size != release['bytes'] or digest.hexdigest() != release['sha256']:
                    raise ValueError('Desktop download is incomplete or damaged')
            _package_metadata(target, release)
            write_json(folder / 'staged.json', release)
            return {'staged': True, 'path': str(target), 'release': release}
        except (OSError, ValueError, KeyError, urllib.error.URLError, zipfile.BadZipFile, tarfile.TarError):
            # Only this function's fresh ignored staging directory; never owner data.
            shutil.rmtree(folder)
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
