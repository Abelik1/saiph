# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bounded direct mesh blobs, authenticated with existing Orion device signatures."""
from __future__ import annotations
import hashlib
import ipaddress
import json
import socket
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID, uuid4
from .hub_client import signed, signed_headers

MAX_CLIPBOARD = 25 * 1024 * 1024
def mesh_address(value):
    address = ipaddress.ip_address(value)
    network = ipaddress.ip_network('100.64.0.0/10') if address.version == 4 else ipaddress.ip_network('fd7a:115c:a1e0::/48')
    if address not in network: raise ValueError('Peer requires a mesh address')
    return str(address)

def local_mesh_address(origin='http://100.64.0.1:8765'):
    from urllib.parse import urlsplit
    from .link_client import mesh_url
    mesh_url(origin)
    target = urlsplit(origin)
    routes = socket.getaddrinfo(target.hostname, target.port or 80, type=socket.SOCK_DGRAM)
    for family, kind, protocol, _, destination in routes:
        try:
            with socket.socket(family, kind, protocol) as sock:
                sock.connect(destination)
                return mesh_address(sock.getsockname()[0])
        except OSError:
            continue
    raise OSError('A private network route to this server is unavailable.')

class Blobs:
    def __init__(self, root):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.items = {}; self.lock = threading.RLock()
        # Old unadvertised cache data cannot be served after process restart.
        for path in self.root.glob('*'):
            if path.is_file() and len(path.name) == 36: path.unlink(missing_ok=True)
    def prune(self):
        for ident, (path, until, size) in list(self.items.items()):
            if until < time.time():
                path.unlink(missing_ok=True); self.items.pop(ident, None)
    def add(self, data):
        if len(data) > MAX_CLIPBOARD: raise ValueError('Clipboard image must become a file send')
        with self.lock:
            self.prune()
            while len(self.items) >= 8:
                ident = next(iter(self.items)); self.items.pop(ident)[0].unlink(missing_ok=True)
            ident = str(uuid4()); path = self.root / ident
            path.write_bytes(data)
            self.items[ident] = (path, time.time() + 300, len(data))
            return ident
    def get(self, ident):
        with self.lock:
            self.prune()
            item = self.items.get(ident)
            return item[0] if item else None
    def clear(self):
        with self.lock:
            for path, _, _ in self.items.values(): path.unlink(missing_ok=True)
            self.items.clear()

class PeerServer:
    def __init__(self, root, config, address=None, port=8766, cache_dir='peer-cache'):
        self.root, self.config = Path(root), config
        self.address = mesh_address(address or local_mesh_address(config['base_url']))
        self.blobs = Blobs(self.root / cache_dir)
        owner = self; slots = threading.BoundedSemaphore(8)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                if not slots.acquire(blocking=False): self.send_error(503); return
                try:
                    mesh_address(self.client_address[0])
                    prefix = f'/v1/peer/{owner.config["device_id"]}/blobs/'
                    if not self.path.startswith(prefix): self.send_error(404); return
                    ident = self.path[len(prefix):]
                    if str(UUID(ident)) != ident: self.send_error(404); return
                    path = owner.blobs.get(ident)
                    if path is None: self.send_error(404); return
                    proof = {name: self.headers.get(name, '') for name in ('X-Orion-Device-Id','X-Orion-Timestamp','X-Orion-Nonce','X-Orion-Signature')}
                    if any(not value or len(value) > 1024 for value in proof.values()): self.send_error(401); return
                    signed(owner.root, owner.config, '/v1/link/peer/verify', 'POST', {'path': self.path, 'headers': proof})
                    with path.open('rb') as data:
                        self.send_response(200); self.send_header('Content-Type','application/octet-stream')
                        self.send_header('Content-Length',str(path.stat().st_size)); self.end_headers()
                        while chunk := data.read(65536): self.wfile.write(chunk)
                except (ValueError, OSError, RuntimeError):
                    # Errors never include request headers, response data or content.
                    self.send_error(403)
                finally: slots.release()
        class Server(ThreadingHTTPServer):
            address_family = socket.AF_INET6 if ':' in owner.address else socket.AF_INET
        self.server = Server((self.address, port), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, name='orion-peer', daemon=True)
        self.thread.start()
    def offer(self, data):
        return {'id': self.blobs.add(data), 'address': self.address, 'port': self.port}
    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.blobs.clear()

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_): return None

def fetch(root, config, source, payload):
    blob = payload['blob']; address = mesh_address(blob['address']); ident = blob['id']
    if str(UUID(ident)) != ident or not 1024 <= blob['port'] <= 65535: raise ValueError('Invalid peer resource')
    size = payload['size']
    if type(size) is not int or not 0 <= size <= MAX_CLIPBOARD: raise ValueError('Clipboard exceeds its size limit')
    path = f'/v1/peer/{source}/blobs/{ident}'
    host = f'[{address}]' if ':' in address else address
    request = urllib.request.Request(f'http://{host}:{blob["port"]}{path}', headers=signed_headers(root,config['device_id'],path))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=20) as response:
            if int(response.headers.get('Content-Length','-1')) != size: raise ValueError('Peer size mismatch')
            data = response.read(size + 1)
        if len(data) != size or hashlib.sha256(data).hexdigest() != payload['sha256']: raise ValueError('Peer content mismatch')
        return data
    except (OSError, urllib.error.URLError): raise ValueError('Direct clipboard transfer is unavailable') from None
