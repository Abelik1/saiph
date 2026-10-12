# SPDX-License-Identifier: AGPL-3.0-or-later
"""Private, verified SQLite recovery copies, including Cloud account ownership."""
from contextlib import closing, contextmanager
import os
from pathlib import Path
import sqlite3
import stat


def regular(path):
    path = Path(path)
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError('Private recovery source is unavailable')
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('Private recovery source is unavailable')
    return path


@contextmanager
def cloud_guard(data):
    """Lock the separate registry before Hub locks, matching provisioning order.

    Never create a registry for an installation that has not enabled Cloud.
    The caller must snapshot this file with SQLite, never copy its live bytes.
    """
    path = Path(data) / 'cloud-provisioning.sqlite3'
    if not path.exists() and not path.is_symlink():
        yield None
        return
    regular(path)
    if os.name != 'nt' and (path.stat().st_mode & 0o077 or os.geteuid() != 0 and path.stat().st_uid not in {0, os.geteuid()}):
        raise ValueError('Private recovery source is unavailable')
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=rw', uri=True, timeout=20)
    try:
        connection.execute('BEGIN IMMEDIATE')
        yield path
    finally:
        connection.rollback()
        connection.close()


def snapshot(source, target):
    source = regular(source)
    target = Path(target)
    if any(item.is_symlink() for item in target.parents):
        raise ValueError('Private recovery destination is unavailable')
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True, timeout=20)) as original:
            with closing(sqlite3.connect(target)) as copy:
                original.backup(copy)
                copy.execute('PRAGMA journal_mode=DELETE')
                if copy.execute('PRAGMA quick_check').fetchone() != ('ok',):
                    raise ValueError('Private recovery copy failed verification')
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def snapshot_pair(data, target):
    """Keep Hub and Cloud snapshots together; failed pairs are never retained.

    Sequential copies are not a cross-database transaction. Registry mutation
    is frozen during both copies; restoration must reconcile grants against
    restored paired devices before reopening Cloud access.
    """
    target = Path(target)
    companion = target.with_suffix('.cloud')
    created = []
    try:
        with cloud_guard(data) as cloud:
            if cloud is not None:
                snapshot(cloud, companion)
                created.append(companion)
            snapshot(Path(data) / 'orion-hub.sqlite3', target)
            created.append(target)
        return target
    except BaseException:
        for item in created:
            item.unlink(missing_ok=True)
        raise
