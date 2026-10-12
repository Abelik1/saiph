# SPDX-License-Identifier: AGPL-3.0-or-later
"""Prepare the official Seafile client without resetting profiles or logging secrets.

This module is a backend adapter, not a credential-import endpoint. Only pass a
profile obtained through the existing authenticated Hub client. Approved setup
and management actions launch the official client; Hub requests stay in the
authenticated caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import socket
import sqlite3
import stat
import subprocess
import sys
import threading
import time
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from urllib.parse import urlsplit
from uuid import UUID


def linux_install_helper():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2])) / 'assets/install-cloud-linux.sh'


def linux_rpc_helper():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2])) / 'assets/cloud-rpc-linux.py'


def _linux_rpc_request(value, *, timeout=20):
    """Use distro Python/modules independently of the frozen Qt environment."""
    helper = _plain_path(linux_rpc_helper())
    payload = json.dumps(value, separators=(',', ':')).encode('utf-8')
    if len(payload) > 16384:
        raise ValueError('The private file sync request is unsupported.')
    try:
        result = subprocess.run(['/usr/bin/python3', '-I', str(helper)], input=payload,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, env=_linux_environment())
        if result.returncode or len(result.stdout) > 128:
            raise ValueError()
        reply = json.loads(result.stdout)
        if (not isinstance(reply, dict) or set(reply) != {'state'}
                or reply['state'] not in {'available', 'link_requested', 'failed'}):
            raise ValueError()
        return reply['state']
    except (OSError, ValueError, subprocess.SubprocessError):
        raise ValueError('The distribution file sync interface is unavailable. Existing profiles were preserved.') from None


def installation_supported(platform=None):
    platform = platform or sys.platform
    return platform == 'win32' or (platform.startswith('linux') and bool(shutil.which('pkexec')) and linux_install_helper().is_file())


def installed_linux_cli():
    path = Path('/usr/bin/seaf-cli')
    return path if path.is_file() and os.access(path, os.X_OK) else None


def server_origin(value: str) -> str:
    """Cloud traffic stays on a numeric mesh address; never accept credentials."""
    try:
        if not isinstance(value, str) or len(value) > 256 or any(ord(c) <= 32 for c in value):
            raise ValueError
        parsed = urlsplit(value)
        address = ipaddress.ip_address(parsed.hostname or '')
        network = ipaddress.ip_network('100.64.0.0/10' if address.version == 4 else 'fd7a:115c:a1e0::/48')
        if (parsed.scheme not in {'http', 'https'} or address not in network
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {'', '/'} or parsed.query or parsed.fragment
                or '%' in value or not 1 <= (parsed.port if parsed.port is not None else (443 if parsed.scheme == 'https' else 80)) <= 65535):
            raise ValueError
        host = f'[{address}]' if address.version == 6 else str(address)
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == 'https' else 80)
        return f'{parsed.scheme}://{host}:{port}'
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Cloud requires a numeric mesh server origin.') from None


@dataclass(frozen=True, repr=False)
class CloudProfile:
    """Validated data, NOT proof of Hub authentication or library-scoped access."""
    server: str
    user: str
    token: str = field(repr=False)
    library_id: str
    token_scope: str = 'account'

    def __post_init__(self):
        object.__setattr__(self, 'server', server_origin(self.server))
        if (not isinstance(self.user, str) or not re.fullmatch(r'[A-Za-z0-9._+@-]{1,254}', self.user)
                or not isinstance(self.token, str) or not re.fullmatch(r'[a-fA-F0-9]{32,128}', self.token)
                or self.token_scope != 'account'):
            raise ValueError('Cloud requires a supported non-admin account profile.')
        try:
            if str(UUID(self.library_id)) != self.library_id:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ValueError('Cloud requires a canonical library identifier.') from None

    def __repr__(self):
        return 'CloudProfile(<private>)'


def paired_profile(value: dict, library_id: str) -> CloudProfile:
    """Validate a private signed-Hub response, never a UI-supplied credential."""
    try:
        if not isinstance(value, dict) or set(value) != {'profile'}:
            raise ValueError
        profile = value['profile']
        if (not isinstance(profile, dict) or type(profile.get('schema')) is not int
                or profile['schema'] != 1 or set(profile) != {'schema', 'server', 'user', 'token', 'token_scope', 'libraries'}):
            raise ValueError
        libraries = profile['libraries']
        if (not isinstance(libraries, list) or len(libraries) != 1 or not isinstance(libraries[0], dict)
                or set(libraries[0]) != {'id', 'name', 'permission'} or libraries[0]['id'] != library_id
                or libraries[0]['permission'] not in {'r', 'rw'}):
            raise ValueError
        return CloudProfile(profile['server'], profile['user'], profile['token'], library_id, profile['token_scope'])
    except (ValueError, KeyError, TypeError):
        raise ValueError('The server returned an unsupported file sync profile. No client settings were changed.') from None


@dataclass(frozen=True)
class _Binding:
    library_id: str = field(repr=False)
    folder: Path = field(repr=False)
    server: str = field(repr=False)


@dataclass(frozen=True)
class ClientStatus:
    installed: bool
    profile_present: bool
    inspection_complete: bool
    prepared: bool
    _bindings: tuple[_Binding, ...] = field(default=(), repr=False)

    def safe(self) -> dict:
        """The only status representation intended for the normal Orion UI."""
        return {'installed': self.installed, 'profile_present': self.profile_present,
                'inspection_complete': self.inspection_complete, 'prepared': self.prepared,
                'selected_libraries': len(self._bindings),
                # Local metadata proves a binding, not daemon health or completion.
                'state': ('not_installed' if not self.installed else
                          'inspection_pending' if not self.inspection_complete else
                          'existing_profile' if self.profile_present else
                          'prepared' if self.prepared else 'not_detected')}


@dataclass(frozen=True, repr=False)
class ClientLocation:
    executable: Path
    config: Path
    data: Path

    def __repr__(self):
        return 'ClientLocation(<local metadata>)'


def _task_location(action: dict) -> ClientLocation:
    """Recognize finite existing Orion task formats; never run its script."""
    if not isinstance(action, dict) or set(action) != {'Execute', 'Arguments'}:
        raise ValueError('Existing Cloud startup needs inspection.')
    executable = Path(action['Execute'])
    arguments = action['Arguments']
    if not isinstance(arguments, str) or len(arguments) > 8192:
        raise ValueError('Existing Cloud startup needs inspection.')
    tokens = [value[1:-1] if value.startswith('"') and value.endswith('"') else value
              for value in shlex.split(arguments, posix=False)]
    if executable.name.lower() in {'pythonw.exe', 'python.exe'}:
        if (len(tokens) != 5 or Path(tokens[0]).name != 'start-seafile-client.py'
                or tokens[1] != '--client-root' or tokens[3] != '--binary-root'):
            raise ValueError('Existing Cloud startup needs inspection.')
        root, binary = _plain_path(Path(tokens[2]), directory=True), _plain_path(Path(tokens[4]), directory=True)
        executable, config, data = binary / 'seafile-applet.exe', root / 'ccnet', root / 'data'
    elif executable.name.lower() == 'seafile-applet.exe':
        if len(tokens) != 4 or tokens[0] != '-c' or tokens[2] != '-d':
            raise ValueError('Existing Cloud startup needs inspection.')
        config, data = Path(tokens[1]), Path(tokens[3])
    else:
        raise ValueError('Existing Cloud startup needs inspection.')
    executable, config, data = _plain_path(executable), _plain_path(config, directory=True), _plain_path(data, directory=True)
    if not executable.is_file():
        raise ValueError('Existing Cloud startup needs inspection.')
    return ClientLocation(executable, config, data)


def _windows_task() -> tuple[ClientLocation | None, bool]:
    """Read only the known task's action metadata, never execute it or echo it."""
    powershell = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    script = """[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new()
try {$t=Get-ScheduledTask -TaskName 'Orion Seafile Client' -ErrorAction Stop
$a=@($t.Actions)
if($a.Count -ne 1){'{"known":false}'}else{
@{known=$true;action=@{Execute=$a[0].Execute;Arguments=$a[0].Arguments}}|ConvertTo-Json -Compress}}
catch{if($_.FullyQualifiedErrorId -like 'CmdletizationQuery_NotFound*'){'{"known":true}'}else{'{"known":false}'}}"""
    try:
        result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', script],
                                capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode or len(result.stdout) > 16384:
            return None, False
        data = json.loads(result.stdout.decode('utf-8-sig'))
        if not isinstance(data, dict) or data.get('known') is not True:
            return None, False
        return (_task_location(data['action']) if 'action' in data else None), True
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        return None, False


