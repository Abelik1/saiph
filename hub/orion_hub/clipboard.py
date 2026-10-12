# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validate clipboard envelopes without storing extra content or logging it."""
import hashlib
import ipaddress
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

MAX_BYTES = 25 * 1024 * 1024
class Blob(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    address: str
    port: int = Field(ge=1024, le=65535)
class Clipboard(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mime: str = Field(pattern=r"^(text/plain|image/png|image/jpeg|image/webp)$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size: int = Field(ge=0, le=MAX_BYTES)
    text: str | None = Field(default=None, max_length=4096)
    blob: Blob | None = None
def validate(event):
    if event.type != "clipboard": return
    try:
        value = Clipboard.model_validate(event.payload)
        if value.text is not None:
            data = value.text.encode()
            if value.mime != "text/plain" or value.blob is not None or len(data) != value.size or hashlib.sha256(data).hexdigest() != value.sha256:
                raise ValueError()
        else:
            if value.blob is None or str(UUID(value.blob.id)) != value.blob.id: raise ValueError()
            address = ipaddress.ip_address(value.blob.address)
            if address not in (ipaddress.ip_network("100.64.0.0/10") if address.version == 4 else ipaddress.ip_network("fd7a:115c:a1e0::/48")): raise ValueError()
    except (ValueError, TypeError): raise ValueError("Invalid clipboard envelope") from None
