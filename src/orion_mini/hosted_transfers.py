# SPDX-License-Identifier: AGPL-3.0-or-later
"""Saiph Cloud file sends that survive a short network drop.

Each file becomes one memory-only job. Its prepared ciphertext and sealed offer
event are reused for every retry, so the relay deduplicates the blob, chunks and
event and the recipient sees exactly one offer. An upload resumes after its last
confirmed chunk. A job retries with backoff for up to ten minutes, and at once
when Saiph Cloud is reachable again; then it fails visibly and can be retried.

An offer which may already have been published is never re-encrypted under a
new event, because the recipient could then see two. Uploads use their own
transport, so a slow upload does not hold the scheduler's lock.

Ciphertext in hosted/outgoing is removed on success, on final failure and when
the app starts. File names and paths stay on this computer; nothing is logged.

When this computer is on a private network, a file first goes directly to the
recipient over it (lan_files.py): a sealed "file" offer invites that one device
to a pinned TLS listener here. It is "Sent" only once the recipient confirms
the exact size and SHA-256. If the recipient cannot connect, says so or does not
answer within `LAN_WAIT` seconds, a file up to the Cloud limit continues with
Saiph Cloud as above; a larger one fails with what to do. Once the recipient has
connected, a dropped connection resumes for up to lan_files.RESUME_SECONDS, then
the send fails visibly with Retry.
"""
from __future__ import annotations

import math
import mimetypes
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from . import hosted_files
from . import lan_files
from .hosted_crypto import EnvelopeError
from .hosted_files import CHUNK_BYTES, MAX_CIPHERTEXT, AttachmentError
from .hosted_keys import _no_links
from .hosted_tokens import HostedUnavailable, SignInRequired
from .hosted_transport import TransportError

MAX_PLAINTEXT = MAX_CIPHERTEXT - 4096  # 20 967 424 bytes; the sealed stream adds up to 4 KiB.
RETRY_DELAYS = (2, 4, 8, 15)  # Seconds between attempts; then every 15 seconds.
TRUST_WAITS = (0.05, 0.1, 0.2, 0.4, 0.8, 1.6)  # Seconds to wait out a roster refresh mid-upload.
RETRY_SECONDS = 600  # Give up ten minutes after the first attempt.
FRESH_SECONDS = 60  # Re-encrypt an unpublished offer with less than this left for the recipient.
SENT_SECONDS = 20  # "Sent to …" stays this long.
MAX_JOBS = 50
SEALED = ".orion-sealed"
ACTIVE = ("queued", "connecting", "sending", "retrying")
LAN_WAIT = 30  # Seconds a recipient has to connect before a small file goes through Saiph Cloud.
OFFLINE = "Saiph Cloud is unreachable. Saiph will retry when you are back online."


def megabytes(size, *, up=False) -> str:
    rounded = (math.ceil if up else math.floor)(size / 1_048_576 * 10) / 10
    return f"{rounded:.1f}"


def too_large(size) -> str:
    return (f"Saiph Cloud sends files up to {megabytes(MAX_PLAINTEXT)} MB. "
            f"This file is {megabytes(size, up=True)} MB. Nothing was sent.")


def needs_network(size, device, *, refused=False) -> str:
    """A file over the Cloud limit, and the recipient never connected directly: say what lets it through."""
    reason = f"{device} couldn't reach this computer" if refused else f"{device} didn't answer"
    return (f"{reason} on your network. Saiph Cloud sends files up to {megabytes(MAX_PLAINTEXT)} MB and this file is "
            f"{megabytes(size, up=True)} MB, so both devices must be on the same Wi-Fi or network with Saiph open. "
            "Nothing was sent.")


def no_network(size) -> str:
    """A file over the Cloud limit, and this computer has no private network to send it directly."""
    return (f"Saiph Cloud sends files up to {megabytes(MAX_PLAINTEXT)} MB. This file is {megabytes(size, up=True)} MB: "
            "connect this computer to the same Wi-Fi or network as the other device to send it directly. "
            "Nothing was sent.")


def remove_orphans(*folders):
    """Ciphertext left by a closed or crashed app; no job can still use it."""
    for folder in folders:
        try:
            entries = [path for path in Path(folder).iterdir() if path.name.endswith(SEALED)]
        except OSError:
            continue
        for path in entries:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass  # At worst opaque ciphertext remains until the next start.


class _Later(Exception):
    def __init__(self, text, *, fresh=False):
        super().__init__(text)
        self.text, self.fresh = text, fresh


class _Final(Exception):
    def __init__(self, text):
        super().__init__(text)
        self.text = text