@dataclass(frozen=True)
class Preparation:
    state: str  # existing_binding or prepared; never "synced"
    mode: str
    credential_file: Path | None = field(default=None, repr=False)
    command: tuple[str, ...] = field(default=(), repr=False)
    folder: Path | None = field(default=None, repr=False)

    def safe(self) -> dict:
        return {'state': self.state, 'needs_library_link': self.state == 'prepared'}


def _plain_path(path: Path, *, directory=False) -> Path:
    path = Path(path)
    if (not path.is_absolute() or '..' in path.parts or path.anchor.startswith('\\\\')
            or any(ord(c) < 32 or c in '";[]#=' for c in str(path))):
        raise ValueError('Choose an absolute local Cloud folder without special configuration characters.')
    # Reject symlinks/junctions in every existing component, not just the leaf.
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if (not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
                or getattr(info, 'st_file_attributes', 0) & 0x400):
            raise ValueError('Cloud setup cannot use redirected folders.')
    if directory and not path.is_dir():
        raise ValueError('Choose an existing local Cloud folder.')
    return path


def _restrict_windows(path: Path):
    """Secure an EMPTY new object before writing; never use account display names."""
    options = {'capture_output': True, 'timeout': 10, 'creationflags': subprocess.CREATE_NO_WINDOW}
    system = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32'
    identity = subprocess.run([str(system / 'whoami.exe'), '/user', '/fo', 'csv', '/nh'], **options)
    matches = re.findall(rb'"(S-1-[0-9-]+)"', identity.stdout)
    if identity.returncode or len(matches) != 1:
        raise OSError('Private permissions could not be secured.')
    grant = '*' + matches[0].decode('ascii') + (':(OI)(CI)(F)' if path.is_dir() else ':(F)')
    result = subprocess.run([str(system / 'icacls.exe'), str(path), '/inheritance:r', '/grant:r', grant], **options)
    if result.returncode:
        raise OSError('Private permissions could not be secured.')


def _private_write(path: Path, content: str):
    _plain_path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            if os.name == 'nt':
                _restrict_windows(path)
            else:
                os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _read_bindings(config: Path, data_dir: Path | None = None) -> tuple[_Binding, ...]:
    """Read only binding properties; never read account/token/key tables.

    immutable avoids SQLite creating or modifying profile sidecars. A live WAL
    means this bounded metadata probe cannot establish current bindings, so fail
    closed instead of ignoring uncheckpointed changes.
    """
    _plain_path(config, directory=True)
    pointer = _plain_path(config / 'seafile.ini')
    with pointer.open('r', encoding='utf-8-sig') as stream:
        value = stream.readline(4097).strip()
    if not value or len(value) > 4096:
        raise ValueError('Cloud profile needs inspection.')
    database = _plain_path(_plain_path(data_dir or Path(value), directory=True) / 'repo.db')
    wal = database.with_name(database.name + '-wal')
    if wal.exists() and wal.stat().st_size:
        raise ValueError('Cloud profile is active; preserve it for client inspection.')
    before = database.stat()
    if before.st_size > 32 * 1024 * 1024:
        raise ValueError('Cloud profile needs inspection.')
    with sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True, timeout=0.1) as connection:
        connection.set_progress_handler(lambda: 1, 100_000)
        rows = connection.execute("""SELECT r.repo_id,
            (SELECT value FROM RepoProperty p WHERE p.repo_id=r.repo_id AND p.key='worktree'),
            (SELECT value FROM RepoProperty p WHERE p.repo_id=r.repo_id AND p.key='server-url')
            FROM Repo r LIMIT 513""").fetchall()
    after = database.stat()
    if len(rows) > 512 or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or (wal.exists() and wal.stat().st_size):
        raise ValueError('Cloud profile needs inspection.')
    bindings = []
    for library, folder, server in rows:
        if str(UUID(library)) != library or not folder or not server:
            raise ValueError('Cloud profile needs inspection.')
        bindings.append(_Binding(library, _plain_path(Path(folder)), server_origin(server)))
    return tuple(bindings)


