# SPDX-License-Identifier: AGPL-3.0-or-later
import bz2
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

def load(name,file):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).resolve().parents[1]/'scripts'/file)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
backup=load('hub_private_backup','backup-orion-hub.py')
installer=load('hub_backup_installer','install-orion-hub-backup.py')

def database(path):
    with closing(sqlite3.connect(path)) as c, c:
        c.execute('PRAGMA journal_mode=WAL');c.execute('CREATE TABLE devices(id TEXT PRIMARY KEY)');c.execute('INSERT INTO devices VALUES("old")')
    return path
def config(tmp_path):
    db=database(tmp_path/'live.sqlite3');secret=tmp_path/'password';secret.write_text('PRIVATE_REPOSITORY_PASSWORD');secret.chmod(0o600)
    metadata=tmp_path/'metadata.json';metadata.write_text('PRIVATE_PHONE_CREDENTIAL')
    return {'database':str(db),'executable':'restic','metadata':{'phone-backup-credentials.json':str(metadata)},'targets':[{'name':'pi','repository':str(tmp_path/'repo'),'password_file':str(secret)}]}

def test_wal_snapshot_and_registry_share_one_short_write_lock(tmp_path,monkeypatch):
    db=database(tmp_path/'live.sqlite3');registry=tmp_path/'registry';registry.write_text('old');started=threading.Event();finished=threading.Event()
    def writer():
        started.set()
        with closing(sqlite3.connect(db,timeout=5)) as c, c:
            c.execute('BEGIN IMMEDIATE');c.execute('UPDATE devices SET id="new"');registry.write_text('new');c.commit()
        finished.set()
    original=backup.sqlite_snapshot;thread=None
    def snapshot(source,target):
        nonlocal thread
        thread=threading.Thread(target=writer);thread.start();assert started.wait(1);time.sleep(.05)
        assert not finished.is_set() # Hub writes pause only during the small export.
        original(source,target)
    monkeypatch.setattr(backup,'sqlite_snapshot',snapshot)
    stage=tmp_path/'stage';manifest=backup.stage_snapshot(db,stage,{'registry.json':str(registry)})
    thread.join(3);assert finished.is_set()
    with closing(sqlite3.connect(stage/'orion-hub.snapshot.sqlite3')) as c:
        assert c.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        assert c.execute('SELECT id FROM devices').fetchone()[0]=='old'
        assert c.execute('PRAGMA journal_mode').fetchone()[0]=='delete'
    assert (stage/'registry.json').read_text()=='old' and not list(stage.glob('*-wal'))
    assert manifest['registry.json']==hashlib.sha256(b'old').hexdigest()

def test_required_credentials_and_unsafe_labels_fail_without_path_disclosure(tmp_path):
    db=database(tmp_path/'live.sqlite3')
    with pytest.raises(backup.BackupError,match='required private backup source'):
        backup.stage_snapshot(db,tmp_path/'missing',{'hub.env':str(tmp_path/'PRIVATE_PATH')},required=['hub.env'])
    with pytest.raises(backup.BackupError,match='Invalid private metadata label'):
        backup.stage_snapshot(db,tmp_path/'unsafe',{'../secret':str(db)})
    secret=tmp_path/'secret';secret.write_text('PRIVATE_SECRET')
    credentials=tmp_path/'systemd';credentials.mkdir();(credentials/'hub.env').write_text('SYSTEMD_SECRET')
    backup.stage_snapshot(db,tmp_path/'safe',{'hub.env':str(secret)},credentials=credentials,required=['hub.env'])
    assert (tmp_path/'safe/hub.env').read_text()=='SYSTEMD_SECRET'


