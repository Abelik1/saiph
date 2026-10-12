# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guided Linux installer; deliberately separate from the owner's Pi deployment."""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import platform
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

SUPPORTED = {"ubuntu": {"22.04": "jammy", "24.04": "noble"}, "debian": {"12": "bookworm", "13": "trixie"}}
INSTALL = Path("/opt/orion-server")
DATA = Path("/var/lib/orion-server")
CONFIG = Path("/etc/orion-server")
UNIT = Path("/etc/systemd/system/orion-server.service")
WRAPPER = Path("/usr/local/sbin/orion-server")
MARKER = "orion-self-hosted-server-v1"
USER = "orion-server"
LOCK = Path("/run/lock/orion-server-install.lock")


class SetupError(ValueError):
    """Fixed, public diagnostic text; upstream replies never enter this type."""


@contextmanager
def installation_lock(path=LOCK):
    """Serialize preflight, activation and rollback across independent installers."""
    import fcntl
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise SetupError("Refusing an unsafe server installation lock")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SetupError("Another Saiph server installation is running; retry after it finishes") from None
        yield
    finally:
        # Keep the inode: unlinking lets a contender lock a different file.
        os.close(descriptor)


def run(argv, *, visible=False, timeout=None):
    result = subprocess.run(argv, check=False, stdout=None if visible else subprocess.PIPE,
                            stderr=None if visible else subprocess.PIPE, text=True, umask=0o022, timeout=timeout)
    if result.returncode:
        raise SetupError("A required installation step failed; existing data was preserved")
    return result.stdout or ""


def mesh_ip(output):
    candidates = output.split()
    if len(candidates) != 1:
        raise SetupError("Complete the official mesh sign-in before installing Saiph")
    address = ipaddress.ip_address(candidates[0])
    network = ipaddress.ip_network("100.64.0.0/10" if address.version == 4 else "fd7a:115c:a1e0::/48")
    if address not in network or "%" in str(address):
        raise SetupError("The official client did not return a supported mesh address")
    return str(address)


def control_origin(value):
    from urllib.parse import urlsplit
    if not value: return None
    url = urlsplit(value)
    if any(ord(ch) <= 32 for ch in value) or not (url.scheme == "https" and url.hostname and
        not url.username and not url.password and url.path in {"", "/"} and not url.query and not url.fragment):
        raise SetupError("Advanced mesh control server must be a trusted HTTPS origin")
    if url.port is not None and not 1 <= url.port <= 65535: raise SetupError("Invalid control port")
    return value.rstrip("/")


def supported_system(values, architecture):
    distro, version = values.get("ID"), values.get("VERSION_ID")
    if distro not in SUPPORTED or version not in SUPPORTED[distro] or architecture not in {"x86_64", "aarch64"}:
        raise SetupError("Supported servers: Ubuntu 22.04/24.04 or Debian 12/13, amd64/arm64")
    return distro, SUPPORTED[distro][version]


def verify_package(folder):
    manifest = json.loads((folder / "package.json").read_text())
    if manifest.get("format") != "orion-server-package" or manifest.get("version") != 1:
        raise SetupError("Unsupported Saiph server package")
    release = manifest.get("release", "")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}", release): raise SetupError("Invalid release")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files: raise SetupError("Incomplete server package")
    if len(files) > 100: raise SetupError("Unexpected server package size")
    for path in folder.rglob('*'):
        if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
            raise SetupError('Server package must not contain links')
    source = manifest.get('source')
    extras = {'package.json', 'SHA256SUMS'} if source is not None else {'package.json'}
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    if actual != set(files) | extras: raise SetupError("Package file list does not match its manifest")
    for name, digest in files.items():
        relative = Path(name)
        path = folder / relative
        allowed = name in {"install.py", "hub/requirements.txt", 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'SOURCE.json', 'docs/SERVER_RELEASE.md'} or re.fullmatch(r"hub/orion_hub/[a-z_]+\.py", name)
        if not allowed or relative.is_absolute() or ".." in relative.parts or path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024**2:
            raise SetupError("Unsafe server package path")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest: raise SetupError("Server package integrity check failed")
    if source is not None:
        if not {'LICENSE', 'THIRD_PARTY_NOTICES.md', 'SOURCE.json', 'docs/SERVER_RELEASE.md'} <= set(files):
            raise SetupError('Server source metadata or notices are missing')
        if json.loads((folder / 'SOURCE.json').read_text()) != source:
            raise SetupError('Server source metadata does not match its manifest')
        checksums = ''.join(hashlib.sha256((folder / name).read_bytes()).hexdigest() + '  ' + name + '\n'
                            for name in sorted(actual - {'SHA256SUMS'}))
        if (folder / 'SHA256SUMS').read_text(encoding='utf-8') != checksums:
            raise SetupError('Server package checksum verification failed')
    return manifest