class SeafileClient:
    def __init__(self, *, home: Path | None = None, private_root: Path,
                 platform: str | None = None, executable: Path | None = None,
                 profile_dirs: tuple[Path, ...] = ()):
        self.home = Path(home or Path.home())
        self.private_root = Path(private_root)
        self.platform = platform or sys.platform
        self.location = None
        self.discovery_complete = True
        discovered = []
        # Explicit test/fixture homes never inspect the current user's task.
        if home is None:
            inherited = os.environ.get('CCNET_CONF_DIR')
            if inherited:
                discovered.append(Path(inherited))
            if self.platform == 'win32':
                self.location, self.discovery_complete = _windows_task()
                if self.location:
                    discovered.append(self.location.config)
        self.executable = (Path(executable) if executable else self.location.executable
                           if self.location else self._find_executable())
        default = self.home / ('ccnet' if self.platform == 'win32' else '.ccnet')
        self.profile_dirs = tuple(dict.fromkeys((default, *map(Path, profile_dirs), *discovered,
                                                self.private_root / 'ccnet')))

    def _find_executable(self):
        for name in (('seafile-applet.exe',) if self.platform == 'win32' else ('seaf-cli', 'seafile-applet')):
            found = shutil.which(name)
            if found:
                return Path(found)
        if self.platform == 'win32':
            roots = (Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Seafile/bin',
                     self.private_root.parent / 'tools/seafile/9.0.21/portable/bin',
                     self.private_root.parent / 'tools/seafile/9.0.21/portable/PFiles/Seafile/bin',
                     self.home / 'AppData/Local/OrionMini/tools/seafile/9.0.21/portable/bin',
                     self.home / 'AppData/Local/OrionMini/tools/seafile/9.0.21/portable/PFiles/Seafile/bin')
            for root in roots:
                if (root / 'seafile-applet.exe').is_file():
                    return root / 'seafile-applet.exe'
        return None

    def install(self, *, consent=False) -> dict:
        """Deliberate first-use installation; no daemon, account or sync launch."""
        if consent is not True:
            raise ValueError('Approve the file sync component installation first.')
        if self.executable and self.executable.is_file():
            return {'installed': True, 'existing_preserved': True}
        if self.platform.startswith('linux'):
            helper, pkexec = linux_install_helper(), shutil.which('pkexec')
            if not helper.is_file() or not pkexec:
                raise ValueError('Operating-system installation approval is unavailable. Use the Seafile instructions in Advanced.')
            try:
                result = subprocess.run([pkexec, '/bin/sh', str(helper)], stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600, env=_linux_environment())
                executable = installed_linux_cli()
                if result.returncode or not executable:
                    raise ValueError
                self.executable = executable
                return {'installed': True, 'existing_preserved': False}
            except (OSError, ValueError, subprocess.SubprocessError):
                raise ValueError('File sync installation did not finish. Approve the operating-system prompt on a supported Ubuntu/Debian desktop; existing profiles were preserved.') from None
        if self.platform != 'win32':
            raise ValueError('File sync component installation is supported on Windows and Ubuntu/Debian.')
        version = _plain_path(self.private_root.parent / 'tools/seafile/9.0.21')
        if os.path.lexists(version):
            raise ValueError('The existing file sync component needs inspection; it was preserved.')
        created = False
        try:
            version.parent.mkdir(parents=True, exist_ok=True)
            _plain_path(version.parent, directory=True)
            version.mkdir(mode=0o700)
            created = True
            _restrict_windows(version)
            installer = version / 'seafile.msi'
            _download_installer(installer)
            _verify_installer_signature(installer)
            portable = version / 'portable'
            portable.mkdir(mode=0o700)
            system = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32'
            # Administrative extraction installs no global package/startup task.
            result = subprocess.run([str(system / 'msiexec.exe'), '/a', str(installer), '/qn',
                                     'TARGETDIR=' + str(portable)], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise ValueError
            # Administrative extraction retains the official MSI's PFiles tree.
            binary = _verified_binary(portable / 'PFiles/Seafile/bin')
            applet = _plain_path(binary / 'seafile-applet.exe')
            if not applet.is_file():
                raise ValueError
            self.executable = applet
            _private_write(version / 'orion-upstream.json', json.dumps({
                'version': '9.0.21', 'source': _INSTALLER_URL, 'sha256': _INSTALLER_SHA256,
                'signature': 'Seafile Ltd.; verified valid'}))
            installer.unlink()
            return {'installed': True, 'existing_preserved': False}
        except (OSError, ValueError, subprocess.SubprocessError):
            # Only this exclusively reserved component directory is removed;
            # never remove an existing package, profile, task or selected folder.
            if created:
                try:
                    _plain_path(version, directory=True)
                    shutil.rmtree(version)
                except (OSError, ValueError):
                    pass
            raise ValueError('The official file sync component could not be installed. Existing profiles were preserved.') from None

    @property
    def preconfiguration(self):
        return self.home / ('seafile.ini' if self.platform == 'win32' else '.seafilerc')

    def detect(self) -> ClientStatus:
        bindings, complete, present = [], self.discovery_complete, False
        for config in self.profile_dirs:
            if not os.path.lexists(config):
                continue
            present = True
            try:
                override = self.location.data if self.location and self.location.config == config else None
                bindings.extend(_read_bindings(config, override))
            except (OSError, ValueError, sqlite3.Error, TypeError, AttributeError, UnicodeError):
                complete = False
        return ClientStatus(bool(self.executable and self.executable.is_file()), present, complete,
                            self.preconfiguration.exists() or (self.private_root / 'account.ini').exists(),
                            tuple(bindings))

    def open(self) -> dict:
        """Deliberate management action. Preserve its exact initialized profile."""
        executable = self.executable
        if not executable or not executable.is_file():
            raise ValueError('Install the official Seafile client before managing file sync.')
        if executable.name not in {'seafile-applet.exe', 'seafile-applet'}:
            found = shutil.which('seafile-applet') if self.platform != 'win32' else None
            if not found:
                raise ValueError('The graphical Seafile client is unavailable. Your profile is unchanged.')
            executable = Path(found)
        _plain_path(executable)
        profiles = [path for path in self.profile_dirs if os.path.lexists(path)]
        if self.location:
            config, data = self.location.config, self.location.data
        elif len(profiles) == 1:
            config = _plain_path(profiles[0], directory=True)
            pointer = _plain_path(config / 'seafile.ini')
            with pointer.open(encoding='utf-8-sig') as stream:
                data = _plain_path(Path(stream.readline(4097).strip()), directory=True)
        elif profiles:
            raise ValueError('More than one file sync profile was found. Review the selected profile in Advanced.')
        elif not self.discovery_complete:
            raise ValueError('The existing file sync configuration needs inspection before opening another profile.')
        else:
            config = data = None
        environment = dict(os.environ)
        command = [str(executable)]
        if config is not None:
            _plain_path(config, directory=True)
            _plain_path(data, directory=True)
            environment['CCNET_CONF_DIR'] = config.as_posix()
            environment['SEAFILE_DATA_DIR'] = data.as_posix()
            command += ['-c', str(config), '-d', str(data)]
        options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
        try:
            subprocess.Popen(command, env=environment, cwd=executable.parent,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, **options)
        except OSError:
            raise ValueError('The official file sync app could not open. Your profile is unchanged.') from None
        return {'opened': True}

    def management_available(self) -> bool:
        """Discover a GUI without launching it or creating any profile state."""
        executable = self.executable
        if executable and executable.is_file() and executable.name in {'seafile-applet', 'seafile-applet.exe'}:
            return True
        return self.platform.startswith('linux') and bool(shutil.which('seafile-applet'))

    def setup(self, profile: CloudProfile, folder: Path) -> dict:
        """One approved library/folder; existing bindings are never replaced."""
        if self.platform == 'win32':
            return _setup_windows(self, profile, folder)
        if self.platform != 'win32' and self.executable and self.executable.name == 'seaf-cli':
            state = self.detect()
            if state.profile_present or not state.inspection_complete:
                raise ValueError('Keep the existing file sync profile. Manage it before adding another account.')
            folder = _plain_path(folder, directory=True)
            private = _plain_path(self.private_root)
            if folder == private or folder.is_relative_to(private) or private.is_relative_to(folder):
                raise ValueError('Cloud credentials must stay outside the selected sync folder.')
            if _linux_rpc_request({'action': 'probe'}) != 'available':
                raise ValueError('The distribution file sync interface is unavailable. No profile was replaced.')
            # Reuse the same bounded, validated upstream metadata as Windows.
            info = _download_info(profile)
            started = False
            try:
                private.mkdir(mode=0o700)
                config = private / 'ccnet'
                environment = _linux_environment()
                command_options = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL,
                                   'stderr': subprocess.DEVNULL, 'timeout': 30, 'env': environment}
                # Upstream initializes only this new Orion-owned directory.
                for arguments in (['init', '-c', str(config), '-d', str(private)], ['start', '-c', str(config)]):
                    result = subprocess.run([str(self.executable), *arguments], **command_options)
                    if result.returncode:
                        raise ValueError
                    if arguments[0] == 'start':
                        started = True
                deadline = time.monotonic() + 8
                while not _linux_daemon_alive(private / 'seafile-data'):
                    if time.monotonic() >= deadline:
                        raise ValueError
                    time.sleep(.1)
                # Pending reservations do not authorize startup supervision.
                marker = {'schema': 1, 'executable': str(self.executable.resolve(strict=True)),
                          'folder': str(folder), 'library': profile.library_id,
                          'state': 'pending'}
                _private_write(private / 'orion-linux-client.json', json.dumps(marker))
                result = _linux_rpc_request({'action': 'clone', 'private': str(private), 'folder': str(folder),
                    'library': profile.library_id, 'server': profile.server,
                    'info': {key: info[key] for key in ('repo_version', 'repo_name', 'token', 'email', 'permission')}})
                if result != 'link_requested':
                    raise ValueError
                marker['state'] = 'link_requested'
                _private_write(private / 'orion-linux-client.pending', json.dumps(marker))
                os.replace(private / 'orion-linux-client.pending', private / 'orion-linux-client.json')
                _read_linux_owned(private)
                # The daemon receives the library clone token. The account token
                # is a temporary enrollment credential, not a client argv value.
                return {'state': 'link_requested', 'needs_library_link': False}
            except (OSError, ValueError, subprocess.SubprocessError):
                if started:
                    # Only this call's newly reserved, initialized profile.
                    try:
                        subprocess.run([str(self.executable), 'stop', '-c', str(private / 'ccnet')],
                                       **command_options)
                    except (OSError, subprocess.SubprocessError):
                        pass
                raise ValueError('File sync setup did not finish. Existing profiles were preserved; inspect the new private setup in Advanced.') from None
        result = self.provision(profile, folder, consent=True)
        self.open()
        return result.safe()

    def provision(self, profile: CloudProfile, folder: Path, *, consent=False,
                  mode='gui', config_dir: Path | None = None,
                  supports_private_config=False) -> Preparation:
        """Prepare only. Caller must authenticate profile and obtain folder consent.

        Legacy CLI preparation is refused: distro -C support does not establish
        token authentication. New Linux profiles use setup() and upstream RPC.
        GUI mode prepares first-use account login only, not library cloning.
        """
        if not isinstance(profile, CloudProfile) or consent is not True:
            raise ValueError('Approve this server account and local folder before Cloud setup.')
        if mode not in {'gui', 'cli'}:
            raise ValueError('Unsupported Cloud preparation mode.')
        folder = _plain_path(folder, directory=True)
        status = self.detect()
        if not status.installed:
            raise ValueError('Install the official Seafile client before Cloud setup.')
        if not status.inspection_complete:
            raise ValueError('Keep the existing Cloud profile; its library bindings need inspection.')
        for binding in status._bindings:
            if binding.library_id == profile.library_id:
                if binding.server == profile.server and binding.folder == folder:
                    return Preparation('existing_binding', mode, folder=folder)
                raise ValueError('This library already has a selected Cloud folder. Preserve that selection.')
            if folder == binding.folder or folder.is_relative_to(binding.folder) or binding.folder.is_relative_to(folder):
                raise ValueError('Choose a Cloud folder outside existing library folders.')
        if mode == 'gui':
            if status.profile_present or os.path.lexists(self.preconfiguration):
                raise ValueError('Preserve the existing Seafile account configuration; automatic enrollment is pending.')
        elif mode == 'cli':
            raise ValueError('CLI account-file preparation is unsupported. Use approved first-use Cloud setup; existing profiles are preserved.')
        private = _plain_path(self.private_root)
        if folder == private or folder.is_relative_to(private) or private.is_relative_to(folder):
            raise ValueError('Cloud credentials must stay outside the selected sync folder.')
        for binding in status._bindings:
            for target in (private, self.preconfiguration):
                if target == binding.folder or target.is_relative_to(binding.folder):
                    raise ValueError('Cloud credentials must stay outside existing library folders.')
        created = False
        try:
            private.mkdir(mode=0o700)  # Never take over an existing private profile.
            created = True
            if os.name == 'nt':
                _restrict_windows(private)
            target = self.preconfiguration
            content = ('[preconfigure]\n'
                       f'PreconfigureDirectory = {private.as_posix()}\n'
                       f'PreconfigureUsername = {profile.user}\n'
                       f'PreconfigureUserToken = {profile.token}\n'
                       f'PreconfigureServerAddr = {profile.server}\n')
            command = ()
            _private_write(target, content)
            return Preparation('prepared', mode, target, command, folder)
        except (OSError, ValueError, subprocess.SubprocessError):
            if created:
                try:
                    private.rmdir()
                except OSError:
                    pass
            raise ValueError('Cloud preparation could not finish. Existing profiles are unchanged.') from None