@dataclass(eq=False)
class Transfer:
    id: str
    source: Path
    target: str
    name: str
    size: int
    notify: bool = False
    state: str = "queued"
    started: float = 0.0
    next_at: float = 0.0
    attempts: int = 0
    confirmed: int = 0  # Chunks the relay accepted for the current prepared upload.
    prepared: object = None
    published: bool = False  # The offer was handed to the relay at least once.
    allocated: bool = False  # The relay holds (part of) this prepared blob.
    error: str = ""
    finished: float = 0.0
    route: str = ""  # "lan" first when this computer is on a private network, else "cloud".
    lan: object = None  # The LanFileServer of the current direct offer.
    offer: str = ""  # Its sealed offer's ID, which a recipient's refusal names.
    lan_until: float = 0.0
    refused: str = ""  # The recipient's reason, when it refused the direct offer.

    def chunks(self) -> int:
        size = self.prepared.descriptor["size"] if self.prepared is not None else self.size + 4096
        return max(1, (size + CHUNK_BYTES - 1) // CHUNK_BYTES)


class HostedTransfers:
    """Queued Cloud file sends for one controller; one upload at a time."""

    background = True  # Tests drive run_due() themselves.

    def __init__(self, controller, *, monotonic=time.monotonic):
        self.c = controller
        self.monotonic = monotonic
        self.jobs: dict[str, Transfer] = {}
        self.lock = threading.RLock()
        self._wake = threading.Event()
        self._thread = None
        self._reported = 0.0
        remove_orphans(self.outgoing, controller.folder / "clipboard-outgoing")

    @property
    def outgoing(self) -> Path:
        return self.c.folder / "outgoing"

    # ---------------------------------------------------------------- queue
    def add(self, source: Path, target: str, *, notify=False) -> Transfer:
        with self.lock:
            if sum(job.state in ACTIVE for job in self.jobs.values()) >= MAX_JOBS:
                raise ValueError(f"Saiph is already sending {MAX_JOBS} files. Wait for them to finish.")
            job = Transfer(str(uuid4()), source, target, source.name, source.stat().st_size, notify)
            job.route = self._route(job)
            self.jobs[job.id] = job
        self._kick()
        return job

    def retry(self, job_id) -> Transfer:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None or job.state != "failed":
                raise ValueError("This transfer is no longer available.")
            if not job.source.is_file():
                raise ValueError("This file is no longer on this computer.")
            size = job.source.stat().st_size
            job.size = size
            route = self._route(job)
            if route == "cloud" and size > MAX_PLAINTEXT:
                raise ValueError(no_network(size))
            job.state, job.error, job.route = "queued", "", route
            job.started = job.next_at = job.finished = 0.0
            job.attempts = job.confirmed = 0
            job.published = False
        self._kick()
        return job

    def dismiss(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise ValueError("This transfer is no longer available.")
            if job.state in ACTIVE:
                raise ValueError("This transfer is still sending.")
            self.jobs.pop(job_id)

    def _route(self, job) -> str:
        """Directly over the network when this computer has a private address and the name suits both platforms."""
        if not lan_files.valid_filename(job.name):
            return "cloud"
        try:
            return "lan" if self.c.lan_addresses() else "cloud"
        except Exception:
            return "cloud"

    def refused(self, source, offer_id, reason):
        """The recipient cannot use our direct offer; the next pass falls back at once."""
        now = self.monotonic()
        with self.lock:
            job = next((job for job in self.jobs.values() if job.offer == offer_id and job.target == source
                        and job.route == "lan" and job.state in ACTIVE), None)
            if job is None:
                return
            job.refused, job.next_at = reason, now
        self._kick()

    def lan_waiting(self) -> bool:
        """A direct offer waits for its recipient: poll Saiph Cloud often for its answer."""
        with self.lock:
            return any(job.route == "lan" and job.state == "connecting" for job in self.jobs.values())

    def online(self):
        """Saiph Cloud answered again: retry waiting jobs now rather than at their next backoff."""
        now = self.monotonic()
        with self.lock:
            waiting = [job for job in self.jobs.values() if job.state == "retrying" and job.next_at > now]
            for job in waiting:
                job.next_at = now
        if waiting:
            self._kick()

    def cancel_all(self, text):
        """Hosted stopped (off, signed out, forgotten or closing): nothing more is uploaded."""
        with self.lock:
            for job in self.jobs.values():
                if job.state in ACTIVE:
                    self._finish(job, "failed", text, alert=False)

    # --------------------------------------------------------------- worker
    def _kick(self):
        self._wake.set()
        if not self.background:
            return
        with self.lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="orion-hosted-files", daemon=True)
                self._thread.start()

    def _run(self):
        while True:
            self._wake.clear()
            try:
                wait = self.run_due()
            except Exception:
                wait = 5.0  # A job's own failures are handled in _attempt; keep the worker alive.
            with self.lock:
                if wait is None:
                    self._thread = None
                    return
            self._wake.wait(wait)

    def run_due(self):
        """Attempt every due job once. Seconds until the next is due, or None when none is active."""
        while True:
            now = self.monotonic()
            with self.lock:
                active = [job for job in self.jobs.values() if job.state in ACTIVE]
                due = next((job for job in active if job.next_at <= now), None)
                if due is None:
                    return max(0.25, min(job.next_at for job in active) - now) if active else None
                if due.route == "lan":
                    due.next_at = now + 0.5
                else:
                    due.state = "sending"
            if due.route == "lan":
                self._lan_step(due)
                continue
            self.c.changed()
            self._attempt(due)

    def _attempt(self, job):
        c = self.c
        if not job.started:
            job.started = self.monotonic()
        job.attempts += 1
        transport = None
        try:
            with c.lock:
                try:
                    c._require_enabled()
                except Exception:
                    raise _Final("Saiph Cloud is off. Nothing was sent.") from None
                c._open()
                if not c._active():
                    raise _Later("Waiting for device approvals to renew. Saiph will retry.")
                if job.target not in c._targets():
                    raise _Final(f"{c.device_name(job.target)} is no longer approved. Nothing was sent.")
                self._authorized()
                session = c.session
                self._prepare(job, session)
                # Encryption may span token expiry: recheck before any network side effect.
                self._authorized()
                transport = c._transport_factory(c._config()["service_url"], session)
            self._upload(job, session, transport)
            self._finish(job, "sent", "")
        except _Final as final:
            self._release(job, transport)
            self._finish(job, "failed", final.text)
        except _Later as later:
            if later.fresh:
                self._release(job, transport)
            self._later(job, later.text, fresh=later.fresh)
        except TransportError as error:
            if error.status == 403 and not job.published:
                self._release(job, transport)
                self._finish(job, "failed", f"{c.device_name(job.target)} is no longer approved. Nothing was sent.")
            else:
                # 409/400: the roster or allocation changed; an unpublished offer is prepared again.
                fresh = error.status in (400, 404, 409)
                if fresh:
                    self._release(job, transport)
                self._later(job, OFFLINE, fresh=fresh)
        except (EnvelopeError, OSError, ValueError):
            self._release(job, transport)
            self._later(job, OFFLINE, fresh=True)
        except Exception:
            self._later(job, OFFLINE)
        finally:
            if transport is not None:
                try:
                    transport.close()
                except Exception:
                    pass

    # ------------------------------------------------------------ direct
    def _lan_step(self, job):
        """Offer the file directly, then follow the recipient's progress; fall back if it never connects."""
        c, now = self.c, self.monotonic()
        if job.lan is None:
            if not job.started:
                job.started = now
            job.attempts += 1
            try:
                with c.lock:
                    try:
                        c._require_enabled()
                    except Exception:
                        raise _Final("Saiph Cloud is off. Nothing was sent.") from None
                    c._open()
                    if job.target not in c._targets():
                        raise _Final(f"{c.device_name(job.target)} is no longer approved. Nothing was sent.")
                if not job.source.is_file():
                    raise _Final("This file is no longer on this computer. Nothing was sent.")
                _no_links(job.source)
                before = job.source.stat()
                size, digest = lan_files.sha256_file(job.source)
                after = job.source.stat()
                if size != before.st_size or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise _Final("This file changed while Saiph was reading it. Nothing was sent.")
                job.size = size
                server = lan_files.LanFileServer("get", job.source, name=job.name, size=size, sha256=digest,
                                                 addresses=c.lan_addresses)
                invite = server.start()
                try:
                    job.offer = c.file_offer(job.target, invite)
                except Exception:
                    server.close()
                    raise
            except _Final as final:
                self._finish(job, "failed", final.text)
                return
            except Exception:
                # No private address, no listener or no sealed offer: Saiph Cloud, if the file fits.
                self._fallback(job, "unreachable", quiet=True)
                return
            with self.lock:
                if job.state not in ACTIVE:
                    server.close()
                    return
                job.lan, job.refused, job.lan_until = server, "", now + LAN_WAIT
                job.state, job.error = "connecting", ""
            getattr(c, "lan_notice", lambda **_: "")(refresh=True)  # Ready if the recipient can't connect.
            c.changed()
            return
        status = job.lan.status()
        if status["state"] == "done":
            self._finish(job, "sent", "")
        elif status["state"] == "failed":
            name = c.device_name(job.target)
            text = {"mismatch": f"{name} received a damaged copy and deleted it. Retry to send it again.",
                    "changed": "This file changed on this computer while it was sending. Retry to send it again.",
                    "missing": "This file is no longer on this computer."}.get(
                status["error"], f"The connection to {name} was lost for too long. Retry when both are on the same network.")
            self._finish(job, "failed", text)
        elif status["state"] == "claimed":
            if job.state != "sending":
                job.state = "sending"
                c.changed()
            self._progress()
        elif job.refused or status["state"] in ("expired", "closed") or now >= job.lan_until:
            self._fallback(job, job.refused or "silent")

    def _fallback(self, job, reason, *, quiet=False):
        c, name = self.c, self.c.device_name(job.target)
        self._close_lan(job, tell=True)
        if reason == "storage":
            self._finish(job, "failed", f"{name} doesn't have enough free space for this file. Nothing was sent.")
            return
        if reason == "busy":
            self._finish(job, "failed", f"{name} is already receiving several files. Retry when they finish.")
            return
        if job.size > MAX_PLAINTEXT:
            text = no_network(job.size) if quiet else needs_network(job.size, name, refused=reason == "unreachable")
            notice = getattr(c, "lan_notice", lambda **_: "")(refresh=True)
            self._finish(job, "failed", notice + " Nothing was sent." if notice and not quiet else text)
            return
        with self.lock:
            if job.state not in ACTIVE:
                return
            job.route, job.state, job.error = "cloud", "queued", ""
            job.started = job.next_at = 0.0
            job.attempts = job.confirmed = 0
        c.changed()
        self._kick()

    def _close_lan(self, job, *, tell=False):
        server, offer = job.lan, job.offer
        job.lan, job.offer = None, ""
        if server is not None:
            server.close()
            if tell and offer and server.status()["state"] != "done":
                # The recipient stops trying at once. Its own thread: callers may hold this lock,
                # and the controller's lock is always taken before it.
                def close():
                    try:
                        self.c.session_close(job.target, offer)
                    except Exception:
                        pass
                threading.Thread(target=close, name="orion-lan-close", daemon=True).start()

    def _authorized(self):
        try:
            self.c._token()
        except SignInRequired:
            raise _Final("Sign in to Saiph Cloud again, then retry.") from None
        except HostedUnavailable:
            raise _Later(OFFLINE) from None

    def _prepare(self, job, session):
        prepared = job.prepared
        if prepared is not None:
            left = prepared.descriptor["expires_at"] - int(time.time())
            current = (prepared.descriptor["roster_version"] == session.roster["version"]
                       and prepared.descriptor["roster_hash"] == session.digest)
            if current and left > 5 and (left >= FRESH_SECONDS or job.published):
                return
            if job.published:
                raise _Final(f"Saiph couldn't confirm that {self.c.device_name(job.target)} received it. "
                             "Check there before sending it again.")
            self._discard(job)
        if not job.source.is_file():
            raise _Final("This file is no longer on this computer. Nothing was sent.")
        if job.source.stat().st_size > MAX_PLAINTEXT:
            raise _Final(too_large(job.source.stat().st_size))
        self.outgoing.mkdir(mode=0o700, exist_ok=True)
        mime = mimetypes.guess_type(job.name)[0] or "application/octet-stream"
        if not re.fullmatch(r"[a-z0-9.+-]{1,63}/[a-z0-9.+-]{1,63}", mime):
            mime = "application/octet-stream"
        try:
            job.prepared = hosted_files.prepare_attachment(session, job.target, job.source, self.outgoing, kind="file", mime=mime)
        except AttachmentError:
            if not job.source.is_file():
                raise _Final("This file is no longer on this computer. Nothing was sent.") from None
            raise _Later("The file could not be prepared. Saiph will retry.") from None
        job.confirmed = 0

    def _upload(self, job, session, transport):
        c, prepared = self.c, job.prepared
        def still():
            if c.session is not session or not c.enabled():
                raise _Later(OFFLINE)

        def call(action, *args):
            # The scheduler re-verifies the roster every pass, briefly withdrawing approval
            # (SealedSession.accept_page). That is not a reason to re-encrypt: wait it out
            # and carry on with the same blob; if it lasts, resume this blob next attempt.
            for wait in TRUST_WAITS:
                try:
                    return action(*args)
                except EnvelopeError:
                    still()
                    time.sleep(wait)
            try:
                return action(*args)
            except EnvelopeError:
                raise _Later(OFFLINE) from None
        _no_links(prepared.ciphertext)
        if hosted_files._digest(prepared.ciphertext) != (prepared.descriptor["size"], prepared.descriptor["sha256"]):
            if job.published:
                raise _Final("The prepared file changed on this computer. Check the recipient before sending again.")
            raise _Later(OFFLINE, fresh=True)
        blob = prepared.descriptor["id"]
        allocated = call(transport.allocate_blob, prepared.descriptor)
        job.allocated = True
        if isinstance(allocated, dict) and allocated.get("duplicate") is False:
            job.confirmed = 0  # The relay holds none of this blob's chunks (new, or expired there).
        with prepared.ciphertext.open("rb") as incoming:
            incoming.seek(job.confirmed * CHUNK_BYTES)
            while chunk := incoming.read(CHUNK_BYTES):
                still()
                call(transport.upload_blob_chunk, blob, job.confirmed, chunk)
                job.confirmed += 1
                self._progress()
        still()
        call(transport.complete_blob, blob)
        still()
        job.published = True
        call(transport.publish, prepared.envelope)

    def _progress(self):
        now = self.monotonic()
        if now - self._reported >= 0.5:
            self._reported = now
            self.c.changed()

    def _later(self, job, text, *, fresh=False):
        with self.lock:
            if job.state not in ACTIVE:
                return  # Cancelled meanwhile.
            if fresh and not job.published:
                self._discard(job)
            now = self.monotonic()
            if now - job.started >= RETRY_SECONDS:
                text = ("Saiph couldn't confirm that " + self.c.device_name(job.target) + " received it. "
                        "Check there before sending it again.") if job.published else \
                    "Saiph Cloud stayed unreachable for 10 minutes. Nothing was sent."
                self._finish(job, "failed", text)
                return
            job.state, job.error = "retrying", text
            job.next_at = now + RETRY_DELAYS[min(job.attempts, len(RETRY_DELAYS)) - 1]
        self.c.changed()

    def _finish(self, job, state, text, *, alert=True):
        with self.lock:
            job.state, job.error, job.finished = state, text, self.monotonic()
            self._discard(job)
            self._close_lan(job, tell=state != "sent")
        name = self.c.device_name(job.target)
        if alert and state == "failed":
            self.c.transfer_alert(f"{job.name} wasn't sent to {name}. Open Saiph to retry.")
        elif alert and job.notify:
            self.c.transfer_alert(f"Sent {job.name} to {name}.")
        self.c.changed()

    def _release(self, job, transport):
        """Free the relay's copy of an unpublished blob about to be abandoned.

        Otherwise it counts against the recipient's few pending blobs until it
        expires, and the next attempts are refused. Best effort: it expires anyway.
        """
        if transport is None or job.published or not job.allocated or job.prepared is None:
            return
        job.allocated = False
        try:
            transport.delete_blob(job.prepared.descriptor["id"])
        except Exception:
            pass

    def _discard(self, job):
        if job.prepared is not None:
            try:
                job.prepared.ciphertext.unlink(missing_ok=True)
            except OSError:
                pass  # Removed at the next start at the latest.
        job.prepared, job.confirmed, job.allocated = None, 0, False

    def close(self):
        self.cancel_all("Saiph closed before the file was sent. Nothing was sent.")

    # ------------------------------------------------------------- snapshot
    def snapshot(self) -> list:
        now = self.monotonic()
        with self.lock:
            for key in [key for key, job in self.jobs.items() if job.state == "sent" and now - job.finished > SENT_SECONDS]:
                self.jobs.pop(key)
            jobs = list(self.jobs.values())
        rows = []
        for job in jobs:
            progress = round(min(1.0, job.confirmed / job.chunks()), 3)
            server = job.lan
            if job.route == "lan" and server is not None:
                status = server.status()
                progress = round(min(1.0, status["bytes"] / status["size"]), 3) if status["size"] else 0.0
            row = {"id": job.id, "name": job.name, "size": job.size, "target": job.target,
                   "target_name": self.c.device_name(job.target), "state": job.state, "error": job.error,
                   "progress": progress if job.state != "sent" else 1.0, "route": job.route,
                   "attempts": job.attempts}
            if job.state == "retrying":
                row["retry_in"] = max(0, math.ceil(job.next_at - now))
            rows.append(row)
        return rows