def check_owned(path, *, uid=0):
    if path.is_symlink(): raise SetupError("Refusing a symbolic link at an installation path")
    if path.exists():
        info = path.stat()
        if info.st_uid != uid or info.st_mode & 0o022:
            raise SetupError("Refusing an unowned or writable installation path")


def private_write(path, value, *, mode=0o600):
    check_owned(path)
    from uuid import uuid4
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.new')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    os.fchmod(fd, mode)
    with os.fdopen(fd, "w") as output:
        output.write(value); output.flush(); os.fsync(output.fileno())
    os.replace(temporary, path)


def unit_text():
    return f'''# {MARKER}
[Unit]
Description=Saiph private Hub
After=network-online.target tailscaled.service
Wants=network-online.target tailscaled.service
[Service]
Type=simple
User={USER}
Group={USER}
WorkingDirectory={INSTALL}/current/hub
EnvironmentFile={CONFIG}/server.env
ExecStart={INSTALL}/current/venv/bin/python -m orion_hub.server
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths={DATA}
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
RestrictSUIDSGID=true
LockPersonality=true
[Install]
WantedBy=multi-user.target
'''


def wrapper_text():
    return f'''#!/bin/sh
# {MARKER}
set -eu
cd {INSTALL}/current/hub
exec runuser -u {USER} -- {INSTALL}/current/venv/bin/python -m orion_hub.managed_cli {CONFIG}/server.env "$@"
'''


def backup_unit_text():
    return f'''# {MARKER}
[Unit]
Description=Saiph private local recovery snapshot
After=orion-server.service
[Service]
Type=oneshot
User={USER}
Group={USER}
WorkingDirectory={INSTALL}/current/hub
EnvironmentFile={CONFIG}/server.env
ExecStart={INSTALL}/current/venv/bin/python -m orion_hub.cli backup --keep 14
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths={DATA}
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_UNIX
RestrictSUIDSGID=true
LockPersonality=true
'''


def backup_timer_text():
    return f'''# {MARKER}
[Unit]
Description=Daily Saiph local recovery snapshot
[Timer]
OnCalendar=*-*-* 04:00:00
RandomizedDelaySec=15m
Persistent=true
Unit=orion-server-backup.service
[Install]
WantedBy=timers.target
'''


def managed_paths():
    return {'unit': UNIT, 'wrapper': WRAPPER,
            'backup_unit': UNIT.with_name('orion-server-backup.service'),
            'backup_timer': UNIT.with_name('orion-server-backup.timer')}


def config_text(address, port, controller):
    if not 1024 <= port <= 65535: raise SetupError("Choose an Advanced port from 1024 to 65535")
    address = mesh_ip(address)
    controller = control_origin(controller)
    lines = [f"ORION_HUB_DATA={DATA}", f"ORION_HUB_AUTOMATIONS={CONFIG}/automations.json",
             f"ORION_HUB_MESH_IP={address}", f"ORION_HUB_PORT={port}",
             f"ORION_PHONE_BACKUP_DATA={DATA}/optional-phone-backup", f"ORION_WAKE_TARGETS={CONFIG}/wake-targets.json"]
    if controller:
        import shlex
        lines.append("ORION_MESH_LOGIN_SERVER=" + shlex.quote(controller))
    return "\n".join(lines) + "\n"


def merged_config(previous, address, port, controller):
    managed = config_text(address, port, controller)
    names = {line.partition('=')[0] for line in managed.splitlines()}
    names.add('ORION_MESH_LOGIN_SERVER')
    retained = [line for line in previous.splitlines() if line.partition('=')[0] not in names]
    return managed + ('\n'.join(retained) + '\n' if retained else '')