# Exact dependencies extracted from the signature-verified official 9.0.21 MSI
# (SHA256 1f06dbd3294a7806e3eb232b38a7e2af11a205ebb2aaa2cf5ecdc9ba1563a082).
# Unknown versions remain detectable/manageable; they are never loaded as RPC code.
_WINDOWS_BINARIES = {
    'seafile-applet.exe': '07d87d6472b0fb5de9dda0cda6ac75aa3bb56eac7d38c19e61c972636040232e',
    'seaf-daemon.exe': '3e92a1ad0f62307476d309644cc6a80ba79bb9950964799012c2687d4c8a6d7c',
    'libsearpc.dll': '03a956bf370b483e52583a18002524d67ee6435adb914e894fb59e59653eaed8',
    'glib-2.0-0.dll': '198da886d978797e7b65c1fee0be7a19609faff16a6c29e6b32daac38ac328db',
    'gobject-2.0-0.dll': 'c04a6ef225d28a6c32d3e9c0c9cf1d1bb508837b2db7d902c79e1a5beffdf9b0',
    'jansson.dll': 'cc3ffdaf6459d389144c72f3d7f0d5e6b7fb723febfa6be8cddb509d1db9a8db',
    'pthreadVC3.dll': '4ad9f36bd30a36f1e3913a91b104694fde3656504356c33d193b5adca5c268ed',
    'iconv-2.dll': '4a5c56e02ac317d5311ae29b6baffbf4e315cb227f98e1d8e12ba6e7d3a0f8fb',
    'intl-8.dll': '16b95e6dc15dd72f5abf9dc19938681edb843e2350a7f68c09af1440c9de30de',
    'pcre2-8.dll': '0896cde38518e62c658205e1980e01ab74d801e59bb187017cdcdebb8e6075cb',
    'ffi-8.dll': '1b60127631e707d774a4f7b415facc1c4c243609b478be486bcfbee0c02149e7',
    'argon2.dll': 'ce7ac83ef685b74564f39cef86890d0996b7a6529afffe7cad7ed65a104f977a',
    'event.dll': 'e2cd658e9ea9fe2a48455bc203fea04b8b186d9720ea87b58be85a2c93bddd0a',
    'getopt.dll': '84cd9d00f34a57e0d17762ebd87bedad69ae4f96fb0fbcb5c2daf2a84685cb18',
    'libcrypto-3-x64.dll': 'b77fdf673f7819c0e3e034e1fd38c44b9791a26f30e418ec9c7dae4934011db7',
    'libssl-3-x64.dll': '2780faf3d46ed1bc0ae6282b60166eddb8bb63953b8480685f1e1a931d8f7962',
    'libcurl.dll': '97955989852bbb91e89905670423e029de806a8610253041b92eb33fd6e69caa',
    'sqlite3.dll': 'e49e10c68b62eefa400456595c509a5aaea6c79c2d7ade75112468ed24fa2747',
    'websockets.dll': '7ccc691e74c4d57f7f4fb4a93dd1ca5624d8e18c77e7e9d8c8fc6e772ed74ebd',
    'uv.dll': '02d588f1cf9dc78677645e1d3798894e9a0769d090d9fcb04fff46ce87a35b89',
    'z.dll': '6b78937300e443af1fe01b92cf3535af17107feb3d7cee7cacb266d573636adb',
}

