# SPDX-License-Identifier: AGPL-3.0-or-later
"""Exercise the actual desktop transport over local WebSockets, without a phone."""
import asyncio
import json
import time
from uuid import uuid4

from websockets.asyncio.server import serve

from orion_mini import link_client


def test_reconnect_reuses_pending_event_id_and_deduplicates_incoming_replay(tmp_path, monkeypatch):
    async def scenario():
        published = []
        signed_nonces = []
        processed = []
        ack_count = 0
        completed = asyncio.Event()
        received_id = str(uuid4())
        connections = 0

        async def server(socket):
            nonlocal connections, ack_count
            connections += 1
            current = connections
            signed_nonces.append(socket.request.headers["X-Orion-Nonce"])
            await socket.send(json.dumps({"op": "welcome", "device_id": "device-test"}))
            assert json.loads(await socket.recv())["op"] == "hello"
            async for raw in socket:
                frame = json.loads(raw)
                if frame["op"] == "publish":
                    published.append(frame["event"])
                    if current == 1:
                        # Hub dies after receiving the frame but before publisher ACK.
                        await socket.close(1012, "Service restart")
                        return
                    await socket.send(json.dumps({"op": "accepted", "id": frame["event"]["id"], "duplicate": True}))
                    incoming = {"op": "event", "id": received_id, "type": "diagnostic.probe", "source": "other-test",
                                "created_at": time.time(), "expires_at": time.time() + 30, "payload": {}}
                    await socket.send(json.dumps(incoming))
                    await socket.send(json.dumps(incoming))
                elif frame["op"] == "ack":
                    assert frame["id"] == received_id
                    ack_count += 1
                    if ack_count == 2:
                        completed.set()

        async with serve(server, "127.0.0.1", 0) as listener:
            port = listener.sockets[0].getsockname()[1]
            monkeypatch.setattr(link_client, "mesh_url", lambda _: f"ws://127.0.0.1:{port}")
            async def received(event):
                processed.append(event["id"])
            client = link_client.LinkClient(tmp_path, "device-test", "http://100.64.0.1:8765", received)
            event = {"id": str(uuid4()), "type": "diagnostic.probe", "ttl_seconds": 30, "targets": ["other-test"], "payload": {}}
            client.publish(event)
            task = asyncio.create_task(client.run())
            try:
                await asyncio.wait_for(completed.wait(), timeout=8)
                assert len(published) == 2 and published[0] == published[1] == event
                assert len(set(signed_nonces)) == 2
                assert processed == [received_id] and ack_count == 2
                assert not client.pending
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


def test_expired_incoming_event_is_acknowledged_without_processing(tmp_path, monkeypatch):
    async def scenario():
        processed = []
        completed = asyncio.Event()
        expired_id = str(uuid4())
        async def server(socket):
            await socket.send(json.dumps({"op": "welcome", "device_id": "device-test"}))
            await socket.recv()  # hello
            await socket.send(json.dumps({"op": "event", "id": expired_id, "type": "diagnostic.probe", "source": "other-test",
                                          "created_at": time.time() - 120, "expires_at": time.time() - 60, "payload": {}}))
            async for raw in socket:
                frame = json.loads(raw)
                if frame["op"] == "ack":
                    assert frame["id"] == expired_id
                    completed.set()
        async with serve(server, "127.0.0.1", 0) as listener:
            port = listener.sockets[0].getsockname()[1]
            monkeypatch.setattr(link_client, "mesh_url", lambda _: f"ws://127.0.0.1:{port}")
            async def received(event):
                processed.append(event)
            client = link_client.LinkClient(tmp_path, "device-test", "http://100.64.0.1:8765", received)
            task = asyncio.create_task(client.run())
            try:
                await asyncio.wait_for(completed.wait(), timeout=5)
                assert processed == []
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