def activate_release(release, address, port, controller, record, first_install):
    """Activate only a complete release; failed health restores prior code/config."""
    current = INSTALL / 'current'
    if current.is_symlink():
        previous = current.resolve(strict=True)
        if previous.parent != INSTALL / 'releases' or previous.name != record.get('release'):
            raise SetupError('Refusing an unrecognized active release path')
    elif current.exists():
        raise SetupError('Refusing an unrecognized active release path')
    else:
        previous = None
    paths = [CONFIG / 'server.env', CONFIG / 'server.json', *managed_paths().values(), INSTALL / 'managed.json']
    retained = {path: (path.read_text(), stat.S_IMODE(path.stat().st_mode)) for path in paths if path.is_file()}
    old_port = json.loads(retained[CONFIG / 'server.json'][0]).get('port', 8765) if previous else None
    had_timer = managed_paths()['backup_timer'] in retained
    timer_enabled = backup_timer_is_enabled() if had_timer else True
    if previous:
        if managed_paths()['backup_timer'].exists():
            run(['systemctl', 'stop', 'orion-server-backup.timer', 'orion-server-backup.service'])
        run(['systemctl', 'stop', 'orion-server'])
    try:
        private_write(CONFIG / 'server.env', merged_config(retained.get(CONFIG / 'server.env', ('',))[0], address, port, controller))
        private_write(CONFIG / 'server.json', json.dumps({'port':port, 'mesh_login_server':controller, 'mesh_ip':address}))
        if not (CONFIG / 'automations.json').exists():
            private_write(CONFIG / 'automations.json', '{"automations":[]}\n', mode=0o644)
        run(['chown', 'root:' + USER, str(CONFIG)]); os.chmod(CONFIG, 0o750)
        for path in (CONFIG / 'server.env', CONFIG / 'automations.json'):
            run(['chown', 'root:' + USER, str(path)]); os.chmod(path, 0o640)
        private_write(UNIT, unit_text(), mode=0o644)
        private_write(WRAPPER, wrapper_text(), mode=0o755)
        private_write(managed_paths()['backup_unit'], backup_unit_text(), mode=0o644)
        private_write(managed_paths()['backup_timer'], backup_timer_text(), mode=0o644)
        private_write(INSTALL / 'managed.json', json.dumps({'format':MARKER, 'release':release.name,
                      'owned_files':{name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in managed_paths().items()}}))
        switch_release(current, release)
        run(['systemctl', 'daemon-reload']); run(['systemctl', 'enable', '--now', 'orion-server'])
        wait_health(port)
        if timer_enabled:
            run(['systemctl', 'enable', '--now', 'orion-server-backup.timer'])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        if previous:
            try:
                run(['systemctl', 'stop', 'orion-server'])
                if managed_paths()['backup_timer'].exists():
                    run(['systemctl', 'stop', 'orion-server-backup.service'])
                    run(['systemctl', 'disable', '--now', 'orion-server-backup.timer'])
                for path, (contents, mode) in retained.items():
                    private_write(path, contents, mode=mode)
                for path in managed_paths().values():
                    if path not in retained:
                        check_owned(path)
                        path.unlink(missing_ok=True)
                run(['chown', 'root:' + USER, str(CONFIG / 'server.env')])
                switch_release(current, previous)
                run(['systemctl', 'daemon-reload']); run(['systemctl', 'start', 'orion-server'])
                wait_health(old_port)
                if had_timer and timer_enabled:
                    run(['systemctl', 'enable', '--now', 'orion-server-backup.timer'])
            except (OSError, ValueError, subprocess.TimeoutExpired):
                raise SetupError('Upgrade and recovery did not become healthy. Private data, old releases and SQLite recovery copies were retained for administrator review.') from None
            raise SetupError('The new release failed health checks. The previous release and configuration were restored; private data was retained.') from None
        try:
            run(['systemctl', 'disable', '--now', 'orion-server'])
            run(['systemctl', 'disable', '--now', 'orion-server-backup.timer'])
        except SetupError:
            pass
        raise SetupError('The first installation did not become healthy. Its service was stopped and private state retained for review.') from None


