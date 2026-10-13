# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import time
import pytest
from fastapi import HTTPException
from orion_hub.hosted_downloads import Downloads, DownloadLimits
from test_hosted_downloads import release
from test_hosted_service import service


def ticket(service, downloads, subject='auth0|alice'):
    return downloads.issue({'issuer':service['auth'].issuer,'subject':subject},'windows')['ticket']


def test_full_download_budget_persists_across_tickets_and_restart(service, release):
    client, downloads, directory = release
    first=ticket(service, downloads)
    for _ in range(4):
        assert client.get('/v1/download/'+first).status_code == 200
    assert client.get('/v1/download/'+first).status_code == 429
    restarted=Downloads(service['registry'], directory)
    second=ticket(service,restarted)
    with pytest.raises(HTTPException) as caught: restarted.response(second)
    assert caught.value.status_code==429
    assert caught.value.headers['Retry-After']=='300'
    # An unrelated entitled account retains its independent budget.
    assert client.get('/v1/download/'+ticket(service,downloads,'auth0|bob')).status_code==200


def test_head_and_range_are_bounded_and_multipart_refused(service, release):
    client, downloads, _=release
    value=ticket(service,downloads)
    assert client.head('/v1/download/'+value).content==b''
    assert client.get('/v1/download/'+value,headers={'Range':'bytes=4-8'}).content==b'hetic'
    assert client.get('/v1/download/'+value,headers={'Range':'bytes=0-18,0-18'}).status_code==416
    # Range conservatively consumes one complete file reservation.
    with service['registry'].connect() as db:
        assert db.execute('SELECT sum(bytes) FROM download_usage').fetchone()[0]==19
        assert db.execute('SELECT count(*) FROM download_streams').fetchone()[0]==0
    for _ in range(6): assert client.head('/v1/download/'+value).status_code==200
    assert client.head('/v1/download/'+value).status_code==429


def test_account_request_limit_cannot_be_reset_with_new_ticket(service, release):
    client, downloads, _=release
    for _ in range(3):
        value=ticket(service,downloads)
        for _ in range(8): assert client.head('/v1/download/'+value).status_code==200
    value=ticket(service,downloads)
    for _ in range(6): assert client.head('/v1/download/'+value).status_code==200
    assert client.head('/v1/download/'+ticket(service,downloads)).status_code==429


def test_global_byte_limit_spans_accounts(service, release):
    client, downloads, _=release
    downloads.limits=replace(downloads.limits,global_file_copies=1)
    assert client.get('/v1/download/'+ticket(service,downloads)).status_code==200
    assert client.get('/v1/download/'+ticket(service,downloads,'auth0|bob')).status_code==429


def test_global_request_budget_spans_accounts(service, release):
    client, downloads, _=release
    downloads.limits=replace(downloads.limits,global_requests=1)
    assert client.head('/v1/download/'+ticket(service,downloads)).status_code==200
    assert client.head('/v1/download/'+ticket(service,downloads,'auth0|bob')).status_code==429


def test_atomic_concurrent_admission_reclaims_crashed_leases(service,release):
    _, downloads, directory=release
    downloads.limits=replace(downloads.limits,account_streams=1)
    value=ticket(service,downloads)
    def reserve(_):
        try: return downloads.response(value)
        except HTTPException as error: return error.status_code
    with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(reserve,range(4)))
    assert results.count(429)==3
    with service['registry'].connect() as db:
        db.execute('UPDATE download_streams SET expires_at=?',(time.time()-1,))
    restarted=Downloads(service['registry'],directory,limits=downloads.limits)
    response=restarted.response(value)
    restarted.release(response.lease)
    with service['registry'].connect() as db:
        assert db.execute('SELECT count(*) FROM download_streams').fetchone()[0]==0


def test_global_concurrency_limit_includes_other_accounts(service,release):
    _, downloads, _=release
    downloads.limits=replace(downloads.limits,global_streams=1)
    first=downloads.response(ticket(service,downloads))
    with pytest.raises(HTTPException) as caught:
        downloads.response(ticket(service,downloads,'auth0|bob'))
    assert caught.value.status_code==429
    downloads.release(first.lease)


@pytest.mark.parametrize('spec',['2.3','2.4'])
@pytest.mark.parametrize('ending',['success','error','cancel','timeout','disconnect'])
def test_stream_lease_released_on_every_exit(service,release,ending,spec):
    _, downloads, _=release
    response=downloads.response(ticket(service,downloads))
    # Starlette >=1.8 watches receive() for a disconnect below ASGI 2.4 (as
    # uvicorn advertises); 2.4 servers report it by raising OSError from send.
    scope={'type':'http','method':'GET','headers':[],'asgi':{'version':'3.0','spec_version':spec},
           'extensions':{'http.response.pathsend':{}}}
    async def run():
        reached=asyncio.Event()
        async def send(message):
            assert message['type']!='http.response.pathsend'
            if message['type']=='http.response.body':
                reached.set()
                if ending=='error': raise OSError('Synthetic disconnect')
                if ending in ('cancel','timeout'): await asyncio.Event().wait()
        async def receive():
            # Only the disconnect case loses the client; the others stay connected.
            if ending!='disconnect': await asyncio.Event().wait()
            return {'type':'http.disconnect'}
        if ending=='timeout': response.seconds=0.02
        task=asyncio.create_task(response(scope,receive,send))
        if ending=='cancel':
            await asyncio.wait_for(reached.wait(),2)
            task.cancel()
        if ending in ('success','disconnect'): await task
        else:
            with pytest.raises({'error':OSError,'cancel':asyncio.CancelledError,'timeout':TimeoutError}[ending]): await task
    asyncio.run(run())
    with service['registry'].connect() as db:
        assert db.execute('SELECT count(*) FROM download_streams').fetchone()[0]==0


def test_old_usage_window_expires(service,release):
    client, downloads, _=release
    value=ticket(service,downloads)
    for _ in range(4): assert client.get('/v1/download/'+value).status_code==200
    with service['registry'].connect() as db:
        db.execute('UPDATE download_usage SET requested_at=?',(time.time()-301,))
    assert client.get('/v1/download/'+value).status_code==200
