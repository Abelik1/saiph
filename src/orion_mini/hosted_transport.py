# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bounded HTTPS adapter for the isolated hosted protocol; never logs content.

Account access tokens admit requests, not decryption authority. Device routes
use only the existing in-memory P-256 identity after local roster verification.
There is no automatic plaintext fallback, key generation or token persistence.
"""
from __future__ import annotations

import base64
from email.utils import parsedate_to_datetime
import hashlib
import json
import re
from pathlib import Path
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
import requests

from .hosted_crypto import EnvelopeError


class TransportError(ValueError):
    def __init__(self, status=None):
        self.status = status
        super().__init__("Hosted service request failed.")


def wire(value):
    try:
        raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
        if len(raw) > 65_536:
            raise ValueError()
        return raw
    except (ValueError, TypeError, RecursionError):
        raise TransportError() from None


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result

    def invalid(_):
        raise ValueError()

    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)


class HostedTransport:
    def __init__(self, base_url, session, *, ca_bundle: Path | None = None):
        try:
            parsed = urlsplit(base_url)
            if (type(base_url) is not str or parsed.scheme != "https" or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.path not in ("", "/") or parsed.query or parsed.fragment
                    or any(c.isspace() or ord(c) < 32 for c in base_url) or "\\" in base_url):
                raise ValueError()
            _ = parsed.port
            if ca_bundle is not None and (not isinstance(ca_bundle, Path) or not ca_bundle.is_file()):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise TransportError() from None
        self.base = base_url.rstrip("/")
        self.session = session
        self.verify = str(ca_bundle.resolve()) if ca_bundle is not None else True
        self.http = requests.Session()
        self.http.trust_env = False
        # The protocol has no cookies, environment proxy or HTTP authentication.
        self.http.auth = None
        # Server time minus local time from the last HTTPS Date header. Used
        # only to schedule roster renewal; never to accept or verify content.
        self.server_offset = None

    def close(self):
        self.http.close()

    def _call(self, method, path, *, token=None, value=None):
        raw = wire(value) if value is not None else b""
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if token is not None:
            if type(token) is not str or not token or len(token) > 16_384 or any(ord(c) < 33 or ord(c) > 126 for c in token):
                raise TransportError()
            headers["Authorization"] = "Bearer " + token
        else:
            self.session.current()
            timestamp, nonce = str(int(time.time())), str(uuid4())
            digest = hashlib.sha256(raw).hexdigest()
            message = f"{method}\n{path}\n{timestamp}\n{nonce}\n{digest}".encode("ascii")
            signature = self.session.signing.sign(message, ec.ECDSA(hashes.SHA256()))
            headers.update({"X-Orion-Device-Id": self.session.device, "X-Orion-Timestamp": timestamp,
                            "X-Orion-Nonce": nonce, "X-Orion-Signature": base64.b64encode(signature).decode("ascii")})
        try:
            self.http.cookies.clear()
            with self.http.request(method, self.base + path, data=raw, headers=headers,
                                   verify=self.verify, timeout=(5, 10), allow_redirects=False, stream=True) as response:
                self._observe_clock(response.headers.get("Date"))
                if response.status_code != 200:
                    raise TransportError(response.status_code)
                if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise TransportError()
                data = bytearray()
                for part in response.iter_content(65_536):
                    data.extend(part)
                    if len(data) > 8_388_608:
                        raise TransportError()
                result = strict_json(bytes(data))
                if type(result) is not dict:
                    raise TransportError()
                return result
        except (requests.RequestException, ValueError, TypeError, RecursionError, UnicodeError) as error:
            if isinstance(error, TransportError):
                raise
            raise TransportError() from None
        finally:
            self.http.cookies.clear()

    def _observe_clock(self, value):
        try:
            if type(value) is str and len(value) <= 64:
                offset = parsedate_to_datetime(value).timestamp() - time.time()
                if abs(offset) <= 7 * 86400:
                    self.server_offset = offset
        except (TypeError, ValueError, OverflowError):
            pass

    def discover_account(self, access_token):
        """Root setup only: learn the account's deployment before any pin exists.

        The returned UUID only names the deployment the root will create; it
        grants no trust. Later calls use account(), which checks the pin.
        """
        if access_token is None:
            raise TransportError()
        result = self._call("GET", "/v1/account", token=access_token)
        try:
            if (set(result) != {"deployment_id", "device_trust_required"} or type(result["deployment_id"]) is not str
                    or str(UUID(result["deployment_id"])) != result["deployment_id"] or result["device_trust_required"] is not True):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise TransportError() from None
        return result["deployment_id"]

    def account(self, access_token):
        if access_token is None:
            raise TransportError()
        result = self._call("GET", "/v1/account", token=access_token)
        if (set(result) != {"deployment_id", "device_trust_required"}
                or result["deployment_id"] != self.session.deployment or result["device_trust_required"] is not True):
            raise TransportError()
        return result

    def enroll(self, access_token, candidate):
        if access_token is None or type(candidate) is not dict or candidate.get("deployment_id") != self.session.deployment:
            raise TransportError()
        return self._call("POST", "/v1/devices/requests", token=access_token, value=candidate)

    def rosters(self, access_token):
        if access_token is None:
            raise TransportError()
        result = self._call("GET", "/v1/devices/rosters", token=access_token)
        if set(result) != {"chain"} or type(result["chain"]) is not list or not 0 <= len(result["chain"]) <= 128:
            raise TransportError()
        return result["chain"]

    def submit_roster(self, access_token, proposal):
        if access_token is None:
            raise TransportError()
        return self._call("POST", "/v1/devices/rosters", token=access_token, value=proposal)

    def roster_page(self, access_token, *, after_version=0, after_hash=None, limit=16):
        if (access_token is None or type(after_version) is not int or not 0 <= after_version <= 2**31 - 1
                or type(limit) is not int or not 1 <= limit <= 16
                or (after_version == 0 and after_hash is not None)
                or (after_version > 0 and (type(after_hash) is not str or not re.fullmatch(r"[a-f0-9]{64}", after_hash)))):
            raise TransportError()
        path = f"/v1/devices/rosters/page?after_version={after_version}&limit={limit}"
        if after_hash is not None:
            path += "&after_hash=" + after_hash
        result = self._call("GET", path, token=access_token)
        if (set(result) != {"chain", "more"} or type(result["chain"]) is not list
                or len(result["chain"]) > limit or type(result["more"]) is not bool
                or (result["more"] and not result["chain"])):
            raise TransportError()
        return result

    def refresh_roster(self, access_token, *, max_pages=64):
        """Persist verified progress; return False when another bounded run is needed.

        Legacy trust-only databases require an explicit full-chain migration by
        their controller. This method never discards an existing trust anchor.
        The server's `more` hint controls scheduling, never signature authority.
        """
        if type(max_pages) is not int or not 1 <= max_pages <= 64:
            raise TransportError()
        self.session.invalidate()
        for _ in range(max_pages):
            cursor = self.session.history_cursor()
            page = self.roster_page(access_token, **cursor)
            self.session.accept_page(page["chain"], final=not page["more"])
            if not page["more"]:
                return True
        return False

    def submit_catchup(self, access_token, proposal):
        if access_token is None:
            raise TransportError()
        return self._call("POST", "/v1/devices/rosters/catchup", token=access_token, value=proposal)

    def publish(self, envelope):
        header = envelope.get("header", {}) if type(envelope) is dict else {}
        self.session.current()
        if (header.get("source") != self.session.device or header.get("deployment_id") != self.session.deployment
                or header.get("roster_version") != self.session.roster["version"]
                or header.get("roster_hash") != self.session.digest or header.get("expires_at", 0) <= int(time.time())):
            raise EnvelopeError("Current device approval is required.")
        result = self._call("POST", "/v1/sealed/events", value=envelope)
        if set(result) != {"accepted", "duplicate"} or result["accepted"] is not True or type(result["duplicate"]) is not bool:
            raise TransportError()
        return result

    def events(self):
        result = self._call("GET", "/v1/sealed/events")
        if set(result) != {"events"} or type(result["events"]) is not list or len(result["events"]) > 100:
            raise TransportError()
        return result["events"]

    @staticmethod
    def _blob_path(blob_id, index=None):
        try:
            if type(blob_id) is not str or str(UUID(blob_id)) != blob_id:
                raise ValueError()
            path = "/v1/sealed/blobs/" + blob_id
            if index is not None:
                if type(index) is not int or not 0 <= index < 640:
                    raise ValueError()
                path += "/chunks/" + str(index)
            return path
        except (ValueError, TypeError, AttributeError):
            raise TransportError() from None

    @staticmethod
    def _accepted(result):
        if set(result) != {"accepted", "duplicate"} or result["accepted"] is not True or type(result["duplicate"]) is not bool:
            raise TransportError()
        return result

    def allocate_blob(self, descriptor):
        members = self.session.current()
        if (type(descriptor) is not dict
                or set(descriptor) != {"id", "target", "roster_version", "roster_hash", "expires_at", "size", "sha256"}):
            raise TransportError()
        self._blob_path(descriptor["id"])
        if (type(descriptor["target"]) is not str or descriptor["target"] not in members or descriptor["target"] == self.session.device
                or type(descriptor["roster_version"]) is not int or descriptor["roster_version"] != self.session.roster["version"]
                or descriptor["roster_hash"] != self.session.digest
                or type(descriptor["size"]) is not int or not 1 <= descriptor["size"] <= 20 * 1024 * 1024
                or type(descriptor["expires_at"]) is not int or not int(time.time()) < descriptor["expires_at"] <= int(time.time()) + 300
                or type(descriptor["sha256"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", descriptor["sha256"])):
            raise TransportError()
        return self._accepted(self._call("POST", "/v1/sealed/blobs", value=descriptor))

    def upload_blob_chunk(self, blob_id, index, data):
        if type(data) is not bytes or not 1 <= len(data) <= 32_768 or type(index) is not int:
            raise TransportError()
        return self._accepted(self._call("POST", self._blob_path(blob_id, index), value={"data": base64.b64encode(data).decode("ascii")}))

    def complete_blob(self, blob_id):
        result = self._call("POST", self._blob_path(blob_id) + "/complete", value={})
        if set(result) != {"ready"} or result["ready"] is not True:
            raise TransportError()
        return result

    def download_blob_chunk(self, blob_id, index):
        if type(index) is not int:
            raise TransportError()
        result = self._call("GET", self._blob_path(blob_id, index))
        try:
            if set(result) != {"data"} or type(result["data"]) is not str or len(result["data"]) > 43_692:
                raise ValueError()
            raw = base64.b64decode(result["data"], validate=True)
            if not 1 <= len(raw) <= 32_768 or base64.b64encode(raw).decode("ascii") != result["data"]:
                raise ValueError()
            return raw
        except (ValueError, TypeError):
            raise TransportError() from None

    def delete_blob(self, blob_id):
        result = self._call("DELETE", self._blob_path(blob_id))
        if set(result) != {"ok"} or result["ok"] is not True:
            raise TransportError()
        return result

    def acknowledge(self, event_id):
        try:
            if str(UUID(event_id)) != event_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise TransportError() from None
        result = self._call("DELETE", "/v1/sealed/events/" + event_id)
        if result != {"ok": True}:
            raise TransportError()
        return result