def test_discarded_copy_is_not_sent_after_a_preceding_send_yields(tmp_path, monkeypatch):
    async def scenario():
        monkeypatch.setattr(link_client, 'mesh_url', lambda _: 'ws://127.0.0.1:1/v1/link')
        client = link_client.LinkClient(tmp_path, 'device-test', 'http://100.64.0.1:8765', None)
        first = {'id': str(uuid4()), 'type': 'file.offer'}
        canceled = {'id': str(uuid4()), 'type': 'clipboard'}
        client.publish(first)
        client.publish(canceled)
        started, release, completed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        sent = []
        class Socket:
            async def send(self, raw):
                frame = json.loads(raw)
                if frame['op'] == 'publish':
                    sent.append(frame['event']['id'])
                    if frame['event']['id'] == first['id']:
                        started.set()
                        await release.wait()
                elif frame['op'] == 'ping': completed.set()
        task = asyncio.create_task(client.transmit(Socket()))
        try:
            await asyncio.wait_for(started.wait(), 2)
            client.discard(canceled['id'])
            release.set()
            await asyncio.wait_for(completed.wait(), 2)
            assert sent == [first['id']]
            assert set(client.pending) == {first['id']}
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


def test_reconnect_now_replaces_a_silent_socket_at_once(tmp_path, monkeypatch):
    # Physical acceptance: after a laptop resume the old socket stayed "open" until
    # the keepalive gave up, so the Hub saw the laptop again only 29.6 s later.
    async def scenario():
        connected = []
        second = asyncio.Event()

        async def server(socket):
            connected.append(time.monotonic())
            await socket.send(json.dumps({"op": "welcome", "device_id": "device-test"}))
            if len(connected) == 2:
                second.set()
            await socket.wait_closed()  # never answers or closes by itself: a half-open peer

        async with serve(server, "127.0.0.1", 0, ping_interval=None) as listener:
            port = listener.sockets[0].getsockname()[1]
            monkeypatch.setattr(link_client, "mesh_url", lambda _: f"ws://127.0.0.1:{port}")
            async def received(event):
                pass
            client = link_client.LinkClient(tmp_path, "device-test", "http://100.64.0.1:8765", received)
            task = asyncio.create_task(client.run())
            try:
                while not connected or client.socket is None:
                    await asyncio.sleep(0.05)
                kicked = time.monotonic()
                client.reconnect_now()
                await asyncio.wait_for(second.wait(), timeout=2)
                assert connected[1] - kicked < 1
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


def test_reconnect_now_skips_the_remaining_backoff(tmp_path, monkeypatch):
    async def scenario():
        attempts = []
        accepted = asyncio.Event()

        async def server(socket):
            attempts.append(time.monotonic())
            if len(attempts) <= 4:
                await socket.close(1012, "Service restart")  # backoff grows to about 4 s
                return
            accepted.set()
            await socket.wait_closed()

        async with serve(server, "127.0.0.1", 0, ping_interval=None) as listener:
            port = listener.sockets[0].getsockname()[1]
            monkeypatch.setattr(link_client, "mesh_url", lambda _: f"ws://127.0.0.1:{port}")
            client = link_client.LinkClient(tmp_path, "device-test", "http://100.64.0.1:8765", None)
            task = asyncio.create_task(client.run())
            try:
                while len(attempts) < 4:
                    await asyncio.sleep(0.05)
                await asyncio.sleep(0.3)
                kicked = time.monotonic()
                client.reconnect_now()  # e.g. the network came back
                await asyncio.wait_for(accepted.wait(), timeout=2)
                assert attempts[4] - kicked < 1
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


def test_quitting_closes_the_link_normally(tmp_path, monkeypatch):
    # Physical acceptance: quitting the app made the Hub log peer_code=1011
    # (internal error) because the cancelled link closed as if it had failed.
    async def scenario():
        codes = []
        connected = asyncio.Event()

        async def server(socket):
            await socket.send(json.dumps({"op": "welcome", "device_id": "device-test"}))
            connected.set()
            await socket.wait_closed()
            codes.append(socket.close_code)

        async with serve(server, "127.0.0.1", 0, ping_interval=None) as listener:
            port = listener.sockets[0].getsockname()[1]
            monkeypatch.setattr(link_client, "mesh_url", lambda _: f"ws://127.0.0.1:{port}")
            async def received(event):
                pass
            client = link_client.LinkClient(tmp_path, "device-test", "http://100.64.0.1:8765", received)
            task = asyncio.create_task(client.run())
            await asyncio.wait_for(connected.wait(), timeout=5)
            while client.socket is None:  # quit after the link is up, as the app does
                await asyncio.sleep(0.05)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            for _ in range(40):
                if codes:
                    break
                await asyncio.sleep(0.05)
            assert codes == [1000]
    asyncio.run(scenario())
