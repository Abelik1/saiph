# SPDX-License-Identifier: AGPL-3.0-or-later
import importlib.util
import json
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location('cloud_export',Path(__file__).parents[1]/'scripts/backup-orion-cloud.py')
backup=importlib.util.module_from_spec(spec);spec.loader.exec_module(backup)

def stack(root,name='seafile',running=True):
    folder=root/name;folder.mkdir(exist_ok=True)
    (folder/'.env').write_text('SYNTHETIC_PRIVATE=test-only-secret')
    return {'name':name,'folder':folder,'application':name+'-app','database':name+'-database',
            'running':running,'image':'sha256:'+'a'*64,'volume':name+'-data','databases':['ccnet_db','seafile_db','seahub_db'] if name=='seafile' else []}

def test_export_stops_only_running_owned_apps_and_restarts_after_failed_dump(tmp_path):
    stacks=[stack(tmp_path),stack(tmp_path,'immich',running=False)]
    destination=tmp_path/'export';destination.mkdir();calls=[]
    def invoke(args,**kwargs):
        calls.append(args)
        if 'exec' in args:raise backup.ExportError('Private tool output must never escape')
        return b''
    with pytest.raises(backup.ExportError):backup.export(tmp_path,destination,stacks,invoke)
    assert calls[0]==['docker','stop','--time','30','seafile-app']
    assert calls[-1]==['docker','start','seafile-app']
    assert not any(args[:2]==['docker','stop'] and 'immich-app' in args for args in calls)
    assert not (destination/'manifest.json').exists()

def test_export_database_precedes_data_and_keeps_private_config_out_of_manifest(tmp_path):
    stacks=[stack(tmp_path),stack(tmp_path,'immich')];destination=tmp_path/'export';destination.mkdir();calls=[]
    def invoke(args,output=None,**kwargs):
        calls.append(args)
        if output is not None:output.write(b'Synthetic SQL' if 'exec' in args else b'\0'*2048)
        return b''
    backup.export(tmp_path,destination,stacks,invoke)
    for name in ('seafile','immich'):
        assert (destination/name/'database.sql').read_bytes()==b'Synthetic SQL'
        assert 'test-only-secret' in (destination/name/'.env').read_text()
    manifest=(destination/'manifest.json').read_text()
    assert 'test-only-secret' not in manifest
    dumps=[i for i,args in enumerate(calls) if args[:2]==['docker','exec']]
    archives=[i for i,args in enumerate(calls) if args[:2]==['docker','run']]
    assert all(dump<archive for dump,archive in zip(dumps,archives))
    assert calls[-2:]==[['docker','start','immich-app'],['docker','start','seafile-app']]
    assert all('test-only-secret' not in str(args) for args in calls)

def test_volume_archive_has_no_network_write_mount_or_image_pull(tmp_path):
    args=backup.volume_command(stack(tmp_path),'exec tar -cf - -C /orion-data .')
    assert '--network=none' in args and '--read-only' in args and '--pull=never' in args
    assert '--cap-drop=ALL' in args and '--security-opt=no-new-privileges' in args
    assert '--cap-add=DAC_READ_SEARCH' in args  # Data may belong to the upstream service UID.
    assert 'type=volume,source=seafile-data,target=/orion-data,readonly' in args
    assert 'sha256:'+'a'*64 in args

def test_capacity_gate_refuses_full_pi_before_any_service_stop(tmp_path):
    stacks=[stack(tmp_path)];calls=[]
    def invoke(args,**kwargs):
        calls.append(args)
        return b'2048 /orion-data\n' if args[0]=='docker' else b'Filesystem 1024-blocks Used Available Capacity Mounted\n/dev/test 100 90 10 90% /srv\n'
    with pytest.raises(backup.ExportError,match='Pi backup storage'):backup.size_gate(stacks,tmp_path,invoke,free=10*1024**3)
    assert not any('stop' in args for args in calls)

def test_foreign_compose_container_is_refused_before_export(tmp_path):
    def invoke(args,**kwargs):
        if args[1]=='compose':return b'owned-container\n'
        return json.dumps([{'Config':{'Labels':{'com.docker.compose.project.working_dir':'/another/project'}}}]).encode()
    with pytest.raises(backup.ExportError,match='does not belong'):backup.discover(tmp_path,invoke)

def test_failed_stop_is_still_restarted_because_timeout_may_have_applied(tmp_path):
    stacks=[stack(tmp_path)];calls=[];destination=tmp_path/'export';destination.mkdir()
    def invoke(args,**kwargs):
        calls.append(args)
        if args[1]=='stop':raise backup.ExportError('Stop status unavailable')
        return b''
    with pytest.raises(backup.ExportError):backup.export(tmp_path,destination,stacks,invoke)
    assert calls[-1]==['docker','start','seafile-app']
