# SPDX-License-Identifier: AGPL-3.0-or-later
"""Opt-in Saiph Hosted preview for the desktop. OFF by default.

With `settings["hosted"]["enabled"]` absent or false, nothing here touches the
network, keys or clipboard, and self-hosted Link behaviour is unchanged.

PROVISIONAL decisions (see docs/HOSTED_INTEGRATION_PLAN.md):
- the desktop is the root: it alone signs rosters;
- rosters last 12 h and are renewed when 4 h remain (`hosted_renewal`);
- clipboard text is the first synced feature, then notifications and files;
- a device is either self-hosted or hosted, never both;
- no SMS or call commands.

Not a security review. Physical-device acceptance, hosted deployment checks
and independent review remain open.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from .clipboard import RecentClipboard
from .hosted_approval import (
    ApprovalError, RootApproval, initialize_root, local_root, make_root_code, prepare_anchored_catchup,
    verify_request_code,
)
from .hosted_crypto import EnvelopeError, canonical
from .hosted_features import (
    CLIPBOARD_TEXT, FILE_OFFER, NOTIFICATION_REMOVE, NOTIFICATION_UPSERT, FeatureError, clipboard_payload,
    dismiss_payload, kind, read_clipboard, read_notification,
)
from .hosted_identity import HostedIdentity
from .hosted_keys import KeyStorageError
from .hosted_login import HostedLoginConfig
from .hosted_mailbox import DurableMailbox
from .hosted_renewal import ROSTER_LIFETIME_SECONDS, assess
from .hosted_session import SealedSession, enrollment
from .hosted_tokens import HostedAccount, HostedUnavailable, SignInRequired, TokenVault
from .hosted_transport import HostedTransport, TransportError
from .user_presence import confirm as confirm_user, status as user_verification

EXCLUSIVE = ("This computer is paired with a self-hosted Hub. A device uses either a self-hosted Hub "
             "or Saiph Hosted, never both.")
HOSTED_ACTIVE = ("This computer uses Saiph Hosted. A device uses either Saiph Hosted or a self-hosted Hub, "
                 "never both. Turn off and forget Saiph Hosted first.")
CONFIG_KEYS = {"service_url", "issuer", "audience", "client_id", "refresh_tokens"}


def packaged_config():
    if not getattr(sys, 'frozen', False) or not getattr(sys, '_MEIPASS', None):
        return None
    from .hosted_distribution import read_configuration, desktop_config
    try:
        return validate_config(desktop_config(read_configuration(Path(sys._MEIPASS) / 'hosted-defaults.json')))
    except (ValueError, OSError, TypeError, KeyError):
        return None


class HostedError(ValueError):
    pass


def hosted_settings(settings) -> dict:
    value = settings.get("hosted") if isinstance(settings, dict) else None
    return value if isinstance(value, dict) else {}


def hosted_enabled(settings) -> bool:
    return hosted_settings(settings).get("enabled") is True


def validate_config(value) -> dict:
    """Owner-entered deployment settings; public builds carry no defaults."""
    if not isinstance(value, dict) or set(value) - CONFIG_KEYS or not {"service_url", "issuer", "audience", "client_id"} <= set(value):
        raise HostedError("Enter the hosted service address, sign-in issuer, API audience and desktop client ID.")
    service = value["service_url"]
    try:
        parsed = urlsplit(service)
        if (type(service) is not str or parsed.scheme != "https" or not parsed.hostname
                or parsed.username is not None or parsed.password is not None or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment or any(c.isspace() or ord(c) < 32 for c in service) or "\\" in service):
            raise ValueError()
        _ = parsed.port
        refresh = value.get("refresh_tokens", False)
        if type(refresh) is not bool:
            raise ValueError()
        HostedLoginConfig(value["issuer"], value["audience"], value["client_id"], refresh_tokens=refresh)
    except (ValueError, TypeError, AttributeError):
        raise HostedError("Use an HTTPS hosted service address and the exact sign-in settings from your deployment.") from None
    return {"service_url": service.rstrip("/"), "issuer": value["issuer"], "audience": value["audience"],
            "client_id": value["client_id"], "refresh_tokens": refresh}


def _uuid(value):
    try:
        return type(value) is str and str(UUID(value)) == value
    except ValueError:
        return False


def qr_modules(text: str) -> list[str]:
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    qr.add_data(text)
    qr.make(fit=True)
    return ["".join("1" if cell else "0" for cell in row) for row in qr.get_matrix()]


def device_fingerprint(member: dict) -> str:
    """Display-only comparison value for a request code's device keys."""
    raw = hashlib.sha256(b"Orion hosted device fingerprint v1\0" + canonical(member)).hexdigest().upper()
    return " ".join(raw[index:index + 4] for index in range(0, len(raw), 4))


