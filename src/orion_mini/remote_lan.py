# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone remote over the local network: the touchpad and keyboard without a cloud round trip.

Saiph Cloud's mailbox is polled, so a swipe took seconds to move the pointer. When the
phone and this computer share a private network the phone asks for a direct channel
(`remote.lan.request`, sealed in the account's usual envelope) and this computer answers
with a one-use invitation (`remote.lan`): the same design as the phone camera, phone
screen and file transfers. An ephemeral P-256 certificate pinned by the invitation, a
256-bit bearer secret that works once, literal private IPv4 addresses and a short
claim window. The invitation travels only inside an envelope for that one approved
phone, so the connection is that phone, and every command still passes the same
`Remote.command` checks (allowed phones, enabled apps, rate limits) as on the
Cloud route. Nothing is recorded, and invitations and commands are never logged.

Messages on the socket (JSON text, each at most `MAX_MESSAGE` bytes):
  phone -> computer  {"t": "cmd", "c": <a remote.command body>}
                     {"t": "hb"}                        every few seconds while idle
  computer -> phone  {"t": "result", "app", "control", "ok", "message"}   failures and button results
"""
from __future__ import annotations

import hmac
import json
import secrets
import threading
import time

from websockets.sync.server import serve

from .camera_session import lan_addresses, local_address, tls_context
from .lan_relay import listen

CLAIM_SECONDS = 60  # The invitation works once, for this long.
IDLE_SECONDS = 20  # The phone sends a heartbeat at least every five seconds.
SESSION_SECONDS = 4 * 3600
MAX_MESSAGE = 4096
MAX_SESSIONS = 4  # One per approved phone; the oldest goes first.


class _Session:
    def __init__(self, device):
        self.device = device
        self.id = secrets.token_hex(16)
        self.secret = secrets.token_urlsafe(32)
        self.server = self.connection = self.relay = None
        self.state = "waiting"
        self.deadline = 0.0
        self.last_message = 0.0


class RemoteLan:
    def __init__(self, remote, *, addresses=lan_addresses, clock=time.monotonic):
        self.remote, self.addresses, self.clock = remote, addresses, clock
        self.lock = threading.RLock()
        self.sessions = {}  # device id -> _Session

    # -------------------------------------------------------------- offers
    def offer(self, device) -> dict | None:
        """A fresh invitation for one allowed phone, or None when this network cannot host one."""
        if not self.remote.allowed(device):
            return None
        addresses = self.addresses()
        if not addresses or any(not local_address(value) for value in addresses):
            return None
        self.close(device)
        with self.lock:
            while len(self.sessions) >= MAX_SESSIONS:
                self._close_locked(next(iter(self.sessions)))
            session = _Session(device)
            self.sessions[device] = session
        try:
            tls, fingerprint = tls_context(addresses, "Saiph Phone Remote")
            made = []

            def bind(host):
                made.append(serve(lambda connection: self._receive(session, connection), host, 0, ssl=tls, max_size=MAX_MESSAGE,
                                  max_queue=8, open_timeout=5, close_timeout=1, compression=None,
                                  process_request=lambda connection, request: self._authorize(session, connection, request)))
                return made[-1].socket.getsockname()[1]
            port, relay = listen(bind, lambda: made.pop().socket.close())
            with self.lock:
                session.server, session.relay = made[-1], relay
                session.deadline = self.clock() + CLAIM_SECONDS
            threading.Thread(target=session.server.serve_forever, name="orion-remote-tls", daemon=True).start()
            threading.Thread(target=self._monitor, args=(session,), name="orion-remote-expiry", daemon=True).start()
        except Exception:
            self.close(device)
            return None
        return {"session": session.id, "addresses": addresses, "port": port, "certificate": fingerprint,
                "secret": session.secret, "expires": int(time.time()) + CLAIM_SECONDS}

    def _authorize(self, session, connection, request):
        with self.lock:
            if (self.sessions.get(session.device) is not session or session.state != "waiting"
                    or self.clock() >= session.deadline or request.path != "/remote/" + session.id
                    or len(request.headers.get_all("Authorization")) != 1
                    or not hmac.compare_digest(request.headers["Authorization"].encode("utf-8"),
                                               ("Bearer " + session.secret).encode("ascii"))):
                return connection.respond(403, "Phone remote invitation is unavailable.\n")
            # Claim before the upgrade: two clients cannot both use the one-use secret.
            session.state, session.connection, session.secret = "live", connection, ""
            session.last_message = self.clock()
            session.deadline = session.last_message + SESSION_SECONDS
        return None

    # ------------------------------------------------------------ messages
    def _receive(self, session, connection):
        def reply(target, kind, value):
            if kind == "remote.result":
                self._send(session, connection, {"t": "result", **{k: value.get(k) for k in ("app", "control", "ok", "message")}})
        try:
            with self.lock:
                if session.connection is not connection:
                    return
            for text in connection:
                if type(text) is not str or len(text) > MAX_MESSAGE:
                    break
                try:
                    message = json.loads(text)
                except ValueError:
                    break
                with self.lock:
                    if self.sessions.get(session.device) is not session or session.connection is not connection:
                        break
                    session.last_message = self.clock()
                if type(message) is not dict:
                    break
                if message.get("t") == "hb":
                    continue
                if message.get("t") != "cmd" or type(message.get("c")) is not dict:
                    break
                # The same checks and answers as a command that came by Saiph Cloud.
                self.remote.event({"type": "remote.command", "payload": message["c"], "source": session.device}, reply)
        except Exception:
            pass  # Deliberately silent: no URLs, secrets or commands in logs.
        finally:
            self._close_if(session, connection)

    def _send(self, session, connection, message):
        try:
            connection.send(json.dumps(message, separators=(",", ":")))
        except Exception:
            self._close_if(session, connection)

    # ------------------------------------------------------------ lifetime
    def _monitor(self, session):
        while True:
            time.sleep(0.5)
            with self.lock:
                if self.sessions.get(session.device) is not session:
                    return
                now = self.clock()
                gone = (now >= session.deadline if session.state == "waiting" else
                        now >= session.deadline or now - session.last_message > IDLE_SECONDS)
            if gone:
                self.close(session.device)
                return

    def _close_if(self, session, connection):
        with self.lock:
            current = self.sessions.get(session.device) is session and session.connection is connection
        if current:
            self.close(session.device)

    def close(self, device=None):
        """End one phone's channel, or all of them."""
        with self.lock:
            for key in [device] if device is not None else list(self.sessions):
                self._close_locked(key)

    def _close_locked(self, device):
        session = self.sessions.pop(device, None)
        if session is None:
            return
        session.secret = ""
        # Shutting down can wait on the handler thread that called us; never block this lock on it.
        threading.Thread(target=self._shutdown, args=(session,), name="orion-remote-close", daemon=True).start()

    @staticmethod
    def _shutdown(session):
        for step in (lambda: session.connection and session.connection.close(), lambda: session.server and session.server.shutdown(),
                     lambda: session.relay and session.relay.close()):
            try:
                step()
            except Exception:
                pass

    def status(self):
        with self.lock:
            return {"phones": sorted(device for device, session in self.sessions.items() if session.state == "live")}

    def live(self, device) -> bool:
        with self.lock:
            session = self.sessions.get(device)
            return session is not None and session.state == "live"
