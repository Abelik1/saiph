# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct mesh requests reuse the hub's device keys and nonce/revocation store."""
from types import SimpleNamespace
from uuid import UUID
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import Headers
from .security import verify_device_request

class Proof(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(max_length=512)
    headers: dict[str, str] = Field(max_length=4)

def verify(db, receiver: str, proof: Proof):
    # Destination is part of the signed path. A different paired peer cannot
    # turn a captured request into authorization for its own endpoint.
    prefix = f"/v1/peer/{receiver}/blobs/"
    if not proof.path.startswith(prefix): raise HTTPException(403, "Wrong peer destination")
    blob = proof.path[len(prefix):]
    try:
        if str(UUID(blob)) != blob: raise ValueError()
    except ValueError: raise HTTPException(400, "Invalid peer resource") from None
    headers = {k.lower(): v for k, v in proof.headers.items()}
    expected = {"x-orion-device-id", "x-orion-timestamp", "x-orion-nonce", "x-orion-signature"}
    if set(headers) != expected or any(len(v) > 1024 for v in headers.values()):
        raise HTTPException(400, "Invalid peer proof")
    request = SimpleNamespace(method="GET", headers=Headers(headers), url=SimpleNamespace(path=proof.path, query=""))
    principal = verify_device_request(db, request, b"")
    if principal["id"] == receiver: raise HTTPException(403, "Peer must be a different device")
    return {"device_id": principal["id"]}
