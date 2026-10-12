#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Export only Orion's cloud stacks, then encrypt the export with configured restic."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from orion_mini.storage import read_json

class ExportError(Exception):
    """Never expose subprocess replies, private environment or personal paths."""

def call(args, *, output=None, env=None, run=subprocess.run, timeout=7200):
    result=run(args, stdout=output if output is not None else subprocess.PIPE,
               stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=timeout, env=env,
               **({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}))
    if result.returncode:raise ExportError('Cloud backup operation failed; services will be restored automatically.')
    return result.stdout

def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    if os.name=='nt':
        owner=os.environ.get('USERNAME')
        if not owner:raise ExportError('Private backup permissions could not be secured.')
        call(['icacls',str(path),'/inheritance:r','/grant:r',owner+':(OI)(CI)(F)'],timeout=10)
    else:path.chmod(0o700)

def check_root(root):
    # Preserve the Windows profile path used by Docker Compose labels. Windows
    # can redirect AppData through a storage junction whose ancestors are not
    # readable by this user; resolving it also changes container ownership paths.
    root=root.expanduser().absolute()
    if any((folder/'.git').exists() for folder in (root,*root.parents)):
        raise ExportError('Cloud backups must stay outside source repositories.')
    for name in ('seafile','immich'):
        folder=root/name
        marker=read_json(folder/'upstream-source.json',{})
        expected=('https://manual.seafile.com/13.0/repo/docker/ce/' if name=='seafile' else 'https://github.com/immich-app/immich/releases/download/')
        if not str(marker.get('url','')).startswith(expected) or not all((folder/file).is_file() for file in ('upstream.yml','mesh.yml','.env')):
            raise ExportError('Use the existing Orion-provisioned cloud configuration.')
    return root

def compose(folder,*arguments,invoke=call):
    return invoke(['docker','compose','--project-directory',str(folder),'-f',str(folder/'upstream.yml'),'-f',str(folder/'mesh.yml'),*arguments])

def discover(root,invoke=call):
    result=[]
    for name,application,database,destination in [('seafile','seafile','db','/shared'),('immich','immich-server','database','/data')]:
        folder=root/name
        ids=compose(folder,'ps','--all','--quiet',invoke=invoke).decode().split()
        if not ids:raise ExportError('Cloud stacks must exist before exporting them.')
        inspected=json.loads(invoke(['docker','inspect',*ids]))
        owned={}
        for container in inspected:
            labels=container.get('Config',{}).get('Labels',{})
            working=str(labels.get('com.docker.compose.project.working_dir','')).replace('\\','/').rstrip('/').lower()
            if working!=folder.as_posix().lower():raise ExportError('A cloud container does not belong to this Orion configuration.')
            service=labels.get('com.docker.compose.service')
            if service in owned:raise ExportError('Scaled cloud services need a separate backup review.')
            owned[service]=container
        app,db=owned.get(application),owned.get(database)
        if not app or not db or not db['State']['Running']:raise ExportError('Cloud database is unavailable.')
        mount=next((entry for entry in app.get('Mounts',[]) if entry.get('Destination')==destination),None)
        if not mount or mount.get('Type')!='volume' or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}',mount.get('Name','')):
            raise ExportError('This exporter requires the Orion Docker named-volume deployment.')
        image=app.get('Image','')
        if not re.fullmatch(r'sha256:[0-9a-f]{64}',image):raise ExportError('Cloud image identity could not be verified.')
        env=dict(value.split('=',1) for value in app['Config'].get('Env',[]) if '=' in value)
        databases=[env.get('SEAFILE_MYSQL_DB_'+key+'_DB_NAME',default) for key,default in [('CCNET','ccnet_db'),('SEAFILE','seafile_db'),('SEAHUB','seahub_db')]] if name=='seafile' else []
        if any(not re.fullmatch('[a-zA-Z0-9_]{1,64}',value) for value in databases):raise ExportError('Unexpected database names.')
        result.append({'name':name,'folder':folder,'application':app['Id'],'database':db['Id'],'running':bool(app['State']['Running']),
                       'image':image,'database_image':db.get('Image',''),'volume':mount['Name'],'databases':databases})
    return result

def volume_command(stack,*args):
    # Existing image ID, no pulls, no network, source volume strictly read-only.
    return ['docker','run','--rm','--pull=never','--network=none','--read-only','--cap-drop=ALL','--cap-add=DAC_READ_SEARCH',
            '--security-opt=no-new-privileges','--mount','type=volume,source='+stack['volume']+',target=/orion-data,readonly',
            '--entrypoint','/bin/sh',stack['image'],'-c',*args]

