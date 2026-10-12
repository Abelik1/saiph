# SPDX-License-Identifier: AGPL-3.0-or-later
"""Optional Seafile accounts subordinate to existing paired device keys.

Administrator credentials never leave this module. The separate private registry
serializes Cloud changes without holding the event bus database's write lock.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode, urlsplit
from uuid import UUID

ERROR = 'Cloud setup needs administrator attention. Existing accounts and files were retained.'
DEVICE = re.compile(r'dev_[a-f0-9]{32}')
TOKEN = re.compile(r'[a-fA-F0-9]{32,128}')
USER = re.compile(r'[A-Za-z0-9._+@-]{1,254}')
MAX_RESPONSE = 1024 * 1024


class CloudError(ValueError):
    def __init__(self):
        super().__init__(ERROR)


def origin(value):
    try:
        if not isinstance(value, str) or len(value) > 256 or any(ord(c) <= 32 for c in value):
            raise ValueError()
        parsed = urlsplit(value)
        address = ipaddress.ip_address(parsed.hostname or '')
        network = ipaddress.ip_network('100.64.0.0/10' if address.version == 4 else 'fd7a:115c:a1e0::/48')
        if (parsed.scheme not in {'http', 'https'} or address not in network or parsed.username is not None or parsed.password is not None
                or parsed.path not in {'', '/'} or parsed.query or parsed.fragment or '%' in value):
            raise ValueError()
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == 'https' else 80)
        if not 1 <= port <= 65535:
            raise ValueError()
        return f"{parsed.scheme}://{'[' + str(address) + ']' if address.version == 6 else str(address)}:{port}"
    except (TypeError, ValueError):
        raise CloudError() from None


def _private_read(path, maximum):
    if not isinstance(path, Path) or not path.is_absolute():
        raise CloudError()
    for item in (path, *path.parents):
        if item.is_symlink():
            raise CloudError()
    info = path.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_size > maximum
            or os.name != 'nt' and (info.st_mode & 0o027 or info.st_uid not in {0, os.geteuid()})):
        raise CloudError()
    return path.read_text(encoding='utf-8')


@dataclass(frozen=True, repr=False)
class Configuration:
    server: str
    admin_token: str = field(repr=False)
    libraries: tuple[dict, ...]

    def __repr__(self):
        return 'Configuration(<private>)'


def configuration():
    configured = os.environ.get('ORION_SEAFILE_CONFIG')
    if not configured:
        return None
    try:
        raw = json.loads(_private_read(Path(configured), 32768))
        if (not isinstance(raw, dict) or set(raw) != {'schema', 'server', 'admin_token_file', 'libraries'}
                or type(raw['schema']) is not int or raw['schema'] != 1
                or not isinstance(raw['libraries'], list) or not 1 <= len(raw['libraries']) <= 8
                or not isinstance(raw['admin_token_file'], str)):
            raise CloudError()
        server = origin(raw['server'])
        token = _private_read(Path(raw['admin_token_file']), 4096).strip()
        if not TOKEN.fullmatch(token):
            raise CloudError()
        libraries = []
        for item in raw['libraries']:
            if (not isinstance(item, dict) or set(item) != {'id', 'name', 'permission'}
                    or not isinstance(item['id'], str) or str(UUID(item['id'])) != item['id']
                    or not isinstance(item['name'], str) or not 1 <= len(item['name']) <= 80
                    or any(ord(c) < 32 for c in item['name']) or item['permission'] not in {'r', 'rw'}):
                raise CloudError()
            libraries.append(dict(item))
        if len({item['id'] for item in libraries}) != len(libraries):
            raise CloudError()
        return Configuration(server, token, tuple(libraries))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise CloudError() from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise CloudError()


class API:
    def __init__(self, config):
        self.config = config
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def __repr__(self):
        return 'API(<private>)'

    def request(self, method, path, values=None, *, token=None, anonymous=False):
        if not isinstance(path, str) or not path.startswith('/api') or not re.fullmatch(r'/[A-Za-z0-9_./%+@-]+', path):
            raise CloudError()
        headers = {'Accept': 'application/json'}
        if not anonymous:
            headers['Authorization'] = 'Token ' + (token if token is not None else self.config.admin_token)
        body = None if values is None else urlencode(values).encode()
        if body is not None:
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        request = urllib.request.Request(self.config.server + path, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=8) as response:
                if response.status not in {200, 201}:
                    raise CloudError()
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise CloudError()
                return json.loads(raw)
        except urllib.error.HTTPError as error:
            # The upstream admin unshare endpoint reports 404 for an already
            # absent share. Retrying our own revoke must remain idempotent.
            if method == 'DELETE' and path == '/api/v2.1/admin/shares/' and error.code == 404:
                return {'success': True}
            raise CloudError() from None
        except (OSError, ValueError, urllib.error.URLError, RecursionError):
            raise CloudError() from None


def _registry_path(db):
    return db.path.parent / 'cloud-provisioning.sqlite3'


@contextmanager
def registry(db, *, create=True):
    path = _registry_path(db)
    if path.is_symlink():
        raise CloudError()
    if not path.exists():
        if not create:
            yield None
            return
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        except FileExistsError:
            pass
    if os.name != 'nt' and path.stat().st_mode & 0o077:
        raise CloudError()
    connection = sqlite3.connect(path, timeout=2)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('CREATE TABLE IF NOT EXISTS accounts (device_id TEXT PRIMARY KEY, server TEXT NOT NULL, user_id TEXT NOT NULL, login TEXT NOT NULL, password TEXT NOT NULL, selection TEXT NOT NULL, state TEXT NOT NULL)')
        yield connection
    finally:
        # Persist known remote account IDs and failed/revoking states even if a
        # bounded API call failed; later reconciliation can close that access.
        connection.commit()
        connection.close()


def _paired(db, device):
    if not isinstance(device, str) or not DEVICE.fullmatch(device) or not db.row('SELECT id FROM devices WHERE id=?', (device,)):
        raise CloudError()


def _selection(config, body):
    if not isinstance(body, dict) or set(body) not in (set(), {'libraries'}):
        raise CloudError()
    selected = body.get('libraries', [item['id'] for item in config.libraries])
    if (not isinstance(selected, list) or not 1 <= len(selected) <= 8 or not all(isinstance(item, str) for item in selected)
            or len(set(selected)) != len(selected) or not set(selected) <= {item['id'] for item in config.libraries}):
        raise CloudError()
    return [dict(item) for item in config.libraries if item['id'] in selected]


def status(db, device):
    _paired(db, device)
    try:
        config = configuration()
        if config is None:
            return {'configured': False, 'state': 'not_configured', 'libraries': []}
        with registry(db, create=False) as connection:
            row = connection.execute('SELECT state FROM accounts WHERE device_id=?', (device,)).fetchone() if connection else None
        return {'configured': True, 'state': 'available' if not row else 'provisioned' if row['state'] == 'active' else 'needs_attention',
                'libraries': list(config.libraries)}
    except (CloudError, OSError, sqlite3.Error):
        return {'configured': False, 'state': 'needs_attention', 'libraries': []}


def _user_path(user):
    if not isinstance(user, str) or not USER.fullmatch(user):
        raise CloudError()
    return '/api/v2.1/admin/users/' + quote(user, safe='') + '/'


def _verify_user(api, user, *, active):
    row = api.request('GET', _user_path(user))
    if (not isinstance(row, dict) or row.get('email') != user or row.get('is_staff') is not False
            or row.get('is_active') is not active):
        raise CloudError()


def _disable(api, user):
    api.request('PUT', _user_path(user), {'is_active': 'false', 'is_staff': 'false'})
    _verify_user(api, user, active=False)


def _close_account(api, row):
    _disable(api, row['user_id'])
    try:
        libraries = json.loads(row['selection'])
        if (not isinstance(libraries, list) or not 1 <= len(libraries) <= 8
                or any(not isinstance(item, dict) or not isinstance(item.get('id'), str)
                       or str(UUID(item['id'])) != item['id'] for item in libraries)):
            raise CloudError()
    except (ValueError, TypeError, KeyError, RecursionError):
        raise CloudError() from None
    for library in libraries:
        result = api.request('DELETE', '/api/v2.1/admin/shares/', {'repo_id': library['id'],
                            'share_type': 'user', 'share_to': row['user_id']})
        if not isinstance(result, dict) or result.get('success') is not True:
            raise CloudError()


def provision(db, device, body, *, api_factory=API):
    _paired(db, device)
    config = configuration()
    if config is None:
        raise CloudError()
    libraries = _selection(config, body)
    selection = json.dumps(libraries, sort_keys=True, separators=(',', ':'))
    api = api_factory(config)
    cleanup_allowed = False
    try:
        with registry(db) as connection:
            _paired(db, device)
            row = connection.execute('SELECT * FROM accounts WHERE device_id=?', (device,)).fetchone()
            if row and row['state'] in {'revoking', 'revoked'}:
                raise CloudError()
            cleanup_allowed = True
            if row and row['state'] == 'failed':
                if not row['user_id'] or row['server'] != config.server:
                    raise CloudError()
                _close_account(api, row)
                connection.execute('DELETE FROM accounts WHERE device_id=?', (device,))
                row = None
            if row and (row['server'] != config.server or row['selection'] != selection):
                # Never send an old account's admin request to a new server.
                if row['server'] != config.server:
                    raise CloudError()
                _close_account(api, row)
                connection.execute('DELETE FROM accounts WHERE device_id=?', (device,))
                row = None
            if row is None:
                login = 'orion-' + secrets.token_hex(24) + '@devices.orion.invalid'
                password = secrets.token_urlsafe(48)
                connection.execute('INSERT INTO accounts VALUES (?,?,?,?,?,?,?)',
                                   (device, config.server, '', login, password, selection, 'reserved'))
                created = api.request('POST', '/api/v2.1/admin/users/',
                                      {'email': login, 'password': password, 'is_staff': 'false', 'is_active': 'false', 'name': 'Orion device'})
                if (not isinstance(created, dict) or not isinstance(created.get('email'), str)
                        or not USER.fullmatch(created['email']) or created.get('is_staff') is not False
                        or created.get('is_active') is not False
                        or (created['email'] != login and (not re.fullmatch(r'[a-f0-9]{32}@auth.local', created['email'])
                            or created.get('contact_email') != login))):
                    raise CloudError()
                user = created['email']
                connection.execute('UPDATE accounts SET user_id=? WHERE device_id=?', (user, device))
                for library in libraries:
                    api.request('POST', '/api/v2.1/admin/shares/', {'repo_id': library['id'], 'share_type': 'user',
                                'share_to': user, 'permission': library['permission']})
                api.request('PUT', _user_path(user), {'is_active': 'true', 'is_staff': 'false'})
                row = connection.execute('SELECT * FROM accounts WHERE device_id=?', (device,)).fetchone()
            _verify_user(api, row['user_id'], active=True)
            reply = api.request('POST', '/api2/auth-token/', {'username': row['login'], 'password': row['password']}, anonymous=True)
            token = reply.get('token') if isinstance(reply, dict) else None
            if not isinstance(token, str) or not TOKEN.fullmatch(token) or token == config.admin_token:
                raise CloudError()
            visible = api.request('GET', '/api2/repos/', token=token)
            selected = {item['id']: item['permission'] for item in libraries}
            if (not isinstance(visible, list) or len(visible) != len(selected)
                    or any(not isinstance(item, dict) or item.get('id') not in selected
                           or item.get('permission') != selected[item['id']] or item.get('encrypted') is True for item in visible)
                    or {item['id'] for item in visible} != set(selected)):
                raise CloudError()
            _paired(db, device)
            connection.execute("UPDATE accounts SET state='active' WHERE device_id=?", (device,))
            return {'profile': {'schema': 1, 'server': config.server, 'user': row['login'], 'token': token,
                                'token_scope': 'account', 'libraries': libraries}}
    except (OSError, ValueError, sqlite3.Error):
        # Failures after activation must not leave a usable grant. Preserve the
        # private registry for retry/reconciliation; never reset an owner account.
        try:
            if not cleanup_allowed:
                raise CloudError()
            with registry(db, create=False) as connection:
                row = connection.execute('SELECT * FROM accounts WHERE device_id=?', (device,)).fetchone() if connection else None
                if row:
                    connection.execute("UPDATE accounts SET state='failed' WHERE device_id=?", (device,))
                    if row['user_id'] and row['server'] == config.server:
                        _close_account(api, row)
        except (OSError, ValueError, sqlite3.Error):
            pass
        raise CloudError() from None


def queue_revoke(db, device):
    """Persist closure intent without remote I/O; never delay Hub revocation."""
    try:
        with registry(db, create=False) as connection:
            if connection is not None:
                connection.execute("UPDATE accounts SET state='revoking' WHERE device_id=? AND state!='revoked'", (device,))
    except (OSError, ValueError, sqlite3.Error):
        raise CloudError() from None


def revoke(db, device, *, api_factory=API):
    """Disable the supporting account and remove its selected library shares."""
    queue_revoke(db, device)
    try:
        with registry(db, create=False) as connection:
            row = connection.execute('SELECT * FROM accounts WHERE device_id=?', (device,)).fetchone() if connection else None
            if row is None or row['state'] == 'revoked':
                return
            connection.execute("UPDATE accounts SET state='revoking' WHERE device_id=?", (device,))
            config = configuration()
            if config is None or config.server != row['server'] or not row['user_id']:
                raise CloudError()
            api = api_factory(config)
            _close_account(api, row)
            connection.execute("UPDATE accounts SET state='revoked',password='' WHERE device_id=?", (device,))
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        raise CloudError() from None


def reconcile(db, *, api_factory=API):
    """Retry pending closure, including devices removed outside the owner CLI."""
    if not _registry_path(db).exists():
        return
    try:
        with registry(db, create=False) as connection:
            rows = [dict(row) for row in connection.execute("SELECT device_id,state,server,selection FROM accounts WHERE state!='revoked'")]
        config = configuration()
        policy = {item['id']: item['permission'] for item in config.libraries} if config else None
        failed = False
        for row in rows:
            policy_changed = False
            if config and row['server'] == config.server:
                try:
                    selected = json.loads(row['selection'])
                    policy_changed = not isinstance(selected, list) or not selected or any(
                        not isinstance(item, dict) or item.get('id') not in policy
                        or item.get('permission') not in {'r', 'rw'}
                        or item.get('permission') == 'rw' and policy[item['id']] == 'r' for item in selected)
                except (ValueError, TypeError, RecursionError):
                    policy_changed = True
            if policy_changed or row['state'] in {'revoking', 'failed'} or not db.row('SELECT id FROM devices WHERE id=?', (row['device_id'],)):
                try:
                    revoke(db, row['device_id'], api_factory=api_factory)
                except CloudError:
                    failed = True
        if failed:
            raise CloudError()
    except (OSError, ValueError, sqlite3.Error):
        raise CloudError() from None
