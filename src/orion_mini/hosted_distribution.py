# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public deployment defaults explicitly selected by the release builder."""
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

FIELDS = {'service_url', 'issuer', 'audience', 'desktop_client_id', 'android_client_id'}


def read_configuration(path):
    raw = Path(path).read_bytes()
    if len(raw) > 4096:
        raise ValueError('Hosted release configuration is too large')
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != FIELDS or any(not isinstance(v, str) for v in value.values()):
        raise ValueError('Hosted release configuration accepts only the five public settings')
    for name in ('service_url', 'issuer', 'audience'):
        item = value[name]
        url = urlsplit(item)
        if (url.scheme != 'https' or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.port not in (None, 443)
                or any(c.isspace() or ord(c) < 32 for c in item) or '\\' in item):
            raise ValueError('Hosted release settings must use fixed HTTPS addresses without secrets')
        if name == 'service_url' and item != url.scheme + '://' + url.netloc:
            raise ValueError('Use the canonical service origin without a trailing slash')
        if name == 'issuer' and (url.path != '/' or not url.hostname.endswith('.auth0.com')):
            raise ValueError('Use the fixed Auth0 issuer with a trailing slash')
    clients = [value['desktop_client_id'], value['android_client_id']]
    if len(set(clients)) != 2 or any(not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', c) for c in clients):
        raise ValueError('Separate public native client IDs are required')
    return value


def desktop_config(value):
    return {**{key:value[key] for key in ('service_url', 'issuer', 'audience')},
            'client_id':value['desktop_client_id'], 'refresh_tokens':True}


def packaged_config():
    """Read validated public defaults without loading crypto or creating a profile."""
    if not getattr(sys, 'frozen', False) or not getattr(sys, '_MEIPASS', None):
        return None
    try:
        return desktop_config(read_configuration(Path(sys._MEIPASS) / 'hosted-defaults.json'))
    except (ValueError, OSError, TypeError, KeyError):
        return None
