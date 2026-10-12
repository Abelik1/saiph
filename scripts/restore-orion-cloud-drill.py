#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Restore cloud dumps/files into disposable, isolated Docker resources."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import time
from uuid import uuid4

spec = importlib.util.spec_from_file_location('orion_cloud_export', Path(__file__).with_name('backup-orion-cloud.py'))
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def run(args, *, input_file=None):
    result = subprocess.run(args, stdin=input_file or subprocess.DEVNULL, capture_output=True, timeout=180,
                            **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
    if result.returncode:
        raise backup.ExportError('The isolated cloud restore drill did not complete.')
    return result.stdout


def drill(root, restored):
    if not (restored / 'manifest.json').is_file():
        raise backup.ExportError('Restore an existing private cloud export first.')
    manifest = json.loads((restored / 'manifest.json').read_text())
    stacks = backup.discover(backup.check_root(root))
    saved = {entry['name']: entry for entry in manifest['stacks']}
    nonce = 'orion-drill-' + uuid4().hex[:12]
    network = nonce + '-network'
    resources = []
    volumes = []
    private_environment_files = []
    try:
        run(['docker', 'network', 'create', '--internal', '--label', 'orion.restore=' + nonce, network])
        for stack in stacks:
            record = saved[stack['name']]
            if record['image'] != stack['image']:
                raise backup.ExportError('Restore with the recorded cloud image versions.')
            db = json.loads(run(['docker', 'inspect', stack['database']]))[0]
            if record.get('database_image') and record['database_image'] != db['Image']:
                raise backup.ExportError('Restore with the recorded database image versions.')
            folder = restored / stack['name']
            with tarfile.open(folder / 'data.tar') as archive:
                expected = {}
                for item in archive.getmembers():
                    path = PurePosixPath(item.name)
                    if path.is_absolute() or '..' in path.parts or item.issym() or item.islnk():
                        raise backup.ExportError('Unexpected path in the private cloud file archive.')
                    if item.isfile():
                        digest = hashlib.sha256()
                        with archive.extractfile(item) as source:
                            while chunk := source.read(1024 * 1024):
                                digest.update(chunk)
                        expected[str(path)] = digest.hexdigest()
            data_volume = nonce + '-' + stack['name'] + '-files'
            db_volume = nonce + '-' + stack['name'] + '-db'
            for volume in (data_volume, db_volume):
                run(['docker', 'volume', 'create', '--label', 'orion.restore=' + nonce, volume])
                volumes.append(volume)
            # Only newly created labeled restore volumes are writable. Live
            # service volumes are never mounted by this drill.
            helper = ['docker', 'run', '-i', '--rm', '--pull=never', '--network=none', '--read-only',
                      '--cap-drop=ALL', '--cap-add=CHOWN', '--cap-add=FOWNER', '--cap-add=DAC_OVERRIDE',
                      '--security-opt=no-new-privileges', '--mount',
                      'type=volume,source=' + data_volume + ',target=/orion-data',
                      '--entrypoint', '/bin/sh', stack['image']]
            with (folder / 'data.tar').open('rb') as source:
                run([*helper, '-c', 'exec tar -xf - -C /orion-data'], input_file=source)
            hashes = run([*helper, '-c', 'cd /orion-data; find . -type f -exec sha256sum {} \;']).decode().splitlines()
            actual = {}
            for line in hashes:
                digest, path = line.split('  ', 1)
                actual[str(PurePosixPath(path))] = digest
            if actual != expected:
                raise backup.ExportError('Restored cloud files did not match the archived hashes.')
            env_file = folder / 'restore-database.env'
            private_environment_files.append(env_file)
            env_file.write_text('\n'.join(db['Config']['Env']) + '\n')
            mount = next(entry for entry in db['Mounts'] if entry['Type'] == 'volume')
            database = run(['docker', 'create', '--pull=never', '--network', network, '--label',
                            'orion.restore=' + nonce, '--env-file', str(env_file), '--mount',
                            'type=volume,source=' + db_volume + ',target=' + mount['Destination'],
                            db['Image']]).decode().strip()
            resources.append(database)
            run(['docker', 'start', database])
            if stack['name'] == 'seafile':
                ready = ['docker', 'exec', database, 'sh', '-c',
                         'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mariadb -uroot --host=127.0.0.1 --batch --skip-column-names -e "SELECT 1"']
                restore = ['docker', 'exec', '-i', database, 'sh', '-c',
                           'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mariadb -uroot']
                count = ['docker', 'exec', database, 'sh', '-c',
                         'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mariadb -uroot --batch --skip-column-names -e "SELECT COUNT(*) FROM seafile_db.Repo"']
            else:
                ready = ['docker', 'exec', database, 'sh', '-c', 'exec pg_isready --host=127.0.0.1 --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"']
                restore = ['docker', 'exec', '-i', database, 'sh', '-c',
                           'exec psql -v ON_ERROR_STOP=1 --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"']
                count = ['docker', 'exec', database, 'sh', '-c',
                         'exec psql -t -A --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" -c "$1"',
                         'orion-drill', 'SELECT COUNT(*) FROM "user"']
            deadline = time.monotonic() + 90
            while True:
                try:
                    run(ready)
                    break
                except backup.ExportError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(1)
            with (folder / 'database.sql').open('rb') as source:
                run(restore, input_file=source)
            value = run(count).decode().strip()
            if not value.isdigit() or int(value) < 1:
                raise backup.ExportError('Restored database did not contain its owner/library records.')
            print(stack['name'] + ': database imported, owner/library records present, ' + str(len(expected)) + ' restored file hashes matched.')
        print('Isolated database and file restore drill passed. Phone photo/album acceptance remains pending.')
    finally:
        for file in private_environment_files:
            file.unlink(missing_ok=True)
        # Delete only resources created and labeled by this invocation. No live
        # server resources, backup snapshots or owner containers are removed.
        for ident in reversed(resources):
            state = json.loads(run(['docker', 'inspect', ident]))[0]
            if state['Config']['Labels'].get('orion.restore') == nonce:
                run(['docker', 'rm', '--force', ident])
        for volume in reversed(volumes):
            state = json.loads(run(['docker', 'volume', 'inspect', volume]))[0]
            if state['Labels'].get('orion.restore') == nonce:
                run(['docker', 'volume', 'rm', volume])
        state = json.loads(run(['docker', 'network', 'inspect', network]))[0]
        if state['Labels'].get('orion.restore') == nonce:
            run(['docker', 'network', 'rm', network])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(os.environ.get('LOCALAPPDATA', '/opt')) / 'OrionCloud')
    parser.add_argument('--restored', type=Path, required=True)
    args = parser.parse_args()
    try:
        drill(args.root, args.restored)
    except (backup.ExportError, OSError, ValueError, KeyError, subprocess.SubprocessError):
        print('Isolated cloud restore drill failed. No private tool output was logged.')
        raise SystemExit(1)
