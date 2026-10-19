# SPDX-License-Identifier: AGPL-3.0-or-later
"""Opt-in Saiph Cloud preview for the desktop. OFF by default.

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
import secrets
import shutil
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from .clipboard import RecentClipboard
from .hosted_clipboard import CloudClipboardImages, IMAGE_FORMATS
from .hosted_approval import (
    ApprovalError, RootApproval, TrustedRoot, initialize_root, inspect_root_code, local_root, make_request_code,
    make_root_code, prepare_anchored_catchup, trust_root_code, verify_request_code,
)
from .hosted_crypto import EnvelopeError, canonical
from .hosted_features import (
    PHOTOS_ITEM, PHOTOS_SYNC, PHOTO_REQUEST, PHOTO_ORIGINAL, ANSWERS, CALL_COMMAND, CALL_DIAL, CALL_HANDLED, CALL_REFUSED, CALL_STATE, CLIPBOARD_TEXT, COMMAND_CAPABILITY,
    DATA_CAPABILITY, FILE_OFFER, NOTIFICATION_REMOVE, NOTIFICATION_UPSERT, PHONE_CAPABILITIES, PHONE_DATA, SMS_OPEN,
    SMS_SEND, SMS_SYNC, MAX_CLIPBOARD_TEXT_BYTES, FeatureError, clipboard_payload, dismiss_payload, kind, phone_command, read_clipboard,
    read_notification, read_phone_data, refused_request, subscribe_payload,
    CONTROL_COMMAND, MEDIA_STATE, PHONE_STATUS, PHONE_WALLPAPER, STATUS_DATA, STATUS_REQUEST, WALLPAPER_REQUEST,
    DEVICE_HELLO, DEVICE_LABELS, device_hello, device_labels, read_device_hello, read_device_labels,
    APPS_LIST, APPS_REQUEST, SCREEN_CAPABILITIES, apps_request_payload, read_apps_list, read_screen_capabilities,
    APPS_ICONS, APPS_ICONS_REQUEST, apps_icons_request_payload, read_apps_icons,
    NOTIFICATION_ACTION, NOTIFICATION_ACTIONS, NOTIFICATION_OPEN, NOTIFICATION_REPLY, PHONE_FEATURES, SMS_ATTACHMENT_ORIGINAL,
    SMS_ATTACHMENT_REQUEST, notification_command, read_notification_actions, read_phone_features,
)
from .paths import received_dir
from .phone_settings import data_allowed, flag as phone_flag
from . import phone_status
from .phone_status import REFRESH_SECONDS, STATUS_SECONDS, WALLPAPER_SECONDS, StatusBook
from .hosted_identity import HostedIdentity
from .hosted_distribution import packaged_config
from .hosted_keys import KeyStorageError
from .hosted_login import HostedLoginConfig
from .hosted_mailbox import DurableMailbox
from .hosted_renewal import ROSTER_LIFETIME_SECONDS, assess
from .hosted_session import SealedSession, enrollment
from .hosted_tokens import HostedAccount, HostedUnavailable, SignInRequired, TokenVault
from .hosted_access import REFRESH_SECONDS as ACCESS_REFRESH_SECONDS, parse_access, summarize
from .hosted_transport import HostedTransport, TransportError
from .hosted_transfers import MAX_PLAINTEXT, HostedTransfers, no_network
from .lan_files import LanInbox
from .session_offer import FILE_REQUEST, SESSION_CLOSE, SESSION_OFFER, SESSION_REFUSE
from .user_presence import confirm as confirm_user, status as user_verification
from .usage import record as record_usage

NAMES_SECONDS = 600  # Device names are re-shared at most every ten minutes unless they change.
JOIN_FLOOD_SECONDS, JOIN_FLOOD_LIMIT = 600, 3  # More than three new devices in ten minutes warns.
PHONE_ONLINE_SECONDS = 300  # Phones re-advertise their capabilities every two minutes.
ANSWER_WINDOW_SECONDS = 60  # Contact results, call history and refusals answer a recent request only.
SUBSCRIBE_SECONDS = 90  # Renew this computer's subscription with each phone heartbeat (phones keep it 10 min).
NOTICE_SECONDS = 60  # "Answered on <computer>" and similar notes stay this long.
FAST_POLL_SECONDS = 4  # Ringing calls need prompt delivery once texts and calls are on.
# A notification already this old when it arrives was on the phone before this
# computer heard of it (a phone resends what is showing when it reconnects or a
# computer joins). It is listed in Saiph but not announced, like Hub "silent" rows.
TOAST_STALE_SECONDS = 600
ROOT_ONLY = "Only your main computer can approve or remove devices."
NO_ACCESS = ("This Saiph account has no Saiph Cloud access yet. Start your free trial or subscribe on the Saiph "
             "website with this same account (or activate an invitation code there), then try again.")
EXCLUSIVE = ("This computer is paired with a self-hosted Hub. A device uses either a self-hosted Hub "
             "or Saiph Cloud, never both.")
HOSTED_ACTIVE = ("This computer uses Saiph Cloud. A device uses either Saiph Cloud or a self-hosted Hub, "
                 "never both. Turn off and forget Saiph Cloud first.")
CONFIG_KEYS = {"service_url", "issuer", "audience", "client_id", "refresh_tokens"}


class HostedError(ValueError):
    pass


def _unreachable(error) -> str:
    return NO_ACCESS if error.status == 403 else "Saiph Cloud is unreachable. Try again when you are online."


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
        self.clipboard_dispatch = None
        self.sign_in_completed = lambda: None
        self.clipboard_images = CloudClipboardImages(self)
        self._outgoing_clipboard = None
        self._offers = {}
        self._photos_asked = {}  # (device, photo) -> (request event, expiry); memory only.
        self._parts_asked = {}  # (device, thread, message, part) -> (request event, expiry); MMS pictures, memory only.
        self._asked = {}  # (phone, request type) -> when this computer asked; memory only.
        self._seen = {}  # phone -> last authenticated event time; memory only.
        self._sync_requested = set()
        self._subscribed = {}  # phone -> when this computer last subscribed to it; memory only.
        self._notices = {}  # phone -> {"text", "at"}: why a call action was not carried out.
        self._lan = None  # Nearby-phone listener; only while the owner's Add a device window is open.
        self._denied = {}  # device -> request expiry; denied requests stay hidden until then. Memory only.
        self._named = {}  # device -> (digest, when) device names were last sent; memory only.
        self._asked_to_join = {}  # device -> first seen; many new devices at once raise a warning.
        self._screen = {}  # phone -> (screen capabilities, when advertised); memory only.
        self._apps = {}  # phone -> {"pages": {page: apps}, "total", "at"}: answers to apps.request; memory only.
        self._icon_asks = {}  # (phone, package) -> when this computer asked for its icon.
        self._icons_in = {}  # phone -> ([(package, version, bytes)], [package]): received, not yet cached.
        self.next_poll_at = 0.0
        self._access = None  # Last /v1/access answer (free trial notice only); memory only.
        self._access_at = None  # time.monotonic() of that answer.
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
        # A short tray message when a Cloud file send finishes or finally fails.
        self.transfer_alert = lambda message: getattr(self.workspace, "phone_alert", lambda *_: None)("Saiph", message)
        self.transfers = HostedTransfers(self)  # Also removes ciphertext a previous run left behind.
        self.lan_inbox = LanInbox(self)  # Files arriving over the local network; removes leftovers too.
        self._firewall = {"notice": "", "at": None, "busy": False}  # Read-only Windows Firewall check, cached.
        self._offer_receipts = None
        self._migrate_packaged_session()

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

    def _migrate_packaged_session(self):
        """Keep existing standard Cloud accounts signed in without moving trust.

        Older packaged builds pinned memory-only sessions. Match every public
        deployment field before enabling the existing protected rotating vault.
        Custom deployments and disabled profiles retain their chosen settings.
        No account token, sign-out tombstone or device identity is changed here.
        """
        if not self.enabled() or self.self_hosted_paired():
            return
        bundled = packaged_config()
        if (bundled and bundled.get("refresh_tokens") is True
                and self.settings.get("refresh_tokens") is not True
                and all(self.settings.get(key) == bundled[key]
                        for key in ("service_url", "issuer", "audience", "client_id"))):
            self._save({**self.settings, "refresh_tokens": True})

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
            raise HostedError("Saiph Cloud is on or off.")
        with self.lock:
            if flag:
                if self.self_hosted_paired():
                    raise HostedError(EXCLUSIVE)
                if self._config() is None:
                    raise HostedError("Enter your hosted deployment settings first.")
            # Pin the selected defaults before creating identity material. Future
            # installer updates cannot silently change an existing deployment.
            self._save({**self.settings, **(self._config() or {}), "enabled": flag})
            if flag:
                self._migrate_packaged_session()
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
            raise HostedError("Confirm that this computer should stop using Saiph Cloud.")
        if self.enabled():
            raise HostedError("Turn off Saiph Cloud first.")
        confirm_user(self.workspace, "retire this computer's Saiph Cloud identity")
        with self.lock:
            if self.enabled():
                raise HostedError("Turn off Saiph Cloud first.")
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
            self.account = HostedAccount(login, vault, on_change=self._account_changed,
                                         on_sign_in=lambda: self.sign_in_completed(), **self._auth)
            self._account_config = login
        return self.account

    def _account_changed(self):
        self._wake.set()
        self.changed()

    def _require_enabled(self):
        if not self.enabled():
            raise HostedError("Turn on Saiph Cloud first.")
        if self.self_hosted_paired():
            raise HostedError(EXCLUSIVE)

    def sign_in(self, google=False) -> dict:
        if type(google) is not bool:
            raise HostedError("Choose a sign-in method.")
        with self.lock:
            self._require_enabled()
            account = self._account()
        if google:
            account.begin_sign_in(google=True)
        else:
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

    def _load_access(self, token, *, force=False):
        """Refresh the free trial notice from the service. Wording only; failures keep the last answer."""
        if not force and self._access_at is not None and time.monotonic() - self._access_at < ACCESS_REFRESH_SECONDS:
            return
        config = self._config()
        if config is None:
            return
        try:
            probe = self._transport_factory(config["service_url"], None)
        except TransportError:
            return
        try:
            self._access = parse_access(probe.access(token))
            self._access_at = time.monotonic()
        except (TransportError, AttributeError):
            pass
        finally:
            probe.close()

    def _refused(self, error, token) -> str:
        """Why Saiph Cloud refused: a free trial that ended reads differently from no access at all."""
        if error.status != 403:
            return _unreachable(error)
        self._load_access(token, force=True)
        summary = summarize(self._access, self.clock())
        return summary["message"] if summary and summary["message"] else NO_ACCESS

    def update_feed(self):
        """The Saiph account's desktop update source, or a package_updates reason code.

        Only the origin packaged into this build qualifies; a custom deployment is never
        an update source, whatever it is called."""
        from .package_updates import CloudFeed
        packaged = packaged_config()
        with self.lock:
            config = self._config()
            account = self._account() if config is not None else None
        if packaged is None or config is None or config["service_url"].rstrip("/") != packaged["service_url"]:
            return "cloud_unofficial"
        try:
            token = account.access_token()
        except SignInRequired:
            return "cloud_signed_out"
        except HostedUnavailable:
            raise ValueError("Saiph is unreachable. Check your connection and try again.") from None
        return CloudFeed(packaged["service_url"], token)

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
        self.transfers.cancel_all("Saiph Cloud was turned off. Nothing was sent." if status == "off"
                                  else "Sign in to Saiph Cloud again, then retry.")
        self.lan_inbox.close()
        self._offers.clear()
        self._asked.clear()
        self._photos_asked.clear()
        self._subscribed.clear()
        self._notices.clear()
        self._access = self._access_at = None
        self._outgoing_clipboard = None
        self.decision = None
        self.clipboard_images.close()
        if self._lan is not None:
            self._lan.stop()
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
            raise HostedError("This computer's clock differs from Saiph Cloud by more than an hour. Correct the clock first.")
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
                    raise HostedError(self._refused(error, token)) from None
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
            raise HostedError("Saiph Cloud returned an invalid device request.")
        return {**member, "expires_at": response["expires_at"]}

    def _token_or_error(self):
        try:
            return self._token()
        except SignInRequired:
            self._deactivate("sign_in_required")
            raise HostedError("Sign in to Saiph Cloud first.") from None
        except HostedUnavailable:
            raise HostedError("Saiph Cloud is unreachable. Try again when you are online.") from None

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

    def _refresh(self, token, *, report_refusal=False):
        try:
            self.transport.refresh_roster(token)
        except TransportError as error:
            # 403: the account has no Cloud access (for example a free trial that ended).
            if report_refusal and error.status == 403:
                raise
        except EnvelopeError:
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

    @property
    def _blocked_path(self) -> Path:
        return self.folder / "blocked-devices.json"

    def _blocked(self) -> set:
        try:
            value = json.loads(self._blocked_path.read_text(encoding="utf-8"))
            return {item for item in value if type(item) is str} if type(value) is list else set()
        except (OSError, ValueError):
            return set()

    def deny_request(self, device_id) -> dict:
        """Hide this request until it expires. The device may ask again with a new request."""
        with self.lock:
            offered = next((item for item in self.offered_requests() if item["device_id"] == device_id), None)
            if offered is None:
                return {"denied": False}
            self._denied[device_id] = offered["expires_at"]
        self.changed()
        return {"denied": True}

    def block_device(self, device_id) -> dict:
        """Never show or approve requests from this device ID or its signing key again on this computer."""
        with self.lock:
            offered = next((item for item in self.offered_requests() if item["device_id"] == device_id), None)
            if offered is None:
                return {"blocked": False}
            blocked = self._blocked() | {device_id, "key:" + offered["signing_key"]}
            self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = self._blocked_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(sorted(blocked)[-500:]), encoding="utf-8")
            temporary.replace(self._blocked_path)
        self.changed()
        return {"blocked": True}

    def pending_approvals(self) -> dict:
        """The approval pop-up's view: one request at a time and a warning when many arrive."""
        requests = self.offered_requests()
        now = int(self.clock())
        with self.lock:
            for item in requests:
                self._asked_to_join.setdefault(item["device_id"], now)
            self._asked_to_join = {key: at for key, at in self._asked_to_join.items() if now - at <= JOIN_FLOOD_SECONDS}
            flood = len(self._asked_to_join) > JOIN_FLOOD_LIMIT
        return {"requests": [{key: item[key] for key in ("code", "device_id", "fingerprint", "expires_at", "location")}
                             for item in requests[:1]], "waiting": len(requests), "flood": flood}

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
            blocked, now = self._blocked(), int(self.clock())
            self._denied = {key: until for key, until in self._denied.items() if until > now}
            offered = {}
            for code in codes:
                try:
                    request = verify_request_code(code, self.root)
                except ApprovalError:
                    continue
                device = request["candidate"]["device"]
                if (device["id"] not in members and device["id"] not in blocked and device["id"] not in self._denied
                        and "key:" + device["signing_key"] not in blocked):
                    # Saiph Cloud does not report where a request came from yet (see QRLESS_CONNECT.md).
                    offered[device["id"]] = {"code": code, "device_id": device["id"], "fingerprint": device_fingerprint(device),
                                             "expires_at": request["expires_at"], "signing_key": device["signing_key"],
                                             "location": None}
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
                checked = verify_request_code(code, self.root)
            except ApprovalError:
                raise HostedError("This request code is invalid, expired or for another deployment.") from None
            blocked = self._blocked()
            device = checked["candidate"]["device"]
            if device["id"] in blocked or "key:" + device["signing_key"] in blocked:
                raise HostedError("You blocked this device on this computer.")
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
                raise HostedError("Saiph Cloud has not accepted the approval yet. It will retry automatically.")
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
                raise HostedError("Saiph Cloud has not accepted the revocation yet. It will retry automatically.")
            self._watch_members()
            labels = self._labels()
            labels.pop(device_id, None)
            self._write_labels(labels)
            self._forget_phone(device_id)
        self.changed()
        return {"revoked": device_id}

    # ------------------------------------------------ nearby phone, no QR code
    def lan_link_start(self) -> dict:
        """Let a signed-in phone on this network find this main computer for five minutes.

        Replaces only the QR's delivery of the root code: the owner compares a
        six-digit code on both screens, and approval still runs through approve()
        with native owner verification. See lan_link.py for the protocol.
        """
        from .lan_link import LinkError, LinkListener
        with self.lock:
            self._require_enabled()
            self._open()
            self._require_root()
            self._token_or_error()
            if self._lan is None:
                self._lan = LinkListener(root_code=lambda: self.root_code()["code"], label=self.label,
                                         verify=self._verify_nearby_request, changed=self.changed)
            listener = self._lan
        try:
            return listener.start()
        except LinkError as error:
            raise HostedError(str(error)) from None

    def _verify_nearby_request(self, code):
        with self.lock:
            self._require_enabled()
            self._open()
            request = verify_request_code(code, self.root)
            if request["candidate"]["device"]["id"] in self.session.current():
                raise ApprovalError("This phone is already approved.")

    def lan_link_status(self) -> dict:
        listener = self._lan
        return listener.status() if listener is not None else {"listening": False, "expires_in": 0, "peer": None, "error": ""}

    def lan_link_stop(self) -> dict:
        listener = self._lan
        return listener.stop() if listener is not None else {"listening": False}

    def lan_link_approve(self, comparison, confirmed) -> dict:
        """Approve the nearby phone whose code the owner compared; Windows Hello still applies."""
        from .lan_link import LinkError
        if confirmed is not True:
            raise HostedError("Check that your phone shows the same code, then approve.")
        listener = self._lan
        if listener is None:
            raise HostedError("No phone is waiting. Open Saiph on your phone and try again.")
        try:
            code, name = listener.take_request(comparison)
        except LinkError as error:
            raise HostedError(str(error)) from None
        try:
            result = self.approve(code, name, True)
        except BaseException:
            listener.finish(False)
            raise
        listener.finish(True)
        return {**result, "label": name}

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
                raise HostedError("This computer already has a Saiph Cloud identity.")
            try:
                info = inspect_root_code(code)
            except ApprovalError:
                raise HostedError("This code is invalid or expired. Show a fresh code on your main computer.") from None
            return {"device_id": info["device_id"], "fingerprint": info["display_fingerprint"]}

    def join(self, code, confirmed, fingerprint=None) -> dict:
        """Join the signed-in account as another computer, approved later by its main computer.

        The pin comes only from the code the owner compared, group by group, with the
        main computer's screen. When the UI passes the fingerprint it displayed, the
        pinned key must be exactly that one. Joining creates new keys and a pending
        request; it grants nothing until the main computer approves this computer.
        """
        if confirmed is not True:
            raise HostedError("Compare the whole fingerprint with your main computer's screen, then confirm.")
        with self.lock:
            self._require_enabled()
            if self.identity.exists():
                raise HostedError("This computer already has a Saiph Cloud identity.")
            try:
                root = (trust_root_code(code, expected_fingerprint=fingerprint) if fingerprint is not None
                        else trust_root_code(code, trusted_out_of_band=True))
            except ApprovalError:
                raise HostedError("This code is invalid or expired. Show a fresh code on your main computer.") from None
            self._pin_and_join(root)
        self.changed()
        return self.request_code()

    def _account_root(self):
        """The main computer named by this account's first roster on Saiph Cloud. Untrusted until compared."""
        config = self._config()
        token = self._token_or_error()
        probe = self._transport_factory(config["service_url"], None)
        try:
            deployment = probe.discover_account(token)
            page = probe.roster_page(token, limit=1)
        except TransportError as error:
            raise HostedError(self._refused(error, token)) from None
        finally:
            probe.close()
        if not page["chain"]:
            raise HostedError("This Saiph account has no main computer yet. Set this computer up as the main computer instead.")
        try:
            genesis = page["chain"][0]["roster"]
            if (genesis.get("version") != 1 or genesis.get("deployment_id") != deployment
                    or type(genesis.get("members")) is not list or len(genesis["members"]) != 1):
                raise ApprovalError()
            member = genesis["members"][0]
            return TrustedRoot(deployment, member["id"], member["signing_key"], member["encryption_key"])
        except (ApprovalError, KeyError, TypeError, AttributeError):
            raise HostedError("Saiph Cloud returned an invalid main computer. Use your main computer's code instead.") from None

    def inspect_account_root(self) -> dict:
        """Join as another computer without pasting: show the account's main computer for comparison.

        Nothing is stored. Saiph Cloud supplies these keys, so they are trusted only
        after the owner compares every group with the main computer's own screen.
        """
        with self.lock:
            self._require_enabled()
            if self.identity.exists():
                raise HostedError("This computer already has a Saiph Cloud identity.")
            root = self._account_root()
            return {"device_id": root.device_id, "fingerprint": root.display_fingerprint}

    def join_account(self, fingerprint, confirmed) -> dict:
        """Pin the account's main computer only if it is exactly the one the owner compared."""
        if confirmed is not True or type(fingerprint) is not str:
            raise HostedError("Compare the whole fingerprint with your main computer's screen, then confirm.")
        with self.lock:
            self._require_enabled()
            if self.identity.exists():
                raise HostedError("This computer already has a Saiph Cloud identity.")
            root = self._account_root()
            if not secrets.compare_digest(root.display_fingerprint.encode(), fingerprint.encode()):
                raise HostedError("Saiph Cloud now names a different main computer. Nothing was trusted; compare again.")
            self._pin_and_join(root)
        self.changed()
        return self.request_code()

    def _pin_and_join(self, root):
        with self.lock:
            config = self._config()
            token = self._token_or_error()
            probe = self._transport_factory(config["service_url"], None)
            try:
                deployment = probe.discover_account(token)
                page = probe.roster_page(token)
            except TransportError as error:
                raise HostedError(self._refused(error, token)) from None
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
                raise HostedError("The request could not be sent to Saiph Cloud. Try again shortly.") from None
            try:
                self.transport.offer_request(token, code)
            except TransportError:
                pass  # An older service: the code can still be pasted on the main computer.
            return {"code": code, "modules": qr_modules(code), "expires_in": 300,
                    "fingerprint": device_fingerprint(candidate["device"]),
                    "root_fingerprint": self.root.display_fingerprint}

    def _labels(self) -> dict:
        """Names for approved devices: this computer's own choices over those its main computer shared."""
        shared = {key: row["label"] for key, row in self._shared_devices().items()}
        try:
            value = json.loads((self.folder / "labels.json").read_text(encoding="utf-8"))
            own = {k: v for k, v in value.items() if type(k) is str and type(v) is str} if isinstance(value, dict) else {}
        except (OSError, ValueError):
            own = {}
        return {**shared, **own}

    def _shared_devices(self) -> dict:
        """device -> {"label", "kind"}: from the main computer (members) or computers' introductions (main)."""
        try:
            value = json.loads((self.folder / "devices.json").read_text(encoding="utf-8"))
            rows = read_device_labels({"type": DEVICE_LABELS, "labels": value})["labels"]
            return {row["id"]: row for row in rows}
        except (OSError, ValueError, FeatureError, TypeError):
            return {}

    def _write_shared_devices(self, rows):
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.folder / "devices.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(sorted(rows, key=lambda row: row["id"])), encoding="utf-8")
        temporary.replace(path)

    def device_kind(self, device):
        if device == getattr(self.root, "device_id", None) or (self.info is not None and device == self.info.device_id):
            return "computer"
        if self.is_phone(device):
            return "phone"
        return (self._shared_devices().get(device) or {}).get("kind")

    def _device_names(self):
        """Main computer: share every approved device's name and kind with computers that introduced themselves.
        Member computer: introduce itself to the main computer under its display name."""
        now = int(self.clock())
        if self.is_root():
            labels = self._labels()
            rows = [{"id": key, "label": self.label() if key == self.info.device_id else labels.get(key, "Device"),
                     "kind": self.device_kind(key)} for key in sorted(self.session.current())]
            try:
                payload = device_labels(rows)
            except FeatureError:
                return
            digest = hashlib.sha256(canonical(payload)).hexdigest()
            computers = {key for key, row in self._shared_devices().items() if row["kind"] == "computer"}
            for target in self._targets():
                if target not in computers or self.is_phone(target):
                    continue  # Only computers that introduced themselves; phones learn names from phone.subscribe.
                if self._named.get(target, ("", 0))[0] != digest or now - self._named[target][1] >= NAMES_SECONDS:
                    self.mailbox.stage(target, payload, ttl_seconds=300)
                    self._named[target] = (digest, now)
        elif self.root is not None and now - self._named.get(self.root.device_id, ("", 0))[1] >= NAMES_SECONDS:
            self.mailbox.stage(self.root.device_id, device_hello(self.label()), ttl_seconds=300)
            self._named[self.root.device_id] = ("", now)

    def _device_event(self, source, payload):
        if payload["type"] == DEVICE_HELLO:
            if not self.is_root():
                raise FeatureError()
            hello = read_device_hello(payload)
            rows = self._shared_devices()
            rows[source] = {"id": source, "label": hello["name"], "kind": "computer"}
            self._write_shared_devices([row for key, row in rows.items() if key in self.session.current()])
            self._named.pop(source, None)  # Answer with the current names soon.
        else:
            # Only the main computer's list counts; it names devices as its owner approved them.
            if self.is_root() or source != self.root.device_id:
                raise FeatureError()
            members = self.session.current()
            self._write_shared_devices([row for row in read_device_labels(payload)["labels"] if row["id"] in members])

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
            # After a refusal, look again each pass so a new subscription clears the notice at once.
            self._load_access(token, force=self.status == "no_access")
            try:
                self._open()
                self._refresh(token, report_refusal=True)
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
                    self.transfers.online()
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
            except TransportError as error:
                if error.status == 403:
                    # The account has no access now, typically a free trial that ended.
                    # Nothing local is removed; a subscription reconnects on the next pass.
                    self.status, self.error = "no_access", self._refused(error, token)
                else:
                    self.status, self.error = "retrying", "Saiph Cloud is temporarily unavailable. Saiph will retry."
            except (ApprovalError, EnvelopeError, HostedError):
                self.status, self.error = "retrying", "Saiph Cloud is temporarily unavailable. Saiph will retry."
            finally:
                wait = self.decision.next_check_in if self.decision else 30
                self.next_step_at = time.monotonic() + min(wait, 15)
        self.changed()

    # ------------------------------------------------------------- features
    def _targets(self):
        return [member for member in self.session.current() if member != self.info.device_id]

    def _sync(self) -> bool:
        """One exchange with the mailbox; True when anything was sent, received or expired."""
        clipboard_on = (self.workspace.settings.get("link") or {}).get("clipboard") is not False
        outgoing, self._outgoing_clipboard = self._outgoing_clipboard, None
        activity = False
        if outgoing is not None and clipboard_on:
            for target in self._targets():
                self.mailbox.stage(target, outgoing, ttl_seconds=60)
                activity = True
        self.clipboard_images.sync()
        try:
            self._device_names()
        except (EnvelopeError, OSError):
            pass  # Names are cosmetic; syncing continues.
        activity |= bool(self.mailbox.flush(self.transport))
        activity |= bool(self.mailbox.poll(self.transport))
        for envelope in self.mailbox.pending():
            activity = True
            event_id = envelope["header"]["id"]
            try:
                payload = self.session.authenticate(envelope)
                event = kind(payload)
            except (EnvelopeError, FeatureError):
                continue
            self._seen[envelope["header"]["source"]] = int(self.clock())
            if event == FILE_OFFER and payload.get("kind") != "clipboard.image":
                self._offers[event_id] = envelope
                continue
            payload = self.mailbox.claim(event_id)
            outcome = "failed"
            try:
                if event == CLIPBOARD_TEXT:
                    data = read_clipboard(payload)
                    if clipboard_on and not self.clipboard_cache.contains_digest("text/plain", hashlib.sha256(data).hexdigest()):
                        self._deliver_clipboard(envelope["header"]["source"], "text/plain", data, envelope["header"]["expires_at"])
                        record_usage(self.workspace, "clipboard_received")
                    outcome = "succeeded"
                elif event == FILE_OFFER:
                    if clipboard_on:
                        self.clipboard_images.receive(envelope)
                    outcome = "succeeded"
                elif event in (NOTIFICATION_UPSERT, NOTIFICATION_REMOVE):
                    self._notification(envelope["header"]["source"], payload)
                    outcome = "succeeded"
                elif event == NOTIFICATION_ACTIONS:
                    self._notification_actions(envelope["header"]["source"], payload)
                    outcome = "succeeded"
                elif event == PHONE_FEATURES:
                    self._phone_features(envelope["header"]["source"], payload)
                    outcome = "succeeded"
                elif event == SMS_ATTACHMENT_ORIGINAL:
                    self._sms_attachment(envelope, payload)
                    outcome = "succeeded"
                elif event == PHOTO_ORIGINAL:
                    self._photo_original(envelope, payload)
                    outcome = "succeeded"
                elif event in PHONE_DATA:
                    self._phone_data(envelope["header"]["source"], event_id, payload)
                    outcome = "succeeded"
                elif event in (DEVICE_HELLO, DEVICE_LABELS):
                    self._device_event(envelope["header"]["source"], payload)
                    outcome = "succeeded"
                elif event == SCREEN_CAPABILITIES:
                    self._screen[envelope["header"]["source"]] = (read_screen_capabilities(payload), int(self.clock()))
                    outcome = "succeeded"
                elif event == APPS_LIST:
                    self._apps_page(envelope["header"]["source"], payload)
                    outcome = "succeeded"
                elif event == APPS_ICONS:
                    self._apps_icons(envelope["header"]["source"], payload)
                    outcome = "succeeded"
                elif event in (SESSION_OFFER, SESSION_CLOSE, SESSION_REFUSE, FILE_REQUEST):
                    self._lan_event(envelope["header"]["source"], event, payload)
                    outcome = "succeeded"
                # Anything else, including phone actions sent to a computer, has no effect here.
            except (FeatureError, ValueError, OSError):
                outcome = "failed"
            finally:
                self.mailbox.complete(event_id, outcome)
        now = int(self.clock())
        for event_id in [key for key, value in self._offers.items() if value["header"]["expires_at"] <= now]:
            self._offers.pop(event_id, None)
            activity = True
        return activity

    # --------------------------------------------------- files on this network
    def lan_addresses(self) -> list:
        """This computer's private IPv4 addresses; empty without a private network (or Qt)."""
        from .camera_session import lan_addresses
        try:
            return lan_addresses()
        except Exception:
            return []

    def _lan_event(self, source, event, payload):
        """Direct file transfers (lan_files.py). Decryption proved the sender is approved."""
        from .session_offer import OfferError, OfferReceipts, read_close, read_file_invite, read_file_request, read_offer, read_refuse
        try:
            if event == SESSION_OFFER:
                offer = read_offer(payload)
                if offer["service"] != "file" or self.is_phone(source):
                    return  # Phones never serve files; computers do not take camera or screen offers.
                invite = read_file_invite(offer["invite"], int(time.time()))
                if invite["mode"] != "get":
                    return
                if self._offer_receipts is None:
                    self._offer_receipts = OfferReceipts()
                if self._offer_receipts.claim(offer):
                    self.lan_inbox.offer(source, offer["id"], invite)
            elif event == SESSION_CLOSE:
                self.lan_inbox.closed(source, read_close(payload))
            elif event == SESSION_REFUSE:
                refusal = read_refuse(payload)
                self.transfers.refused(source, refusal["id"], refusal["reason"])
            elif event == FILE_REQUEST and self.is_phone(source):
                request = read_file_request(payload)
                if self._offer_receipts is None:
                    self._offer_receipts = OfferReceipts()
                if self._offer_receipts.claim({"id": request["id"], "expires_at": request["expires_at"]}):
                    self.lan_inbox.request(source, request)
        except OfferError:
            raise FeatureError() from None

    def file_offer(self, target, invite) -> str:
        """Seal a local file invitation to one approved device; returns the offer ID its answers name."""
        from .session_offer import OfferError, build_offer
        with self.lock:
            self._require_enabled()
            self._open()
            if not self._active() or target not in self._targets():
                raise HostedError("That device is no longer approved.")
            now = int(time.time())
            try:
                payload = build_offer("file", invite, now)
                self.mailbox.stage(target, payload, ttl_seconds=max(1, payload["expires_at"] - now))
            except (OfferError, EnvelopeError):
                raise HostedError("The file offer could not be sent.") from None
            self._wake.set()
        return payload["id"]

    def file_refuse(self, target, offer_id, reason):
        """Tell a sender we cannot take its direct offer, so it falls back at once. Best effort."""
        from .session_offer import refuse_payload
        try:
            with self.lock:
                if self.session is None or self.mailbox is None or target not in self._targets():
                    return
                self.mailbox.stage(target, refuse_payload(offer_id, reason), ttl_seconds=120)
                self._wake.set()
        except Exception:
            pass  # The sender falls back on its own after a short wait.

    def lan_notice(self, *, refresh=False) -> str:
        """Why devices on this network can't reach this computer, when Windows Firewall says so.

        Reads rules only (lan_relay.firewall_state) on its own thread, at most every ten
        minutes or when a direct transfer needs it; returns the last answer at once.
        """
        state = self._firewall
        due = state["at"] is None or time.monotonic() - state["at"] > (60 if refresh else 600)
        if due and not state["busy"] and self._firewall_program() is not None:
            state["busy"] = True

            def check():
                from .lan_relay import firewall_notice, firewall_state
                try:
                    notice = firewall_notice(firewall_state(self._firewall_program()))
                except Exception:
                    notice = ""
                changed = notice != state["notice"]
                state.update(notice=notice, at=time.monotonic(), busy=False)
                if changed:
                    self.changed()
            threading.Thread(target=check, name="orion-firewall-check", daemon=True).start()
        return state["notice"]

    def _firewall_program(self):
        """The program Windows Firewall sees listening: the fixed-path relay, else this executable."""
        from .lan_relay import relay_path
        if sys.platform != "win32" or not getattr(sys, "frozen", False):
            return None
        return relay_path() or Path(sys.executable)

    def open_firewall_settings(self) -> dict:
        from .lan_relay import open_firewall_settings
        if sys.platform != "win32":
            raise HostedError("Firewall settings are part of Windows.")
        open_firewall_settings()
        self._firewall["at"] = None  # Check again after the owner returns.
        return {"opened": True}

    def lan_received(self, item):
        name = self.device_name(item.source)
        self.transfer_alert(f"Received {item.name} from {name}. Open Saiph to save it.")

    def clear_local_clipboard(self):
        self._outgoing_clipboard = None
        self.clipboard_images.clear()

    def _deliver_clipboard(self, source, mime, data, expires_at=None):
        session = self.session
        def allowed():
            try:
                return (self.session is session and session is not None and self.enabled()
                        and self.status in ("active", "clock")
                        and (expires_at is None or self.clock() < expires_at)
                        and (self.workspace.settings.get("link") or {}).get("clipboard") is not False
                        and source in session.current())
            except EnvelopeError:
                return False
        if self.clipboard_dispatch is not None:
            self.clipboard_dispatch(mime, data, allowed)
        elif allowed() and self.clipboard_cache.claim(mime, data):
            self.clipboard_sink(mime, data)

    def local_clipboard(self, mime, data) -> bool:
        """GUI-thread hook: keep only the newest local change; the worker sends it."""
        if (type(data) is bytes and mime in {"text/plain", *IMAGE_FORMATS} and self.enabled()
                and self.session is not None and (self.workspace.settings.get("link") or {}).get("clipboard") is not False
                and self.clipboard_cache.contains_digest(mime, hashlib.sha256(data).hexdigest())):
            return False  # Preserve an identical copy which is still waiting to send.
        self.clear_local_clipboard()
        if not self.enabled() or mime not in {"text/plain", *IMAGE_FORMATS} or self.session is None or type(data) is not bytes:
            return False
        if (self.workspace.settings.get("link") or {}).get("clipboard") is False:
            return False
        if mime in IMAGE_FORMATS:
            if not self.clipboard_images.queue(mime, data):
                return False
        else:
            try:
                payload = clipboard_payload(data)
            except FeatureError:
                if len(data) > MAX_CLIPBOARD_TEXT_BYTES:
                    self.clipboard_images.notice = "This clipboard text is too large to share. Send it as a file."
                    self.changed()
                return False
            self._outgoing_clipboard = payload
            self.clipboard_images.notice = ""
        self.clipboard_cache.claim(mime, data)
        self._wake.set()
        record_usage(self.workspace, "clipboard_sent")
        return True

    def _toasts(self, hook, *args):
        """Native desktop notifications go through the desktop's phone runtime, which
        hands them to its own notifier loop; this worker thread never touches the OS
        notifier. Without that runtime (tests, headless) notifications are only listed."""
        runtime = getattr(self.workspace, "phone_runtime", None)
        try:
            getattr(runtime, hook, lambda *_: None)(*args)
        except Exception:
            pass  # A toast is a convenience; the notification is already listed in Saiph.

    def _reconcile_toasts(self):
        self._toasts("cloud_reconcile", {row["id"] for row in self.workspace.store.all("hosted_notification")})

    def _notification(self, source, payload):
        action, value = read_notification(payload)
        if action == "upsert" and not data_allowed(self.workspace.settings, "notification."):
            return  # The owner turned phone notifications off on this computer.
        identifier = hashlib.sha256((source + "\0" + (value if action == "remove" else value["key"])).encode()).hexdigest()
        if action == "remove":
            self.workspace.store.delete("hosted_notification", identifier)
            self.workspace.store.delete("hosted_notification_actions", identifier)
            self._reconcile_toasts()
        else:
            try:
                previous = self.workspace.store.get("hosted_notification", identifier)
            except ValueError:
                previous = None
            row = self.workspace.store.save("hosted_notification", {**value, "id": identifier, "device_id": source})
            record_usage(self.workspace, "phone_notification")
            # Phones repeat unchanged notifications (progress, re-posts): those never pop up again.
            if previous is None or any(previous.get(key) != value[key] for key in ("app", "title", "text")):
                stale = self.clock() * 1000 - value["timestamp"] > TOAST_STALE_SECONDS * 1000
                self._toasts("cloud_notification", {**self._with_actions(row), "silent": stale})

    def _notification_actions(self, source, payload):
        """Buttons and the reply key of one notification, from a phone that offers them."""
        body = read_notification_actions(payload)
        if not self.is_phone(source) or "notification-actions" not in self._capabilities(source):
            raise FeatureError()
        if not data_allowed(self.workspace.settings, "notification."):
            return
        identifier = hashlib.sha256((source + "\0" + body["key"]).encode()).hexdigest()
        self.workspace.store.save("hosted_notification_actions", {**body, "id": identifier, "device_id": source})

    def _with_actions(self, row):
        """A stored notification with its buttons and reply key, when they belong to this post of it."""
        try:
            extra = self.workspace.store.get("hosted_notification_actions", row["id"])
        except ValueError:
            return row
        if extra.get("device_id") != row.get("device_id") or extra.get("timestamp") != row.get("timestamp"):
            return row
        return {**row, "actions": extra["actions"], "reply_key": extra["reply_key"] or None}

    def notifications(self) -> list:
        return [self._with_actions(row) for row in self.workspace.store.all("hosted_notification")[:200]]

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
            self.workspace.store.delete("hosted_notification_actions", row["id"])
            self._wake.set()
        self._reconcile_toasts()
        self.changed()
        return {"ok": True}

    def notification_command(self, notification_id, operation, **extra) -> dict:
        """Press a notification's button, reply to it or open it on the phone (Hub parity)."""
        kinds = {"action": NOTIFICATION_ACTION, "reply": NOTIFICATION_REPLY, "open": NOTIFICATION_OPEN}
        if operation == "dismiss":
            return self.dismiss_notification(notification_id)
        if operation not in kinds:
            raise HostedError("Unknown notification action.")
        with self.lock:
            self._require_enabled()
            self._token_or_error()
            try:
                row = self._with_actions(self.workspace.store.get("hosted_notification", str(notification_id)))
            except ValueError:
                raise HostedError("This notification is no longer on your phone.") from None
            self._open()
            if not self._active():
                raise HostedError("Device approvals are being renewed. Try again shortly.")
            device = row["device_id"]
            if device not in self._targets():
                raise HostedError("That device is no longer approved.")
            phone = next((item for item in self.phones() if item["id"] == device), None)
            if phone is None or "notification-actions" not in phone["capabilities"]:
                raise HostedError("Update Saiph on your phone to reply to notifications here.")
            if not phone["online"]:
                raise HostedError(f"{phone['name']} is offline. Nothing was sent; try again when it reconnects.")
            body = {"key": row["key"]}
            if operation == "action":
                index = extra.get("index")
                if type(index) is not int or index not in {action["index"] for action in row.get("actions") or []}:
                    raise HostedError("This button is no longer on the notification.")
                body["index"] = index
            elif operation == "reply":
                if not row.get("reply_key") or extra.get("reply_key") not in (None, row["reply_key"]):
                    raise HostedError("This notification no longer takes replies.")
                text = extra.get("text")
                if type(text) is not str or not text.strip() or len(text) > 4096:
                    raise HostedError("Enter a reply up to 4096 characters.")
                body.update(reply_key=row["reply_key"], text=text)
            try:
                payload = notification_command(kinds[operation], body)
                event_id = self.mailbox.stage(device, payload, ttl_seconds=60)
            except (FeatureError, EnvelopeError):
                raise HostedError("This reply could not be sent. Shorten it and try again.") from None
            self._wake.set()
        return {"queued": True, "id": event_id}

    def send_file(self, path, target, notify=False) -> dict:
        """Queue one file for an approved device; the transfer worker encrypts and uploads it.

        Refusals that need the owner (sign-in, size, approval) are raised here,
        before anything is encrypted. A network drop is retried automatically.
        """
        with self.lock:
            self._require_enabled()
            try:
                self._token()
            except SignInRequired:
                self._deactivate("sign_in_required")
                raise HostedError("Sign in to Saiph Cloud first.") from None
            except HostedUnavailable:
                pass  # Queued: it is sent when Saiph Cloud is reachable again.
            self._open()
            if not self._active():
                raise HostedError("Device approvals are being renewed. Try again shortly.")
            source = Path(path) if isinstance(path, str) else None
            if source is None or not source.is_absolute() or not source.is_file():
                raise HostedError("Choose a file on this computer.")
            if target not in self._targets():
                raise HostedError("Choose an approved device.")
            size = source.stat().st_size
            if size > MAX_PLAINTEXT and not self.lan_addresses():
                raise HostedError(no_network(size))
            try:
                job = self.transfers.add(source, target, notify=notify is True)
            except ValueError as error:
                raise HostedError(str(error)) from None
        self.changed()
        return {"queued": True, "id": job.id, "name": job.name, "target_name": self.device_name(target)}

    def retry_transfer(self, transfer_id) -> dict:
        with self.lock:
            self._require_enabled()
            try:
                job = self.transfers.retry(transfer_id)
            except ValueError as error:
                raise HostedError(str(error)) from None
        self.changed()
        return {"queued": True, "id": job.id}

    def dismiss_transfer(self, transfer_id) -> dict:
        try:
            if self.lan_inbox.has(transfer_id):
                self.lan_inbox.dismiss(transfer_id)  # A received file not yet saved, or one that failed.
            else:
                self.transfers.dismiss(transfer_id)
        except ValueError as error:
            raise HostedError(str(error)) from None
        self.changed()
        return {"ok": True}

    def device_name(self, device) -> str:
        """Display name for an approved device; never takes the controller lock."""
        label = self._labels().get(device)
        if label:
            return label
        if self.root is not None and device == self.root.device_id:
            return "your main computer"
        return "your phone" if self.is_phone(device) else "your device"

    def save_offer(self, event_id, downloads: Path | None = None) -> dict:
        from .hosted_files import _manifest, download_attachment, AttachmentError, AttachmentPublicationUncertain
        if self.lan_inbox.has(event_id):
            return self._save_lan(event_id, downloads)
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
            folder = Path(downloads) if downloads else received_dir()
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
            if self.is_phone(envelope["header"]["source"]):
                self.workspace.store.save("phone_file", {"id": event_id, "device_id": envelope["header"]["source"],
                    "name": saved.name, "path": str(saved), "size": payload["size"]})
        self.changed()
        return {"path": str(saved)}

    def _save_lan(self, offer_id, downloads=None) -> dict:
        """A file received over the network is already verified here: move it into place."""
        folder = Path(downloads) if downloads else received_dir()
        try:
            saved, item = self.lan_inbox.save(offer_id, folder)
        except ValueError as error:
            raise HostedError(str(error)) from None
        except OSError:
            raise HostedError("The file could not be saved. Check that the Downloads folder has space.") from None
        if self.is_phone(item.source):
            self.workspace.store.save("phone_file", {"id": offer_id, "device_id": item.source,
                                                     "name": saved.name, "path": str(saved), "size": item.size})
        self.changed()
        return {"path": str(saved)}

    # ------------------------------------------------------- texts and calls
    def _capabilities(self, device) -> list:
        """Advertised capabilities plus the newer features a phone lists in `phone.features`."""
        try:
            row = self.workspace.store.get("hosted_phone", device)
        except ValueError:
            return []
        return [*(row.get("capabilities") or []), *(row.get("features") or [])]

    def _phone_features(self, source, payload):
        """Notification actions, MMS pictures and group replies; stored with the phone's capabilities."""
        names = read_phone_features(payload)
        try:
            row = self.workspace.store.get("hosted_phone", source)
        except ValueError:
            raise FeatureError() from None  # Capabilities come first and make the device a phone.
        self.workspace.store.save("hosted_phone", {**row, "features": names})
        if "notification-actions" not in names:
            for item in self.workspace.store.all("hosted_notification_actions"):
                if item.get("device_id") == source:
                    self.workspace.store.delete("hosted_notification_actions", item["id"])
        if "sms-mms" not in names:
            self._parts_asked = {key: value for key, value in self._parts_asked.items() if key[0] != source}

    def _phone_data(self, source, event_id, payload):
        """Show a phone's texts and call state; actions never originate here."""
        kind_, body = read_phone_data(payload)
        now = int(self.clock())
        if kind_ == PHONE_CAPABILITIES:
            try:
                features = self.workspace.store.get("hosted_phone", source).get("features") or []
            except ValueError:
                features = []
            # Features follow in their own event; texts features end with the texts capability.
            if "sms" not in body["capabilities"]:
                features = [name for name in features if not name.startswith("sms-")]
            self.workspace.store.save("hosted_phone", {"id": source, "capabilities": body["capabilities"], "seen_at": now,
                                                       "features": features})
            if now - self._subscribed.get(source, 0) >= SUBSCRIBE_SECONDS:
                # Any approved computer, root or not, asks for texts and calls by name.
                self.mailbox.stage(source, subscribe_payload(self.label()), ttl_seconds=300)
                self._subscribed[source] = now
                self._wake.set()
            if "photos" not in body["capabilities"]:
                for kind_ in ("photo", "thumbnail", "photo_intent"):
                    for row in self.workspace.store.all("phone_" + kind_):
                        if row.get("device_id") == source:
                            if kind_ == "photo":
                                self.workspace.store.delete("phone_photo_intent", self.workspace.phone_features._photo_key(source, row["photo_id"]))
                            self.workspace.store.delete("phone_" + kind_, row["id"])
                self._photos_asked = {key: value for key, value in self._photos_asked.items() if key[0] != source}
            if "sms" not in body["capabilities"]:
                self._sync_requested.discard(source)
            elif source not in self._sync_requested and not any(
                    row.get("device_id") == source for row in self.workspace.store.all("phone_thread")):
                # A computer without this phone's conversations asks once for a fresh list.
                self._sync_requested.add(source)
                self.mailbox.stage(source, phone_command(SMS_SYNC, {}), ttl_seconds=60)
                self._wake.set()
            return
        if kind_ in STATUS_DATA:
            self._status_data(source, kind_, body, now)
            return
        if not data_allowed(self.workspace.settings, kind_):
            return  # The owner turned this feature off on this computer; nothing is stored.
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
        features.event({"id": event_id, "type": "photos.index" if kind_ == PHOTOS_ITEM else kind_, "payload": body, "source": source}, None)
        if kind_ == CALL_STATE:
            self._call(body)

    @property
    def status_book(self) -> StatusBook:
        """Status shared with Hub phones: one store record per phone, one view, one wallpaper request window."""
        book = getattr(self, "_status_book", None)
        if book is None:
            book = self._status_book = StatusBook(self.workspace.store, clock=self.clock)
        return book

    def _status_data(self, source, kind_, body, now):
        """Battery, network, sound and media from an approved phone that advertised itself."""
        if not self.is_phone(source):
            raise FeatureError()
        book = self.status_book
        features = getattr(self.workspace, "phone_features", None)
        if kind_ in phone_status.STATUS_EVENTS:  # Status, signal bars and media.
            # Cloud phones list media among their quick actions, never in phone.capabilities.
            if not book.apply(source, kind_, body, now, capabilities=self._capabilities(source), features=features):
                raise FeatureError()
            if kind_ == PHONE_STATUS:
                self._toasts("cloud_battery", source, self._labels().get(source, "Your phone"), body["battery"], body["charging"])
                if book.wallpaper_due(source, phone_flag(self.workspace.settings, "wallpaper"), now):
                    self._request_wallpaper(source, now)
            return
        # PHONE_WALLPAPER: only this computer's own request.
        self._asked.pop((source, WALLPAPER_REQUEST), None)
        if not book.wallpaper_answer(source, body, now):
            raise FeatureError()

    def _request_wallpaper(self, device, now):
        self.mailbox.stage(device, phone_command(WALLPAPER_REQUEST, {}), ttl_seconds=60)
        self.status_book.wallpaper_asked(device, now)
        self._wake.set()

    def _photo_original(self, envelope, payload):
        from .hosted_files import _manifest, download_attachment
        from .phone_features import safe_name
        source = envelope["header"]["source"]
        if type(payload) is not dict or set(payload) != {"type", "photo_id", "request", "file"}:
            raise FeatureError()
        photo = payload["photo_id"]
        if type(photo) is not str or "photos" not in self._capabilities(source):
            raise FeatureError()
        asked = self._photos_asked.get((source, photo))
        if asked is None or asked[0] != payload["request"] or asked[1] <= self.clock():
            raise FeatureError()
        manifest, _ = _manifest(self.session, envelope)
        if not manifest["mime"].startswith("image/"):
            raise FeatureError()
        features = self.workspace.phone_features
        if not any(row.get("device_id") == source and row.get("photo_id") == photo for row in self.workspace.store.all("phone_photo")):
            raise FeatureError()
        folder = self.workspace.root / "phone-originals"
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        destination = (folder / (str(uuid4()) + "-" + safe_name(manifest["name"]))).absolute()
        self._token_or_error()
        saved = download_attachment(self.session, self.transport, envelope, destination)
        self._photos_asked.pop((source, photo), None)
        features.cloud_original(source, photo, saved, manifest)

    def _sms_attachment(self, envelope, payload):
        """One MMS part this computer asked for, as a sealed attachment: kept with the conversation."""
        from .hosted_files import _manifest, download_attachment
        from .phone_features import MAX_ATTACHMENT, safe_name
        source = envelope["header"]["source"]
        if type(payload) is not dict or set(payload) != {"type", "thread", "message", "part", "request", "file"}:
            raise FeatureError()
        key = (source, payload["thread"], payload["message"], payload["part"])
        if "sms-mms" not in self._capabilities(source) or not data_allowed(self.workspace.settings, "sms."):
            raise FeatureError()
        asked = self._parts_asked.get(key)
        if asked is None or asked[0] != payload["request"] or asked[1] <= self.clock():
            raise FeatureError()
        manifest, _ = _manifest(self.session, envelope)
        if manifest["size"] > MAX_ATTACHMENT:
            raise FeatureError()
        folder = self.workspace.root / "sms-attachments"
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        destination = (folder / (str(uuid4()) + "-" + safe_name(manifest["name"]))).absolute()
        self._token_or_error()
        saved = download_attachment(self.session, self.transport, envelope, destination)
        self._parts_asked.pop(key, None)
        self.workspace.phone_features.cloud_attachment(source, payload["thread"], payload["message"], payload["part"], saved, manifest)

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
        self.status_book.forget(device)
        self._seen.pop(device, None)
        self._sync_requested.discard(device)
        self._photos_asked = {key: value for key, value in self._photos_asked.items() if key[0] != device}
        self._parts_asked = {key: value for key, value in self._parts_asked.items() if key[0] != device}
        for row in store.all("hosted_notification_actions"):
            if row.get("device_id") == device:
                store.delete("hosted_notification_actions", row["id"])
        for name in ("thread", "message", "call", "attachment", "attachment_file", "photo", "thumbnail", "photo_intent", "media", "ringer"):
            for row in store.all("phone_" + name):
                if row.get("device_id") == device:
                    if name == "photo":
                        store.delete("phone_photo_intent", self.workspace.phone_features._photo_key(device, row["photo_id"]))
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
                online = members is not None and now - seen <= PHONE_ONLINE_SECONDS
                book = self.status_book
                view = book.view(row["id"], [*(row.get("capabilities") or []), *(row.get("features") or [])], online, now)
                result.append({"id": row["id"], "name": labels.get(row["id"], "Phone"), "hosted": True,
                               "call_notice": notice["text"] if notice and 0 <= now - notice["at"] <= NOTICE_SECONDS else None,
                               **view,
                               "wallpaper": book.saved(row["id"]).get("wallpaper") or None if phone_flag(self.workspace.settings, "wallpaper") else None,
                               "screen": self.screen_capabilities(row["id"]),
                               "last_seen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seen)) if seen else None})
        return result

    def screen_capabilities(self, device) -> list:
        """Phone screen and app-list support, from the phone's recent separate advertisement."""
        advertised = self._screen.get(device)
        if advertised is None or not 0 <= int(self.clock()) - advertised[1] <= PHONE_ONLINE_SECONDS:
            return []
        return list(advertised[0])

    def _screen_phone(self, device, capability):
        """An approved, online phone that offers `capability`; caller holds the lock."""
        self._require_enabled()
        self._token_or_error()
        self._open()
        if not self._active():
            raise HostedError("Device approvals are being renewed. Try again shortly.")
        if device not in self._targets():
            raise HostedError("That device is no longer approved.")
        phone = next((row for row in self.phones() if row["id"] == device), None)
        if phone is None or capability not in phone["screen"]:
            raise HostedError("Update Saiph on your phone to use this feature.")
        if not phone["online"]:
            raise HostedError(f"{phone['name']} is offline. Nothing was sent; try again when it reconnects.")
        return phone

    def request_apps(self, device) -> dict:
        """Ask one phone for its launchable apps; the answer arrives as apps.list pages."""
        with self.lock:
            self._screen_phone(device, "apps")
            asked = self._asked.get((device, APPS_REQUEST))
            if asked is None or int(self.clock()) - asked > 10:
                self.mailbox.stage(device, apps_request_payload(), ttl_seconds=60)
                self._asked[(device, APPS_REQUEST)] = int(self.clock())
                self._wake.set()
        return {"queued": True}

    def _apps_page(self, source, payload):
        """Accept app-list pages only in answer to this computer's own recent request."""
        page, pages, apps = read_apps_list(payload)
        now = int(self.clock())
        asked = self._asked.get((source, APPS_REQUEST))
        if asked is None or not 0 <= now - asked <= ANSWER_WINDOW_SECONDS or "apps" not in self.screen_capabilities(source):
            raise FeatureError()
        current = self._apps.get(source)
        if current is None or current["total"] != pages or current["asked"] != asked:
            current = self._apps[source] = {"pages": {}, "total": pages, "asked": asked, "at": now}
        current["pages"][page] = apps
        current["at"] = now

    def request_app_icons(self, device, rows) -> dict:
        """Ask one phone for small app icons; answers arrive as apps.icons events."""
        payload = apps_icons_request_payload(rows)
        with self.lock:
            self._screen_phone(device, "apps")
            now = int(self.clock())
            self.mailbox.stage(device, payload, ttl_seconds=60)
            for row in payload["apps"]:
                self._icon_asks[(device, row["package"])] = now
            if len(self._icon_asks) > 4000:
                self._icon_asks = {key: at for key, at in self._icon_asks.items() if now - at <= ANSWER_WINDOW_SECONDS}
            self._wake.set()
        return {"queued": True}

    def _apps_icons(self, source, payload):
        """Accept icons only for packages this computer asked this phone about recently."""
        icons, same = read_apps_icons(payload)
        now = int(self.clock())
        if "apps" not in self.screen_capabilities(source):
            raise FeatureError()
        for package in [row[0] for row in icons] + same:
            asked = self._icon_asks.get((source, package))
            if asked is None or not 0 <= now - asked <= ANSWER_WINDOW_SECONDS:
                raise FeatureError()
        received, unchanged = self._icons_in.setdefault(source, ([], []))
        received.extend(icons)
        unchanged.extend(same)
        del received[:-200], unchanged[:-400]

    def take_app_icons(self, device):
        """Icons received from this phone since the last call: ([(package, version, bytes)], [package])."""
        with self.lock:
            return self._icons_in.pop(device, ([], []))

    def phone_apps(self, device):
        """The latest complete app list from this phone, or None while it is still arriving."""
        with self.lock:
            current = self._apps.get(device)
            if current is None or len(current["pages"]) != current["total"]:
                return None
            rows = {app["package"]: app for page in current["pages"].values() for app in page}
            return {"apps": sorted(rows.values(), key=lambda app: app["name"].lower()), "at": current["at"]}

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
            if kind_ == PHOTO_REQUEST and not any(row.get("device_id") == device and row.get("photo_id") == payload["id"]
                    for row in self.workspace.store.all("phone_photo")):
                raise HostedError("That photo is no longer available.")
            if kind_ in (SMS_OPEN, SMS_SEND):
                thread = next((row for row in self.workspace.store.all("phone_thread")
                               if row.get("device_id") == device and row.get("thread") == payload["thread"]), None)
                if thread is None:
                    raise HostedError("This conversation is unavailable.")
                recipients = len(thread.get("recipients") or [])
                if kind_ == SMS_SEND and recipients != 1 and not (1 < recipients <= 10 and "sms-group" in phone["capabilities"]):
                    raise HostedError("Group replies stay in your phone's messaging app. Update Saiph on your phone to reply here.")
            if kind_ == SMS_ATTACHMENT_REQUEST:
                if not any(row.get("device_id") == device and row.get("thread") == payload["thread"] and row.get("message") == payload["message"]
                           and any(part.get("part") == payload["part"] for part in row.get("parts") or [])
                           for row in self.workspace.store.all("phone_attachment")):
                    raise HostedError("That picture is no longer available.")
                self._parts_asked = {key: value for key, value in self._parts_asked.items() if value[1] > self.clock()}
                if len(self._parts_asked) >= 100:
                    raise HostedError("Pictures are still loading. Try again shortly.")
            if kind_ == CALL_COMMAND:
                call = next((row for row in self.workspace.store.all("phone_call") if row.get("device_id") == device), {})
                if call.get("state") != "ringing":
                    handled = call.get("handled_by")
                    raise HostedError(refusal_text({"reason": "handled", "handled": call.get("handled"), "by": handled})
                                      if handled is not None else "The call is no longer ringing.")
            if kind_ == WALLPAPER_REQUEST and not phone_flag(self.workspace.settings, "wallpaper"):
                raise HostedError("Turn on Use phone wallpaper in Settings first.")
            if kind_ == STATUS_REQUEST:
                # Refresh: the phone resends its status and media to this computer.
                asked = self._asked.get((device, STATUS_REQUEST))
                if asked is not None and 0 <= int(self.clock()) - asked < REFRESH_SECONDS:
                    return {"queued": True}
                self._asked[(device, STATUS_REQUEST)] = int(self.clock())
            if kind_ == PHOTO_REQUEST:
                self._photos_asked = {key: value for key, value in self._photos_asked.items() if value[1] > self.clock()}
                if len(self._photos_asked) >= 100:
                    raise HostedError("Photos are still loading. Try again shortly.")
            try:
                event_id = self.mailbox.stage(device, payload, ttl_seconds=30 if kind_ == CALL_COMMAND else 60)
            except EnvelopeError:
                raise HostedError("This request could not be sent. Shorten the message and try again.") from None
            if kind_ == PHOTO_REQUEST:
                self._photos_asked[(device, payload["id"])] = (event_id, self.clock() + 300)
            if kind_ == SMS_ATTACHMENT_REQUEST:
                self._parts_asked[(device, payload["thread"], payload["message"], payload["part"])] = (event_id, self.clock() + 300)
            if kind_ in ANSWERS.values() or kind_ in (CALL_COMMAND, CALL_DIAL):
                # Answers and refusals are accepted only for this computer's own recent request.
                self._asked[(device, kind_)] = int(self.clock())
                self._notices.pop(device, None)
            if kind_ == WALLPAPER_REQUEST:
                self.status_book.wallpaper_asked(device, int(self.clock()))
            self._wake.set()
        return {"queued": True, "id": event_id}

    def session_offer(self, device, service, invite) -> dict:
        """Send a one-use local invitation (the camera QR's content) to one approved phone.

        The sealed envelope replaces the visual channel: it is encrypted to that
        phone's current keys and expires with the invitation. The phone still asks
        its owner, verifies with the screen lock and needs the foreground; the
        local session still accepts exactly one pinned TLS connection.
        """
        from .session_offer import OfferError, build_offer
        with self.lock:
            self._require_enabled()
            self._token_or_error()
            self._open()
            if not self._active():
                raise HostedError("Device approvals are being renewed. Scan the code instead.")
            if device not in self._targets():
                raise HostedError("That device is no longer approved.")
            phone = next((row for row in self.phones() if row["id"] == device), None)
            if phone is None:
                raise HostedError("Choose your phone, or scan the code instead.")
            if not phone["online"]:
                raise HostedError(f"{phone['name']} is offline. Scan the code instead.")
            now = int(self.clock())
            try:
                payload = build_offer(service, invite, now)
            except OfferError:
                raise HostedError("This code has expired. Start a new session.") from None
            try:
                event_id = self.mailbox.stage(device, payload, ttl_seconds=max(1, payload["expires_at"] - now))
            except EnvelopeError:
                raise HostedError("The request could not be sent. Scan the code instead.") from None
            self._wake.set()
        return {"sent": True, "id": event_id, "offer": payload["id"], "name": phone["name"]}

    def session_close(self, device, offer_id) -> dict:
        """Tell the phone an offer it received is answered, cancelled or expired (prompt cleanup only)."""
        from .session_offer import close_payload
        payload = close_payload(offer_id)
        with self.lock:
            self._require_enabled()
            self._token_or_error()
            self._open()
            if not self._active() or device not in self._targets():
                return {"sent": False}
            try:
                self.mailbox.stage(device, payload, ttl_seconds=180)
            except EnvelopeError:
                return {"sent": False}
            self._wake.set()
        return {"sent": True}

    def poll(self) -> None:
        """Deliver queued actions and fetch new events between full scheduler passes."""
        with self.lock:
            if not self.enabled() or self.self_hosted_paired() or self.session is None or self.decision is None:
                return
            if self.decision.blocked or self.status != "active" or not self._active():
                return
            try:
                activity = self._sync()
            except (ApprovalError, EnvelopeError, TransportError, HostedError, FeatureError, OSError):
                return  # The next full step reports the connection state.
        # Every 4 s while a phone shares calls or texts: a quiet poll changes
        # nothing on screen, so it must not make the dashboard rebuild its state.
        if activity:
            self.changed()

    def _fast_poll(self) -> bool:
        """Poll often while a phone shares calls or texts, or a direct file offer waits for an answer."""
        if self.transfers.lan_waiting():
            return True
        return any({"calls", "sms"} & set(row.get("capabilities") or []) for row in self.workspace.store.all("hosted_phone"))

    # ------------------------------------------------------------- snapshot
    def snapshot(self) -> dict:
        settings = self.settings
        config = self._config()
        result = {"enabled": self.enabled(), "configured": config is not None,
                  "config": {key: (config or settings).get(key, False if key == "refresh_tokens" else "") for key in sorted(CONFIG_KEYS)},
                  "identity": self.identity.exists(), "self_hosted_paired": self.self_hosted_paired(),
                  "status": self.status if self.enabled() else "off", "error": self.error if self.enabled() else "",
                  "clipboard_notice": self.clipboard_images.notice,
                  "account": {"status": "signed_out", "refresh_tokens": bool(config and config["refresh_tokens"]), "error": ""},
                  "role": None, "device_id": None, "fingerprint": None, "roster": None, "offers": [],
                  "notifications": [], "user_verification": user_verification(self.workspace), "security_events": [],
                  "transfers": self.transfers.snapshot(), "file_limit": MAX_PLAINTEXT,
                  "lan_notice": self.lan_notice() if self.enabled() else "",
                  "access": summarize(self._access, self.clock()) if self.enabled() else None}
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
                                 "kind": self.device_kind(key),
                                 "fingerprint": device_fingerprint(value)} for key, value in sorted(members.items())]}
            for event_id, envelope in list(self._offers.items()):
                try:
                    payload = self.session.authenticate(envelope)
                    result["offers"].append({"id": event_id, "name": payload["name"], "size": payload["size"],
                                             "mime": payload["mime"], "source": envelope["header"]["source"],
                                             "expires_at": envelope["header"]["expires_at"]})
                except (EnvelopeError, KeyError, TypeError):
                    self._offers.pop(event_id, None)
        result["offers"].extend(self.lan_inbox.snapshot())
        result["notifications"] = self.notifications()
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
                        self.status, self.error = "retrying", "Saiph Cloud is temporarily unavailable. Saiph will retry."
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
