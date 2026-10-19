# SPDX-License-Identifier: AGPL-3.0-or-later
"""Paid and trial Hosted grants pushed by the account website (docs/PAID_HOSTED.md).

The website applies verified Stripe webhooks (and free trial starts) to its own
database and signs the resulting grant with an Ed25519 key. This service holds
only public keys. A push can set or end exactly one ``paid`` grant
(``stripe:sub_...``) or ``trial`` grant (``trial:<32 hex>``); it cannot touch
beta/admin grants, reactivate a suspended account or approve a device.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .hosted import reject

MAX_BODY = 2048
CLOCK_SKEW = 300
# Longest expiry one push may set. The website rolls grants forward daily, so a
# leaked key, a forged push or a stopped website grants at most this much access.
HORIZON = 45 * 86400
CONTEXT = b'saiph-billing-grant-v1.'
GRANT = re.compile(r'stripe:sub_[A-Za-z0-9]{1,200}|trial:[a-f0-9]{32}')
# A free trial lasts at most 30 days (website setting); a trial push may not set more.
TRIAL_HORIZON = 31 * 86400
KEY_ID = re.compile(r'[a-z0-9-]{1,32}')
FIELDS = ('issuer', 'subject', 'grant', 'until', 'sequence', 'livemode')


def _b64url(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError('Invalid base64url value')
    try:
        return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
    except (binascii.Error, ValueError):
        raise ValueError('Invalid base64url value') from None


class BillingGrants:
    """Verifies signed grant pushes for one mode (sandbox or live)."""

    def __init__(self, mode, keys):
        if mode not in ('sandbox', 'live'):
            raise ValueError('Billing grant mode must be sandbox or live')
        if not keys:
            raise ValueError('At least one billing grant public key is required')
        self.livemode = mode == 'live'
        self.keys = {}
        for key_id, encoded in keys.items():
            raw = _b64url(encoded)
            if not KEY_ID.fullmatch(key_id) or len(raw) != 32:
                raise ValueError('Invalid billing grant public key')
            self.keys[key_id] = Ed25519PublicKey.from_public_bytes(raw)

    @classmethod
    def from_environment(cls, env):
        """``ORION_BILLING_GRANTS=sandbox|live`` and ``ORION_BILLING_GRANT_KEYS=id:key,...``; both or neither."""
        mode, keys = env.get('ORION_BILLING_GRANTS'), env.get('ORION_BILLING_GRANT_KEYS')
        if not mode and not keys:
            return None
        if not mode or not keys:
            raise ValueError('Billing grants need both a mode and public keys')
        parsed = {}
        for entry in keys.split(','):
            key_id, separator, encoded = entry.partition(':')
            if not separator or key_id in parsed:
                raise ValueError('Invalid billing grant public keys')
            parsed[key_id] = encoded
        return cls(mode, parsed)

    def verify(self, header, raw, *, now=None):
        """Return the validated push or reject. Never echoes key or body details."""
        now = int(time.time()) if now is None else now
        if not isinstance(header, str) or len(header) > 512 or not isinstance(raw, (bytes, bytearray)) or len(raw) > MAX_BODY:
            reject(401)
        parts = {}
        for item in header.split(','):
            name, separator, value = item.partition('=')
            if not separator or name in parts:
                reject(401)
            parts[name] = value
        if set(parts) != {'t', 'k', 'v1'} or not re.fullmatch(r'[0-9]{1,12}', parts['t']):
            reject(401)
        timestamp = int(parts['t'])
        key = self.keys.get(parts['k'])
        if key is None or abs(now - timestamp) > CLOCK_SKEW:
            reject(401)
        try:
            signature = _b64url(parts['v1'])
            key.verify(signature, CONTEXT + parts['t'].encode() + b'.' + bytes(raw))
        except (ValueError, InvalidSignature):
            reject(401)

        def unique(pairs):
            result = {}
            for name, value in pairs:
                if name in result:
                    raise ValueError()
                result[name] = value
            return result
        try:
            value = json.loads(bytes(raw), object_pairs_hook=unique)
        except ValueError:
            reject(400)
        if not isinstance(value, dict) or set(value) != set(FIELDS):
            reject(400)
        if (not isinstance(value['issuer'], str) or not isinstance(value['subject'], str)
                or not isinstance(value['grant'], str) or not GRANT.fullmatch(value['grant'])
                or type(value['until']) is not int or not 0 <= value['until'] <= now + HORIZON
                or (value['grant'].startswith('trial:') and value['until'] > now + TRIAL_HORIZON)
                or type(value['sequence']) is not int or not 1 <= value['sequence'] < 2 ** 62
                or type(value['livemode']) is not bool):
            reject(400)
        if value['livemode'] is not self.livemode:
            # A test-mode subscription never grants access on a live service, or vice versa.
            reject(403)
        return value
