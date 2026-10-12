#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Consistent Hub state and private metadata, encrypted with standard restic."""
from __future__ import annotations
import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time

class BackupError(Exception):
    """Fixed errors only: subprocess output, secrets and source paths stay private."""

def private_directory(path):
    path=Path(path);path.mkdir(parents=True,mode=0o700,exist_ok=True)
    if path.is_symlink():raise BackupError('Backup directory is not private.')
    if os.name!='nt':path.chmod(0o700)
    return path
def private_json(path,value):
    path=Path(path);temporary=path.with_name(path.name+'.tmp')
    with temporary.open('w',encoding='utf-8') as output:
        if os.name!='nt':os.fchmod(output.fileno(),0o600)
        json.dump(value,output,separators=(',',':'));output.write('\n');output.flush();os.fsync(output.fileno())
    temporary.replace(path)
def read_json(path):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):raise BackupError('Private backup configuration is unavailable.') from None
def regular(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise BackupError('A required private backup source is unavailable.')
    return path
def source_uri(path):return Path(path).resolve().as_uri()+'?mode=rw'
def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda:source.read(65536),b''):result.update(chunk)
    return result.hexdigest()
def sqlite_snapshot(source,target):
    with closing(sqlite3.connect(source_uri(source),uri=True,timeout=15)) as reader,closing(sqlite3.connect(target)) as copy:
        reader.backup(copy);copy.execute('PRAGMA journal_mode=DELETE')
        if copy.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise BackupError('Consistent database snapshot failed verification.')
    if os.name!='nt':Path(target).chmod(0o600)

@contextmanager
def cloud_guard(database):
    """Freeze the optional independent registry before taking any Hub lock."""
    cloud=Path(database).parent/'cloud-provisioning.sqlite3'
    if not cloud.exists() and not cloud.is_symlink():
        yield None
        return
    regular(cloud)
    if any(p.is_symlink() for p in cloud.parents) or os.name!='nt' and (cloud.stat().st_mode & 0o077 or os.geteuid()!=0 and cloud.stat().st_uid not in {0,os.geteuid()}):
        raise BackupError('Private Cloud registry is unavailable.')
    with closing(sqlite3.connect(source_uri(cloud),uri=True,timeout=20)) as connection:
        connection.execute('BEGIN IMMEDIATE')
        try:yield cloud
        finally:connection.rollback()

def stage_snapshot(database,staging,metadata,*,credentials=None,required=()):
    """Freeze Hub writes while snapshotting state and the revocation registry.

    Phone registry changes hold BEGIN IMMEDIATE on this same Hub database. A
    separate connection performs SQLite's online backup, avoiding copying WAL
    files and avoiding calling backup on the write-lock connection itself.
    """
    database=regular(database);staging=private_directory(staging)
    files={};credential_root=Path(credentials) if credentials else None
    with cloud_guard(database) as cloud, closing(sqlite3.connect(source_uri(database),uri=True,timeout=20)) as guard:
        guard.execute('BEGIN IMMEDIATE')
        try:
            if cloud is not None:
                target=staging/'cloud-provisioning.snapshot.sqlite3';sqlite_snapshot(cloud,target)
                files[target.name]=digest(target)
            target=staging/'orion-hub.snapshot.sqlite3';sqlite_snapshot(database,target)
            files[target.name]=digest(target)
            for label,source in metadata.items():
                if not re.fullmatch(r'[a-z][a-z0-9_.-]{0,79}',label) or label in {'manifest.json','orion-hub.snapshot.sqlite3','cloud-provisioning.snapshot.sqlite3'}:raise BackupError('Invalid private metadata label.')
                resolved=credential_root/label if credential_root and (credential_root/label).is_file() else Path(source)
                # Optional future phone registry is absent until bootstrapped.
                if not resolved.exists():
                    if label in required:raise BackupError('A required private backup source is unavailable.')
                    continue
                resolved=regular(resolved)
                if resolved.stat().st_size>16*1024**2:raise BackupError('Private metadata exceeded its size limit.')
                destination=staging/label
                with resolved.open('rb') as incoming,destination.open('xb') as outgoing:
                    if os.name!='nt':os.fchmod(outgoing.fileno(),0o600)
                    shutil.copyfileobj(incoming,outgoing,65536)
                files[label]=digest(destination)
        finally:guard.rollback()
    private_json(staging/'manifest.json',{'schema':'orion.hub.backup/v1','created_at':datetime.now(timezone.utc).isoformat(),'files':files})
    return files

def call(executable,arguments,environment,*,run=subprocess.run,timeout=7200):
    result=run([str(executable),'--quiet','--no-cache',*arguments],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=environment,timeout=timeout)
    if result.returncode:raise BackupError('Encrypted backup operation did not complete.')
    return result.stdout
