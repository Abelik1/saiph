#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Install the private Pi Hub restic timer; dry-run unless --apply is supplied."""
from __future__ import annotations
import argparse
import bz2
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import secrets
import shlex
import shutil
import subprocess
from urllib.request import urlopen

VERSION='0.19.1'
ASSET='restic_0.19.1_linux_arm64.bz2'
ASSET_SHA256='a5f64aaab53d51e311fa3829124c5b703f2d14cf187d8640b6be3b2b49376465'
SOURCE='https://github.com/restic/restic/releases/download/v0.19.1/'+ASSET
CHECKSUM_SOURCE='https://github.com/restic/restic/releases/download/v0.19.1/SHA256SUMS'
ROOT=Path('/var/lib/orion-hub/encrypted-backup')
REPOSITORY=Path('/srv/orion-hub-backups')
EXECUTABLE=Path('/opt/orion-mini/tools/restic/0.19.1/restic')
MARKER='orion.hub.encrypted-backup/v1'

class InstallError(Exception):pass
def call(arguments,*,run=subprocess.run):
    result=run(arguments,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
    if result.returncode:raise InstallError('Encrypted backup installation did not complete.')
    return result.stdout
def private(path,*,owner=None,directory=False,data=None):
    path=Path(path)
    if path.is_symlink():raise InstallError('Private backup path must not be a symbolic link.')
    if directory:path.mkdir(parents=True,exist_ok=True,mode=0o700)
    elif data is not None:
        with path.open('wb') as output:
            os.fchmod(output.fileno(),0o600);output.write(data if isinstance(data,bytes) else data.encode());output.flush();os.fsync(output.fileno())
    path.chmod(0o700 if directory else 0o600)
    if owner:os.chown(path,owner.pw_uid,owner.pw_gid)
    return path
def read_environment(path):
    result={}
    for line in Path(path).read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        key,separator,value=line.partition('=')
        if not separator or not re.fullmatch('[A-Z][A-Z0-9_]*',key):raise InstallError('Hub environment format needs review.')
        parts=shlex.split(value,comments=False)
        if len(parts)>1:raise InstallError('Hub environment format needs review.')
        result[key]=parts[0] if parts else ''
    return result
def systemd_path(path):
    value=str(path)
    if not PurePosixPath(value).is_absolute() or any(c in value for c in '\n\r%"\\'):raise InstallError('Private credential path needs review.')
    # systemd treats unescaped whitespace as an argument separator.
    return value.replace(' ','\\x20')
def service(credentials):
    lines=['# Managed by '+MARKER,'[Unit]','Description=Orion Hub encrypted consistent backup','After=network-online.target orion-hub.service','Wants=network-online.target','','[Service]','Type=oneshot','User=orion','Group=orion','UMask=0077',
           'ExecStart=/usr/bin/python3 /opt/orion-mini/backup-orion-hub.py','Nice=10','IOSchedulingClass=idle','TimeoutStartSec=3h','NoNewPrivileges=true','ProtectSystem=strict','ProtectHome=true','PrivateTmp=true',
           'ReadWritePaths=/var/lib/orion-hub /srv/orion-hub-backups', 'ReadOnlyPaths=-/var/lib/orion-phone-backup -/srv/orion-phone-backups','RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6','StandardOutput=journal','StandardError=null']
    for label,path in credentials.items():lines.append('LoadCredential='+label+':'+systemd_path(path))
    return '\n'.join(lines)+'\n'
TIMER='''# Managed by orion.hub.encrypted-backup/v1
[Unit]
Description=Encrypt Orion Hub state daily

[Timer]
OnCalendar=*-*-* 03:50
RandomizedDelaySec=15m
Persistent=true
Unit=orion-hub-encrypted-backup.service

[Install]
WantedBy=timers.target
'''
def verified_binary(*,fetch=None):
    if fetch is None:
        def fetch(url,limit):
            with urlopen(url,timeout=60) as response:return response.read(limit+1)
    compressed=fetch(SOURCE,64*1024**2)
    if len(compressed)>64*1024**2 or hashlib.sha256(compressed).hexdigest()!=ASSET_SHA256:raise InstallError('Official restic release checksum did not match.')
    expanded=bz2.decompress(compressed)
    if len(expanded)>128*1024**2 or expanded[:4]!=b'\x7fELF' or expanded[18:20]!=b'\xb7\x00':raise InstallError('Official restic architecture did not match this Pi.')
    return expanded
def configure(offsite=None):
    env=read_environment('/etc/orion-hub.env')
    if env.get('ORION_HUB_DATA','/var/lib/orion-hub')!='/var/lib/orion-hub':raise InstallError('Nonstandard Hub data location needs review before installation.')
    metadata={'hub.env':'/etc/orion-hub.env','automations.json':env.get('ORION_HUB_AUTOMATIONS','/opt/orion-mini/hub/config/automations.json'),
              'phone-backup-config.json':'/var/lib/orion-phone-backup/config.json','phone-backup-credentials.json':'/var/lib/orion-phone-backup/credentials.json','phone-backup-auth.htpasswd':'/var/lib/orion-phone-backup/auth.htpasswd'}
    credentials={'hub.env':'/etc/orion-hub.env'}
    if env.get('ORION_FIREBASE_CREDENTIALS'):
        firebase=Path(env['ORION_FIREBASE_CREDENTIALS'])
        if firebase.is_symlink() or not firebase.is_file():raise InstallError('Configured Hub push credential is unavailable.')
        metadata['firebase-service-account.json']=str(firebase);credentials['firebase-service-account.json']=str(firebase)
    target={'name':'pi','repository':str(REPOSITORY),'password_file':str(ROOT/'password')}
    targets=[target]
    if offsite:
        value=json.loads(Path(offsite).read_text())
        if not isinstance(value,dict) or set(value)-{'repository','password_file','environment_file','include_android_repositories'} or not all(isinstance(value.get(key),str) and value[key] for key in ('repository','password_file')):raise InstallError('Use an existing private offsite repository configuration.')
        for key,label in [('password_file','offsite.password'),('environment_file','offsite.environment')]:
            if value.get(key):
                path=Path(value[key])
                if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:raise InstallError('Offsite credential files must be private existing files.')
                credentials[label]=str(path)
        targets.append({'name':'offsite',**value})
    required=['hub.env','automations.json']
    if 'firebase-service-account.json' in metadata:required.append('firebase-service-account.json')
    if env.get('ORION_SEAFILE_CONFIG'):
        cloud=Path(env['ORION_SEAFILE_CONFIG'])
        if cloud.is_symlink() or not cloud.is_file():raise InstallError('Configured Cloud recovery source is unavailable.')
        value=json.loads(cloud.read_text())
        token=Path(value['admin_token_file'])
        if not token.is_absolute() or token.is_symlink() or not token.is_file():raise InstallError('Configured Cloud recovery source is unavailable.')
        for label,path in [('seafile-cloud.json',cloud),('seafile-admin-token',token)]:
            metadata[label]=str(path);credentials[label]=str(path);required.append(label)
    return {'schema':'orion.hub.backup-config/v1','database':'/var/lib/orion-hub/orion-hub.sqlite3','executable':str(EXECUTABLE),'metadata':metadata,'required_metadata':required,'targets':targets,'android_repositories':'/srv/orion-phone-backups','verify_restore':True},credentials
def check_existing(root=ROOT,repository=REPOSITORY,units=None,runner=Path('/opt/orion-mini/backup-orion-hub.py')):
    """A reinstall may upgrade our files, never take over unrelated private state."""
    units=units or [Path('/etc/systemd/system/orion-hub-encrypted-backup.service'),Path('/etc/systemd/system/orion-hub-encrypted-backup.timer')]
    for unit in units:
        if unit.is_symlink() or unit.exists() and not unit.read_text().startswith('# Managed by '+MARKER+'\n'):raise InstallError('Existing unrelated backup service was retained.')
    if runner.is_symlink() or runner.exists() and 'Consistent Hub state and private metadata, encrypted with standard restic.' not in runner.read_text()[:300]:raise InstallError('Existing unrelated backup runner was retained.')
    if root.is_symlink() or repository.is_symlink():raise InstallError('Existing private backup paths were retained.')
    managed=False
    if root.exists() and any(root.iterdir()):
        config=root/'config.json';marker=root/'managed.json'
        if config.is_symlink() or marker.is_symlink():raise InstallError('Existing private backup configuration was retained.')
        if config.is_file():
            value=json.loads(config.read_text())
            target=(value.get('targets') or [{}])[0]
            if value.get('schema')!='orion.hub.backup-config/v1' or target.get('name')!='pi' or target.get('repository')!=str(repository) or target.get('password_file')!=str(root/'password'):raise InstallError('Existing unrelated backup configuration was retained.')
            managed=True
        elif marker.is_file() and json.loads(marker.read_text()).get('schema')==MARKER:managed=True
        else:raise InstallError('Existing unrelated private backup data was retained.')
    if repository.exists() and any(repository.iterdir()):
        if not managed or not (root/'password').is_file() or (root/'password').is_symlink():raise InstallError('Existing encrypted repository and password were retained.')
    return managed
def install(*,offsite=None,run=subprocess.run):
    if os.geteuid()!=0 or platform.machine() not in {'aarch64','arm64'}:raise InstallError('Run this installer as root on the ARM64 Pi.')
    import pwd
    owner=pwd.getpwnam('orion');check_existing();config,credentials=configure(offsite)
    if shutil.disk_usage('/srv').free<512*1024**2:raise InstallError('Pi backup storage is too small; no services were changed.')
    binary=verified_binary()
    if EXECUTABLE.is_symlink() or EXECUTABLE.exists() and hashlib.sha256(EXECUTABLE.read_bytes()).digest()!=hashlib.sha256(binary).digest():raise InstallError('Existing unrelated restic binary was retained.')
    private(EXECUTABLE.parent,directory=True);EXECUTABLE.parent.chmod(0o755)
    private(EXECUTABLE,data=binary);EXECUTABLE.chmod(0o755)
    info=call([str(EXECUTABLE),'version'],run=run)
    if not info.startswith(b'restic '+VERSION.encode()+b' '):raise InstallError('Restic release verification failed.')
    private(ROOT,directory=True,owner=owner);private(REPOSITORY,directory=True,owner=owner)
    private(ROOT/'managed.json',data=json.dumps({'schema':MARKER})+'\n',owner=owner)
    password=ROOT/'password'
    if not password.exists():
        fd=os.open(password,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as handle:handle.write(secrets.token_urlsafe(48)+'\n')
    private(password,owner=owner)
    existing=ROOT/'config.json'
    if existing.exists():
        previous=json.loads(existing.read_text())
        # Reinstall keeps an already configured offsite target unless the owner
        # explicitly supplies an updated private configuration.
        if not offsite:config['targets']=[config['targets'][0],*[t for t in previous.get('targets',[]) if t.get('name')=='offsite']]
        for target in config['targets'][1:]:
            for key,label in [('password_file','offsite.password'),('environment_file','offsite.environment')]:
                if target.get(key):credentials[label]=target[key]
    private(existing,data=json.dumps(config,indent=2)+'\n',owner=owner)
    runner=Path(__file__).with_name('backup-orion-hub.py')
    if not runner.is_file():raise InstallError('Deploy both reviewed backup scripts together.')
    destination=Path('/opt/orion-mini/backup-orion-hub.py')
    shutil.copyfile(runner,destination);destination.chmod(0o755)
    unit=Path('/etc/systemd/system/orion-hub-encrypted-backup.service');unit.write_text(service(credentials));unit.chmod(0o644)
    timer=Path('/etc/systemd/system/orion-hub-encrypted-backup.timer');timer.write_text(TIMER);timer.chmod(0o644)
    private(ROOT/'upstream-source.json',data=json.dumps({'version':VERSION,'asset':ASSET,'url':SOURCE,'checksum_url':CHECKSUM_SOURCE,'sha256':ASSET_SHA256})+'\n',owner=owner)
    call(['systemctl','daemon-reload'],run=run);call(['systemctl','enable','--now','orion-hub-encrypted-backup.timer'],run=run)
    # First run establishes the repository; verify separately via the same
    # credential-bearing service context without leaking credentials to a shell.
    call(['systemctl','start','orion-hub-encrypted-backup.service'],run=run)
    print('Daily encrypted Hub backup installed. Privately preserve its password to allow disaster recovery.')
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');parser.add_argument('--offsite-config',type=Path)
    args=parser.parse_args()
    if not args.apply:
        print('Review: install checksum-pinned ARM64 restic, preserve existing Hub copies, add daily encrypted snapshot/config backup and a private password. No services were changed.');return
    install(offsite=args.offsite_config)
if __name__=='__main__':
    try:main()
    except (InstallError,OSError,ValueError,KeyError,subprocess.SubprocessError):
        print('Encrypted Hub backup installation did not complete. Check private setup and Pi capacity. No personal data was logged.');raise SystemExit(1)
