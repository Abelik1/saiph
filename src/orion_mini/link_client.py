# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phase 1 probe transport; stable event IDs across automatic reconnects."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import random
import socket
import time
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlsplit

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from .hub_client import signed_headers


def mesh_url(base: str) -> str:
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Use the hub's mesh HTTP(S) origin")
    networks = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    if not addresses or not all(any(ipaddress.ip_address(row[4][0]) in net for net in networks) for row in addresses):
        raise ValueError("The hub must resolve only to mesh addresses")
    return ("wss" if parsed.scheme == "https" else "ws") + "://" + parsed.netloc + "/v1/link"


class LinkClient:
    def __init__(self, root: Path, device_id: str, base_url: str, on_event, on_status=None, *, capabilities=None, on_connected=None):
        self.root, self.device_id = root, device_id
        self.url = mesh_url(base_url)
        self.on_event = on_event
        self.on_status = on_status or (lambda _: None)
        self.capabilities = capabilities or ["test"]
        self.on_connected = on_connected
        self.pending: dict[str, tuple[dict, float]] = {}
        self.seen: OrderedDict[str, float] = OrderedDict()
        self.outgoing = asyncio.Event()
        self.socket = None
        self.wake = asyncio.Event()

    def publish(self, event: dict):
        # Called on the client's event loop. Keep the original envelope on retry.
        if len(self.pending) >= 1000 and event["id"] not in self.pending:
            raise ValueError("Probe queue is full")
        self.pending.setdefault(event["id"], (event, time.time() + event.get("ttl_seconds", 60)))
        self.outgoing.set()

    def reconnect_now(self):
        """Drop a socket that may have died unseen and reconnect without backoff.

        After a resume or a network change the old TCP connection is usually gone
        while the keepalive still believes it; waiting for its timeout cost about
        30 s on a physical laptop. Called on the client's event loop."""
        self.wake.set()
        if self.socket is not None:
            self.socket.transport.abort()

    def discard(self, event_id: str):
        """Cancel an unaccepted local event; already-transmitted frames cannot be recalled."""
        self.pending.pop(event_id, None)

    async def transmit(self, ws):
        next_publish = next_ping = 0
        advertised = tuple(self.capabilities)
        while True:
            if tuple(self.capabilities) != advertised:
                advertised=tuple(self.capabilities)
                await ws.send(json.dumps({'op':'hello','capabilities':list(advertised)}))
            now = time.time()
            if now >= next_publish or self.outgoing.is_set():
                self.outgoing.clear()
                for event_id, (event, expires) in list(self.pending.items()):
                    if event_id not in self.pending:
                        continue  # Superseded while a preceding socket send awaited.
                    if now >= expires:
                        self.pending.pop(event_id, None)
                        self.on_status({"op": "expired", "id": event_id})
                    else:
                        await ws.send(json.dumps({"op": "publish", "event": event}, allow_nan=False))
                next_publish = now + 1
            if now >= next_ping:
                await ws.send('{"op":"ping"}')
                next_ping = now + 15
            await asyncio.sleep(0.25)

    async def receive(self, ws):
        async for text in ws:
            message = json.loads(text)
            op = message.get("op")
            if op == "event":
                now = time.time()
                self.seen = OrderedDict((k, v) for k, v in self.seen.items() if v > now - 86400)
                event_id = message["id"]
                if event_id not in self.seen and message["expires_at"] > now:
                    await self.on_event(message)
                    self.seen[event_id] = now
                    if len(self.seen) > 10000:
                        self.seen.popitem(last=False)
                await ws.send(json.dumps({"op": "ack", "id": event_id}))
            elif op == "accepted":
                self.pending.pop(message["id"], None)
                self.on_status(message)
            elif op in {"welcome", "presence", "error"}:
                self.on_status(message)
                if op == "welcome" and self.on_connected:
                    await self.on_connected()

    async def run(self):
        delay = 0.25
        while True:
            try:
                async with connect(self.url, additional_headers=signed_headers(self.root, self.device_id, "/v1/link"),
                                   max_size=65536, open_timeout=10, close_timeout=2, proxy=None) as ws:
                    started = time.monotonic()
                    self.socket = ws
                    self.wake.clear()
                    await ws.send(json.dumps({"op": "hello", "capabilities": self.capabilities}))
                    tasks = [asyncio.create_task(self.transmit(ws)), asyncio.create_task(self.receive(ws))]
                    try:
                        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                        for task in done:
                            task.result()
                    except asyncio.CancelledError:
                        # Quitting is a normal close; websockets would report a cancelled
                        # block to the Hub as an internal error (1011).
                        await ws.close()
                        raise
                    finally:
                        self.socket = None
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                    if time.monotonic() - started > 10:
                        delay = 0.25
            except (OSError, WebSocketException, asyncio.TimeoutError):
                # Errors can contain server replies. Report only a fixed status.
                pass
            self.on_status({"op": "reconnecting"})
            try:
                await asyncio.wait_for(self.wake.wait(), delay + random.uniform(0, delay / 4))
            except asyncio.TimeoutError:
                pass
            if self.wake.is_set():
                self.wake.clear()
                delay = 0.25
            else:
                delay = min(delay * 2, 10)
