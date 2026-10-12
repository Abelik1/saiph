# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bounded expiry cleanup independent of authenticated account traffic.

Deletes logical rows, not SQLite free pages or backups. Never creates a missing
workspace, changes device trust, or requires an account to remain entitled.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, closing
import logging
from pathlib import Path
import sqlite3
import time

LOG = logging.getLogger(__name__)


def cleanup_database(config, *, now=None, batch_size=256):
    if type(batch_size) is not int or not 1 <= batch_size <= 1024:
        raise ValueError('Bound the expiry cleanup batch')
    path = Path(config.database)
    if not path.is_absolute() or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise ValueError('Invalid cleanup workspace')
    if not path.is_file():
        return 0  # Uninitialized accounts must not gain a workspace from cleanup.
    now = int(time.time()) if now is None else now
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=1)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        expected = (config.deployment_id, config.auth.issuer, config.auth.owner_subject, config.auth.audience)
        if db.execute('SELECT deployment_id,issuer,subject,audience FROM deployment WHERE id=1').fetchone() != expected:
            raise ValueError('Cleanup ownership mismatch')
        db.execute('DELETE FROM sealed_events WHERE id IN (SELECT id FROM sealed_events WHERE expires_at<=? ORDER BY expires_at LIMIT ?)',
                   (now, batch_size))
        db.execute('DELETE FROM candidates WHERE id IN (SELECT id FROM candidates WHERE expires_at<=? ORDER BY expires_at LIMIT ?)',
                   (now, batch_size))
        db.execute('DELETE FROM nonces WHERE rowid IN (SELECT rowid FROM nonces WHERE seen_at<=? ORDER BY seen_at LIMIT ?)',
                   (now - 120, batch_size))
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if {'hosted_blobs', 'hosted_blob_chunks'} <= tables:
            expired = [row[0] for row in db.execute('SELECT id FROM hosted_blobs WHERE expires_at<=? ORDER BY expires_at LIMIT ?',
                                                   (now, batch_size))]
            db.executemany('DELETE FROM hosted_blob_chunks WHERE blob=?', [(value,) for value in expired])
            db.executemany('DELETE FROM hosted_blobs WHERE id=?', [(value,) for value in expired])
        return db.total_changes


class WorkspaceCleanup:
    """Keyset pages visit active, idle and suspended accounts without caching apps."""
    def __init__(self, registry, *, workspace_limit=32, batch_size=256):
        if type(workspace_limit) is not int or not 1 <= workspace_limit <= 256:
            raise ValueError('Bound the workspace cleanup pass')
        if type(batch_size) is not int or not 1 <= batch_size <= 1024:
            raise ValueError('Bound the expiry cleanup batch')
        self.registry, self.workspace_limit, self.batch_size = registry, workspace_limit, batch_size
        self.after = ''

    def __call__(self):
        with self.registry.connect() as db:
            rows = db.execute('SELECT id,issuer,subject FROM accounts WHERE id>? ORDER BY id LIMIT ?',
                              (self.after, self.workspace_limit)).fetchall()
            if not rows and self.after:
                self.after = ''
                rows = db.execute('SELECT id,issuer,subject FROM accounts ORDER BY id LIMIT ?',
                                  (self.workspace_limit,)).fetchall()
        deleted, errors = 0, 0
        for row in rows:
            self.after = row['id']
            try:
                deleted += cleanup_database(self.registry.config(dict(row)), batch_size=self.batch_size)
            except (ValueError, OSError, sqlite3.Error):
                errors += 1  # Do not log subjects, paths, database values or bodies.
        if errors:
            LOG.warning('Hosted expiry cleanup could not process %d workspaces', errors)
        return {'workspaces': len(rows), 'deleted': deleted, 'errors': errors}


@asynccontextmanager
async def maintenance_context(cleanup, *, interval=60):
    stop = asyncio.Event()

    async def run():
        while not stop.is_set():
            try:
                await asyncio.to_thread(cleanup)
            except Exception:
                LOG.warning('Hosted expiry cleanup pass failed')
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    task = asyncio.create_task(run())
    try:
        yield
    finally:
        stop.set()
        await task  # Finish the bounded pass before reporting shutdown complete.


def app_lifespan(cleanup):
    @asynccontextmanager
    async def lifespan(app):
        async with maintenance_context(cleanup):
            yield
    return lifespan
