# SPDX-License-Identifier: AGPL-3.0-or-later
"""One process/event bus, with loopback and optional mesh listeners."""
from __future__ import annotations

import ipaddress
import logging
import os
import socket

import uvicorn

from .link import MAX_FRAME_BYTES, MESH_V4, MESH_V6


def listener_hosts():
    hosts = ["127.0.0.1"]
    mesh = os.environ.get("ORION_HUB_MESH_IP", "")
    if mesh:
        address = ipaddress.ip_address(mesh)
        if address not in (MESH_V4 if address.version == 4 else MESH_V6):
            raise ValueError("ORION_HUB_MESH_IP must be a Tailscale mesh address")
        hosts.append(str(address))
    return hosts


def listener_port():
    value = os.environ.get("ORION_HUB_PORT", "8765")
    if not value.isdecimal() or not 1024 <= int(value) <= 65535:
        raise ValueError("ORION_HUB_PORT must be an unprivileged port")
    return int(value)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    listeners = []
    try:
        for host in listener_hosts():
            sock = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM)
            listeners.append(sock)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, listener_port()))
            sock.listen(128)
            sock.setblocking(False)
        config = uvicorn.Config("orion_hub.app:app", proxy_headers=True, forwarded_allow_ips="127.0.0.1",
                                access_log=False, ws_max_size=MAX_FRAME_BYTES, ws_ping_interval=15, ws_ping_timeout=30)
        uvicorn.Server(config).run(sockets=listeners)
    finally:
        for sock in listeners:
            sock.close()


if __name__ == "__main__":
    main()