def environment(target):
    env={key:value for key,value in os.environ.items() if not key.startswith('RESTIC_')}
    credentials=Path(os.environ['CREDENTIALS_DIRECTORY']) if os.environ.get('CREDENTIALS_DIRECTORY') else None
    if target.get('environment_file'):
        provider=credentials/'offsite.environment' if target['name']=='offsite' and credentials and (credentials/'offsite.environment').is_file() else target['environment_file']
        values=read_json(regular(provider))
        if not isinstance(values,dict) or not all(isinstance(k,str) and re.fullmatch('[A-Z][A-Z0-9_]*',k) and isinstance(v,str) for k,v in values.items()):raise BackupError('Invalid private provider credentials.')
        # Provider configuration cannot replace executable search paths or restic
        # password/repository inputs, which come from separately reviewed files.
        if any(k.startswith('RESTIC_') or k in {'PATH','LD_PRELOAD','PYTHONPATH'} for k in values):raise BackupError('Invalid private provider credentials.')
        env.update(values)
    password=regular(credentials/'offsite.password' if target['name']=='offsite' and credentials and (credentials/'offsite.password').is_file() else target['password_file'])
    if os.name!='nt' and password.stat().st_mode & 0o077:raise BackupError('Backup password permissions are too broad.')
    env.update(RESTIC_PASSWORD_FILE=str(password),RESTIC_REPOSITORY=target['repository'])
    return env
def local_repository(target):
    if target['name']!='pi':return None
    path=Path(target['repository'])
    if not path.is_absolute():raise BackupError('The Pi backup repository must be a private local directory.')
    return path
def gate_storage(config,staging_parent,*,free=None):
    database=regular(config['database']);size=database.stat().st_size
    for source in config.get('metadata',{}).values():
        source=Path(source)
        if source.is_file():size+=source.stat().st_size
    required=max(512*1024**2,size*3+128*1024**2)
    available=shutil.disk_usage(staging_parent).free if free is None else free
    if available<required:raise BackupError('Backup needs more free storage. Existing snapshots were retained.')
    for target in config['targets']:
        repo=local_repository(target)
        if repo:
            existing=repo
            while not existing.exists():existing=existing.parent
            if shutil.disk_usage(existing).free<required:raise BackupError('Backup repository needs more free storage. Existing snapshots were retained.')
    return required
def verify_restore(executable,target,restore_root,*,run=subprocess.run):
    restore_root=private_directory(restore_root)
    env=environment(target)
    call(executable,['restore','latest','--tag','orion-hub','--host','pi','--target',str(restore_root)],env,run=run)
    manifests=list(restore_root.rglob('manifest.json'))
    if len(manifests)!=1:raise BackupError('Isolated restore verification failed.')
    manifest=read_json(manifests[0]);folder=manifests[0].parent
    if manifest.get('schema')!='orion.hub.backup/v1':raise BackupError('Isolated restore verification failed.')
    for label,expected in manifest['files'].items():
        if not re.fullmatch(r'[a-z][a-z0-9_.-]{0,79}',label) or digest(folder/label)!=expected:raise BackupError('Isolated restore integrity check failed.')
    for label in ('orion-hub.snapshot.sqlite3','cloud-provisioning.snapshot.sqlite3'):
        if label not in manifest['files']:continue
        with closing(sqlite3.connect((folder/label).as_uri()+'?mode=ro',uri=True)) as restored:
            if restored.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise BackupError('Restored SQLite database failed verification.')
    return {'verified':True,'files':len(manifest['files']),'sqlite_quick_check':'ok'}

def object_files(directory,pattern=r'[0-9a-f]{64}'):
    """Only committed standard-restic object names; never recurse implicitly."""
    directory=Path(directory)
    if directory.is_symlink():raise BackupError('Phone backup storage could not be verified.')
    if not directory.exists():return []
    if not directory.is_dir():raise BackupError('Phone backup storage could not be verified.')
    return sorted(regular(item) for item in directory.iterdir() if re.fullmatch(pattern,item.name))

