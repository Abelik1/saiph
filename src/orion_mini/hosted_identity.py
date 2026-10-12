# SPDX-License-Identifier: AGPL-3.0-or-later
"""This computer's hosted device identity, separate from any Hub identity.

A device is either self-hosted or hosted, never both (provisional decision),
so the hosted signing key is new and never reuses `hub-device-key.pem`. The
P-256 signing key and Tink recipient key are OS-protected; only public
metadata (deployment, device ID, public keys, role) is stored in clear.
Creation is explicit; an unreadable identity is preserved, never replaced.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .hosted_crypto import canonical, export_public
from .hosted_keys import KeyStorageError, RecipientVault
from .hosted_session import public_signing_key, read_signing_key
from .hosted_storage import ProtectedBlob, private_folder

ROLES = ("root",)


@dataclass(frozen=True)
class IdentityInfo:
    deployment_id: str
    device_id: str
    signing_key: str
    encryption_key: str
    role: str

    def public(self):
        return {"protocol_version": 1, "deployment_id": self.deployment_id, "device_id": self.device_id,
                "signing_key": self.signing_key, "encryption_key": self.encryption_key, "role": self.role}


class HostedIdentity:
    def __init__(self, folder: Path, *, protection=None):
        self.folder = Path(folder)
        self._protection = protection

    @property
    def _meta(self) -> Path:
        return self.folder / "identity.json"

    def exists(self) -> bool:
        return self._meta.exists() or (self.folder / "signing-key.enc").exists()

    def _signing_blob(self, binding):
        context = b"Orion/hosted-signing-storage/v1\0" + canonical(binding)
        return ProtectedBlob(self.folder, "signing-key.enc", context, protection=self._protection)

    def info(self) -> IdentityInfo:
        try:
            raw = self._meta.read_bytes()
            if len(raw) > 8192:
                raise ValueError()
            value = json.loads(raw)
            if (type(value) is not dict or set(value) != {"protocol_version", "deployment_id", "device_id", "signing_key", "encryption_key", "role"}
                    or value["protocol_version"] != 1 or str(UUID(value["deployment_id"])) != value["deployment_id"]
                    or type(value["device_id"]) is not str or not re.fullmatch(r"dev_[a-f0-9]{32}", value["device_id"])
                    or value["role"] not in ROLES):
                raise ValueError()
            read_signing_key(value["signing_key"])
            return IdentityInfo(value["deployment_id"], value["device_id"], value["signing_key"], value["encryption_key"], value["role"])
        except Exception:
            raise KeyStorageError() from None

    def create(self, deployment_id: str, *, role: str = "root"):
        """Explicit new hosted identity. Refuses to replace any existing one."""
        try:
            if role not in ROLES or str(UUID(deployment_id)) != deployment_id or self.exists():
                raise KeyStorageError()
            private_folder(self.folder)
            device_id = "dev_" + uuid4().hex
            signing = ec.generate_private_key(ec.SECP256R1())
            signing_public = public_signing_key(signing.public_key())
            binding = {"protocol_version": 1, "deployment_id": deployment_id, "device_id": device_id,
                       "signing_key": signing_public}
            self._signing_blob(binding).save(signing.private_bytes(
                serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            encryption = RecipientVault(self.folder / "recipient", deployment_id, device_id, signing_public,
                                        _protection=self._protection).create()
            info = IdentityInfo(deployment_id, device_id, signing_public, export_public(encryption), role)
            temporary = self.folder / "identity.json.tmp"
            temporary.write_bytes(canonical(info.public()))
            temporary.replace(self._meta)
            return info, signing, encryption
        except Exception:
            raise KeyStorageError() from None

    def load(self):
        """Return (info, signing_private_key, recipient_keyset) or fail closed."""
        try:
            info = self.info()
            binding = {"protocol_version": 1, "deployment_id": info.deployment_id, "device_id": info.device_id,
                       "signing_key": info.signing_key}
            raw = self._signing_blob(binding).load()
            if raw is None:
                raise KeyStorageError()
            signing = serialization.load_der_private_key(raw, password=None)
            if not isinstance(signing, ec.EllipticCurvePrivateKey) or public_signing_key(signing.public_key()) != info.signing_key:
                raise KeyStorageError()
            encryption = RecipientVault(self.folder / "recipient", info.deployment_id, info.device_id, info.signing_key,
                                        _protection=self._protection).load(info.encryption_key)
            return info, signing, encryption
        except Exception:
            raise KeyStorageError() from None
