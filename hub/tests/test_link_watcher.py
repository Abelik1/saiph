# SPDX-License-Identifier: AGPL-3.0-or-later
"""SQLite watcher shutdown must not close a connection in an active worker."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

from orion_hub import link


def test_close_waits_for_inflight_query_and_prevents_late_connection(monkeypatch, tmp_path):
    started, release, close_started, closed = Event(), Event(), Event(), Event()
    calls = []

    class Connection:
        def execute(self, statement):
            calls.append(statement)
            started.set()
            assert release.wait(3)
            assert not closed.is_set()
            return self

        def fetchone(self):
            return (1,)

        def close(self):
            closed.set()

    connection = Connection()
    # Cursor cleanup must be distinct from connection cleanup.
    cursor = SimpleNamespace(fetchone=connection.fetchone, close=lambda: None)
    execute = connection.execute
    connection.execute = lambda statement: (execute(statement), cursor)[1]
    monkeypatch.setattr(link.sqlite3, "connect", lambda *args, **kwargs: connection)
    reader = link.DataVersionReader(tmp_path / "synthetic.db")
    with ThreadPoolExecutor(max_workers=2) as pool:
        reading = pool.submit(reader.read)
        assert started.wait(3)
        def close():
            close_started.set()
            reader.close()
        closing = pool.submit(close)
        try:
            assert close_started.wait(3)
            assert not closed.wait(0.05), "Connection closed while SQLite was executing"
        finally:
            release.set()
        assert reading.result(timeout=3) == 1
        closing.result(timeout=3)
    assert closed.is_set()
    assert reader.read() is None
    assert calls == ["PRAGMA data_version"]
    reader.close()


def test_cancelled_watcher_finishes_worker_before_closing(monkeypatch, tmp_path):
    started, release, closed = Event(), Event(), Event()

    class Reader:
        def __init__(self, path):
            pass
        def read(self):
            started.set()
            assert release.wait(3)
            assert not closed.is_set()
            return 1
        def close(self):
            # Production reader's lock ensures this is safe even if queued
            # worker operations outlive cancellation of their asyncio futures.
            assert release.wait(3)
            closed.set()

    monkeypatch.setattr(link, "DataVersionReader", Reader)
    async def run():
        bus = link.Bus(SimpleNamespace(path=tmp_path / "synthetic.db"))
        bus.sessions["synthetic"] = SimpleNamespace(wake=asyncio.Event())
        watcher = asyncio.create_task(bus.watch())
        assert await asyncio.to_thread(started.wait, 3)
        watcher.cancel()
        await asyncio.sleep(0.01)
        assert not closed.is_set()
        release.set()
        result = await asyncio.gather(watcher, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert closed.is_set()
    asyncio.run(run())