def test_cloud_registry_snapshot_blocks_mutation_and_is_restorable(tmp_path,monkeypatch):
    cfg=config(tmp_path)
    cloud=database(tmp_path/'cloud-provisioning.sqlite3');cloud.chmod(0o600)
    started=threading.Event();finished=threading.Event();thread=None
    original=backup.sqlite_snapshot
    def writer():
        started.set()
        with closing(sqlite3.connect(cloud,timeout=5)) as connection, connection:
            connection.execute('UPDATE devices SET id="changed"');connection.commit()
        finished.set()
    def snapshot(source,target):
        nonlocal thread
        if Path(source)==cloud:
            thread=threading.Thread(target=writer);thread.start();assert started.wait(1)
            time.sleep(.05);assert not finished.is_set()
        original(source,target)
    monkeypatch.setattr(backup,'sqlite_snapshot',snapshot)
    run=Restic(tmp_path);status=backup.once(cfg,tmp_path/'private',run=run,verify=True)
    thread.join(3);assert finished.is_set()
    assert status['targets']['pi']['restore']['files']==3
    with closing(sqlite3.connect(run.snapshot/'cloud-provisioning.snapshot.sqlite3')) as restored:
        assert restored.execute('SELECT id FROM devices').fetchone()==('old',)
        assert restored.execute('PRAGMA quick_check').fetchone()==('ok',)


@pytest.mark.parametrize('label',['manifest.json','orion-hub.snapshot.sqlite3','cloud-provisioning.snapshot.sqlite3'])
def test_metadata_cannot_replace_backup_manifest_or_database(tmp_path,label):
    db=database(tmp_path/'live.sqlite3')
    with pytest.raises(backup.BackupError,match='Invalid private metadata label'):
        backup.stage_snapshot(db,tmp_path/'stage',{label:str(db)})

def test_storage_gate_never_deletes_existing_repository(tmp_path):
    cfg=config(tmp_path);repository=Path(cfg['targets'][0]['repository']);repository.mkdir();(repository/'keep').write_text('existing')
    with pytest.raises(backup.BackupError,match='free storage'):backup.gate_storage(cfg,tmp_path,free=1)
    assert (repository/'keep').read_text()=='existing'

class Restic:
    def __init__(self,root):self.root=root;self.calls=[];self.snapshot=root/'captured';self.fail_backup=False;self.corrupt_restore=False;self.selected=[];self.fail_repository=None
    def __call__(self,args,**kwargs):
        self.calls.append((args,kwargs['env'].copy()))
        assert kwargs['stdout']==subprocess.PIPE and kwargs['stderr']==subprocess.PIPE
        operation=args[3]
        if operation=='init':
            repo=Path(kwargs['env']['RESTIC_REPOSITORY']);repo.mkdir(exist_ok=True);(repo/'config').write_text('encrypted')
        if operation=='backup':
            if '--files-from-verbatim' in args:
                selection=Path(args[args.index('--files-from-verbatim')+1])
                if os.name!='nt':assert selection.stat().st_mode & 0o077==0
                sources=[Path(line) for line in selection.read_text().splitlines()]
                self.selected.append(sources);stage=sources[0].parent
                assert all(source.is_file() and source.is_absolute() for source in sources)
            else:stage=Path(args[args.index('--')+1])
            if self.fail_backup or kwargs['env']['RESTIC_REPOSITORY']==self.fail_repository:return SimpleNamespace(returncode=1,stdout=b'PRIVATE_SMS',stderr=b'PRIVATE_SECRET_PATH')
            shutil.copytree(stage,self.snapshot,dirs_exist_ok=True)
            # The write lock has been released before slow repository I/O.
            with closing(sqlite3.connect(self.root/'live.sqlite3',timeout=.1)) as c:c.execute('BEGIN IMMEDIATE');c.rollback()
        if operation=='restore':
            target=Path(args[args.index('--target')+1:][0]);shutil.copytree(self.snapshot,target/'restored')
            if self.corrupt_restore:(target/'restored/phone-backup-credentials.json').write_text('CORRUPT')
        return SimpleNamespace(returncode=0,stdout=b'PRIVATE_RESTIC_OUTPUT',stderr=b'PRIVATE_ENV')

