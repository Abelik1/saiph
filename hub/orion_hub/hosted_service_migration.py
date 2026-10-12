# SPDX-License-Identifier: AGPL-3.0-or-later
"""One-time offline import of a protected owner snapshot into an empty registry."""
from contextlib import closing
from pathlib import Path
import os
import sqlite3
import time
from uuid import UUID

from .hosted import DEVICE, HostedConfig, Mailbox
from .hosted_auth import Auth0Config


def import_owner(registry, snapshot, expected_subject, *, expires_at):
    snapshot = Path(snapshot).absolute()
    if (not registry.valid_subject(expected_subject) or type(expires_at) is not int
            or not int(time.time()) < expires_at <= int(time.time()) + 90 * 86400
            or not snapshot.is_file() or snapshot.is_relative_to(registry.directory)
            or any(p.is_symlink() or p.is_junction() for p in (snapshot, *snapshot.parents))):
        raise ValueError('Use a protected snapshot, verified owner and bounded temporary access')
    with closing(sqlite3.connect(snapshot.as_uri() + '?mode=ro', uri=True)) as source:
        if source.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise ValueError('Snapshot integrity failed')
        deployment = source.execute('SELECT deployment_id,issuer,subject,audience FROM deployment WHERE id=1').fetchone()
        if not deployment or deployment[1:] != (registry.auth.issuer, expected_subject, registry.auth.audience):
            raise ValueError('Snapshot ownership does not match protected configuration')
        identifier = deployment[0]
        if str(UUID(identifier)) != identifier:
            raise ValueError('Invalid snapshot deployment')
        devices = [row[0] for row in source.execute('SELECT id FROM used_devices')]
        if any(not isinstance(device, str) or not DEVICE.fullmatch(device) for device in devices):
            raise ValueError('Invalid snapshot device directory')
        destination = registry.directory / 'workspaces' / identifier / 'orion-hosted.sqlite3'
        with registry.connect() as directory:
            directory.execute('BEGIN IMMEDIATE')
            if (directory.execute('SELECT 1 FROM accounts LIMIT 1').fetchone()
                    or directory.execute('SELECT 1 FROM devices LIMIT 1').fetchone()
                    or directory.execute('SELECT 1 FROM beta_codes LIMIT 1').fetchone()
                    or destination.parent.exists()):
                raise ValueError('Owner import requires empty, inactive shared state')
            destination.parent.mkdir(parents=True, mode=0o700)
            # Never overwrite or alter the original snapshot. If interrupted after
            # copying, the unregistered workspace fails closed and requires review.
            descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            with closing(sqlite3.connect(destination)) as target:
                source.backup(target)
                if target.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                    raise ValueError('Copied workspace integrity failed')
            Mailbox(HostedConfig(identifier, destination, Auth0Config(registry.auth.issuer,
                    registry.auth.audience, registry.auth.client_ids, expected_subject)))
            directory.execute('INSERT INTO accounts VALUES(?,?,?,1)', (identifier, registry.auth.issuer, expected_subject))
            directory.execute("INSERT INTO access_grants VALUES(?,'admin',?,?,0)", (identifier, identifier, expires_at))
            directory.executemany('INSERT INTO devices VALUES(?,?)', [(device, identifier) for device in devices])
    return {'imported': True, 'devices': len(devices)}