class HostedController:
    """Owns hosted state for one desktop profile; safe to construct when off."""

    def __init__(self, workspace, *, protection=None, attempt_factory=None, refresher=None, revoker=None,
                 transport_factory=HostedTransport, clock=time.time, changed=lambda: None):
        self.workspace = workspace
        self.folder = Path(workspace.root) / "hosted"
        self._protection = protection
        self._auth = {key: value for key, value in (("attempt_factory", attempt_factory), ("refresher", refresher),
                                                     ("revoker", revoker)) if value is not None}
        self._transport_factory = transport_factory
        self.clock = clock
        self.changed = changed
        self.lock = threading.RLock()
        self.identity = HostedIdentity(self.folder / "identity", protection=protection)
        self.account = None
        self._account_config = None
        self.session = self.transport = self.mailbox = self.root = self.info = self.signing = None
        self.status = "off"
        self.error = ""
        self.decision = None
        self.next_step_at = 0.0
        self.clipboard_cache = RecentClipboard()
        self.clipboard_sink = lambda mime, data: None
        self._outgoing_clipboard = None
        self._offers = {}
        self._thread = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        # Called with a short message when the approved device list changes; the
        # desktop window installs a thread-safe tray notification.
        self.alert = lambda message: getattr(self.workspace, "security_alert", lambda _: None)(message)

    # ------------------------------------------------------------ settings
    @property
    def settings(self):
        return hosted_settings(self.workspace.settings)

    def enabled(self) -> bool:
        return hosted_enabled(self.workspace.settings)

    def self_hosted_paired(self) -> bool:
        return bool((self.workspace.settings.get("hub") or {}).get("paired"))

    def blocks_self_hosted(self) -> bool:
        """Mutual exclusion: any hosted identity or enabled flag blocks Hub pairing."""
        return self.enabled() or self.identity.exists()

    def _config(self):
        settings = self.settings
        if not any(key in settings for key in CONFIG_KEYS):
            return None if self.identity.exists() else packaged_config()
        try:
            return validate_config({key: settings[key] for key in CONFIG_KEYS if key in settings})
        except HostedError:
            return None

    def _save(self, hosted):
        self.workspace.settings["hosted"] = hosted
        self.workspace.save()

    def configure(self, args) -> dict:
        config = validate_config(args)
        with self.lock:
            if self.identity.exists() and any(self.settings.get(key) != config[key]
                                              for key in ("service_url", "issuer", "audience", "client_id")):
                raise HostedError("This computer already has a hosted identity for another deployment. Forget it first.")
            previous = self.account or (self._account() if self._config() else None)
            if previous is not None:
                previous.sign_out()
            self._drop_account()
            self._save({**self.settings, **config, "enabled": self.enabled()})
        return {"ok": True}

    def set_enabled(self, flag) -> dict:
        if type(flag) is not bool:
            raise HostedError("Saiph Hosted is on or off.")
        with self.lock:
            if flag:
                if self.self_hosted_paired():
                    raise HostedError(EXCLUSIVE)
                if self._config() is None:
                    raise HostedError("Enter your hosted deployment settings first.")
            # Pin the selected defaults before creating identity material. Future
            # installer updates cannot silently change an existing deployment.
            self._save({**self.settings, **(self._config() or {}), "enabled": flag})
            if not flag:
                if self.account is not None:
                    self.account.cancel_sign_in()
                self._deactivate("off")
            else:
                self.status = "starting"
                self._wake.set()
        self.changed()
        return {"ok": True}

    def forget(self, confirm) -> dict:
        """Retire this computer's hosted identity without deleting key material.

        The folder is renamed aside (recoverable by the owner) so the computer
        may pair with a self-hosted Hub. A retired root cannot be restored
        automatically; root transfer is not implemented.
        """
        if confirm is not True:
            raise HostedError("Confirm that this computer should stop using Saiph Hosted.")
        if self.enabled():
            raise HostedError("Turn off Saiph Hosted first.")
        confirm_user(self.workspace, "retire this computer's Saiph Hosted identity")
        with self.lock:
            if self.enabled():
                raise HostedError("Turn off Saiph Hosted first.")
            self._deactivate("off")
            if self.account is not None:
                self.account.sign_out()
            self._drop_account()
            if self.folder.exists():
                target = self.folder.with_name("hosted-retired-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime(self.clock())))
                if target.exists():
                    raise HostedError("A retired hosted profile with this time already exists. Try again shortly.")
                shutil.move(str(self.folder), str(target))
            settings = {key: value for key, value in self.settings.items() if key != "enabled"}
            if settings:
                self._save({**settings, "enabled": False})
            else:
                self.workspace.settings.pop("hosted", None)
                self.workspace.save()
            self.identity = HostedIdentity(self.folder / "identity", protection=self._protection)
        self.changed()
        return {"ok": True}

    # ------------------------------------------------------------- account
    def _drop_account(self):
        if self.account is not None:
            self.account.cancel_sign_in()
        self.account, self._account_config = None, None

    def _account(self) -> HostedAccount:
        config = self._config()
        if config is None:
            raise HostedError("Enter your hosted deployment settings first.")
        login = HostedLoginConfig(config["issuer"], config["audience"], config["client_id"],
                                  refresh_tokens=config["refresh_tokens"])
        if self.account is None or self._account_config != login:
            vault = TokenVault(self.folder / "account", login, protection=self._protection) if login.refresh_tokens else None
            self.account = HostedAccount(login, vault, on_change=self._account_changed, **self._auth)
            self._account_config = login
        return self.account

    def _account_changed(self):
        self._wake.set()
        self.changed()

    def _require_enabled(self):
        if not self.enabled():
            raise HostedError("Turn on Saiph Hosted first.")
        if self.self_hosted_paired():
            raise HostedError(EXCLUSIVE)

    def sign_in(self) -> dict:
        with self.lock:
            self._require_enabled()
            account = self._account()
        account.begin_sign_in()
        self.changed()
        return {"started": True}

    def sign_out(self) -> dict:
        with self.lock:
            account = self.account or (self._account() if self._config() else None)
            try:
                if account is not None:
                    account.sign_out()
            except (KeyStorageError, OSError):
                self._save({**self.settings, "enabled": False})
                raise
            finally:
                self._deactivate("signed_out" if self.enabled() else "off")
        self.changed()
        return {"ok": True}

    def _token(self) -> str:
        return self._account().access_token()

    # -------------------------------------------------------------- devices
    def _deactivate(self, status):
        if self.transport is not None:
            try:
                self.transport.close()
            except Exception:
                pass
        if self.session is not None:
            self.session.invalidate()
        self.session = self.transport = self.mailbox = self.root = self.info = self.signing = None
        self._offers.clear()
        self._outgoing_clipboard = None
        self.decision = None
        self.status, self.error = status, ""

    def _open(self):
        """Load the existing identity; never creates or repairs one."""
        if self.session is not None:
            return
        config = self._config()
        info, signing, encryption = self.identity.load()
        if info.role != "root":
            raise KeyStorageError()
        root = local_root(info.deployment_id, info.device_id, signing, encryption)
        session = SealedSession(self.folder / "trust.sqlite3", info.deployment_id, root.signing_key, info.device_id,
                                signing, encryption)
        self.transport = self._transport_factory(config["service_url"], session)
        self.session, self.mailbox, self.root, self.info, self.signing = session, DurableMailbox(session), root, info, signing

    def _active(self) -> bool:
        if self.session is None:
            return False
        try:
            self.session.current()
            return True
        except EnvelopeError:
            return False

    def _ttl(self):
        offset = getattr(self.transport, "server_offset", None)
        decision = assess(None, self.clock(), server_offset=offset)
        if decision.blocked:
            raise HostedError("This computer's clock differs from Saiph Hosted by more than an hour. Correct the clock first.")
        return decision.ttl_seconds

    def setup_root(self) -> dict:
        """Create this desktop's root identity and the deployment's first roster."""
        with self.lock:
            self._require_enabled()
            config = self._config()
            token = self._token_or_error()
            if not self.identity.exists():
                probe = self._transport_factory(config["service_url"], None)
                try:
                    deployment = probe.discover_account(token)
                    page = probe.roster_page(token)
                finally:
                    probe.close()
                if page["chain"]:
                    raise HostedError("This hosted account already has a root device. Root transfer is not available.")
                self.identity.create(deployment, role="root")
            self._open()
            self._genesis(token)
            self._watch_members()  # Baseline: only this computer, so the first approval alerts.
            self.status = "active"
            self.error = ""
        self.changed()
        return self.root_code()

    def _genesis(self, token):
        if self.session.history_cursor()["after_version"] == 0:
            page = self.transport.roster_page(token)
            if not page["chain"]:
                candidate = enrollment(self.info.deployment_id, self.info.device_id, self.signing, self.session.encryption)
                pending = self._pending(self.transport.enroll(token, candidate), candidate["device"])
                # Fixed TTL: an identical retry after a crash must reuse the
                # journaled genesis proposal byte for byte.
                proposal = initialize_root(self.root, self.signing, self.session.encryption, pending,
                                           state=self.session.state, roster_ttl_seconds=ROSTER_LIFETIME_SECONDS)
                try:
                    self.transport.submit_roster(token, proposal)
                except TransportError:
                    pass  # A lost reply is confirmed by the refresh below.
        self.transport.refresh_roster(token)

    @staticmethod
    def _pending(response, member):
        if (type(response) is not dict or set(response) != {"status", "expires_at"} or response["status"] != "pending"
                or type(response["expires_at"]) is not int):
            raise HostedError("Saiph Hosted returned an invalid device request.")
        return {**member, "expires_at": response["expires_at"]}

    def _token_or_error(self):
        try:
            return self._token()
        except SignInRequired:
            self._deactivate("sign_in_required")
            raise HostedError("Sign in to Saiph Hosted first.") from None
        except HostedUnavailable:
            raise HostedError("Saiph Hosted is unreachable. Try again when you are online.") from None

    def root_code(self) -> dict:
        """A fresh public root code as QR modules plus the full fingerprint."""
        with self.lock:
            self._require_enabled()
            if self.root is None:
                self._open()
            code = make_root_code(self.root, self.signing, ttl_seconds=300)
            return {"modules": qr_modules(code), "code": code, "expires_in": 300,
                    "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.clock() + 300)),
                    "fingerprint": self.root.display_fingerprint}

    def _refresh(self, token):
        try:
            self.transport.refresh_roster(token)
        except (EnvelopeError, TransportError):
            pass  # Expired/unavailable: renewal or the next step handles it.

    def _settle(self, token):
        """Submit any journaled proposal (crash/lost reply) before a new one."""
        self._refresh(token)
        approval = RootApproval(self.session, self.root)
        pending = approval.pending_proposal()
        if pending is not None:
            self._submit(token, approval, pending)
        self.transport.refresh_roster(token)

    def _submit(self, token, approval, proposal):
        expected = self.session.history_cursor()["after_hash"]
        if proposal["roster"]["expires_at"] <= int(self.clock()) + 60:
            catchup = prepare_anchored_catchup(self.session, self.root, expected_hash=expected,
                                               roster_ttl_seconds=self._ttl())
            try:
                self.transport.submit_catchup(token, catchup)
            except TransportError:
                pass
        else:
            try:
                self.transport.submit_roster(token, proposal)
            except TransportError:
                pass  # Refresh decides: the server may already hold it.
        self._refresh(token)

    def inspect_request(self, code) -> dict:
        with self.lock:
            self._require_enabled()
            self._open()
            try:
                request = verify_request_code(code, self.root)
            except ApprovalError:
                raise HostedError("This request code is invalid, expired or for another deployment.") from None
            device = request["candidate"]["device"]
            return {"device_id": device["id"], "fingerprint": device_fingerprint(device), "expires_at": request["expires_at"]}

    def approve(self, code, label, confirmed) -> dict:
        if confirmed is not True:
            raise HostedError("Compare the device fingerprint on both screens, then confirm.")
        if type(label) is not str or not 0 < len(label.strip()) <= 40:
            raise HostedError("Name the device you are approving.")
        with self.lock:
            self._require_enabled()
            self._open()
            try:
                verify_request_code(code, self.root)
            except ApprovalError:
                raise HostedError("This request code is invalid, expired or for another deployment.") from None
        # An approved device receives future content; the person at the computer
        # must prove presence. Prompt outside the lock so syncing continues.
        confirm_user(self.workspace, f"approve the device \"{label.strip()}\" for your Saiph account")
        with self.lock:
            self._require_enabled()
            token = self._token_or_error()
            self._open()
            try:
                request = verify_request_code(code, self.root)
                self._settle(token)
                candidate = request["candidate"]
                # Same candidate and proof the phone submitted; the server must
                # report a pending entry with exactly these keys or refuse.
                pending = self._pending(self.transport.enroll(token, candidate), candidate["device"])
                approval = RootApproval(self.session, self.root)
                proposal = approval.approve(code, pending, roster_ttl_seconds=self._ttl())
                self._submit(token, approval, proposal)
                members = self.session.current()
            except (ApprovalError, EnvelopeError, TransportError):
                raise HostedError("The device could not be approved. Ask it for a fresh request code.") from None
            if candidate["device"]["id"] not in members:
                raise HostedError("Saiph Hosted has not accepted the approval yet. It will retry automatically.")
            self._set_label(candidate["device"]["id"], label.strip())
            self._watch_members()
        self.changed()
        return {"approved": candidate["device"]["id"]}

    def revoke(self, device_id) -> dict:
        if type(device_id) is not str:
            raise HostedError("Choose an approved device.")
        confirm_user(self.workspace, "remove a device from your Saiph account")
        with self.lock:
            self._require_enabled()
            token = self._token_or_error()
            self._open()
            try:
                self._settle(token)
                approval = RootApproval(self.session, self.root)
                proposal = approval.revoke(device_id)
                self._submit(token, approval, proposal)
                members = self.session.current()
            except (ApprovalError, EnvelopeError, TransportError):
                raise HostedError("Revocation could not be confirmed. Saiph will refresh the device list when it reconnects.") from None
            if device_id in members:
                raise HostedError("Saiph Hosted has not accepted the revocation yet. It will retry automatically.")
            self._watch_members()
            labels = self._labels()
            labels.pop(device_id, None)
            self._write_labels(labels)
        self.changed()
        return {"revoked": device_id}

    def _labels(self) -> dict:
        try:
            value = json.loads((self.folder / "labels.json").read_text(encoding="utf-8"))
            return {k: v for k, v in value.items() if type(k) is str and type(v) is str} if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_labels(self, labels):
        path = self.folder / "labels.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(labels, sort_keys=True), encoding="utf-8")
        temporary.replace(path)

    def _set_label(self, device_id, label):
        labels = self._labels()
        labels[device_id] = label
        self._write_labels(labels)

    # --------------------------------------------------------------- alerts
    def _watch_members(self):
        """Record and announce every change to the verified device list.

        The first list seen on this computer is the baseline. Later additions and
        removals are kept as security events and raised as a system notification,
        so an approval made while the owner was away is noticed.
        """
        try:
            current = sorted(self.session.current())
        except EnvelopeError:
            return
        path = self.folder / "members-seen.json"
        try:
            seen = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(seen, list) or not all(type(item) is str for item in seen):
                seen = None
        except (OSError, ValueError):
            seen = None
        if seen == current:
            return
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(current), encoding="utf-8")
        temporary.replace(path)
        if seen is None:
            return
        labels, now = self._labels(), int(self.clock())
        changes = [("added", device) for device in sorted(set(current) - set(seen))]
        changes += [("removed", device) for device in sorted(set(seen) - set(current))]
        for change, device in changes:
            label = labels.get(device, "A device")
            self.workspace.store.save("hosted_security_event", {
                "id": hashlib.sha256(f"{change}|{device}|{now}".encode()).hexdigest(),
                "kind": change, "device_id": device, "label": label, "at": now})
            if change == "added":
                self.alert(f"{label} was approved for your Saiph account. If this wasn't you, remove it in Settings.")
            else:
                self.alert(f"{label} was removed from your Saiph account.")
        for old in self.workspace.store.all("hosted_security_event")[50:]:
            self.workspace.store.delete("hosted_security_event", old["id"])

    # ------------------------------------------------------------- schedule
    def step(self) -> None:
        """One bounded scheduler pass: refresh, renew if due, sync features."""
        with self.lock:
            if not self.enabled() or self.self_hosted_paired():
                if self.session is not None or self.status != "off":
                    self._deactivate("off")
                return
            if not self.identity.exists():
                self.status = "setup"
                return
            try:
                token = self._token()
            except SignInRequired:
                self._deactivate("sign_in_required")
                return
            except HostedUnavailable:
                self.status = "offline"
                return
            try:
                self._open()
                self._refresh(token)
                expires = self.session.roster["expires_at"] if self._active() else None
                if expires is None and self.session.history_cursor()["after_version"] == 0:
                    self._genesis(token)
                    expires = self.session.roster["expires_at"] if self._active() else None
                self.decision = assess(expires, self.clock(), server_offset=getattr(self.transport, "server_offset", None))
                if self.decision.blocked:
                    self.status, self.error = "clock", "Correct this computer's clock to keep devices approved."
                elif self.decision.due:
                    approval = RootApproval(self.session, self.root)
                    pending = approval.pending_proposal()
                    proposal = pending if pending is not None else approval.renew(roster_ttl_seconds=self.decision.ttl_seconds)
                    self._submit(token, approval, proposal)
                    expires = self.session.roster["expires_at"] if self._active() else None
                    self.decision = assess(expires, self.clock(), server_offset=getattr(self.transport, "server_offset", None))
                if self._active() and not self.decision.blocked:
                    self._watch_members()
                    self.status = "active" if not self.decision.skew_warning else "clock"
                    if self.status == "active":
                        self.error = ""
                    self._sync()
                elif not self.decision.blocked:
                    self.status, self.error = "renewal_pending", "Waiting to renew device approvals. Saiph will retry."
            except KeyStorageError:
                self.status, self.error = "keys_unavailable", "This computer could not unlock its hosted keys. They were kept unchanged."
            except (ApprovalError, EnvelopeError, TransportError, HostedError):
                self.status, self.error = "retrying", "Saiph Hosted is temporarily unavailable. Saiph will retry."
            finally:
                wait = self.decision.next_check_in if self.decision else 30
                self.next_step_at = time.monotonic() + min(wait, 15)
        self.changed()

    # ------------------------------------------------------------- features
    def _targets(self):
        return [member for member in self.session.current() if member != self.info.device_id]

    def _sync(self):
        clipboard_on = (self.workspace.settings.get("link") or {}).get("clipboard") is not False
        outgoing, self._outgoing_clipboard = self._outgoing_clipboard, None
        if outgoing is not None and clipboard_on:
            for target in self._targets():
                self.mailbox.stage(target, outgoing, ttl_seconds=60)
        self.mailbox.flush(self.transport)
        self.mailbox.poll(self.transport)
        for envelope in self.mailbox.pending():
            event_id = envelope["header"]["id"]
            try:
                payload = self.session.authenticate(envelope)
                event = kind(payload)
            except (EnvelopeError, FeatureError):
                continue
            if event == FILE_OFFER:
                self._offers[event_id] = envelope
                continue
            payload = self.mailbox.claim(event_id)
            outcome = "failed"
            try:
                if event == CLIPBOARD_TEXT:
                    data = read_clipboard(payload)
                    if clipboard_on and self.clipboard_cache.claim("text/plain", data):
                        self.clipboard_sink("text/plain", data)
                    outcome = "succeeded"
                elif event in (NOTIFICATION_UPSERT, NOTIFICATION_REMOVE):
                    self._notification(envelope["header"]["source"], payload)
                    outcome = "succeeded"
            except (FeatureError, ValueError, OSError):
                outcome = "failed"
            finally:
                self.mailbox.complete(event_id, outcome)
        now = int(self.clock())
        for event_id in [key for key, value in self._offers.items() if value["header"]["expires_at"] <= now]:
            self._offers.pop(event_id, None)

    def local_clipboard(self, mime, data) -> bool:
        """GUI-thread hook: record the newest local text; the worker sends it."""
        if not self.enabled() or mime != "text/plain" or self.session is None:
            return False
        if (self.workspace.settings.get("link") or {}).get("clipboard") is False:
            return False
        if self.clipboard_cache.contains_digest(mime, hashlib.sha256(data).hexdigest()):
            return False  # Echo of a value just received or sent.
        try:
            payload = clipboard_payload(data)
        except FeatureError:
            return False
        self.clipboard_cache.claim(mime, data)
        self._outgoing_clipboard = payload
        self._wake.set()
        return True

    def _notification(self, source, payload):
        action, value = read_notification(payload)
        identifier = hashlib.sha256((source + "\0" + (value if action == "remove" else value["key"])).encode()).hexdigest()
        if action == "remove":
            self.workspace.store.delete("hosted_notification", identifier)
        else:
            self.workspace.store.save("hosted_notification", {**value, "id": identifier, "device_id": source})

    def dismiss_notification(self, notification_id) -> dict:
        with self.lock:
            self._require_enabled()
            self._token_or_error()
            row = self.workspace.store.get("hosted_notification", str(notification_id))
            self._open()
            if row["device_id"] not in self.session.current():
                raise HostedError("That device is no longer approved.")
            self.mailbox.stage(row["device_id"], dismiss_payload(row["key"]), ttl_seconds=60)
            self.workspace.store.delete("hosted_notification", row["id"])
            self._wake.set()
        self.changed()
        return {"ok": True}

    def send_file(self, path, target) -> dict:
        from .hosted_files import prepare_attachment, upload_attachment, AttachmentError
        with self.lock:
            self._require_enabled()
            self._token_or_error()
            self._open()
            if not self._active():
                raise HostedError("Device approvals are being renewed. Try again shortly.")
            source = Path(path) if isinstance(path, str) else None
            if source is None or not source.is_absolute() or not source.is_file():
                raise HostedError("Choose a file on this computer.")
            if target not in self._targets():
                raise HostedError("Choose an approved device.")
            outgoing = self.folder / "outgoing"
            outgoing.mkdir(mode=0o700, exist_ok=True)
            mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
            if not __import__("re").fullmatch(r"[a-z0-9.+-]{1,63}/[a-z0-9.+-]{1,63}", mime):
                mime = "application/octet-stream"
            try:
                prepared = prepare_attachment(self.session, target, source, outgoing, kind="file", mime=mime)
                # Selection and encryption may span token expiry. Recheck at
                # the network side effect, not only when the dialog was opened.
                try:
                    self._token_or_error()
                except HostedError:
                    prepared.ciphertext.unlink(missing_ok=True)
                    raise
                upload_attachment(self.transport, prepared)
            except AttachmentError:
                raise HostedError("The transfer did not complete. The recipient may already have received the file.") from None
            prepared.ciphertext.unlink(missing_ok=True)
        return {"sent": True}

    def save_offer(self, event_id, downloads: Path | None = None) -> dict:
        from .hosted_files import _manifest, download_attachment, AttachmentError, AttachmentPublicationUncertain
        with self.lock:
            self._require_enabled()
            self._token_or_error()
            envelope = self._offers.get(event_id)
            if envelope is None:
                raise HostedError("This file offer has expired.")
            try:
                payload, _ = _manifest(self.session, envelope)
            except (AttachmentError, EnvelopeError):
                self._offers.pop(event_id, None)
                raise HostedError("This file offer has expired.") from None
            folder = Path(downloads) if downloads else Path.home() / "Downloads" / "Saiph"
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            stem, suffix = os.path.splitext(payload["name"])
            destination = folder / payload["name"]
            index = 1
            while destination.exists():
                destination = folder / f"{stem} ({index}){suffix}"
                index += 1
            self.mailbox.claim(event_id)
            self._offers.pop(event_id, None)
            try:
                saved = download_attachment(self.session, self.transport, envelope, destination)
            except AttachmentPublicationUncertain:
                self.mailbox.complete(event_id, "uncertain")
                raise HostedError("Check your Downloads folder: the file may have been saved.") from None
            except (AttachmentError, TransportError):
                self.mailbox.complete(event_id, "failed")
                raise HostedError("The file could not be saved. Ask the sender to share it again.") from None
            self.mailbox.complete(event_id, "succeeded")
        self.changed()
        return {"path": str(saved)}

    # ------------------------------------------------------------- snapshot
    def snapshot(self) -> dict:
        settings = self.settings
        config = self._config()
        result = {"enabled": self.enabled(), "configured": config is not None,
                  "config": {key: (config or settings).get(key, False if key == "refresh_tokens" else "") for key in sorted(CONFIG_KEYS)},
                  "identity": self.identity.exists(), "self_hosted_paired": self.self_hosted_paired(),
                  "status": self.status if self.enabled() else "off", "error": self.error if self.enabled() else "",
                  "account": {"status": "signed_out", "refresh_tokens": bool(config and config["refresh_tokens"]), "error": ""},
                  "role": None, "device_id": None, "fingerprint": None, "roster": None, "offers": [],
                  "notifications": [], "user_verification": user_verification(self.workspace), "security_events": []}
        if not self.enabled() and not self.identity.exists():
            return result
        with self.lock:
            if self.account is not None:
                result["account"] = self.account.snapshot()
            if self.info is not None:
                result.update(role=self.info.role, device_id=self.info.device_id, fingerprint=self.root.display_fingerprint)
            if self.session is not None and self._active():
                labels = self._labels()
                members = self.session.current()
                decision = self.decision
                expires = self.session.roster["expires_at"]
                result["roster"] = {
                    "version": self.session.roster["version"], "expires_at": expires,
                    "renew_at": expires - 4 * 3600, "clock_warning": bool(decision and decision.skew_warning),
                    "members": [{"id": key, "root": key == self.info.device_id,
                                 "label": "This computer" if key == self.info.device_id else labels.get(key, "Device"),
                                 "fingerprint": device_fingerprint(value)} for key, value in sorted(members.items())]}
            for event_id, envelope in list(self._offers.items()):
                try:
                    payload = self.session.authenticate(envelope)
                    result["offers"].append({"id": event_id, "name": payload["name"], "size": payload["size"],
                                             "mime": payload["mime"], "source": envelope["header"]["source"],
                                             "expires_at": envelope["header"]["expires_at"]})
                except (EnvelopeError, KeyError, TypeError):
                    self._offers.pop(event_id, None)
        result["notifications"] = self.workspace.store.all("hosted_notification")[:200]
        result["security_events"] = self.workspace.store.all("hosted_security_event")[:20]
        return result

    # --------------------------------------------------------------- thread
    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="orion-hosted", daemon=True)
            self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            if self.enabled() or self.session is not None:
                if time.monotonic() >= self.next_step_at or self._wake.is_set():
                    self._wake.clear()
                    try:
                        self.step()
                    except Exception:
                        self.status, self.error = "retrying", "Saiph Hosted is temporarily unavailable. Saiph will retry."
            self._wake.wait(1.0)

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        with self.lock:
            self._deactivate("off")