_INSTALLER_URL = 'https://sos-ch-dk-2.exo.io/seafile-downloads/seafile-9.0.21-en.msi'
_INSTALLER_SHA256 = '1f06dbd3294a7806e3eb232b38a7e2af11a205ebb2aaa2cf5ecdc9ba1563a082'


def _download_installer(path: Path):
    # Exact public upstream artifact, no credentials, redirects or proxy headers.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            _restrict_windows(path)
            digest, total = hashlib.sha256(), 0
            deadline = time.monotonic() + 120
            with build_opener(ProxyHandler({}), _NoRedirect()).open(_INSTALLER_URL, timeout=20) as response:
                if response.geturl() != _INSTALLER_URL:
                    raise ValueError
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > 160 * 1024 * 1024 or time.monotonic() > deadline:
                        raise ValueError
                    digest.update(block)
                    stream.write(block)
            if digest.hexdigest() != _INSTALLER_SHA256:
                raise ValueError
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _verify_installer_signature(path: Path):
    system = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32'
    script = "Import-Module ([IO.Path]::Combine($PSHOME,'Modules','Microsoft.PowerShell.Security','Microsoft.PowerShell.Security.psd1')) -ErrorAction Stop; " \
             "$s=Get-AuthenticodeSignature -LiteralPath $env:ORION_CLOUD_INSTALLER; " \
             "if($s.Status -eq 'Valid' -and $s.SignerCertificate.Subject -match '(^|, )O=Seafile Ltd\\.(,|$)'){exit 0}; exit 1"
    result = subprocess.run([str(system / 'WindowsPowerShell/v1.0/powershell.exe'), '-NoProfile',
                             '-NonInteractive', '-Command', script],
                            env={**os.environ, 'ORION_CLOUD_INSTALLER': str(path)},
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise ValueError('The official file sync installer signature could not be verified.')


def _verified_binary(binary: Path) -> Path:
    binary = _plain_path(binary, directory=True)
    for name, expected in _WINDOWS_BINARIES.items():
        path = _plain_path(binary / name)
        if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError('Automatic file sync requires the verified official Windows client.')
        with path.open('rb') as stream:
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
            if digest.hexdigest() != expected:
                raise ValueError('Automatic file sync requires the verified official Windows client.')
    # Windows imports must resolve to the OS, never a dropped local shadow DLL.
    system_names = {'kernel32', 'advapi32', 'ws2_32', 'crypt32', 'user32', 'shell32', 'ole32',
                    'psapi', 'rpcrt4', 'bcrypt', 'secur32', 'iphlpapi', 'userenv', 'dbghelp',
                    'vcruntime140', 'msvcp140'}
    for path in binary.glob('*.dll'):
        if path.stem.lower() in system_names or path.name.lower().startswith('api-ms-win-'):
            raise ValueError('The official client directory needs inspection before automatic setup.')
    return binary


def _worker_command() -> list[str]:
    return ([sys.executable, '--cloud-rpc-worker'] if getattr(sys, 'frozen', False) else
            [sys.executable, '-m', 'orion_mini.cloud_client', '--cloud-rpc-worker'])


def _worker_request(value: dict, *, timeout=15) -> str:
    """Only bounded, private stdin reaches the native worker; output is finite."""
    payload = json.dumps(value, separators=(',', ':')).encode('utf-8')
    if len(payload) > 16384:
        raise ValueError('The file sync request could not be prepared.')
    environment = {key: value for key, value in os.environ.items()
                   if key.lower() not in {'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'}}
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    try:
        # subprocess.run kills and waits for this child on timeout. No owner
        # daemon is stopped, and native errors/output never enter logs or UI.
        result = subprocess.run(_worker_command(), input=payload, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=timeout, env=environment, **options)
        if result.returncode or len(result.stdout) > 128:
            raise ValueError
        answer = json.loads(result.stdout)
        if (not isinstance(answer, dict) or set(answer) != {'state'} or answer['state'] not in
                {'absent', 'matching', 'conflict', 'link_requested', 'failed'}):
            raise ValueError
        return answer['state']
    except (OSError, ValueError, subprocess.SubprocessError):
        raise ValueError('File sync could not complete this request. Existing profiles were preserved.') from None


def _read_owned(private: Path, *, pending=False) -> dict:
    private = _plain_path(private, directory=True)
    marker = _plain_path(private / 'orion-client.json')
    if marker.stat().st_size > 8192:
        raise ValueError('The private file sync profile needs inspection.')
    value = json.loads(marker.read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or set(value) != {'schema', 'binary', 'folder', 'library', 'state'}
            or type(value['schema']) is not int or value['schema'] != 1
            or value['state'] not in ({'pending', 'link_requested'} if pending else {'link_requested'})
            or str(UUID(value['library'])) != value['library']):
        raise ValueError('The private file sync profile needs inspection.')
    _verified_binary(Path(value['binary']))
    _plain_path(Path(value['folder']), directory=True)
    config = _plain_path(private / 'ccnet', directory=True)
    data = _plain_path(private / 'data', directory=True)
    pointer = _plain_path(config / 'seafile.ini')
    if pointer.read_text(encoding='utf-8').strip() != data.as_posix():
        raise ValueError('The private file sync profile needs inspection.')
    return value


def _pipe_server_pid(transport: int) -> int:
    """Read the pinned upstream transport's HANDLE; use the official Windows API."""
    import ctypes
    class Transport(ctypes.Structure):
        _fields_ = [('path', ctypes.c_char * 4096), ('pipe', ctypes.c_void_p)]
    kernel = ctypes.WinDLL('kernel32.dll', winmode=0x800)
    kernel.GetNamedPipeServerProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
    kernel.GetNamedPipeServerProcessId.restype = ctypes.c_int
    process = ctypes.c_uint()
    if not kernel.GetNamedPipeServerProcessId(Transport.from_address(transport).pipe, ctypes.byref(process)):
        raise ValueError
    return process.value


def _native_rpc(value: dict) -> str:
    """Finite adapter over upstream's C named-pipe transport, in a child only."""
    import base64
    import ctypes
    binary = _verified_binary(Path(value['binary']))
    folder = _plain_path(Path(value['folder']), directory=True)
    # The same username/ANSI conversion as upstream's Windows daemon.
    username = ctypes.create_string_buffer(257)
    size = ctypes.c_uint(len(username))
    advapi = ctypes.WinDLL('advapi32.dll', winmode=0x800)
    if not advapi.GetUserNameA(username, ctypes.byref(size)):
        raise ValueError
    pipe = b'\\\\.\\pipe\\seafile_' + base64.b64encode(username.value)
    # DLL_LOAD_DIR | SYSTEM32 avoids PATH/CWD dependency loading.
    library = ctypes.CDLL(str(binary / 'libsearpc.dll'), winmode=0x900)
    glib = ctypes.CDLL(str(binary / 'glib-2.0-0.dll'), winmode=0x900)
    ptr, char, integer = ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int
    create = library.searpc_create_named_pipe_client
    create.argtypes, create.restype = [char], ptr
    client = library.searpc_client_with_named_pipe_transport
    client.argtypes, client.restype = [ptr, char], ptr
    connect = library.searpc_named_pipe_client_connect
    connect.argtypes, connect.restype = [ptr], integer
    free = library.searpc_free_client_with_pipe_transport
    free.argtypes, free.restype = [ptr], None
    call = library.searpc_client_call__string
    call.argtypes, call.restype = [ptr, char, ctypes.POINTER(ptr), integer], ptr
    glib.g_free.argtypes, glib.g_free.restype = [ptr], None
    glib.g_error_free.argtypes, glib.g_error_free.restype = [ptr], None
    transport = create(pipe)
    if not transport:
        raise ValueError
    rpc = client(transport, b'seafile-rpcserver')
    if not rpc:
        raise ValueError

    def invoke(name, *arguments):
        error = ptr()
        # Upstream's variadic ABI takes (type-name, pointer-sized value) pairs,
        # including integer values cast through void*. Count is logical params.
        pairs = []
        for argument in arguments:
            pairs.extend((char(b'int'), ptr(argument.value)) if isinstance(argument, integer)
                         else (char(b'string'), argument))
        returned = call(rpc, name, ctypes.byref(error), integer(len(arguments)), *pairs)
        try:
            if error or not returned:
                raise ValueError
            # Both methods return tiny strings (path or UUID), never accounts.
            result = ctypes.string_at(returned, 1)
            if not result:
                raise ValueError
            return ctypes.string_at(returned).decode('utf-8')
        finally:
            if returned:
                glib.g_free(returned)
            if error:
                glib.g_error_free(error)
    try:
        if connect(transport) < 0:
            return 'absent'
        if 'pid' in value and _pipe_server_pid(transport) != value['pid']:
            return 'conflict'
        current = invoke(b'seafile_get_config', char(b'wktree'))
        if os.path.normcase(os.path.normpath(current)) != os.path.normcase(os.path.normpath(str(folder))):
            return 'conflict'
        if value['action'] == 'probe':
            return 'matching'
        marker = _read_owned(Path(value['private']), pending=True)
        if marker['binary'] != str(binary) or marker['folder'] != str(folder):
            raise ValueError
        profile = CloudProfile(**value['profile'])
        if marker['library'] != profile.library_id:
            raise ValueError
        info = _download_info(profile)
        extra = json.dumps({'server_url': profile.server, 'is_readonly': int(info['permission'] == 'r')})
        result = invoke(b'seafile_clone', char(profile.library_id.encode()), integer(info['repo_version']),
                        char(info['repo_name'].encode('utf-8')), char(str(folder).encode('utf-8')),
                        char(info['token'].encode()), char(None), char(None), char(info['email'].encode()),
                        char(None), integer(0), char(extra.encode()))
        if result != profile.library_id:
            raise ValueError
        return 'link_requested'
    finally:
        free(rpc)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('File sync redirects are unsupported.')


def _download_info(profile: CloudProfile) -> dict:
    request = Request(f'{profile.server}/api2/repos/{profile.library_id}/download-info/',
                      headers={'Authorization': 'Token ' + profile.token})
    with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=10) as response:
        content = response.read(16385)
    if len(content) > 16384:
        raise ValueError
    info = json.loads(content)
    if (not isinstance(info, dict) or info.get('repo_id') != profile.library_id
            or not (info.get('encrypted') == '' or
            type(info.get('encrypted')) is int and info['encrypted'] == 0)
            or type(info.get('repo_version')) is not int or not 0 <= info['repo_version'] <= 10
            or info.get('permission') not in {'r', 'rw'} or not isinstance(info.get('email'), str)
            or not re.fullmatch(r'[A-Za-z0-9._+@-]{1,254}', info['email'])
            or not isinstance(info.get('token'), str) or not re.fullmatch(r'[a-fA-F0-9]{32,128}', info['token'])
            or not isinstance(info.get('repo_name'), str) or not 1 <= len(info['repo_name']) <= 255
            or any(ord(c) < 32 for c in info['repo_name'])):
        raise ValueError('The selected library requires an unsupported setup step.')
    return info