def test_encrypted_backup_isolated_restore_and_no_secret_status_or_output(tmp_path,capsys):
    cfg=config(tmp_path);run=Restic(tmp_path);status=backup.once(cfg,tmp_path/'private',run=run,verify=True)
    assert status['targets']['pi']['restore']=={'verified':True,'files':2,'sqlite_quick_check':'ok'}
    assert not status['offsite_configured']
    saved=(tmp_path/'private/status.json').read_text()
    assert 'PRIVATE_' not in saved and str(tmp_path) not in saved
    assert capsys.readouterr().out==''
    assert not list((tmp_path/'private').glob('hub-snapshot-*')) and not list((tmp_path/'private').glob('hub-restore-*'))
    assert all('PRIVATE_REPOSITORY_PASSWORD' not in ' '.join(args) for args,_ in run.calls)
    assert not any(arg in {'prune','forget'} for args,_ in run.calls for arg in args)


def test_snapshot_and_restore_close_database_handles_without_garbage_collection(tmp_path,monkeypatch):
    cfg=config(tmp_path);database(tmp_path/'cloud-provisioning.sqlite3').chmod(0o600)
    opened=[];original=sqlite3.connect
    def connect(*args,**kwargs):
        connection=original(*args,**kwargs);opened.append(connection);return connection
    monkeypatch.setattr(backup.sqlite3,'connect',connect)
    status=backup.once(cfg,tmp_path/'private',run=Restic(tmp_path),verify=True)
    assert status['targets']['pi']['restore']['verified'] and len(opened)>=7
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError,match='closed database'):
            connection.execute('SELECT 1')


def test_snapshot_failure_closes_and_releases_guard_connections(tmp_path,monkeypatch):
    db=database(tmp_path/'live.sqlite3');database(tmp_path/'cloud-provisioning.sqlite3').chmod(0o600)
    opened=[];original=sqlite3.connect
    def connect(*args,**kwargs):
        connection=original(*args,**kwargs);opened.append(connection);return connection
    monkeypatch.setattr(backup.sqlite3,'connect',connect)
    with pytest.raises(backup.BackupError,match='required private backup source'):
        backup.stage_snapshot(db,tmp_path/'stage',{'hub.env':str(tmp_path/'missing')},required=['hub.env'])
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError,match='closed database'):
            connection.execute('SELECT 1')
    with closing(original(db,timeout=.1)) as connection:
        connection.execute('BEGIN IMMEDIATE');connection.rollback()

def test_corrupt_restore_is_failure_even_when_backup_succeeded(tmp_path):
    cfg=config(tmp_path);run=Restic(tmp_path);run.corrupt_restore=True
    with pytest.raises(backup.BackupError):backup.once(cfg,tmp_path/'private',run=run,verify=True)
    state=json.loads((tmp_path/'private/status.json').read_text());assert state['targets']['pi']['ok'] is False
    assert 'CORRUPT' not in json.dumps(state)

def test_existing_nonrestic_repository_and_backup_failures_are_preserved(tmp_path):
    cfg=config(tmp_path);repo=Path(cfg['targets'][0]['repository']);repo.mkdir();(repo/'unrelated').write_text('keep')
    run=Restic(tmp_path)
    with pytest.raises(backup.BackupError):backup.once(cfg,tmp_path/'private',run=run)
    assert (repo/'unrelated').read_text()=='keep' and not run.calls
    (repo/'config').write_text('encrypted');run.fail_backup=True
    with pytest.raises(backup.BackupError):backup.once(cfg,tmp_path/'private',run=run)
    assert (repo/'unrelated').read_text()=='keep'
    assert 'PRIVATE_' not in (tmp_path/'private/status.json').read_text()

def phone_repository(android):
    repo=android/('orion-'+'a'*32)
    for directory in ('snapshots','keys','index','data/aa','locks'):(repo/directory).mkdir(parents=True,exist_ok=True)
    (repo/'config').write_bytes(b'encrypted configuration')
    for directory,name in (('snapshots','1'*64),('keys','2'*64),('index','3'*64),('data/aa','a'*64)):
        (repo/directory/name).write_bytes(b'ciphertext')
    return repo

