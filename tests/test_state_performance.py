# SPDX-License-Identifier: AGPL-3.0-or-later
"""The window reads the whole state every second, so building it must stay cheap."""
import base64
import hashlib
import os

from orion_mini import phone_features, setup_guide
from orion_mini.link_service import LinkWorkspace


def test_optional_tool_scan_is_reused_between_state_reads(tmp_path, monkeypatch):
    workspace = LinkWorkspace(tmp_path)
    scans = []
    monkeypatch.setattr(setup_guide, 'tools', lambda: scans.append(1) or {'tools': {}, 'linux': {}, 'platform': 'test'})
    clock = [1000.0]
    monkeypatch.setattr('orion_mini.link_service.time.monotonic', lambda: clock[0])
    folders = [0]
    monkeypatch.setattr('orion_mini.companion_tools.locations_fingerprint', lambda: (('tools', folders[0]),))
    for _ in range(5):
        assert workspace.state()['setup']['platform'] == 'test'
    assert len(scans) == 1
    clock[0] += 10  # Nothing installed: the cheap folder check skips the PATH walk.
    workspace.state()
    workspace._tools_refresh_thread.join(timeout=2)
    assert len(scans) == 1
    folders[0] += 1  # A tool installed meanwhile shows up within ten seconds.
    clock[0] += 10
    workspace.state()
    workspace._tools_refresh_thread.join(timeout=2)
    assert len(scans) == 2


def test_periodic_tool_probe_does_not_block_fresh_setup_state(tmp_path, monkeypatch):
    import threading
    workspace = LinkWorkspace(tmp_path)
    workspace._tools = (0, {'tools': {}, 'platform': 'previous'})
    started, release = threading.Event(), threading.Event()
    def probe():
        started.set()
        assert release.wait(2)
        return {'tools': {}, 'platform': 'refreshed'}
    monkeypatch.setattr(setup_guide, 'tools', probe)
    try:
        assert workspace.setup_state()['platform'] == 'previous'
        assert started.wait(1)
        # The UI continues checking actual setup preferences during discovery.
        workspace.settings['setup'] = {'completed': True}
        assert workspace.setup_state()['completed'] is True
        assert workspace._tools_refresh_thread.is_alive()
    finally:
        release.set()
        workspace._tools_refresh_thread.join(timeout=2)
    assert workspace.setup_state()['platform'] == 'refreshed'


def test_inline_mms_picture_is_hashed_once_per_file_version(tmp_path, monkeypatch):
    picture = tmp_path / 'IMG.jpg'
    picture.write_bytes(b'synthetic picture')
    row = {'id': 'a', 'device_id': 'phone', 'thread': 1, 'message': 2, 'part': 3, 'name': 'IMG.jpg', 'mime': 'image/jpeg',
           'size': picture.stat().st_size, 'path': str(picture), 'sha256': hashlib.sha256(picture.read_bytes()).hexdigest()}
    hashed = []
    real = phone_features.file_sha256
    monkeypatch.setattr(phone_features, 'file_sha256', lambda path: hashed.append(path) or real(path))
    monkeypatch.setattr(phone_features, '_previews', {})
    views = [phone_features.PhoneFeatures._attachment_view(row) for _ in range(5)]
    assert views[0]['preview'] == 'data:image/jpeg;base64,' + base64.b64encode(b'synthetic picture').decode()
    assert all(view == views[0] for view in views) and len(hashed) == 1
    # Different bytes on disk are checked again, and a mismatch shows no picture.
    picture.write_bytes(b'synthetic pictures')
    os.utime(picture, ns=(picture.stat().st_atime_ns, picture.stat().st_mtime_ns + 1_000_000))
    changed = phone_features.PhoneFeatures._attachment_view(row)
    assert 'preview' not in changed and changed['ready'] is True
    picture.unlink()
    assert phone_features.PhoneFeatures._attachment_view(row)['ready'] is False


def test_a_snapshot_reads_the_store_over_one_connection(tmp_path, monkeypatch):
    import sqlite3
    from orion_mini.storage import Store
    store = Store(tmp_path)
    store.save('note', {'id': 'a', 'text': 'synthetic'})
    opened = []
    real = sqlite3.connect
    # Count only this store's file: other tests' daemon threads may still use theirs.
    monkeypatch.setattr('orion_mini.storage.sqlite3.connect',
                        lambda *a, **k: (opened.append(1) if str(a[0]) == str(store.path) else None) or real(*a, **k))
    with store.reading():
        assert store.get('note', 'a')['text'] == 'synthetic'
        assert [row['id'] for row in store.all('note')] == ['a']
        with store.connect() as db:
            db.execute('BEGIN')  # Each access still ends its own transaction.
            db.execute('SELECT 1')
        store.save('note', {'id': 'b', 'text': 'written inside'})
    assert len(opened) == 1
    assert {row['id'] for row in store.all('note')} == {'a', 'b'}  # Committed, visible to a new connection.