def android_repository_files(directory):
    """Freeze snapshots before collecting their immutable append-only objects.

    A committed snapshot references objects uploaded before it. Capture every
    repository's snapshots first, then keys/indexes, then packs. The phone
    server forbids replacing/deleting these objects; later snapshots are never
    selected. Capturing indexes before packs likewise avoids an index whose
    new packs were missed. Locks and temporary names are never copied.
    """
    directory=Path(directory)
    if directory.is_symlink():raise BackupError('Phone backup storage could not be verified.')
    if not directory.exists():return []
    if not directory.is_dir():raise BackupError('Phone backup storage could not be verified.')
    repositories=[];selected=[]
    for repository in sorted(directory.iterdir()):
        if not re.fullmatch(r'orion-[0-9a-f]{32}',repository.name):continue
        if repository.is_symlink() or not repository.is_dir():raise BackupError('Phone backup storage could not be verified.')
        snapshots=object_files(repository/'snapshots')
        if not (repository/'config').exists() and not snapshots:continue # Initial upload is not committed yet.
        repositories.append(repository)
        selected.extend(snapshots)
    for repository in repositories:
        selected.append(regular(repository/'config'))
        selected.extend(object_files(repository/'keys'))
        selected.extend(object_files(repository/'index'))
    for repository in repositories:
        data=repository/'data'
        if data.is_symlink() or not data.is_dir():raise BackupError('Phone backup storage could not be verified.')
        for shard in sorted(data.iterdir()):
            if not re.fullmatch(r'[0-9a-f]{2}',shard.name):continue
            selected.extend(object_files(shard,re.escape(shard.name)+r'[0-9a-f]{62}'))
    return selected

def explicit_file_list(root,sources):
    descriptor,name=tempfile.mkstemp(prefix='offsite-files-',dir=root)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8',newline='\n') as output:
            if os.name!='nt':os.fchmod(output.fileno(),0o600)
            for source in sources:
                value=str(regular(source).absolute())
                if any(c in value for c in '\r\n\0'):raise BackupError('Private backup file selection could not be verified.')
                output.write(value+'\n')
            output.flush();os.fsync(output.fileno())
        return Path(name)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise

def once(config,root,*,run=subprocess.run,verify=False):
    root=private_directory(root);gate_storage(config,root)
    if not config.get('targets') or config['targets'][0]['name']!='pi':raise BackupError('Configure the primary encrypted Pi repository first.')
    status={'started_at':time.time(),'targets':{},'offsite_configured':any(t['name']=='offsite' for t in config['targets'])}
    stage=Path(tempfile.mkdtemp(prefix='hub-snapshot-',dir=root));stage.chmod(0o700)
    try:
        files=stage_snapshot(config['database'],stage,config.get('metadata',{}),credentials=os.environ.get('CREDENTIALS_DIRECTORY'),required=config.get('required_metadata',[]))
        for target in config['targets']:
            name=target['name']
            if name not in {'pi','offsite'}:raise BackupError('Invalid encrypted backup target.')
            record={'ok':False};status['targets'][name]=record
            try:
                env=environment(target);repository=local_repository(target)
                if repository and not (repository/'config').is_file():
                    if repository.exists() and any(repository.iterdir()):raise BackupError('Existing repository contents were retained.')
                    private_directory(repository);call(config['executable'],['init'],env,run=run)
                call(config['executable'],['cat','config'],env,run=run,timeout=60)
                if name=='offsite' and target.get('include_android_repositories'):
                    android=Path(config.get('android_repositories','/srv/orion-phone-backups'))
                    sources=sorted(stage.iterdir())+android_repository_files(android)
                    selection=explicit_file_list(root,sources)
                    try:call(config['executable'],['backup','--tag','orion-hub','--host','pi','--files-from-verbatim',str(selection)],env,run=run)
                    finally:selection.unlink(missing_ok=True)
                else:call(config['executable'],['backup','--tag','orion-hub','--host','pi','--',str(stage)],env,run=run)
                record.update(ok=True,completed_at=time.time(),files=len(files))
                if verify:
                    restore=Path(tempfile.mkdtemp(prefix='hub-restore-',dir=root))
                    try:record['restore']=verify_restore(config['executable'],target,restore,run=run)
                    finally:shutil.rmtree(restore)
            except (BackupError,OSError,subprocess.SubprocessError):record.update(ok=False,error='Encrypted backup could not complete. Existing snapshots were retained.')
        private_json(root/'status.json',status)
        if not all(t['ok'] for t in status['targets'].values()):raise BackupError('One encrypted backup target needs attention; successful targets were retained.')
        return status
    finally:shutil.rmtree(stage)
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('/var/lib/orion-hub/encrypted-backup'))
    parser.add_argument('--verify-restore',action='store_true')
    args=parser.parse_args();root=private_directory(args.root)
    import fcntl
    with (root/'run.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise BackupError('An encrypted backup is already running.') from None
        config=read_json(root/'config.json')
        once(config,root,verify=args.verify_restore or config.get('verify_restore',False))
    print('Encrypted Hub backup completed.' if not args.verify_restore else 'Encrypted Hub backup and isolated SQLite restore verified.')
if __name__=='__main__':
    try:main()
    except (BackupError,OSError,ValueError,KeyError,sqlite3.Error,subprocess.SubprocessError):
        print('Encrypted Hub backup did not finish. Check private configuration and available storage. No personal data was logged.')
        raise SystemExit(1)
