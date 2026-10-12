# SPDX-License-Identifier: AGPL-3.0-or-later
"""Disposable TLS JWKS fixture; never run against real accounts or credentials."""
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import ssl


class Issuer(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path != "/.well-known/jwks.json":
            self.send_response(404)
            self.end_headers()
            return
        body = Path("/fixture/jwks.json").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


server = HTTPServer(("0.0.0.0", 443), Issuer)
tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
tls.load_cert_chain("/fixture/issuer.crt", "/fixture/issuer.key")
server.socket = tls.wrap_socket(server.socket, server_side=True)
server.serve_forever()
