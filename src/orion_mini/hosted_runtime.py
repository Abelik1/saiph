# SPDX-License-Identifier: AGPL-3.0-or-later
"""Opt-in Saiph Hosted preview for the desktop. OFF by default.

With `settings["hosted"]["enabled"]` absent or false, nothing here touches the
network, keys or clipboard, and self-hosted Link behaviour is unchanged.

PROVISIONAL decisions (see docs/HOSTED_INTEGRATION_PLAN.md):
- the desktop is the root: it alone signs rosters;
- rosters last 12 h and are renewed when 4 h remain (`hosted_renewal`);
- clipboard text is the first synced feature, then notifications and files;
- a device is either self-hosted or hosted, never both;
- texts and calls (owner decisions 2026-10-14): every approved computer, root
  or not, subscribes to a phone and may send phone actions to an approved phone
  that advertised the capability; calls are first come, first served on the
  phone. Phone data is shown through the shared Phone page store (see
  `hosted_features`).
- a second computer joins as a member, the way a phone does: it pins the root
  code after the owner compares the full fingerprint, shows a request code the
  root approves, and never signs, renews, approves or revokes rosters.

Not a security review. Physical-device acceptance, hosted deployment checks
and independent review remain open.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from .clipboard import RecentClipboard
from .hosted_approval import (
    ApprovalError, RootApproval, TrustedRoot, initialize_root, inspect_root_code, local_root, make_request_code,
    make_root_code, prepare_anchored_catchup, trust_root_code, verify_request_code,
)
from .hosted_crypto import EnvelopeError, canonical
from .hosted_features import (
    ANSWERS, CALL_COMMAND, CALL_DIAL, CALL_HANDLED, CALL_REFUSED, CALL_STATE, CLIPBOARD_TEXT, COMMAND_CAPABILITY,
    DATA_CAPABILITY, FILE_OFFER, NOTIFICATION_REMOVE, NOTIFICATION_UPSERT, PHONE_CAPABILITIES, PHONE_DATA, SMS_OPEN,
    SMS_SEND, SMS_SYNC, FeatureError, clipboard_payload, dismiss_payload, kind, phone_command, read_clipboard,
    read_notification, read_phone_data, refused_request, subscribe_payload,
)
from .hosted_identity import HostedIdentity
from .hosted_distribution import packaged_config
from .hosted_keys import KeyStorageError
from .hosted_login import HostedLoginConfig
from .hosted_mailbox import DurableMailbox
from .hosted_renewal import ROSTER_LIFETIME_SECONDS, assess
from .hosted_session import SealedSession, enrollment
from .hosted_tokens import HostedAccount, HostedUnavailable, SignInRequired, TokenVault
from .hosted_transport import HostedTransport, TransportError
from .user_presence import confirm as confirm_user, status as user_verification
from .usage import record as record_usage

PHONE_ONLINE_SECONDS = 300  # Phones re-advertise their capabilities every two minutes.
ANSWER_WINDOW_SECONDS = 60  # Contact results, call history and refusals answer a recent request only.
SUBSCRIBE_SECONDS = 90  # Renew this computer's subscription with each phone heartbeat (phones keep it 10 min).
NOTICE_SECONDS = 60  # "Answered on <computer>" and similar notes stay this long.
FAST_POLL_SECONDS = 4  # Ringing calls need prompt delivery once texts and calls are on.
ROOT_ONLY = "Only your main computer can approve or remove devices."
NO_ACCESS = ("This Saiph account has no beta access yet. Activate your invitation code on your Saiph "
             "account page with this same account, then try again.")
EXCLUSIVE = ("This computer is paired with a self-hosted Hub. A device uses either a self-hosted Hub "
             "or Saiph Hosted, never both.")
HOSTED_ACTIVE = ("This computer uses Saiph Hosted. A device uses either Saiph Hosted or a self-hosted Hub, "
                 "never both. Turn off and forget Saiph Hosted first.")
CONFIG_KEYS = {"service_url", "issuer", "audience", "client_id", "refresh_tokens"}


class HostedError(ValueError):
    pass


def _unreachable(error) -> str:
    return NO_ACCESS if error.status == 403 else "Saiph Hosted is unreachable. Try again when you are online."


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


def refusal_text(body) -> str:
    """Plain words for a call action another computer, or the phone's state, overtook."""
    if body["reason"] == "handled":
        if not body["by"]:
            return "Already handled on another computer."
        return ("Answered on " if body["handled"] == "answer" else "Declined on ") + body["by"] + "."
    return {"not_ringing": "The call is no longer ringing.",
            "in_call": "Not dialed: your phone is already on a call.",
            "dialing": "Not dialed: your phone is already placing a call."}[body["reason"]]


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
        self._asked = {}  # (phone, request type) -> when this computer asked; memory only.
        self._seen = {}  # phone -> last authenticated event time; memory only.
        self._sync_requested = set()
        self._subscribed = {}  # phone -> when this computer last subscribed to it; memory only.
        self._notices = {}  # phone -> {"text", "at"}: why a call action was not carried out.
        self.next_poll_at = 0.0
        # Installed by the desktop window: pause media while a call rings, and
        # show incoming/missed calls as system notifications.
        self.call_state = lambda state: None
        self.phone_alert = lambda title, text: getattr(self.workspace, "phone_alert", lambda *_: None)(title, text)
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
            bundled = None if self.identity.exists() else packaged_config()
            settings = bundled or {}
        try:
            return validate_config({key: settings[key] for key in CONFIG_KEYS if key in settings}) if settings else None
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
            for phone in self.workspace.store.all("hosted_phone"):
                self._forget_phone(phone["id"])
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
        self._asked.clear()
        self._subscribed.clear()
        self._notices.clear()
        self._outgoing_clipboard = None
        self.decision = None
        self.status, self.error = status, ""

    def _open(self):
        """Load the existing identity; never creates or repairs one."""
        if self.session is not None:
            return
        config = self._config()
        info, signing, encryption = self.identity.load()
        if info.role == "root":
            root = local_root(info.deployment_id, info.device_id, signing, encryption)
        elif info.role == "member":
            root = self._pinned_root()
            if root is None or root.deployment_id != info.deployment_id or root.device_id == info.device_id:
                raise KeyStorageError()
        else:
            raise KeyStorageError()
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
                except TransportError as error:
                    raise HostedError(_unreachable(error)) from None
                finally:
                    probe.close()
                if page["chain"]:
                    raise HostedError("This Saiph account already has a main computer. To add this computer, "
                                      "choose Join as another computer and approve it on your main computer.")
                self.identity.create(deployment, role="root")
            self._open()
            if not self.is_root():
                raise HostedError("This computer joined as another computer. Its main computer approves devices.")
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
            if not self.is_root():
                raise HostedError("Show the code from your main computer; it approves new devices.")
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
            self._require_root()
            try:
                request = verify_request_code(code, self.root)
            except ApprovalError:
                raise HostedError("This request code is invalid, expired or for another deployment.") from None
            device = request["candidate"]["device"]
            return {"device_id": device["id"], "fingerprint": device_fingerprint(device), "expires_at": request["expires_at"]}

    def offered_requests(self) -> list:
        """Requests that devices offered through the service, verified here against this root.

        The service is untrusted: each code must carry a valid signature bound to this
        computer's root, and the owner still compares the full fingerprint before approving."""
        with self.lock:
            self._require_enabled()
            self._open()
            self._require_root()
            token = self._token_or_error()
            try:
                codes = self.transport.offered_requests(token)
            except TransportError:
                return []  # Offline, or a service without offered requests: pasting still works.
            members = set(self.session.current())
            offered = {}
            for code in codes:
                try:
                    request = verify_request_code(code, self.root)
                except ApprovalError:
                    continue
                device = request["candidate"]["device"]
                if device["id"] not in members:
                    offered[device["id"]] = {"code": code, "device_id": device["id"], "fingerprint": device_fingerprint(device),
                                             "expires_at": request["expires_at"]}
            return sorted(offered.values(), key=lambda item: item["expires_at"])
    def approve(self, code, label, confirmed) -> dict:
        if confirmed is not True:
            raise HostedError("Compare the device fingerprint on both screens, then confirm.")
        if type(label) is not str or not 0 < len(label.strip()) <= 40:
            raise HostedError("Name the device you are approving.")
        with self.lock:
            self._require_enabled()
            self._open()
            self._require_root()
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
        with self.lock:
            self._require_enabled()
            self._open()
            self._require_root()
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
            self._forget_phone(device_id)
        self.changed()
        return {"revoked": device_id}

    # ------------------------------------------------------ second computer
    def is_root(self) -> bool:
        return self.info is not None and self.info.role == "root"

    def _require_root(self):
        if not self.is_root():
            raise HostedError(ROOT_ONLY)

    @property
    def _pin_path(self) -> Path:
        return self.folder / "root-pin.json"

    def _pinned_root(self):
        """The main computer this member trusts, pinned once after a fingerprint comparison."""
        try:
            raw = self._pin_path.read_bytes()
            value = json.loads(raw) if len(raw) <= 4096 else None
            if type(value) is not dict or set(value) != {"deployment_id", "device_id", "signing_key", "encryption_key"}:
                return None
            return TrustedRoot(value["deployment_id"], value["device_id"], value["signing_key"], value["encryption_key"])
        except (OSError, ValueError, ApprovalError):
            return None

    def inspect_join(self, code) -> dict:
        """What the main computer's code says, for comparison before anything is created."""
        with self.lock:
            self._require_enabled()
            if self.identity.exists():
                raise HostedError("This computer already has a Saiph Hosted identity.")
            try:
                info = inspect_root_code(code)
            except ApprovalError:
                raise HostedError("This code is invalid or expired. Show a fresh code on your main computer.") from None
            return {"device_id": info["device_id"], "fingerprint": info["display_fingerprint"]}

    def join(self, code, confirmed) -> dict:
        """Join the signed-in account as another computer, approved later by its main computer.

        The pin comes only from the code the owner compared, group by group, with the
        main computer's screen. Joining creates new keys and a pending request; it
        grants nothing until the main computer approves this computer's fingerprint.
        """
        if confirmed is not True:
            raise HostedError("Compare the whole fingerprint with your main computer's screen, then confirm.")
        with self.lock:
            self._require_enabled()
            if self.identity.exists():
                raise HostedError("This computer already has a Saiph Hosted identity.")
            try:
                root = trust_root_code(code, trusted_out_of_band=True)
            except ApprovalError:
                raise HostedError("This code is invalid or expired. Show a fresh code on your main computer.") from None
            config = self._config()
            token = self._token_or_error()
            probe = self._transport_factory(config["service_url"], None)
            try:
                deployment = probe.discover_account(token)
                page = probe.roster_page(token)
            except TransportError as error:
                raise HostedError(_unreachable(error)) from None
            finally:
                probe.close()
            if deployment != root.deployment_id:
                raise HostedError("This code belongs to a different Saiph account. Sign in with the account your main computer uses.")
            if not page["chain"]:
                raise HostedError("This Saiph account has no main computer yet. Set this computer up as the main computer instead.")
            # Record the pin before creating keys: an interrupted join keeps its keys and
            # needs an explicit Forget, never a silent replacement.
            self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = self._pin_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"deployment_id": root.deployment_id, "device_id": root.device_id,
                                             "signing_key": root.signing_key, "encryption_key": root.encryption_key},
                                            sort_keys=True), encoding="utf-8")
            temporary.replace(self._pin_path)
            self.identity.create(root.deployment_id, role="member")
            self._open()
            self.status, self.error = "awaiting_approval", ""
        self.changed()
        return self.request_code()

    def request_code(self) -> dict:
        """A fresh request code for the main computer, with this computer's fingerprint."""
        with self.lock:
            self._require_enabled()
            self._open()
            if self.is_root():
                raise HostedError("This is your main computer; it approves other devices.")
            token = self._token_or_error()
            try:
                code = make_request_code(self.root, self.info.device_id, self.signing, self.session.encryption)
                candidate = enrollment(self.info.deployment_id, self.info.device_id, self.signing, self.session.encryption)
                # The main computer approves exactly the pending request this computer submitted.
                self._pending(self.transport.enroll(token, candidate), candidate["device"])
            except (ApprovalError, TransportError):
                raise HostedError("The request could not be sent to Saiph Hosted. Try again shortly.") from None
            try:
                self.transport.offer_request(token, code)
            except TransportError:
                pass  # An older service: the code can still be pasted on the main computer.
            return {"code": code, "modules": qr_modules(code), "expires_in": 300,
                    "fingerprint": device_fingerprint(candidate["device"]),
                    "root_fingerprint": self.root.display_fingerprint}

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
                if expires is None and self.is_root() and self.session.history_cursor()["after_version"] == 0:
                    self._genesis(token)
                    expires = self.session.roster["expires_at"] if self._active() else None
                self.decision = assess(expires, self.clock(), server_offset=getattr(self.transport, "server_offset", None))
                if self.decision.blocked:
                    self.status, self.error = "clock", "Correct this computer's clock to keep devices approved."
                elif self.decision.due and self.is_root():
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
                elif not self.decision.blocked and not self.is_root():
                    membership = self.session.membership()
                    if membership == "removed":
                        self.status, self.error = "removed", "Your main computer removed this computer from your Saiph account."
                    elif membership == "pending":
                        self.status, self.error = "awaiting_approval", ""
                    else:
                        self.status, self.error = "renewal_pending", "Waiting for your main computer to renew device approvals."
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
            self._seen[envelope["header"]["source"]] = int(self.clock())
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
                        record_usage(self.workspace, "clipboard_received")
                    outcome = "succeeded"
                elif event in (NOTIFICATION_UPSERT, NOTIFICATION_REMOVE):
                    self._notification(envelope["header"]["source"], payload)
                    outcome = "succeeded"
                elif event in PHONE_DATA:
                    self._phone_data(envelope["header"]["source"], event_id, payload)
                    outcome = "succeeded"
                # Anything else, including phone actions sent to a computer, has no effect here.
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
        record_usage(self.workspace, "clipboard_sent")
        return True

    def _notification(self, source, payload):
        action, value = read_notification(payload)
        identifier = hashlib.sha256((source + "\0" + (value if action == "remove" else value["key"])).encode()).hexdigest()
        if action == "remove":
            self.workspace.store.delete("hosted_notification", identifier)
        else:
            self.workspace.store.save("hosted_notification", {**value, "id": identifier, "device_id": source})
            record_usage(self.workspace, "phone_notification")

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

    # ------------------------------------------------------- texts and calls
    def _capabilities(self, device) -> list:
        try:
            return list(self.workspace.store.get("hosted_phone", device).get("capabilities") or [])
        except ValueError:
            return []

    def _phone_data(self, source, event_id, payload):
        """Show a phone's texts and call state; actions never originate here."""
        kind_, body = read_phone_data(payload)
        now = int(self.clock())
        if kind_ == PHONE_CAPABILITIES:
            self.workspace.store.save("hosted_phone", {"id": source, "capabilities": body["capabilities"], "seen_at": now})
            if now - self._subscribed.get(source, 0) >= SUBSCRIBE_SECONDS:
                # Any approved computer, root or not, asks for texts and calls by name.
                self.mailbox.stage(source, subscribe_payload(self.label()), ttl_seconds=300)
                self._subscribed[source] = now
                self._wake.set()
            if "sms" not in body["capabilities"]:
                self._sync_requested.discard(source)
            elif source not in self._sync_requested and not any(
                    row.get("device_id") == source for row in self.workspace.store.all("phone_thread")):
                # A computer without this phone's conversations asks once for a fresh list.
                self._sync_requested.add(source)
                self.mailbox.stage(source, phone_command(SMS_SYNC, {}), ttl_seconds=60)
                self._wake.set()
            return
        if kind_ == CALL_REFUSED:
            # Only in answer to this computer's own recent call action.
            asked = self._asked.get((source, refused_request(body)))
            if asked is None or not 0 <= now - asked <= ANSWER_WINDOW_SECONDS:
                raise FeatureError()
            self._notices[source] = {"text": refusal_text(body), "at": now}
            return
        if DATA_CAPABILITY[kind_] not in self._capabilities(source):
            raise FeatureError()
        if kind_ == CALL_HANDLED:
            self._call_handled(source, event_id, body)
            return
        if kind_ in ANSWERS:
            asked = self._asked.get((source, ANSWERS[kind_]))
            if asked is None or not 0 <= now - asked <= ANSWER_WINDOW_SECONDS:
                raise FeatureError()
        features = getattr(self.workspace, "phone_features", None)
        if features is None:
            raise FeatureError()
        if kind_ == CALL_STATE and body["state"] != "ringing":
            # Keep "Answered on <computer>" while the same call continues or ends.
            current = next((row for row in self.workspace.store.all("phone_call") if row.get("device_id") == source), {})
            if current.get("handled_by") is not None and current.get("state") != "ringing":
                body = {**body, "handled": current.get("handled"), "handled_by": current["handled_by"]}
        features.event({"id": event_id, "type": kind_, "payload": body, "source": source}, None)
        if kind_ == CALL_STATE:
            self._call(body)

    def label(self) -> str:
        """This computer's name as other computers see it in "Answered on ..."."""
        name = (self.workspace.settings.get("machine") or {}).get("name")
        return name if type(name) is str and name.strip() else "Computer"

    def _call_handled(self, source, event_id, body):
        """Another computer (or this one) won the race: stop ringing everywhere at once."""
        features = getattr(self.workspace, "phone_features", None)
        if features is None:
            raise FeatureError()
        current = next((row for row in self.workspace.store.all("phone_call") if row.get("device_id") == source), {})
        state = "active" if body["operation"] == "answer" else "ended"
        row = {"state": state, "number": current.get("number", ""), "name": current.get("name", ""),
               "handled": body["operation"], "handled_by": body["by"]}
        features.event({"id": event_id, "type": CALL_STATE, "payload": row, "source": source}, None)
        try:
            self.call_state(state)
        except Exception:
            pass

    def _call(self, body):
        try:
            self.call_state(body["state"])
        except Exception:
            pass  # Pausing media is a convenience; the call state is already shown.
        if (self.workspace.settings.get("link") or {}).get("call_alerts") is False:
            return
        caller = body["name"] or body["number"] or "Unknown caller"
        if body["state"] == "ringing":
            self.phone_alert("Incoming call", f"{caller} is calling. Answer or decline in Saiph.")
        elif body["state"] == "missed":
            self.phone_alert("Missed call", caller)

    def _forget_phone(self, device):
        """Remove a revoked phone's capabilities and its texts and calls from this computer."""
        store = self.workspace.store
        store.delete("hosted_phone", device)
        self._seen.pop(device, None)
        self._sync_requested.discard(device)
        for name in ("thread", "message", "call", "attachment"):
            for row in store.all("phone_" + name):
                if row.get("device_id") == device:
                    store.delete("phone_" + name, row["id"])

    def phones(self) -> list[dict]:
        """Approved phones that shared texts or calls, for the shared Phone page."""
        if not self.enabled():
            return []
        rows = self.workspace.store.all("hosted_phone")
        with self.lock:
            try:
                members = set(self._targets()) if self.session is not None and self._active() else None
            except EnvelopeError:
                members = None
            labels = self._labels()
            now = int(self.clock())
            result = []
            for row in rows:
                if members is not None and row["id"] not in members:
                    continue
                seen = max(int(row.get("seen_at") or 0), self._seen.get(row["id"], 0))
                notice = self._notices.get(row["id"])
                result.append({"id": row["id"], "name": labels.get(row["id"], "Phone"), "hosted": True,
                               "call_notice": notice["text"] if notice and 0 <= now - notice["at"] <= NOTICE_SECONDS else None,
                               "online": members is not None and now - seen <= PHONE_ONLINE_SECONDS,
                               "capabilities": list(row.get("capabilities") or []),
                               "last_seen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seen)) if seen else None})
        return result

    def is_phone(self, device) -> bool:
        return type(device) is str and any(row["id"] == device for row in self.workspace.store.all("hosted_phone"))

    def phone_command(self, device, kind_, body) -> dict:
        """Queue one phone action for an approved phone that offers it.

        The phone repeats every check: it acts only for current, subscribed roster
        members, only with its owner's texts-and-calls setting and the matching
        Android permission, and settles call races itself (first answer or
        decline wins; the others get `call.refused`, shown as a notice here).
        """
        capability = COMMAND_CAPABILITY.get(kind_)
        if capability is None:
            raise HostedError("This feature is unavailable on that device.")
        with self.lock:
            self._require_enabled()
            self._token_or_error()
            self._open()
            if not self._active():
                raise HostedError("Device approvals are being renewed. Try again shortly.")
            if device not in self._targets():
                raise HostedError("That device is no longer approved.")
            phone = next((row for row in self.phones() if row["id"] == device), None)
            if phone is None or capability not in phone["capabilities"]:
                raise HostedError("This feature is unavailable on that device.")
            if not phone["online"]:
                raise HostedError(f"{phone['name']} is offline. Nothing was sent; try again when it reconnects.")
            try:
                payload = phone_command(kind_, body)
            except FeatureError:
                raise HostedError("This request could not be sent. Check the number or shorten the message.") from None
            if kind_ in (SMS_OPEN, SMS_SEND):
                thread = next((row for row in self.workspace.store.all("phone_thread")
                               if row.get("device_id") == device and row.get("thread") == payload["thread"]), None)
                if thread is None:
                    raise HostedError("This conversation is unavailable.")
                if kind_ == SMS_SEND and len(thread.get("recipients") or []) != 1:
                    raise HostedError("Group replies stay in your phone's messaging app.")
            if kind_ == CALL_COMMAND:
                call = next((row for row in self.workspace.store.all("phone_call") if row.get("device_id") == device), {})
                if call.get("state") != "ringing":
                    handled = call.get("handled_by")
                    raise HostedError(refusal_text({"reason": "handled", "handled": call.get("handled"), "by": handled})
                                      if handled is not None else "The call is no longer ringing.")
            try:
                event_id = self.mailbox.stage(device, payload, ttl_seconds=30 if kind_ == CALL_COMMAND else 60)
            except EnvelopeError:
                raise HostedError("This request could not be sent. Shorten the message and try again.") from None
            if kind_ in ANSWERS.values() or kind_ in (CALL_COMMAND, CALL_DIAL):
                # Answers and refusals are accepted only for this computer's own recent request.
                self._asked[(device, kind_)] = int(self.clock())
                self._notices.pop(device, None)
            self._wake.set()
        return {"queued": True, "id": event_id}

    def poll(self) -> None:
        """Deliver queued actions and fetch new events between full scheduler passes."""
        with self.lock:
            if not self.enabled() or self.self_hosted_paired() or self.session is None or self.decision is None:
                return
            if self.decision.blocked or self.status != "active" or not self._active():
                return
            try:
                self._sync()
            except (ApprovalError, EnvelopeError, TransportError, HostedError, FeatureError, OSError):
                return  # The next full step reports the connection state.
        self.changed()

    def _fast_poll(self) -> bool:
        """Poll often only while a phone shares calls or texts with this computer."""
        return any({"calls", "sms"} & set(row.get("capabilities") or []) for row in self.workspace.store.all("hosted_phone"))

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
                own = {"id": self.info.device_id, "signing_key": self.info.signing_key, "encryption_key": self.info.encryption_key}
                result.update(role=self.info.role, device_id=self.info.device_id,
                              fingerprint=self.root.display_fingerprint if self.is_root() else device_fingerprint(own),
                              root_fingerprint=self.root.display_fingerprint)
            if self.session is not None and self._active():
                labels = self._labels()
                members = self.session.current()
                decision = self.decision
                expires = self.session.roster["expires_at"]
                result["roster"] = {
                    "version": self.session.roster["version"], "expires_at": expires,
                    "renew_at": expires - 4 * 3600, "clock_warning": bool(decision and decision.skew_warning),
                    "members": [{"id": key, "root": key == self.root.device_id, "self": key == self.info.device_id,
                                 "label": "This computer" if key == self.info.device_id
                                 else labels.get(key, "Main computer" if key == self.root.device_id else "Device"),
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
                    self.next_poll_at = time.monotonic() + FAST_POLL_SECONDS
                elif time.monotonic() >= self.next_poll_at:
                    self.next_poll_at = time.monotonic() + FAST_POLL_SECONDS
                    try:
                        if self._fast_poll():
                            self.poll()
                    except Exception:
                        pass  # The next full step reports the connection state.
            self._wake.wait(1.0)

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        with self.lock:
            self._deactivate("off")
