# SPDX-License-Identifier: AGPL-3.0-or-later
import hashlib
from uuid import uuid4
import pytest
from orion_mini.clipboard import RecentClipboard,envelope
from orion_mini.peer import Blobs,mesh_address,MAX_CLIPBOARD
from orion_mini.adb_worker import AdbWorker,worker_command

def test_all_six_clipboard_directions_and_rapid_redispatch_do_not_echo():
    for source in range(3):
        for target in range(3):
            if source==target:continue
            clocks=[0];caches=[RecentClipboard(lambda:clocks[0]) for _ in range(3)]
            for count in range(500):
                data=f'PRIVATE_CLIP_{count}'.encode()
                assert caches[source].claim('text/plain',data)
                assert caches[target].claim('text/plain',data)
                assert caches[target].claim('text/plain',data) is None
            clocks[0]=301
            assert caches[target].claim('text/plain',data)  # Bounded time retention.

def test_repeated_content_after_another_copy_is_delivered_again():
    # Physical acceptance: a reused image fixture never reached the phone because
    # any value seen in the previous five minutes was suppressed.
    clock=[0];sender=RecentClipboard(lambda:clock[0]);receiver=RecentClipboard(lambda:clock[0])
    for value in (b'A',b'B',b'A',b'B',b'A'):
        clock[0]+=1
        assert sender.claim('text/plain',value)
        # The queued GUI delivery writes directly; it does not claim first.
        assert not receiver.contains_digest('text/plain',hashlib.sha256(value).hexdigest())
        receiver.received('text/plain',value)
        # The receiver's own OS change callback is the echo and is suppressed.
        assert receiver.contains_digest('text/plain',hashlib.sha256(value).hexdigest())
        assert receiver.claim('text/plain',value) is None
    clock[0]+=11
    # Copying the same value again later, e.g. after an unobserved change on
    # the other device, is a real copy rather than an echo.
    assert sender.claim('text/plain',b'A')

def test_reencoded_image_echo_and_crossing_copy_within_window():
    clock=[0];cache=RecentClipboard(lambda:clock[0])
    assert cache.claim('image/jpeg',b'original-jpeg')
    cache.received('image/png',b'reencoded-png',alias=True)
    assert cache.contains_digest('image/png',hashlib.sha256(b'reencoded-png').hexdigest())
    assert cache.contains_digest('image/jpeg',hashlib.sha256(b'original-jpeg').hexdigest())
    # A local copy replaces the synced value, so the other side's next copy of
    # the earlier image is not mistaken for an echo inside the window.
    clock[0]+=2
    assert cache.claim('text/plain',b'local copy')
    assert not cache.contains_digest('image/png',hashlib.sha256(b'reencoded-png').hexdigest())
    assert cache.claim('image/jpeg',b'original-jpeg')

def test_text_and_direct_image_have_matching_hashes_and_bounded_cache(tmp_path):
    data=b'PRIVATE_CLIP';digest=hashlib.sha256(data).hexdigest()
    assert envelope('text/plain',data,digest)['text']=='PRIVATE_CLIP'
    blobs=Blobs(tmp_path);ident=blobs.add(b'image');assert blobs.get(ident).read_bytes()==b'image'
    for _ in range(10):blobs.add(b'image')
    assert blobs.get(ident) is None and len(blobs.items)==8
    with pytest.raises(ValueError):blobs.add(b'x'*(MAX_CLIPBOARD+1))
    blobs.clear();assert not list(tmp_path.iterdir())
    with pytest.raises(ValueError):mesh_address('127.0.0.1')

def test_adb_launch_requires_paired_identity_and_fixed_installed_worker(monkeypatch):
    apk='/data/app/~~abcd/com.orionmini.mobile-abcd/base.apk'
    starter=apk.rsplit('/',1)[0]+'/lib/arm64/libsefirah_worker.so'
    valid=dict(apk=apk,starter=starter)
    assert worker_command(valid).startswith(starter+' --apk=')
    for value in [dict(valid,starter='/system/bin/sh'),dict(valid,apk=apk+'; command'),dict(valid,starter=starter+' $(command)')]:
        with pytest.raises(ValueError):worker_command(value)
    worker=AdbWorker();worker.adb='test-adb';calls=[]
    def run(*args):
        calls.append(args)
        if args==('devices',):return 'List of devices attached\nserial device\n'
        if 'content' in args:return f'Bundle[{{device_id=unpaired,watching=true,worker_alive=false,apk={apk},starter={starter}}}]'
        return ''
    monkeypatch.setattr(worker,'run',run);worker.poll({'paired'})
    assert not any(len(c)>3 and c[2]=='shell' and 'libsefirah' in c[3] for c in calls)


@pytest.mark.parametrize('mode,approved,watching,fresh,launch', [
    ('cloud', True, True, True, True), ('cloud', False, True, True, False),
    ('cloud', True, False, True, False), ('cloud', True, True, False, False),
    ('self_hosted', True, True, True, False), ('unexpected', True, True, True, False),
])
def test_cloud_worker_requires_matching_mode_current_roster_and_consent(monkeypatch, mode, approved, watching, fresh, launch):
    apk='/data/app/~~abcd/com.orionmini.mobile-abcd/base.apk'
    starter=apk.rsplit('/',1)[0]+'/lib/arm64/libsefirah_worker.so'
    worker=AdbWorker();worker.adb='synthetic-adb';calls=[]
    def run(*args):
        calls.append(args)
        if args==('devices',): return 'List of devices attached\nsynthetic device\n'
        if 'content' in args: return f'Bundle[{{mode={mode},device_id=cloud-phone,watching={str(watching).lower()},worker_alive=false,apk={apk},starter={starter}}}]'
        return ''
    monkeypatch.setattr(worker,'run',run)
    worker.poll(set(),cloud={'cloud-phone'} if approved else set(),authorize=lambda device,connection:fresh)
    assert any(len(c)>3 and c[2]=='shell' and 'libsefirah' in c[3] for c in calls) is launch


def test_cloud_worker_targets_exclude_expired_account_revoked_roster_and_optout():
    from types import SimpleNamespace
    from orion_mini.phone import clipboard_worker_targets
    from orion_mini.hosted_crypto import EnvelopeError
    hosted=SimpleNamespace(enabled=lambda:True,status='active',session=object(),account=SimpleNamespace(status='signed_in'),_targets=lambda:['approved-phone'])
    workspace=SimpleNamespace(settings={'hub':{'paired':False}},_hosted=hosted)
    state=SimpleNamespace(connected=False,devices=[])
    assert clipboard_worker_targets(workspace,state)==(set(),{'approved-phone'})
    hosted.account.status='expired'
    assert clipboard_worker_targets(workspace,state)==(set(),set())
    hosted.account.status='signed_in'
    def invalid(): raise EnvelopeError()
    hosted._targets=invalid
    assert clipboard_worker_targets(workspace,state)==(set(),set())
    hosted._targets=lambda:['approved-phone']
    workspace.settings['link']={'clipboard':False}
    assert clipboard_worker_targets(workspace,state)==(set(),set())