def _worker_stream(number: int):
    """PyInstaller windowed executables have sys.stdin/stdout=None.

    Duplicate only the already inherited pipe handle; never attach a console or
    create a temporary credential file to work around windowed bootloaders.
    """
    stream = sys.stdin if number == 0 else sys.stdout
    if stream is not None:
        return stream.buffer, False
    import ctypes
    import msvcrt
    kernel = ctypes.WinDLL('kernel32.dll', winmode=0x800)
    kernel.GetStdHandle.argtypes, kernel.GetStdHandle.restype = [ctypes.c_uint], ctypes.c_void_p
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.DuplicateHandle.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint, ctypes.c_int, ctypes.c_uint]
    kernel.DuplicateHandle.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.GetStdHandle(-10 if number == 0 else -11)
    current, duplicate = kernel.GetCurrentProcess(), ctypes.c_void_p()
    if not handle or handle == ctypes.c_void_p(-1).value or not kernel.DuplicateHandle(
            current, handle, current, ctypes.byref(duplicate), 0, False, 2):
        raise ValueError
    try:
        fd = msvcrt.open_osfhandle(duplicate.value, os.O_BINARY | (os.O_RDONLY if number == 0 else os.O_WRONLY))
    except Exception:
        kernel.CloseHandle(duplicate)
        raise
    return os.fdopen(fd, 'rb' if number == 0 else 'wb'), True


