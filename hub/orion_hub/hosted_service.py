# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared Hosted API with durable, explicitly admitted account workspaces.

Account tokens select a workspace by verified issuer/subject. Signed device
requests select it through an immutable index populated only by root-approved
rosters. Client-supplied account IDs, email addresses and file paths never select
storage. Each workspace retains the existing single-account protocol/quotas.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import contextmanager
import json
import hashlib
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from uuid import UUID, uuid4

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from .hosted import DEVICE, HostedConfig, body, create_app, exact, reject
from .hosted_auth import AccessTokens, Auth0Config, ServiceAuth0Config
from .hosted_maintenance import WorkspaceCleanup, maintenance_context


class AccountRegistry:
    def __init__(self, directory: Path, auth: ServiceAuth0Config):
        self.directory, self.auth = Path(directory), auth
        if not self.directory.is_absolute():
            raise ValueError('Use an absolute dedicated shared-service state directory')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / 'accounts.sqlite3'
        policy = json.dumps([auth.issuer, auth.audience, list(auth.client_ids)], separators=(',', ':'))
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS policy(id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS accounts(
                    id TEXT PRIMARY KEY, issuer TEXT NOT NULL, subject TEXT NOT NULL,
                    active INTEGER NOT NULL CHECK(active IN (0,1)), UNIQUE(issuer,subject));
                CREATE TABLE IF NOT EXISTS devices(
                    id TEXT PRIMARY KEY, account TEXT NOT NULL REFERENCES accounts(id));
                CREATE TABLE IF NOT EXISTS access_grants(
                    account TEXT NOT NULL REFERENCES accounts(id), kind TEXT NOT NULL,
                    reference TEXT NOT NULL, expires_at INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(kind,reference));
                CREATE INDEX IF NOT EXISTS grants_account ON access_grants(account,expires_at);
                CREATE TABLE IF NOT EXISTS beta_codes(
                    digest TEXT PRIMARY KEY, expires_at INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
                    redeemed_by TEXT REFERENCES accounts(id));
                CREATE TABLE IF NOT EXISTS beta_attempts(identity TEXT NOT NULL, attempted_at INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS attempts_time ON beta_attempts(attempted_at);
            ''')
            db.execute('INSERT OR IGNORE INTO policy VALUES(1,?)', (policy,))
            if db.execute('SELECT body FROM policy WHERE id=1').fetchone()[0] != policy:
                raise ValueError('Shared-service identity policy changed; explicit migration required')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def valid_subject(subject):
        return (isinstance(subject, str) and 1 <= len(subject) <= 256
                and all(33 <= ord(c) <= 126 for c in subject))

    def _account(self, db, subject):
        row = db.execute('SELECT id,active FROM accounts WHERE issuer=? AND subject=?', (self.auth.issuer, subject)).fetchone()
        if row:
            if not row['active']:
                reject(403)
            return row['id']
        identifier = str(uuid4())
        db.execute('INSERT INTO accounts VALUES(?,?,?,1)', (identifier, self.auth.issuer, subject))
        return identifier

    @staticmethod
    def _entitled(db, account):
        row = db.execute('SELECT max(expires_at) FROM access_grants WHERE account=? AND revoked=0 AND expires_at>?',
                         (account, int(time.time()))).fetchone()
        return row[0]

    def admit(self, subject, *, expires_at):
        """Administrator action only; an arbitrary successful login cannot enroll."""
        if not self.valid_subject(subject):
            raise ValueError('A valid private provider subject is required')
        if type(expires_at) is not int or not int(time.time()) < expires_at <= int(time.time()) + 90 * 86400:
            raise ValueError('Temporary administrative access needs a future expiry within 90 days')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            identifier = self._account(db, subject)
            db.execute("INSERT INTO access_grants VALUES(?,'admin',?,?,0) ON CONFLICT(kind,reference) DO UPDATE SET expires_at=excluded.expires_at,revoked=0",
                       (identifier, identifier, expires_at))
            return identifier

    def issue_code(self, expires_at):
        if type(expires_at) is not int or not int(time.time()) < expires_at <= int(time.time()) + 90 * 86400:
            raise ValueError('Beta access needs a future expiry within 90 days')
        code = 'SAIPH-' + secrets.token_urlsafe(24)
        digest = hashlib.sha256(code.encode()).hexdigest()
        with self.connect() as db:
            db.execute('INSERT INTO beta_codes(digest,expires_at) VALUES(?,?)', (digest, expires_at))
        return code

    def revoke_code(self, digest):
        if not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest):
            raise ValueError('Use the code digest, never the code on the command line')
        with self.connect() as db:
            if db.execute('UPDATE beta_codes SET revoked=1 WHERE digest=?', (digest,)).rowcount != 1:
                raise ValueError('Unknown code digest')
            db.execute("UPDATE access_grants SET revoked=1 WHERE kind='beta' AND reference=?", (digest,))

    def redeem(self, identity, code):
        if identity.get('issuer') != self.auth.issuer or not self.valid_subject(identity.get('subject')):
            reject(403)
        now = int(time.time())
        key = hashlib.sha256((identity['issuer'] + '\0' + identity['subject']).encode()).hexdigest()
        # Commit bounded attempt accounting even if the subsequent redemption fails.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM beta_attempts WHERE attempted_at<=?', (now - 900,))
            if db.execute('SELECT count(*) FROM beta_attempts WHERE identity=?', (key,)).fetchone()[0] >= 5:
                reject(429)
            busy = db.execute('SELECT count(*) FROM beta_attempts').fetchone()[0] >= 1000
            db.execute('INSERT INTO beta_attempts VALUES(?,?)', (key, now))
        # Codes carry 192 random bits, so the global limit only throttles failures:
        # other accounts' failed attempts must not lock out a holder of a valid code.
        failed = 429 if busy else 403
        if not isinstance(code, str) or not re.fullmatch(r'SAIPH-[A-Za-z0-9_-]{32}', code):
            reject(failed)
        digest = hashlib.sha256(code.encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM beta_codes WHERE digest=? AND revoked=0 AND expires_at>?', (digest, now)).fetchone()
            if row is None:
                reject(failed)
            # Account creation, single-use consumption and entitlement are one transaction.
            identifier = self._account(db, identity['subject'])
            if row['redeemed_by'] is not None and row['redeemed_by'] != identifier:
                reject(failed)
            db.execute('UPDATE beta_codes SET redeemed_by=? WHERE digest=?', (identifier, digest))
            db.execute("INSERT OR IGNORE INTO access_grants VALUES(?,'beta',?,?,0)", (identifier, digest, row['expires_at']))
            return {'entitled': True, 'until': row['expires_at']}

    def status(self, identity):
        with self.connect() as db:
            row = db.execute('SELECT id FROM accounts WHERE issuer=? AND subject=? AND active=1',
                             (identity['issuer'], identity['subject'])).fetchone()
            until = self._entitled(db, row['id']) if row else None
            return {'entitled': until is not None, 'until': until}

    def set_active(self, identifier, active):
        if type(active) is not bool:
            raise ValueError('Account status must be explicit')
        with self.connect() as db:
            if db.execute('UPDATE accounts SET active=? WHERE id=?', (int(active), identifier)).rowcount != 1:
                raise ValueError('Unknown account')

    def principal(self, identity):
        with self.connect() as db:
            row = db.execute('SELECT * FROM accounts WHERE issuer=? AND subject=? AND active=1',
                             (identity['issuer'], identity['subject'])).fetchone()
            if row is None or self._entitled(db, row['id']) is None:
                reject(403)
            return dict(row)

    def device(self, identifier):
        if not isinstance(identifier, str) or not DEVICE.fullmatch(identifier):
            reject(401)
        with self.connect() as db:
            row = db.execute('SELECT a.* FROM devices d JOIN accounts a ON a.id=d.account WHERE d.id=? AND a.active=1', (identifier,)).fetchone()
            if row is None or self._entitled(db, row['id']) is None:
                reject(403)
            return dict(row)

    def claim_devices(self, account, devices):
        if any(not isinstance(d, str) or not DEVICE.fullmatch(d) for d in devices):
            reject()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM accounts WHERE id=? AND active=1', (account,)).fetchone() is None:
                reject(403)
            if self._entitled(db, account) is None:
                reject(403)
            for device in devices:
                previous = db.execute('SELECT account FROM devices WHERE id=?', (device,)).fetchone()
                if previous and previous['account'] != account:
                    reject(409)
                db.execute('INSERT OR IGNORE INTO devices VALUES(?,?)', (device, account))

    def config(self, account):
        identifier = account['id']
        if str(UUID(identifier)) != identifier:
            raise ValueError('Invalid stored workspace identity')
        return HostedConfig(identifier, self.directory / 'workspaces' / identifier / 'orion-hosted.sqlite3',
                            Auth0Config(self.auth.issuer, self.auth.audience, self.auth.client_ids, account['subject']))


class BoundTokens:
    def __init__(self, tokens, registry, account):
        self.tokens, self.registry, self.account = tokens, registry, account

    def principal(self, request):
        identity = self.tokens.principal(request)
        if self.registry.principal(identity)['id'] != self.account:
            reject(403)
        return identity


class SharedHosted:
    """One API origin; bounded process cache, durable routing across restarts."""
    def __init__(self, registry: AccountRegistry, *, tokens=None, web_tokens=None, downloads=None, cache_size=64):
        if type(cache_size) is not int or not 1 <= cache_size <= 256:
            raise ValueError('Bound the workspace application cache')
        self.registry = registry
        self.tokens = tokens or AccessTokens(registry.auth)
        self.web_tokens = web_tokens
        self.downloads = downloads
        self.cache_size = cache_size
        self.apps = OrderedDict()
        self.lock = threading.Lock()
        self.maintenance = WorkspaceCleanup(registry)

    def application(self, account):
        with self.lock:
            identifier = account['id']
            app = self.apps.pop(identifier, None)
            if app is None:
                app = create_app(self.registry.config(account), device_registry=self.registry,
                                 tokens=BoundTokens(self.tokens, self.registry, identifier))
            self.apps[identifier] = app
            while len(self.apps) > self.cache_size:
                self.apps.popitem(last=False)
            return app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            async with maintenance_context(self.maintenance):
                while True:
                    message = await receive()
                    if message['type'] == 'lifespan.startup':
                        await send({'type': 'lifespan.startup.complete'})
                    elif message['type'] == 'lifespan.shutdown':
                        break
            await send({'type': 'lifespan.shutdown.complete'})
            return
        if scope['type'] != 'http':
            return
        request = Request(scope, receive=receive)
        try:
            path = scope['path']
            if path == '/v1/health' and request.method == 'GET':
                response = JSONResponse({'ok': True, 'service': 'saiph-hosted-shared'})
            elif path.startswith('/v1/download/') and request.method in ('GET', 'HEAD'):
                if (self.downloads is None or request.headers.get('origin') or request.cookies
                        or request.headers.get('authorization') or request.url.query):
                    reject(404)
                response = await asyncio.to_thread(self.downloads.response, path.removeprefix('/v1/download/'),
                                                  method=request.method, range_header=request.headers.get('range'))
            elif path in ('/v1/beta/redeem', '/v1/beta/access', '/v1/beta/download'):
                if self.web_tokens is None:
                    reject(404)
                if request.headers.get('origin') or request.cookies or request.url.query:
                    reject(403)
                identity = await asyncio.to_thread(self.web_tokens.principal, request)
                if path.endswith('/access') and request.method == 'GET':
                    result = await asyncio.to_thread(self.registry.status, identity)
                elif path.endswith('/redeem') and request.method == 'POST':
                    _, value = await body(request)
                    exact(value, ('code',))
                    result = await asyncio.to_thread(self.registry.redeem, identity, value['code'])
                elif path.endswith('/download') and request.method == 'POST' and self.downloads is not None:
                    _, value = await body(request)
                    exact(value, ('artifact',))
                    result = await asyncio.to_thread(self.downloads.issue, identity, value['artifact'])
                else:
                    reject(405)
                response = JSONResponse(result)
            elif path == '/v1/account' or path.startswith('/v1/devices/'):
                if request.headers.get('origin') or request.cookies:
                    reject(403)
                identity = await asyncio.to_thread(self.tokens.principal, request)
                account = await asyncio.to_thread(self.registry.principal, identity)
                app = await asyncio.to_thread(self.application, account)
                return await app(scope, receive, send)
            elif path.startswith('/v1/sealed/'):
                if (request.headers.get('origin') or request.cookies or request.headers.get('authorization')
                        or len(request.headers.getlist('x-orion-device-id')) != 1):
                    reject(403)
                account = await asyncio.to_thread(self.registry.device, request.headers.get('x-orion-device-id'))
                app = await asyncio.to_thread(self.application, account)
                return await app(scope, receive, send)
            else:
                reject(404)
        except HTTPException as error:
            response = JSONResponse({'detail': error.detail}, status_code=error.status_code, headers=error.headers)
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
        await response(scope, receive, send)
