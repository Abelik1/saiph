# SPDX-License-Identifier: AGPL-3.0-or-later
"""Immutable checked release files and short-lived, account-bound download tickets.

The directory is installed by the administrator and read-only to the service.
No client input is ever interpreted as a filesystem path. Tickets are hashed at
rest, expire after five minutes, and recheck account standing on every request.
"""
import hashlib
import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import re
import secrets
import time

from starlette.responses import FileResponse
from fastapi import HTTPException
from .hosted import reject


@dataclass(frozen=True)
class DownloadLimits:
    window_seconds: int = 300
    ticket_requests: int = 8
    account_requests: int = 30
    global_requests: int = 120
    account_streams: int = 2
    global_streams: int = 8
    stream_seconds: int = 300
    account_file_copies: int = 4
    global_file_copies: int = 16

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in vars(self).values()):
            raise ValueError('Download limits must be positive integers')


# Desktop update feed (docs/DESKTOP_UPDATES.md): a catalog may describe the Windows
# installer and the Linux .run for native Saiph account clients. Each description is
# checked against its installer when the service starts, so a mismatched catalog
# never loads. Keys: platform -> (description entry, installer entry).
DESKTOP_RELEASES = {'windows-x86_64': ('windows_release', 'windows'), 'linux-x86_64': ('linux_release', 'linux')}
DESCRIPTION_KEYS = {'schema', 'platform', 'profile', 'build', 'version', 'sha256', 'bytes', 'notes'}
VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?')
MAX_DESCRIPTION = 16384
MAX_NOTES = 4000


def _strict(raw):
    def pairs(items):
        if len({key for key, _ in items}) != len(items):
            raise ValueError('Repeated key')
        return dict(items)

    def constant(_):
        raise ValueError('Invalid number')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)


def desktop_description(raw, platform, installer):
    """The exact bytes a desktop client will accept for this installer, else ValueError.

    Mirrors the client's rules (orion_mini.package_updates.validate_cloud_release) so a
    description the desktop would refuse is refused here first, when the service starts.
    """
    try:
        value = _strict(raw) if len(raw) <= MAX_DESCRIPTION else None
    except (ValueError, UnicodeError, RecursionError):
        value = None
    path, sha256 = installer
    notes = value.get('notes') if isinstance(value, dict) else None
    if (not isinstance(value, dict) or set(value) != DESCRIPTION_KEYS
            or type(value['schema']) is not int or value['schema'] != 1
            or value['platform'] != platform
            or value['profile'] not in ('link', 'workspace')
            or type(value['build']) is not int or not 1 <= value['build'] <= 2 ** 53 - 1
            or not isinstance(value['version'], str) or len(value['version']) > 100 or not VERSION.fullmatch(value['version'])
            or value['sha256'] != sha256
            or type(value['bytes']) is not int or value['bytes'] != path.stat().st_size
            or not isinstance(notes, str) or len(notes) > MAX_NOTES
            or any((ord(c) < 32 and c != '\n') or ord(c) == 127 or '‪' <= c <= '‮' or '⁦' <= c <= '⁩'
                   for c in notes)):
        raise ValueError(f'Desktop release description for {platform} does not match its installer')
    return raw


class LimitedFileResponse(FileResponse):
    """Keep the durable stream lease until completion, error or cancellation."""
    def __init__(self, *args, release, lease, seconds, **kwargs):
        super().__init__(*args, **kwargs)
        self.release, self.lease, self.seconds = release, lease, seconds

    async def __call__(self, scope, receive, send):
        # Use awaited, backpressured chunks rather than delegating a file path
        # whose transfer completion this application cannot observe.
        scope = {**scope, 'extensions': {key: value for key, value in scope.get('extensions', {}).items()
                                       if key != 'http.response.pathsend'}}
        try:
            await asyncio.wait_for(super().__call__(scope, receive, send), timeout=self.seconds)
        finally:
            await asyncio.shield(asyncio.to_thread(self.release, self.lease))


