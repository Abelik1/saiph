# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import sqlite3
from contextlib import closing
import threading
import time
from fastapi.testclient import TestClient
from orion_hub.hosted import create_app
from orion_hub.hosted_maintenance import WorkspaceCleanup, cleanup_database, maintenance_context
from orion_hub.hosted_service import SharedHosted
from test_hosted_service import service, send


def config(service,index=0):
    return service['registry'].config({'id':service['accounts'][index]['id'],'subject':['auth0|alice','auth0|bob'][index]})


def expired(service,index=0):
    account=service['accounts'][index]
    source,target=account['devices']
    value=source['session'].encrypt(target['id'],{'text':'Synthetic expiry probe'})
    assert send(service['client'],source,'POST','/v1/sealed/events',value).status_code==200
    with closing(sqlite3.connect(config(service,index).database)) as db, db:
        db.execute('UPDATE sealed_events SET expires_at=1')
    return value


def count(service,index=0):
    with closing(sqlite3.connect(config(service,index).database)) as db, db:
        return db.execute('SELECT count(*) FROM sealed_events WHERE expires_at<=?',(int(time.time()),)).fetchone()[0]


def test_idle_suspended_account_expiry_includes_blobs_candidates_and_nonces(service):
    expired(service)
    account=service['accounts'][0]
    source,target=account['devices']
    value=source['session'].encrypt(target['id'],{'text':'Synthetic live probe'})
    assert send(service['client'],source,'POST','/v1/sealed/events',value).status_code==200
    # Posting also performs opportunistic cleanup: add a second expired event
    # directly so the autonomous pass must remove it while retaining the live one.
    with closing(sqlite3.connect(config(service).database)) as db, db:
        db.execute("INSERT INTO sealed_events SELECT 'synthetic-expired',source,target,version,header,ciphertext,digest,1 FROM sealed_events LIMIT 1")
        db.executemany('INSERT INTO candidates VALUES(?,?,?,?)', [('expired','synthetic','synthetic',1),('live','synthetic','synthetic',int(time.time())+300)])
        db.execute("INSERT INTO nonces VALUES('synthetic','expired',1)")
        db.executemany('INSERT INTO hosted_blobs VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       [(v,account['id'],source['id'],target['id'],2,'synthetic',expiry,3,'synthetic','synthetic',0)
                        for v,expiry in [('expired',1),('live',int(time.time())+300)]])
        db.executemany('INSERT INTO hosted_blob_chunks VALUES(?,0,?)',[('expired',b'opaque'),('live',b'opaque')])
    service['registry'].set_active(account['id'],False)
    result=WorkspaceCleanup(service['registry'])()
    assert result['errors']==0 and result['deleted']>=5
    with closing(sqlite3.connect(config(service).database)) as db, db:
        assert db.execute('SELECT count(*) FROM sealed_events').fetchone()[0]==1
        for table in ('candidates','hosted_blobs'):
            assert db.execute('SELECT id FROM '+table).fetchall()==[('live',)]
        assert db.execute('SELECT blob FROM hosted_blob_chunks').fetchall()==[('live',)]
        assert db.execute("SELECT count(*) FROM nonces WHERE nonce='expired'").fetchone()[0]==0


def test_bounded_pages_visit_every_workspace_without_creating_uninitialized_state(service):
    for index in range(2): expired(service,index)
    new=service['registry'].admit('auth0|uninitialized',expires_at=int(time.time())+300)
    missing=service['registry'].directory/'workspaces'/new
    cleanup=WorkspaceCleanup(service['registry'],workspace_limit=1,batch_size=1)
    for _ in range(6): assert cleanup()['workspaces']==1
    assert count(service,0)==count(service,1)==0
    assert not missing.exists()


def test_corrupt_ownership_is_skipped_and_other_workspaces_continue(service):
    for index in range(2): expired(service,index)
    with closing(sqlite3.connect(config(service).database)) as db, db:
        db.execute("UPDATE deployment SET subject='auth0|different-synthetic'")
    result=WorkspaceCleanup(service['registry'])()
    assert result['errors']==1
    assert count(service,0)==1 and count(service,1)==0


def test_per_database_batch_preserves_backlog_and_live_data(service):
    expired(service)
    with closing(sqlite3.connect(config(service).database)) as db, db:
        db.execute("INSERT INTO sealed_events SELECT 'synthetic-second',source,target,version,header,ciphertext,digest,1 FROM sealed_events LIMIT 1")
    cleanup_database(config(service),batch_size=1)
    assert count(service)==1
    cleanup_database(config(service),batch_size=1)
    assert count(service)==0


def test_shared_lifespan_cleans_without_account_requests_and_stops(service):
    expired(service)
    app=SharedHosted(service['registry'],tokens=service['tokens'])
    done=threading.Event()
    cleanup=app.maintenance
    def observed():
        result=cleanup();done.set();return result
    app.maintenance=observed
    with TestClient(app) as client:
        assert done.wait(3)
        assert client.get('/v1/health').status_code==200
    assert count(service)==0


def test_owner_lifespan_runs_cleanup_without_authenticated_traffic(service,monkeypatch):
    from orion_hub import hosted_maintenance
    expired(service)
    done=threading.Event()
    original=hosted_maintenance.cleanup_database
    def observed(*args,**kwargs):
        result=original(*args,**kwargs);done.set();return result
    monkeypatch.setattr(hosted_maintenance,'cleanup_database',observed)
    with TestClient(create_app(config(service),tokens=service['tokens'])):
        assert done.wait(3)
    assert count(service)==0


def test_scheduler_recovers_from_pass_failure_and_finishes_on_shutdown():
    calls=[]
    async def run():
        event=asyncio.Event()
        loop=asyncio.get_running_loop()
        def cleanup():
            calls.append(1)
            if len(calls)==1: raise sqlite3.OperationalError('Synthetic locked database')
            loop.call_soon_threadsafe(event.set)
        async with maintenance_context(cleanup,interval=0.01):
            await asyncio.wait_for(event.wait(),3)
        final=len(calls)
        await asyncio.sleep(0.03)
        assert len(calls)==final
    asyncio.run(run())
    assert len(calls)>=2
