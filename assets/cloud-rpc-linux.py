# SPDX-License-Identifier: AGPL-3.0-or-later
"""Finite local adapter for distro Seafile; invoked with system Python -I.

No HTTP, CLI authentication, token arguments or account files. The parent fetches
validated download metadata using the signed Hub's supporting account. Only the
upstream local clone API receives the short-lived private stdin payload.
"""
import contextlib
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import urlsplit
from uuid import UUID


def plain(path, *, directory=False):
    path = Path(path)
    if not path.is_absolute() or any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError()
    info = path.stat()
    if (directory and not stat.S_ISDIR(info.st_mode) or not directory and not stat.S_ISREG(info.st_mode)):
        raise ValueError()
    return path


def validate(value):
    if not isinstance(value, dict) or set(value) != {'action', 'private', 'folder', 'library', 'server', 'info'}:
        raise ValueError()
    if value['action'] != 'clone' or not isinstance(value['library'], str) or str(UUID(value['library'])) != value['library']:
        raise ValueError()
    private = plain(value['private'], directory=True)
    folder = plain(value['folder'], directory=True)
    if folder == private or folder.is_relative_to(private) or private.is_relative_to(folder):
        raise ValueError()
    if private.stat().st_uid != os.getuid() or stat.S_IMODE(private.stat().st_mode) & 0o077:
        raise ValueError()
    marker_path = plain(private / 'orion-linux-client.json')
    if marker_path.stat().st_size > 8192 or marker_path.stat().st_uid != os.getuid():
        raise ValueError()
    marker = json.loads(marker_path.read_text(encoding='utf-8'))
    if (set(marker) != {'schema', 'executable', 'folder', 'library', 'state'}
            or type(marker['schema']) is not int or marker['schema'] != 1 or marker['state'] != 'pending'
            or marker['folder'] != str(folder) or marker['library'] != value['library']):
        raise ValueError()
    plain(marker['executable'])
    config = plain(private / 'ccnet', directory=True)
    data = plain(private / 'seafile-data', directory=True)
    pointer = plain(config / 'seafile.ini')
    if pointer.stat().st_size > 4096 or pointer.read_text(encoding='utf-8').strip() != str(data):
        raise ValueError()
    socket_path = data / 'seafile.sock'
    socket_info = socket_path.lstat()
    if not stat.S_ISSOCK(socket_info.st_mode) or socket_info.st_uid != os.getuid():
        raise ValueError()
    if config.stat().st_uid != os.getuid() or data.stat().st_uid != os.getuid():
        raise ValueError()
    server = value['server']
    if not isinstance(server, str) or len(server) > 256 or any(ord(char) <= 32 for char in server):
        raise ValueError()
    origin = urlsplit(server)
    address = ipaddress.ip_address(origin.hostname or '')
    network = ipaddress.ip_network('100.64.0.0/10' if address.version == 4 else 'fd7a:115c:a1e0::/48')
    if (origin.scheme not in {'http', 'https'} or address not in network or origin.username is not None
            or origin.password is not None or origin.path not in {'', '/'} or origin.query or origin.fragment
            or '%' in server or not 1 <= (origin.port if origin.port is not None else
                                        (443 if origin.scheme == 'https' else 80)) <= 65535):
        raise ValueError()
    info = value['info']
    if (not isinstance(info, dict) or set(info) != {'repo_version', 'repo_name', 'token', 'email', 'permission'}
            or type(info['repo_version']) is not int or not 0 <= info['repo_version'] <= 10
            or not isinstance(info['repo_name'], str) or not 1 <= len(info['repo_name']) <= 255
            or any(ord(char) < 32 for char in info['repo_name']) or info['permission'] not in {'r', 'rw'}
            or not isinstance(info['email'], str) or not re.fullmatch(r'[A-Za-z0-9._+@-]{1,254}', info['email'])
            or not isinstance(info['token'], str) or not re.fullmatch(r'[a-fA-F0-9]{32,128}', info['token'])):
        raise ValueError()
    return private, folder, data, info


def dispatch(value, rpc_class):
    if value == {'action': 'probe'} and callable(getattr(rpc_class, 'clone', None)):
        return 'available'
    _, folder, data, info = validate(value)
    rpc = rpc_class(str(data / 'seafile.sock'))
    extra = json.dumps({'server_url': value['server'], 'is_readonly': int(info['permission'] == 'r')})
    result = rpc.clone(value['library'], info['repo_version'], info['repo_name'], str(folder), info['token'],
                       None, None, info['email'], None, 0, extra)
    if result != value['library']:
        raise ValueError()
    return 'link_requested'


def main():
    result = 'failed'
    try:
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise ValueError()
        value = json.loads(raw)
        # Upstream Python output/errors never cross the finite worker boundary.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import seafile
            result = dispatch(value, seafile.RpcClient)
    except Exception:
        pass
    sys.stdout.write(json.dumps({'state': result}))


if __name__ == '__main__':
    main()