def test_android_encrypted_repositories_are_offsite_only(tmp_path,capsys):
    cfg=config(tmp_path);android=tmp_path/'android';repo=phone_repository(android)
    cfg['android_repositories']=str(android)
    offsite={'name':'offsite','repository':'existing:offsite','password_file':cfg['targets'][0]['password_file'],'include_android_repositories':True}
    cfg['targets'].append(offsite);run=Restic(tmp_path)
    backup.once(cfg,tmp_path/'private',run=run)
    backups=[(args,env) for args,env in run.calls if args[3]=='backup']
    assert '--files-from-verbatim' not in backups[0][0] and '--files-from-verbatim' in backups[1][0]
    assert repo/'snapshots'/('1'*64) in run.selected[0] and repo/'data/aa'/('a'*64) in run.selected[0]
    assert android not in run.selected[0] and repo not in run.selected[0]
    assert not list((tmp_path/'private').glob('offsite-files-*'))
    assert str(android) not in (tmp_path/'private/status.json').read_text() and capsys.readouterr().out==''
    assert not any(args[3]=='init' and env['RESTIC_REPOSITORY']=='existing:offsite' for args,env in run.calls)

def test_offsite_selection_freezes_snapshots_before_concurrent_uploads(tmp_path,monkeypatch,capsys):
    android=tmp_path/'PRIVATE_PHONE_REPOSITORIES';repo=phone_repository(android)
    (repo/'locks'/('4'*64)).write_bytes(b'transient lock')
    (repo/'snapshots'/'tmp-PRIVATE_NAME').write_bytes(b'partial upload')
    (repo/'data/aa'/('b'*64)).write_bytes(b'wrong shard')
    (android/'unrelated').mkdir();(android/'unrelated'/'PRIVATE_FILE').write_bytes(b'exclude')
    ready=threading.Event();finished=threading.Event();original=backup.object_files
    def upload():
        assert ready.wait(3)
        (repo/'data/bb').mkdir();(repo/'data/bb'/('b'*64)).write_bytes(b'new immutable pack')
        (repo/'index'/('5'*64)).write_bytes(b'new index referencing the new pack')
        (repo/'snapshots'/('6'*64)).write_bytes(b'new committed snapshot')
        finished.set()
    writer=threading.Thread(target=upload);writer.start()
    def select(directory,pattern=r'[0-9a-f]{64}'):
        if Path(directory).name=='keys':
            ready.set();assert finished.wait(3) # Snapshots already captured; uploads continue during selection.
        return original(directory,pattern)
    monkeypatch.setattr(backup,'object_files',select)
    selected=backup.android_repository_files(android);writer.join(3);assert not writer.is_alive()
    assert repo/'snapshots'/('1'*64) in selected and repo/'snapshots'/('6'*64) not in selected
    assert repo/'data/aa'/('a'*64) in selected
    assert repo/'index'/('5'*64) in selected and repo/'data/bb'/('b'*64) in selected
    assert len(selected)==7 and all(item.is_file() for item in selected)
    assert not any('locks' in item.parts or 'tmp-' in item.name or item.parent.name=='unrelated' for item in selected)
    assert capsys.readouterr().out==''

@pytest.mark.parametrize('relative',['.', 'data/aa', 'snapshots/'+('1'*64)])
def test_offsite_selection_refuses_symlinks_without_disclosing_paths(tmp_path,monkeypatch,relative):
    android=tmp_path/'PRIVATE_PHONE_REPOSITORIES';repo=phone_repository(android);unsafe=repo/relative
    original=Path.is_symlink
    monkeypatch.setattr(Path,'is_symlink',lambda path:path==unsafe or original(path))
    with pytest.raises(backup.BackupError) as error:backup.android_repository_files(android)
    assert 'PRIVATE_' not in str(error.value) and str(tmp_path) not in str(error.value)

def test_failed_offsite_transfer_removes_private_selection_list(tmp_path):
    cfg=config(tmp_path);android=tmp_path/'android';phone_repository(android)
    cfg['android_repositories']=str(android)
    cfg['targets'].append({'name':'offsite','repository':'existing:offsite','password_file':cfg['targets'][0]['password_file'],'include_android_repositories':True})
    run=Restic(tmp_path);run.fail_repository='existing:offsite'
    with pytest.raises(backup.BackupError):backup.once(cfg,tmp_path/'private',run=run)
    status=json.loads((tmp_path/'private/status.json').read_text())
    assert status['targets']['pi']['ok'] and not status['targets']['offsite']['ok']
    assert not list((tmp_path/'private').glob('offsite-files-*'))

