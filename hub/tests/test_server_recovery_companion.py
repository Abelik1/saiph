# SPDX-License-Identifier: AGPL-3.0-or-later
"""Installer recovery includes the separately locked Cloud ownership registry."""
import sqlite3

from orion_hub import server_install


def database(path, marker):
    with sqlite3.connect(path) as connection:
        connection.execute('create table marker(value text)')
        connection.execute('insert into marker values(?)', (marker,))
    path.chmod(0o600)


def test_install_upgrade_recovery_keeps_cloud_registry_with_hub(tmp_path):
    database(tmp_path / 'orion-hub.sqlite3', 'synthetic Hub')
    database(tmp_path / 'cloud-provisioning.sqlite3', 'synthetic Cloud')
    target = server_install.backup_state(tmp_path)
    for path, marker in [(target, 'synthetic Hub'), (target.with_suffix('.cloud'), 'synthetic Cloud')]:
        with sqlite3.connect(path) as connection:
            assert connection.execute('pragma quick_check').fetchone() == ('ok',)
            assert connection.execute('select value from marker').fetchone() == (marker,)


def test_install_upgrade_recovery_does_not_create_optional_cloud_registry(tmp_path):
    database(tmp_path / 'orion-hub.sqlite3', 'synthetic Hub')
    target = server_install.backup_state(tmp_path)
    assert target.is_file() and not target.with_suffix('.cloud').exists()
    assert not (tmp_path / 'cloud-provisioning.sqlite3').exists()


def test_daily_private_snapshot_unit_uses_shared_cli_and_no_network():
    unit = server_install.backup_unit_text()
    assert 'python -m orion_hub.cli backup --keep 14' in unit
    assert 'User=orion-server' in unit and 'UMask=0077' in unit
    assert 'RestrictAddressFamilies=AF_UNIX' in unit
    timer = server_install.backup_timer_text()
    assert 'Persistent=true' in timer and 'OnCalendar=*-*-* 04:00:00' in timer
    assert 'Unit=orion-server-backup.service' in timer
    assert set(server_install.managed_paths()) == {'unit','wrapper','backup_unit','backup_timer'}