def rpc_worker_main() -> int:
    """No Qt application, logs, UI or arbitrary command/method dispatch."""
    owned = []
    try:
        incoming, close_incoming = _worker_stream(0)
        if close_incoming:
            owned.append(incoming)
        outgoing, close_outgoing = _worker_stream(1)
        if close_outgoing:
            owned.append(outgoing)
    except Exception:
        for stream in owned:
            stream.close()
        return 2
    try:
        content = incoming.read(16385)
        if os.name != 'nt' or len(content) > 16384:
            raise ValueError
        value = json.loads(content)
        if not isinstance(value, dict) or value.get('action') not in {'probe', 'clone'}:
            raise ValueError
        keys = {'action', 'binary', 'folder'} | ({'private', 'profile', 'pid'} if value['action'] == 'clone' else set())
        if value['action'] == 'probe' and 'pid' in value:
            keys.add('pid')
        if set(value) != keys:
            raise ValueError
        if 'pid' in value and (type(value['pid']) is not int or not 1 <= value['pid'] <= 0xFFFFFFFF):
            raise ValueError
        result = _native_rpc(value)
    except Exception:
        result = 'failed'
    try:
        outgoing.write(json.dumps({'state': result}).encode('ascii'))
        outgoing.flush()
    finally:
        for stream in owned:
            stream.close()
    return 0


def _start_owned(private: Path, marker: dict):
    binary, folder = _verified_binary(Path(marker['binary'])), _plain_path(Path(marker['folder']), directory=True)
    environment = {key: value for key, value in os.environ.items()
                   if key.lower() not in {'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'}}
    environment['PATH'] = str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32')
    return subprocess.Popen([str(binary / 'seaf-daemon.exe'), '-c', str(private / 'ccnet'),
                             '-d', str(private / 'data'), '-w', str(folder)],
                            cwd=private, env=environment, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)


def _linux_environment() -> dict:
    """Keep the frozen app's Python/Qt libraries out of the official CLI."""
    environment = {key: value for key, value in os.environ.items()
                   if key.lower() not in {'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'}
                   and key not in {'PYTHONHOME', 'PYTHONPATH', 'CCNET_CONF_DIR', 'SEAFILE_DATA_DIR'}}
    original = environment.pop('LD_LIBRARY_PATH_ORIG', None)
    environment.pop('LD_LIBRARY_PATH', None)
    if original:
        environment['LD_LIBRARY_PATH'] = original
    return environment


def _read_linux_owned(private: Path) -> tuple[dict, Path]:
    """Validate only our successfully initialized private Linux profile."""
    private = _plain_path(private, directory=True)
    marker_path = _plain_path(private / 'orion-linux-client.json')
    if marker_path.stat().st_size > 8192:
        raise ValueError('The private file sync profile needs inspection.')
    marker = json.loads(marker_path.read_text(encoding='utf-8'))
    if (not isinstance(marker, dict) or set(marker) != {'schema', 'executable', 'folder', 'library', 'state'}
            or type(marker['schema']) is not int or marker['schema'] != 1
            or marker['state'] != 'link_requested' or str(UUID(marker['library'])) != marker['library']):
        raise ValueError('The private file sync profile needs inspection.')
    executable = _plain_path(Path(marker['executable']))
    if not executable.is_file():
        raise ValueError('The official file sync component is unavailable.')
    _plain_path(Path(marker['folder']), directory=True)
    config = _plain_path(private / 'ccnet', directory=True)
    pointer = _plain_path(config / 'seafile.ini')
    if pointer.stat().st_size > 4096:
        raise ValueError('The private file sync profile needs inspection.')
    data = _plain_path(Path(pointer.read_text(encoding='utf-8').strip()), directory=True)
    if data != private / 'seafile-data':
        raise ValueError('The private file sync profile needs inspection.')
    if os.name != 'nt':
        for path in (private, config, data, marker_path, pointer):
            info = path.stat()
            if info.st_uid != os.getuid() or (path == private and stat.S_IMODE(info.st_mode) & 0o077):
                raise ValueError('The private file sync profile needs inspection.')
    return marker, data


def _linux_daemon_alive(data: Path) -> bool:
    """Probe only the selected profile's local upstream RPC socket."""
    path = data / 'seafile.sock'
    if not os.path.lexists(path):
        return False
    if not stat.S_ISSOCK(path.lstat().st_mode):
        raise ValueError('The private file sync profile needs inspection.')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.5)
        try:
            connection.connect(str(path))
            return True
        except (FileNotFoundError, ConnectionRefusedError):
            return False


