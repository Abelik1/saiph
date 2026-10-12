# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations
import ipaddress, socket
from urllib.parse import urlparse

def validate_watch_url(url:str, allow_http:bool=False)->str:
    p=urlparse(url)
    schemes={"https"} | ({"http"} if allow_http else set())
    if p.scheme not in schemes or not p.hostname or p.username or p.password: raise ValueError("Only normal HTTPS URLs are allowed")
    if p.port and p.port not in ({443} if p.scheme=="https" else {80}): raise ValueError("Non-standard ports are blocked")
    try: infos=socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=="https" else 80),type=socket.SOCK_STREAM)
    except socket.gaierror as e: raise ValueError("Host does not resolve") from e
    for info in infos:
        ip=ipaddress.ip_address(info[4][0])
        if not ip.is_global: raise ValueError("Private, loopback, link-local, multicast, and reserved hosts are blocked")
    return url