def size_gate(stacks,output_root,invoke=call,free=None):
    total=0
    for stack in stacks:
        output=invoke(volume_command(stack,'du -sk /orion-data')).split()
        if not output or not output[0].isdigit():raise ExportError('Cloud storage size could not be checked.')
        total+=int(output[0])*1024
    required=total*2+1024**3  # tar/SQL overhead plus working reserve; no retention deletion.
    available=shutil.disk_usage(output_root).free if free is None else free
    if available<required:raise ExportError('Cloud export needs more local free storage; no services were stopped.')
    # The current primary backup target is the existing small Pi drive.
    fields=invoke(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15','pi','df','-Pk','/srv/orion-backups/desktop']).decode().splitlines()
    try:pi_free=int(fields[-1].split()[3])*1024
    except (ValueError,IndexError):raise ExportError('Pi backup capacity could not be checked.') from None
    if pi_free<required:raise ExportError('Pi backup storage is too small for this export; no services were stopped.')
    return total

def export(root,destination,stacks,invoke=call):
    stopped=[]
    try:
        for stack in stacks:
            if stack['running']:
                # Track before stop: a timeout may still have stopped the container.
                stopped.append(stack['application'])
                invoke(['docker','stop','--time','30',stack['application']])
        manifest={'schema':'orion.cloud.export/v1','created_at':datetime.now(timezone.utc).isoformat(),'stacks':[]}
        for stack in stacks:
            folder=destination/stack['name'];folder.mkdir(mode=0o700)
            # Configuration includes credentials and is private backup material.
            for file in ('upstream.yml','mesh.yml','.env','upstream-source.json','client-bootstrap.json','owner.json'):
                source=stack['folder']/file
                if source.is_file():shutil.copy2(source,folder/file)
            if stack['name']=='seafile':
                command='export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; if command -v mariadb-dump >/dev/null 2>&1; then exec mariadb-dump -uroot --single-transaction --routines --databases "$@"; else exec mysqldump -uroot --single-transaction --routines --databases "$@"; fi'
                args=['docker','exec',stack['database'],'sh','-c',command,'orion-dump',*stack['databases']]
            else:
                args=['docker','exec',stack['database'],'sh','-c','exec pg_dump --clean --if-exists --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"']
            with (folder/'database.sql').open('wb') as output:invoke(args,output=output)
            with (folder/'data.tar').open('wb') as output:invoke(volume_command(stack,'exec tar -cf - -C /orion-data .'),output=output)
            if not (folder/'database.sql').stat().st_size or (folder/'data.tar').stat().st_size<1024:raise ExportError('Cloud export is incomplete.')
            manifest['stacks'].append({'name':stack['name'],'image':stack['image'],'database_image':stack.get('database_image',''),
                                       'volume':stack['volume'],'databases':stack['databases']})
        (destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    finally:
        failures=[]
        for ident in reversed(stopped):
            try:invoke(['docker','start',ident])
            except (ExportError,OSError,subprocess.SubprocessError):failures.append(ident)
        if failures:raise ExportError('Cloud export ended, but an Orion cloud service needs restart.')

def encrypt(data,export_directory,invoke=call):
    config=read_json(data/'backups/config.json',{})
    if not config.get('enabled') or not config.get('targets'):raise ExportError('Configure private restic backups first.')
    for target in config['targets']:
        env=os.environ.copy()
        if target.get('environment_file'):
            values=read_json(Path(target['environment_file']),{})
            if not isinstance(values,dict) or not all(isinstance(k,str) and isinstance(v,str) for k,v in values.items()):raise ExportError('Invalid private backup credential configuration.')
            env.update(values)
        env['RESTIC_REPOSITORY']=target['repository'];env['RESTIC_PASSWORD_FILE']=target['password_file']
        env.pop('RESTIC_PASSWORD',None);env.pop('RESTIC_PASSWORD_COMMAND',None)
        args=[config.get('executable','restic'),'--quiet','-o','sftp.args=-oBatchMode=yes -oConnectTimeout=15']
        if os.name=='nt':args.append('--no-cache')
        invoke([*args,'backup','--tag','orion-cloud','--',str(export_directory)],env=env)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(os.environ.get('LOCALAPPDATA','/opt'))/'OrionCloud')
    parser.add_argument('--data',type=Path,required=True,help='Existing private Orion app-data directory')
    args=parser.parse_args()
    root=check_root(args.root)
    config=read_json(args.data/'backups/config.json',{})
    if not config.get('enabled') or not config.get('targets'):raise ExportError('Configure private restic backups before exporting cloud services.')
    exports=root/'exports';exports.mkdir(mode=0o700,exist_ok=True)
    stacks=discover(root);size_gate(stacks,exports)
    destination=exports/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8])
    private_directory(destination)
    export(root,destination,stacks)
    encrypt(args.data,destination)
    print('Cloud database/data export encrypted into all configured restic targets. A full isolated server restore is still required.')

if __name__=='__main__':
    try:main()
    except (ExportError,OSError,ValueError,KeyError,subprocess.SubprocessError):
        print('Cloud backup did not complete. Check private setup, capacity and Orion cloud service health locally. No personal data was logged.')
        raise SystemExit(1)