def test_provider_credentials_cannot_override_restic_or_executable_environment(tmp_path,monkeypatch):
    cfg=config(tmp_path);provider=tmp_path/'provider';provider.write_text(json.dumps({'AWS_SECRET_ACCESS_KEY':'PRIVATE_KEY'}))
    monkeypatch.setenv('RESTIC_PASSWORD','DONT_USE');target={**cfg['targets'][0],'environment_file':str(provider)}
    env=backup.environment(target);assert env['AWS_SECRET_ACCESS_KEY']=='PRIVATE_KEY' and 'RESTIC_PASSWORD' not in env
    provider.write_text(json.dumps({'PATH':'malicious'}))
    with pytest.raises(backup.BackupError):backup.environment(target)

def test_installer_pins_arm64_checksum_and_hardened_private_credentials(monkeypatch):
    binary=b'\x7fELF'+bytes(14)+b'\xb7\x00'+bytes(40);compressed=bz2.compress(binary)
    monkeypatch.setattr(installer,'ASSET_SHA256',hashlib.sha256(compressed).hexdigest())
    assert installer.verified_binary(fetch=lambda url,limit:compressed)==binary
    with pytest.raises(installer.InstallError):installer.verified_binary(fetch=lambda url,limit:b'wrong')
    unit=installer.service({'hub.env':'/etc/orion-hub.env'})
    assert 'User=orion' in unit and 'LoadCredential=hub.env:/etc/orion-hub.env' in unit
    assert 'ProtectSystem=strict' in unit and 'StandardError=null' in unit
    assert 'Persistent=true' in installer.TIMER
    with pytest.raises(installer.InstallError):installer.service({'hub.env':'/etc/secret\nExecStart=/bin/evil'})


def test_installer_adds_private_cloud_configuration_as_required_credentials(tmp_path,monkeypatch):
    token=tmp_path/'token';token.write_text('PRIVATE_ADMIN_TOKEN');token.chmod(0o600)
    cloud=tmp_path/'cloud.json';cloud.write_text(json.dumps({'admin_token_file':str(token)}));cloud.chmod(0o600)
    monkeypatch.setattr(installer,'read_environment',lambda path:{'ORION_SEAFILE_CONFIG':str(cloud)})
    cfg,credentials=installer.configure()
    assert cfg['metadata']['seafile-cloud.json']==str(cloud)
    assert credentials['seafile-admin-token']==str(token)
    assert {'seafile-cloud.json','seafile-admin-token'}<=set(cfg['required_metadata'])
    assert 'PRIVATE_ADMIN_TOKEN' not in json.dumps(cfg)
    token.unlink()
    with pytest.raises(installer.InstallError,match='Cloud recovery source'):installer.configure()

def test_installer_refuses_unrelated_units_configuration_or_repository(tmp_path):
    root=tmp_path/'private';repo=tmp_path/'repository';unit=tmp_path/'backup.service';runner=tmp_path/'runner.py'
    unit.write_text('[Service]\nExecStart=/bin/unrelated\n')
    with pytest.raises(installer.InstallError,match='unrelated backup service'):installer.check_existing(root,repo,[unit],runner)
    unit.write_text('# Managed by '+installer.MARKER+'\n[Service]\n')
    root.mkdir();(root/'unrelated').write_text('keep')
    with pytest.raises(installer.InstallError,match='unrelated private backup'):installer.check_existing(root,repo,[unit],runner)
    (root/'config.json').write_text(json.dumps({'schema':'orion.hub.backup-config/v1','targets':[{'name':'pi','repository':str(repo),'password_file':str(root/'password')}]}))
    repo.mkdir();(repo/'config').write_text('encrypted')
    with pytest.raises(installer.InstallError,match='repository and password'):installer.check_existing(root,repo,[unit],runner)
    (root/'password').write_text('PRIVATE')
    assert installer.check_existing(root,repo,[unit],runner)
    assert (root/'unrelated').read_text()=='keep' and (repo/'config').read_text()=='encrypted'
    runner.write_text('unrelated runner')
    with pytest.raises(installer.InstallError,match='unrelated backup runner'):installer.check_existing(root,repo,[unit],runner)