class Downloads:
    def __init__(self, registry, directory, *, limits=None):
        self.registry = registry
        self.limits = limits or DownloadLimits()
        root = Path(directory)
        if not root.is_absolute() or any(p.is_symlink() for p in (root, *root.parents)):
            raise ValueError('Use a dedicated absolute release directory without links')
        raw = (root / 'catalog.json').read_bytes()
        if len(raw) > 16384:
            raise ValueError('Download catalog too large')
        catalog = json.loads(raw)
        if not isinstance(catalog, dict) or not 1 <= len(catalog) <= 20:
            raise ValueError('Invalid release catalog')
        self.files = {}
        for key, entry in catalog.items():
            if (not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', key) or not isinstance(entry, dict)
                    or set(entry) != {'file', 'sha256'} or not isinstance(entry['file'], str)
                    or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,199}', entry['file'])
                    or not isinstance(entry['sha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', entry['sha256'])):
                raise ValueError('Invalid checked download entry')
            path = root / entry['file']
            if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
                raise ValueError('A regular nonempty release file is required')
            with path.open('rb') as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != entry['sha256']:
                    raise ValueError('Release checksum mismatch')
            self.files[key] = (path, entry['sha256'])
        # Release descriptions are small metadata, not downloads: kept in memory, never ticketed.
        self.desktop = {}
        for platform, (description, installer) in DESKTOP_RELEASES.items():
            if description in self.files:
                if installer not in self.files:
                    raise ValueError(f'Desktop release description for {platform} has no installer')
                path, _ = self.files.pop(description)
                self.desktop[platform] = desktop_description(path.read_bytes(), platform, self.files[installer])
        if not self.files:
            raise ValueError('Invalid release catalog')
        self.largest_file = max(path.stat().st_size for path, _ in self.files.values())
        with registry.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS download_tickets(
                digest TEXT PRIMARY KEY, account TEXT NOT NULL REFERENCES accounts(id),
                artifact TEXT NOT NULL, checksum TEXT NOT NULL, expires_at INTEGER NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS tickets_expiry ON download_tickets(expires_at)')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS download_usage(
                    account TEXT NOT NULL, ticket TEXT NOT NULL, requested_at REAL NOT NULL,
                    bytes INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS download_usage_account ON download_usage(account,requested_at);
                CREATE INDEX IF NOT EXISTS download_usage_ticket ON download_usage(ticket,requested_at);
                CREATE TABLE IF NOT EXISTS download_streams(
                    id TEXT PRIMARY KEY, account TEXT NOT NULL, expires_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS download_streams_account ON download_streams(account,expires_at);
            ''')

    def issue(self, identity, artifact):
        if not isinstance(artifact, str) or artifact not in self.files:
            reject(404)
        account = self.registry.principal(identity)
        now = int(time.time())
        ticket = secrets.token_urlsafe(32)
        with self.registry.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM download_tickets WHERE expires_at<=?', (now,))
            if db.execute('SELECT count(*) FROM download_tickets WHERE account=?', (account['id'],)).fetchone()[0] >= 30:
                reject(429)
            db.execute('INSERT INTO download_tickets VALUES(?,?,?,?,?)',
                       (hashlib.sha256(ticket.encode()).hexdigest(), account['id'], artifact, self.files[artifact][1], now + 300))
        return {'ticket': ticket}

    def desktop_release(self, identity, platform):
        """Native Saiph account clients: this platform's description bytes, or None."""
        if platform not in DESKTOP_RELEASES:
            reject(404)
        self.registry.principal(identity)  # Active, entitled account only.
        return self.desktop.get(platform)

    def desktop_ticket(self, identity, platform):
        """A ticket for the installer a description is published for; nothing else."""
        if platform not in self.desktop:
            reject(404)
        return self.issue(identity, DESKTOP_RELEASES[platform][1])

    def _limited(self):
        raise HTTPException(429, 'Hosted download limit reached',
                            headers={'Retry-After': str(self.limits.window_seconds)})

    def release(self, lease):
        with self.registry.connect() as db:
            db.execute('DELETE FROM download_streams WHERE id=?', (lease,))

    def response(self, ticket, *, method='GET', range_header=None):
        if not isinstance(ticket, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', ticket):
            reject(404)
        if method not in ('GET', 'HEAD'):
            reject(405)
        # A single range supports resume. Multipart/overlapping ranges can send
        # more than a whole file and would evade the conservative byte charge.
        if range_header is not None and (len(range_header) > 128 or ',' in range_header):
            reject(416)
        digest = hashlib.sha256(ticket.encode()).hexdigest()
        now, limits = time.time(), self.limits
        lease = secrets.token_hex(16)
        with self.registry.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('''SELECT t.*,a.subject,a.issuer,a.active FROM download_tickets t
                JOIN accounts a ON a.id=t.account WHERE t.digest=? AND t.expires_at>?''',
                (digest, now)).fetchone()
            if row is None or not row['active'] or self.registry._entitled(db, row['account']) is None:
                reject(404)
            item = self.files.get(row['artifact'])
            if item is None or item[1] != row['checksum']:
                reject(404)
            db.execute('DELETE FROM download_usage WHERE requested_at<=?', (now - limits.window_seconds,))
            db.execute('DELETE FROM download_streams WHERE expires_at<=?', (now,))
            count, charged = db.execute('SELECT count(*),coalesce(sum(bytes),0) FROM download_usage WHERE account=?',
                                        (row['account'],)).fetchone()
            total_count, total_bytes = db.execute('SELECT count(*),coalesce(sum(bytes),0) FROM download_usage').fetchone()
            ticket_count = db.execute('SELECT count(*) FROM download_usage WHERE ticket=?', (digest,)).fetchone()[0]
            # Reserve a full file even for Range/retry: partial and interrupted
            # transfers cannot hide usage or oversubscribe a concurrent budget.
            charge = item[0].stat().st_size if method == 'GET' else 0
            if (count >= limits.account_requests or total_count >= limits.global_requests
                    or ticket_count >= limits.ticket_requests
                    or charged + charge > self.largest_file * limits.account_file_copies
                    or total_bytes + charge > self.largest_file * limits.global_file_copies
                    or db.execute('SELECT count(*) FROM download_streams WHERE account=?', (row['account'],)).fetchone()[0] >= limits.account_streams
                    or db.execute('SELECT count(*) FROM download_streams').fetchone()[0] >= limits.global_streams):
                self._limited()
            db.execute('INSERT INTO download_usage VALUES(?,?,?,?)', (row['account'], digest, now, charge))
            # Grace exceeds the response timeout, so a live stream is never
            # intentionally reaped. Crashed processes leave only bounded leases.
            db.execute('INSERT INTO download_streams VALUES(?,?,?)', (lease, row['account'], now + limits.stream_seconds + 30))
        return LimitedFileResponse(item[0], release=self.release, lease=lease, seconds=limits.stream_seconds,
                            filename=item[0].name, media_type='application/octet-stream',
                            headers={'Cache-Control':'private, no-store', 'Referrer-Policy':'no-referrer',
                                     'X-Content-Type-Options':'nosniff', 'X-Robots-Tag':'noindex, nofollow'})
