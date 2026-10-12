# SPDX-License-Identifier: AGPL-3.0-or-later
"""The probe's reconnect loop and recipient deduplication, without network access."""
import asyncio
import json
import time
from uuid import uuid4

import pytest

from orion_mini import link_client


def test_mesh_url_refuses_public_lan_and_credential_urls(monkeypatch):
    monkeypatch.setattr(link_client.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("100.64.0.1", 8765))])
    assert link_client.mesh_url("http://pi.orion.internal:8765") == "ws://pi.orion.internal:8765/v1/link"
    for url in ["http://user:pass@pi:8765", "http://pi:8765/v1", "http://pi:8765?x=1", "ws://pi:8765"]:
        with pytest.raises(ValueError):
            link_client.mesh_url(url)
    for address in ["192.168.1.19", "127.0.0.1", "1.1.1.1"]:
        monkeypatch.setattr(link_client.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (address, 8765))])
        with pytest.raises(ValueError):
            link_client.mesh_url("http://pi:8765")


def test_received_duplicate_is_acked_without_reprocessing(tmp_path, monkeypatch):
    monkeypatch.setattr(link_client, "mesh_url", lambda _: "ws://mesh/v1/link")
    event = {"op": "event", "id": str(uuid4()), "expires_at": time.time() + 60, "payload": {}}
    processed, sent = [], []

    class Socket:
        def __aiter__(self):
            async def messages():
                for value in [event, event]:
                    yield json.dumps(value)
            return messages()
        async def send(self, value):
            sent.append(json.loads(value))

    async def process(value):
        processed.append(value)

    client = link_client.LinkClient(tmp_path, "device", "mesh", process)
    asyncio.run(client.receive(Socket()))
    assert processed == [event]
    assert sent == [{"op": "ack", "id": event["id"]}] * 2


def test_reconnect_resigns_and_retries_original_id(tmp_path, monkeypatch):
    monkeypatch.setattr(link_client, "mesh_url", lambda _: "ws://mesh/v1/link")
    signatures, sent = [], []
    event = {"id": str(uuid4()), "type": "test", "ttl_seconds": 60, "payload": {}}

    def sign(*a):
        value = {"nonce": str(uuid4())}
        signatures.append(value)
        return value
    monkeypatch.setattr(link_client, "signed_headers", sign)

    async def exercise():
        received = asyncio.Event()

        class Socket:
            async def send(self, value):
                value = json.loads(value)
                if value["op"] == "publish":
                    sent.append(value["event"])
                    if len(sent) > 1:
                        received.set()
            def __aiter__(self):
                async def messages():
                    # First connection closes before the producer acknowledgement.
                    if len(signatures) == 1:
                        while not sent:
                            await asyncio.sleep(0)
                        return
                    await asyncio.Future()
                    yield "{}"
                return messages()

        class Connection:
            async def __aenter__(self): return Socket()
            async def __aexit__(self, *a): pass

        monkeypatch.setattr(link_client, "connect", lambda *a, **k: Connection())
        async def process(_): pass
        client = link_client.LinkClient(tmp_path, "device", "mesh", process)
        client.publish(event)
        task = asyncio.create_task(client.run())
        try:
            await asyncio.wait_for(received.wait(), timeout=3)
            assert sent == [event, event]
            assert len(signatures) == 2 and signatures[0] != signatures[1]
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())


def test_changed_capabilities_are_advertised_without_reconnecting(tmp_path, monkeypatch):
    monkeypatch.setattr(link_client, "mesh_url", lambda _: "ws://mesh/v1/link")
    frames=[]
    async def process(_):pass
    client=link_client.LinkClient(tmp_path,"device","mesh",process,capabilities=["clipboard","files"])
    async def pause(_):
        if not frames or frames[-1].get("op")!="hello":client.capabilities=["files"]
        else:raise asyncio.CancelledError()
    class Socket:
        async def send(self,value):frames.append(json.loads(value))
    monkeypatch.setattr(link_client.asyncio,"sleep",pause)
    with pytest.raises(asyncio.CancelledError):asyncio.run(client.transmit(Socket()))
    assert [frame for frame in frames if frame["op"]=="hello"]==[{"op":"hello","capabilities":["files"]}]
