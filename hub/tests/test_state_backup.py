# SPDX-License-Identifier: AGPL-3.0-or-later
import os
from pathlib import Path
import sqlite3
from contextlib import closing

import pytest

from orion_hub.cli import backup_database
from orion_hub.state_backup import snapshot_pair


def database(path, value):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE state (value TEXT)')
        connection.execute('INSERT INTO state VALUES (?)', (value,))
    path.chmod(0o600)


def read(path):
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)) as connection:
        assert connection.execute('PRAGMA quick_check').fetchone() == ('ok',)
        assert connection.execute('PRAGMA journal_mode').fetchone() == ('delete',)
        return connection.execute('SELECT value FROM state').fetchone()[0]


def test_cloud_registry_is_private_verified_companion_and_retained_together(tmp_path):
    database(tmp_path/'orion-hub.sqlite3', 'paired')
    database(tmp_path/'cloud-provisioning.sqlite3', 'PRIVATE_RECOVERY_RECORD')
    first = backup_database(tmp_path, 1)
    assert read(first) == 'paired'
    assert read(first.with_suffix('.cloud')) == 'PRIVATE_RECOVERY_RECORD'
    if os.name != 'nt':
        assert first.stat().st_mode & 0o077 == 0
        assert first.with_suffix('.cloud').stat().st_mode & 0o077 == 0
    second = backup_database(tmp_path, 1)
    assert second != first
    assert not first.exists() and not first.with_suffix('.cloud').exists()
    assert second.with_suffix('.cloud').exists()


def test_missing_source_does_not_create_empty_database_or_keep_partial_pair(tmp_path):
    database(tmp_path/'cloud-provisioning.sqlite3', 'private')
    target = tmp_path/'snapshot.sqlite3'
    with pytest.raises(OSError): snapshot_pair(tmp_path, target)
    assert not (tmp_path/'orion-hub.sqlite3').exists()
    assert not target.exists() and not target.with_suffix('.cloud').exists()


def test_destination_collision_preserves_existing_copy(tmp_path):
    database(tmp_path/'orion-hub.sqlite3', 'paired')
    database(tmp_path/'cloud-provisioning.sqlite3', 'private')
    target=tmp_path/'snapshot.sqlite3';target.write_bytes(b'existing')
    with pytest.raises(FileExistsError):snapshot_pair(tmp_path,target)
    assert target.read_bytes()==b'existing'
    assert not target.with_suffix('.cloud').exists()


@pytest.mark.skipif(os.name=='nt',reason='Unix symlink and private-mode boundary')
def test_redirected_or_public_registry_is_refused_before_backup(tmp_path):
    database(tmp_path/'orion-hub.sqlite3','paired')
    source=tmp_path/'other.sqlite3';database(source,'private')
    cloud=tmp_path/'cloud-provisioning.sqlite3';cloud.symlink_to(source)
    with pytest.raises(ValueError):backup_database(tmp_path,1)
    cloud.unlink();cloud.write_bytes(source.read_bytes());cloud.chmod(0o644)
    with pytest.raises(ValueError):backup_database(tmp_path,1)
    assert not list((tmp_path/'backups').glob('*.sqlite3'))