def _resume_linux_owned(private: Path):
    """Probe upstream RPC and serialize our starts; older CLIs have no PID lock."""
    import fcntl
    marker, data = _read_linux_owned(private)
    lockfile = _plain_path(private / 'orion-start.lock')
    fd = os.open(lockfile, os.O_WRONLY | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if _linux_daemon_alive(data):
            return
        pidfile = _plain_path(data / 'seaf-daemon.pid')
        if pidfile.exists():
            # Current upstream uses this lock; do not truncate its PID file.
            pid_fd = os.open(pidfile, os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0))
            try:
                try:
                    fcntl.flock(pid_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return
            finally:
                os.close(pid_fd)
        result = subprocess.run([marker['executable'], 'start', '-c', str(private / 'ccnet')],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=30, env=_linux_environment())
        if result.returncode:
            raise ValueError('The private file sync daemon did not restart.')
        # Keep our start lock until the upstream daemon is reachable, avoiding
        # duplicate launches across two Orion processes during daemonization.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if _linux_daemon_alive(data):
                return
            time.sleep(0.1)
        raise ValueError('The private file sync daemon did not become ready.')
    finally:
        os.close(fd)


def _setup_windows(client: SeafileClient, profile: CloudProfile, folder: Path) -> dict:
    state = client.detect()
    if not isinstance(profile, CloudProfile) or not state.installed or not state.inspection_complete:
        raise ValueError('Keep existing file sync settings; the official client needs inspection.')
    if state.profile_present or state.prepared:
        raise ValueError('Keep the existing file sync profile. Manage it before adding another account.')
    folder, private = _plain_path(folder, directory=True), _plain_path(client.private_root)
    if folder == private or folder.is_relative_to(private) or private.is_relative_to(folder):
        raise ValueError('Cloud credentials must stay outside the selected sync folder.')
    binary = _verified_binary(client.executable.parent)
    request = {'action': 'probe', 'binary': str(binary), 'folder': str(folder)}
    if _worker_request(request) != 'absent':
        raise ValueError('An existing file sync client is running. Its profile has been preserved.')
    process = None
    try:
        private.mkdir(mode=0o700)
        _restrict_windows(private)
        for name in ('ccnet', 'data', 'ccnet/logs'):
            (private / name).mkdir(mode=0o700)
        _private_write(private / 'ccnet/seafile.ini', (private / 'data').as_posix() + '\n')
        marker = {'schema': 1, 'binary': str(binary), 'folder': str(folder),
                  'library': profile.library_id, 'state': 'pending'}
        _private_write(private / 'orion-client.json', json.dumps(marker))
        process = _start_owned(private, marker)
        request['pid'] = process.pid
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise ValueError
            result = _worker_request(request, timeout=3)
            if result == 'matching':
                break
            if result != 'absent':
                raise ValueError
            time.sleep(0.2)
        else:
            raise ValueError
        request.update(action='clone', private=str(private), profile={
            'server': profile.server, 'user': profile.user, 'token': profile.token,
            'library_id': profile.library_id, 'token_scope': profile.token_scope})
        if _worker_request(request, timeout=20) != 'link_requested':
            raise ValueError
        marker['state'] = 'link_requested'
        _private_write(private / 'orion-client.pending', json.dumps(marker))
        os.replace(private / 'orion-client.pending', private / 'orion-client.json')
        return {'state': 'link_requested', 'needs_library_link': False}
    except (OSError, ValueError, subprocess.SubprocessError):
        # Only a daemon handle created in this call can be stopped on failure.
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        raise ValueError('File sync setup did not finish. Existing profiles were preserved; inspect the new private setup in Advanced.') from None


class CloudSupervisor:
    """Resume only new Orion-owned profiles; never adopt existing services."""
    def __init__(self, private_root: Path):
        self.private_root = Path(private_root)
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.next_probe = 0.0
        self.process = None

    def poll(self):
        marker = 'orion-client.json' if sys.platform == 'win32' else 'orion-linux-client.json'
        if (sys.platform not in {'win32', 'linux'} or self.stopped.is_set() or time.monotonic() < self.next_probe
                or not (self.private_root / marker).is_file() or not self.lock.acquire(False)):
            return
        self.next_probe = time.monotonic() + 30
        threading.Thread(target=self._probe, name='orion-cloud-supervisor', daemon=True).start()

    def _probe(self):
        try:
            if sys.platform == 'linux':
                if not self.stopped.is_set():
                    _resume_linux_owned(self.private_root)
                return
            marker = _read_owned(self.private_root)
            state = _worker_request({'action': 'probe', 'binary': marker['binary'], 'folder': marker['folder']})
            if (state == 'absent' and not self.stopped.is_set()
                    and (self.process is None or self.process.poll() is not None)):
                self.process = _start_owned(self.private_root, marker)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            pass
        finally:
            self.lock.release()

    def stop(self):
        # Sync remains a background supporting process. This only stops probes.
        self.stopped.set()


def status(private_root: Path, *, home: Path | None = None,
           profile_dirs: tuple[Path, ...] = ()) -> dict:
    """Read-only UI status. No account credentials, folder paths or library IDs."""
    try:
        client = SeafileClient(private_root=private_root, home=home, profile_dirs=profile_dirs)
        return {**client.detect().safe(), 'management_available': client.management_available(),
                'service_state': owned_service_status(private_root, platform=client.platform)}
    except (OSError, ValueError, sqlite3.Error):
        return ClientStatus(False, False, False, False).safe()


def owned_service_status(private_root: Path, *, platform=None) -> str:
    """Local reachability of our profile, never transfer/server health.

    Reuse the supervisor's existing identity-checked probes. No init, start,
    account command, profile adoption, or remote server request occurs here.
    """
    platform = platform or sys.platform
    private = Path(private_root)
    marker = ('orion-client.json' if platform == 'win32' else
              'orion-linux-client.json' if platform.startswith('linux') else None)
    if marker is None or not os.path.lexists(private / marker):
        return 'not_managed'
    try:
        if platform.startswith('linux'):
            _, data = _read_linux_owned(private)
            return 'reachable' if _linux_daemon_alive(data) else 'unavailable'
        owned = _read_owned(private)
        try:
            result = _worker_request({'action': 'probe', 'binary': owned['binary'], 'folder': owned['folder']})
        except ValueError:
            return 'unavailable'
        return {'matching': 'reachable', 'absent': 'unavailable', 'conflict': 'needs_attention'}.get(result, 'unavailable')
    except (ValueError, TypeError, KeyError, UnicodeError):
        return 'needs_attention'
    except (OSError, subprocess.SubprocessError):
        return 'unavailable'


if __name__ == '__main__':
    raise SystemExit(rpc_worker_main() if sys.argv[1:] == ['--cloud-rpc-worker'] else 2)
