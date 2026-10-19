# SPDX-License-Identifier: AGPL-3.0-or-later
import sqlite3

import pytest

from orion_mini.storage import Store


def test_completed_store_transactions_release_connections_without_gc(tmp_path):
    store = Store(tmp_path)
    retained = []
    for index in range(20):
        with store.connect() as connection:
            connection.execute('INSERT INTO records VALUES(?,?,?)', ('test', str(index), '{}'))
            retained.append(connection)
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            connection.execute('SELECT 1')
    assert len(store.all('test')) == 20


def test_failed_store_transaction_rolls_back_and_releases_connection(tmp_path):
    store = Store(tmp_path)
    with pytest.raises(RuntimeError, match='synthetic failure'):
        with store.connect() as connection:
            connection.execute('INSERT INTO records VALUES(?,?,?)', ('test', 'rollback', '{}'))
            raise RuntimeError('synthetic failure')
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        connection.execute('SELECT 1')
    assert store.all('test') == []