def switch_release(current, release):
    from uuid import uuid4
    staging = current.with_name('current.' + uuid4().hex + '.new')
    staging.symlink_to(release)
    os.replace(staging, current)


def backup_timer_is_enabled():
    result = subprocess.run(['systemctl', 'is-enabled', 'orion-server-backup.timer'],
                            capture_output=True, text=True)
    return result.returncode == 0 and result.stdout.strip() == 'enabled'


def backup_state(data):
    source = data / "orion-hub.sqlite3"
    if not source.exists(): return None
    folder = data / "upgrade-backups"; folder.mkdir(mode=0o700, exist_ok=True)
    target = folder / (str(time.time_ns()) + ".sqlite3")
    # install.py lives at the verified package root, outside its hub package.
    # Load the package's shared recovery helper from that exact source folder;
    # never import administrator CWD/user-controlled Python modules.
    import importlib.util
    helper = Path(__file__).resolve().parent / 'hub/orion_hub/state_backup.py'
    if not helper.is_file():
        helper = Path(__file__).resolve().with_name('state_backup.py')
    spec = importlib.util.spec_from_file_location('_orion_install_recovery', helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Registry lock is acquired before SQLite Hub backup, matching provisioning
    # order. Companion Cloud registry keeps ownership/revocation recoverable.
    module.snapshot_pair(data, target)
    return target


def read_mesh_auth_key(value):
    """Read a root-private enrollment key without placing it in argv or config."""
    if value is None:
        return None
    path = Path(value)
    if not path.is_absolute() or any(item.is_symlink() for item in (path, *path.parents)):
        raise SetupError('Mesh enrollment key must be an absolute root-private regular file')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(descriptor, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_size > 4096:
            raise SetupError('Mesh enrollment key must be an absolute root-private regular file')
        raw = source.read(4097).strip()
    if not re.fullmatch(rb'[A-Za-z0-9_-]{16,4096}', raw):
        raise SetupError('Mesh enrollment key file has an unsupported format')
    return raw


def ensure_mesh(distro, codename, controller, *, auth_key=None):
    if not shutil.which("tailscale"):
        key = Path("/usr/share/keyrings/tailscale-archive-keyring.gpg")
        source = Path("/etc/apt/sources.list.d/tailscale.list")
        if key.exists() or source.exists(): raise SetupError("Existing Tailscale apt configuration needs administrator review")
        prefix = f"https://pkgs.tailscale.com/stable/{distro}/{codename}"
        for url, target in ((prefix + ".noarmor.gpg", key), (prefix + ".tailscale-keyring.list", source)):
            raw = urllib.request.urlopen(url, timeout=30).read(65537)
            if len(raw) > 65536: raise SetupError("Unexpected upstream package configuration")
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(fd, "wb") as output: output.write(raw)
        run(["apt-get", "update"]); run(["apt-get", "install", "-y", "tailscale"])
    run(["systemctl", "enable", "--now", "tailscaled"])
    state = json.loads(run(["tailscale", "status", "--json"]))
    preferences = json.loads(run(["tailscale", "debug", "prefs"]))
    previous_controller = control_origin(preferences.get('ControlURL'))
    if (controller and previous_controller and previous_controller != controller
            and (state.get('BackendState') == 'Running' or preferences.get('Persist'))):
        raise SetupError('Existing mesh uses another controller; preserve it or explicitly enroll separately')
    if state.get("BackendState") != "Running":
        if preferences.get('Persist'):
            # Bare up is upstream's resume-without-changes path. Adding even a
            # timeout flag can reject saved nondefault route/DNS preferences.
            # Never force reauthentication or consume a new key for this profile.
            run(['tailscale', 'up'], timeout=130)
        elif auth_key is not None:
            with tempfile.TemporaryDirectory(prefix='orion-mesh-', dir='/run') as private:
                target = Path(private) / 'enrollment.key'
                private_write(target, auth_key.decode('ascii'))
                argv = ['tailscale', 'up', '--timeout=120s', '--auth-key=file:' + str(target)]
                if controller: argv.append('--login-server=' + controller)
                run(argv, timeout=130)
        else:
            print("Complete the official Tailscale sign-in in your browser. Saiph adds no account or password.")
            argv = ["tailscale", "up", "--timeout=120s"]
            if controller: argv.append("--login-server=" + controller)
            run(argv, visible=True, timeout=130)
    # Provision the actual existing controller, not a guessed owner/default URL.
    current = json.loads(run(["tailscale", "debug", "prefs"]))
    discovered = control_origin(current.get("ControlURL"))
    if controller and discovered != controller:
        raise SetupError("Existing mesh uses another controller; preserve it or explicitly enroll separately")
    if discovered in {"https://controlplane.tailscale.com", "https://login.tailscale.com"}: discovered = None
    try: address = mesh_ip(run(["tailscale", "ip", "-4"]))
    except ValueError: address = mesh_ip(run(["tailscale", "ip", "-6"]))
    return address, discovered


def wait_health(port):
    for _ in range(30):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/health", timeout=2) as response:
                value = json.load(response)
                if value.get("ok") and value.get("service") == "orion-hub": return
        except (OSError, ValueError): pass
        time.sleep(1)
    raise SetupError("Saiph did not become healthy; use the private upgrade backup before any rollback")


def export_initial_invite():
    folder = DATA / "enrollments"
    folder.mkdir(mode=0o700, exist_ok=True)
    run(["chown", f"{USER}:{USER}", str(folder)])
    target = folder / ("device-" + str(time.time_ns()) + ".orion-enrollment")
    run([str(WRAPPER), "enroll", "--output", str(target), "--minutes", "30"])
    invoker = os.environ.get("SUDO_USER", "root")
    if invoker == "root": return target
    # Write into the invoking user's home as that user, not with root privileges
    # through user-controlled home-directory symlinks. Secrets travel on stdin.
    payload = json.dumps({"invite": target.read_text(), "qr": target.with_suffix(".svg").read_text()})
    script = '''import json,os,sys
from pathlib import Path
data=json.load(sys.stdin)
folder=Path.home()/'.local/share/OrionServerInvites'
folder.mkdir(mode=0o700,parents=True,exist_ok=True)
os.chmod(folder,0o700)
for suffix,key in (('.orion-enrollment','invite'),('.svg','qr')):
    target=folder/(sys.argv[1]+suffix)
    with os.fdopen(os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as output:
        output.write(data[key])
'''
    result = subprocess.run(["runuser", "-u", invoker, "--", sys.executable, "-c", script, target.stem],
                            input=payload, capture_output=True, text=True)
    if result.returncode: raise SetupError("Server is healthy; private invitation export needs administrator review")
    import pwd
    return Path(pwd.getpwnam(invoker).pw_dir) / ".local/share/OrionServerInvites" / target.name


def main():
    parser = argparse.ArgumentParser(description="Install or upgrade your private Saiph server")
    parser.add_argument("--port", type=int, help="Advanced port override (default 8765 on first install)")
    parser.add_argument("--mesh-login-server", help="Advanced trusted Headscale HTTPS origin")
    parser.add_argument('--mesh-auth-key-file', type=Path,
                        help='Optional root-private one-use network enrollment key file; never put the key itself in arguments')
    args = parser.parse_args()
    if platform.system() != "Linux" or os.geteuid() != 0: raise SetupError("Run this server installer with sudo on a supported Linux host")
    if sys.version_info < (3, 10): raise SetupError("Python 3.10 or newer is required")
    if not Path("/run/systemd/system").exists(): raise SetupError("A running systemd host is required")
    with installation_lock():
        install(args)


def install(args):
    values = dict(line.split("=", 1) for line in Path("/etc/os-release").read_text().splitlines() if "=" in line)
    values = {key: value.strip('"') for key, value in values.items()}
    distro, codename = supported_system(values, platform.machine())
    controller = control_origin(args.mesh_login_server)
    auth_key = read_mesh_auth_key(getattr(args, 'mesh_auth_key_file', None))
    folder = Path(__file__).resolve().parent
    manifest = verify_package(folder)
    for path in (INSTALL, CONFIG, *managed_paths().values()): check_owned(path)
    existing = INSTALL / "managed.json"
    check_owned(existing)
    if INSTALL.exists() and (not existing.is_file() or json.loads(existing.read_text()).get("format") != MARKER):
        raise SetupError("Existing installation is unrecognized; nothing was replaced")
    record = json.loads(existing.read_text()) if existing.exists() else {}
    first_install = not existing.exists()
    for name, path in managed_paths().items():
        if path.exists() and record.get("owned_files", {}).get(name) != hashlib.sha256(path.read_bytes()).hexdigest():
            raise SetupError("An unrelated or locally changed service/command needs administrator review")
    settings = json.loads((CONFIG / "server.json").read_text()) if existing.exists() else {}
    if not existing.exists() and (CONFIG.exists() or DATA.exists()):
        raise SetupError("Existing private state is unrecognized; nothing was replaced")
    port = args.port if args.port is not None else settings.get("port", 8765)
    if not 1024 <= port <= 65535: raise SetupError("Advanced port must be between 1024 and 65535")
    if existing.exists() and controller is not None and controller != settings.get("mesh_login_server"):
        raise SetupError("An upgrade cannot silently change the existing mesh controller")
    controller = settings.get("mesh_login_server", controller)
    if shutil.disk_usage("/var/lib").free < 1024**3: raise SetupError("At least 1 GiB free disk is required")
    available = next(int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:"))
    if available < 512 * 1024: raise SetupError("At least 512 MiB available memory is required for installation")
    run(["apt-get", "update"]); run(["apt-get", "install", "-y", "python3-venv", "python3-pip", "ca-certificates"])
    address, controller = ensure_mesh(distro, codename, controller, auth_key=auth_key)
    if not existing.exists() or port != settings.get("port"):
        for host in ("127.0.0.1", address):
            with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET) as probe:
                try: probe.bind((host, port))
                except OSError: raise SetupError("The Hub port is in use; choose another port with Advanced --port") from None
    account_exists = subprocess.run(["id", "-u", USER], capture_output=True).returncode == 0
    if account_exists and not existing.exists(): raise SetupError("An unrelated Saiph service account already exists")
    if not account_exists:
        run(["useradd", "--system", "--user-group", "--home-dir", str(DATA), "--shell", "/usr/sbin/nologin", USER])
    for path in (INSTALL, INSTALL / "releases", DATA, CONFIG):
        if path.is_symlink(): raise SetupError("Refusing a symbolic link at an installation path")
        path.mkdir(mode=0o700 if path in (DATA, CONFIG) else 0o755, parents=True, exist_ok=True)
        if path not in (DATA, CONFIG): os.chmod(path, 0o755)
    run(["chown", f"{USER}:{USER}", str(DATA)]); os.chmod(DATA, 0o700)
    release = INSTALL / "releases" / manifest["release"]
    if release.exists(): raise SetupError("This release is already staged; keep it and use a new package version")
    release.mkdir(mode=0o755); os.chmod(release, 0o755)
    for name in manifest["files"]:
        if not name.startswith("hub/"): continue
        target = release / name; target.parent.mkdir(parents=True, exist_ok=True)
        for parent in (target.parent, release / "hub"):
            os.chmod(parent, 0o755)
        shutil.copyfile(folder / name, target); os.chmod(target, 0o644)
    run([sys.executable, "-m", "venv", str(release / "venv")])
    run([str(release / "venv/bin/pip"), "--isolated", "install", "--index-url", "https://pypi.org/simple", "-r", str(release / "hub/requirements.txt")])
    backup_state(DATA)
    activate_release(release, address, port, controller, record, first_install)
    if first_install:
        invitation = export_initial_invite()
        print(f"Private first-device invitation and QR: {invitation}")
    print("Saiph server is healthy. Create a separate private invitation for each device:")
    print("  sudo orion-server enroll --output /var/lib/orion-server/device.orion-enrollment")
    print("The invitation and QR are private. Transfer them securely; do not paste their contents into chat or logs.")


if __name__ == "__main__":
    try: main()
    except SetupError as error:
        raise SystemExit(str(error)) from None
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        raise SystemExit("Saiph setup did not finish. Check prerequisites/Advanced options; existing private data and releases were retained.") from None
