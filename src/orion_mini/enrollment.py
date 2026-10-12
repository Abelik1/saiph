# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bounded private invitations; the dashboard receives metadata or a QR grid, never code text."""
from __future__ import annotations

import ipaddress
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from uuid import uuid4


def forward_invitation(root: Path, path: str) -> bool:
    """Forward a file association to the existing authenticated local API."""
    import urllib.request
    try:
        info = json.loads((root / 'api.json').read_text(encoding='utf-8-sig'))
        origin = urlsplit(info['url'])
        if origin.scheme != 'http' or origin.hostname != '127.0.0.1' or not origin.port or origin.path not in {'', '/'} or origin.query or origin.fragment or origin.username is not None:
            return False
        request = urllib.request.Request(info['url'].rstrip('/') + '/v1/enrollment/import',
                                         data=json.dumps({'path': str(Path(path).resolve())}).encode(),
                                         headers={'Authorization': 'Bearer ' + info['token'], 'Content-Type': 'application/json'})
        from .hub_client import _NoRedirect
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=5) as response:
            return response.status == 200
    except (OSError, ValueError, KeyError, TypeError):
        return False


def mesh_origin(value: str) -> str:
    try:
        if not isinstance(value, str) or any(ord(char) <= 32 for char in value):
            raise ValueError
        parsed = urlsplit(value)
        address = ipaddress.ip_address(parsed.hostname or '')
        network = ipaddress.ip_network('100.64.0.0/10' if address.version == 4 else 'fd7a:115c:a1e0::/48')
        if (parsed.scheme != 'http' or address not in network or parsed.username is not None
                or parsed.password is not None or parsed.path not in {'', '/'}
                or parsed.query or parsed.fragment or not 1024 <= (parsed.port or 0) <= 65535):
            raise ValueError
        host = f'[{address}]' if address.version == 6 else str(address)
        return f'http://{host}:{parsed.port}'
    except (ValueError, TypeError, AttributeError):
        raise ValueError('The invitation must name a numeric mesh Hub origin.') from None


def login_server(value):
    if value is None:
        return None
    try:
        if not isinstance(value, str) or any(ord(char) <= 32 for char in value):
            raise ValueError
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.path not in {'', '/'}
                or parsed.query or parsed.fragment or not 1 <= (parsed.port or 443) <= 65535):
            raise ValueError
        return value.rstrip('/')
    except (ValueError, TypeError, AttributeError):
        raise ValueError('The invitation has an invalid mesh sign-in provider.') from None


def parse_invitation(raw: bytes, now=None) -> dict:
    if len(raw) > 4096:
        raise ValueError('The invitation is too large.')
    try:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError
                result[key] = value
            return result
        item = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique)
        if not isinstance(item, dict) or item.get('format') != 'orion-enrollment' or type(item.get('version')) is not int or item['version'] != 1:
            raise ValueError
        if not set(item) <= {'format', 'version', 'hub', 'code', 'expires_at', 'mesh_login_server'}:
            raise ValueError
        if not isinstance(item.get('code'), str) or not re.fullmatch(r'[0-9]{8}', item['code']):
            raise ValueError
        expires = datetime.fromisoformat(item['expires_at'].replace('Z', '+00:00'))
        if expires.tzinfo is None:
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise ValueError('This is not a valid Saiph invitation.') from None
    remaining = (expires - (now or datetime.now(timezone.utc))).total_seconds()
    if not 0 < remaining <= 3660:
        raise ValueError('This invitation has expired or has an unsupported expiry. Ask your server for a fresh invitation.')
    return {'format': 'orion-enrollment', 'version': 1, 'hub': mesh_origin(item.get('hub')),
            'code': item['code'], 'expires_at': expires.isoformat(),
            'mesh_login_server': login_server(item.get('mesh_login_server'))}


class Invitations:
    def __init__(self):
        self._lock = threading.RLock()
        self._item = None
        self._id = None

    def import_file(self, path):
        try:
            source = Path(path)
            if source.suffix.lower() != '.orion-enrollment':
                raise ValueError
            with source.open('rb') as stream:
                item = parse_invitation(stream.read(4097))
        except OSError:
            raise ValueError('The invitation file could not be opened.') from None
        except (TypeError, ValueError) as error:
            if str(error):
                raise
            raise ValueError('Choose a Saiph invitation file.') from None
        with self._lock:
            self._item, self._id = item, str(uuid4())
            return self.status()

    def status(self):
        with self._lock:
            if self._item and datetime.fromisoformat(self._item['expires_at']) <= datetime.now(timezone.utc):
                self.clear()
            return {'ready': bool(self._item), 'id': self._id,
                    'expires_at': self._item['expires_at'] if self._item else None,
                    'custom_mesh': bool(self._item and self._item['mesh_login_server'])}

    def approved(self, invitation_id):
        with self._lock:
            if not self.status()['ready'] or invitation_id != self._id:
                raise ValueError('Open a current invitation before approving setup.')
            return dict(self._item)

    def clear(self, invitation_id=None):
        with self._lock:
            if invitation_id is None or self._id == invitation_id:
                self._item = self._id = None


def pairing_link(item: dict) -> str:
    """The Android scanner's existing ``orion://pair`` link for a parsed invitation."""
    query = {'v': '1', 'hub': mesh_origin(item['hub']), 'code': item['code']}
    if item.get('mesh_login_server'):
        query['mesh_login_server'] = login_server(item['mesh_login_server'])
    return 'orion://pair?' + urlencode(query)


def pairing_qr(item: dict, now=None) -> dict:
    """Render a parsed invitation as QR modules for on-screen display only.

    The result carries the module grid and expiry, not the code or link text, so
    the dashboard never holds the credential as a string. Nothing is written.
    """
    import qrcode
    remaining = (datetime.fromisoformat(item['expires_at']) - (now or datetime.now(timezone.utc))).total_seconds()
    if not 0 < remaining <= 3660:
        raise ValueError('This invitation has expired or has an unsupported expiry.')
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    qr.add_data(pairing_link(item))
    qr.make(fit=True)
    return {'modules': [''.join('1' if cell else '0' for cell in row) for row in qr.get_matrix()],
            'expires_at': item['expires_at'], 'expires_in': int(remaining)}
