# SPDX-License-Identifier: AGPL-3.0-or-later
"""Local, expiring QR provisioning for the existing one-use pairing codes."""
from __future__ import annotations

import os
import ipaddress
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import qrcode
import qrcode.image.svg

from .db import Database
from .security import create_pairing_code

DEFAULT_ORIGIN = "http://100.64.0.1:8765"


def validate_origin(origin: str) -> str:
    u = urlsplit(origin)
    try:
        address = ipaddress.ip_address(u.hostname or "")
        mesh = address in ipaddress.ip_network("100.64.0.0/10") if address.version == 4 else address in ipaddress.ip_network("fd7a:115c:a1e0::/48")
    except ValueError:
        mesh = u.hostname == "pi.orion.internal"  # Existing private owner QR compatibility.
    if not (u.scheme == "http" and mesh
            and u.port is not None and 1024 <= u.port <= 65535 and u.username is None and u.password is None
            and u.path in {"", "/"} and not u.query and not u.fragment):
        raise ValueError("Pairing requires a private mesh origin")
    return origin.rstrip("/")


def write_pairing_qr(db: Database, target: Path, minutes: int, origin: str = DEFAULT_ORIGIN) -> None:
    origin = validate_origin(origin)
    if target.suffix.lower() != ".svg":
        raise ValueError("pairing QR output must be an .svg file")
    # A QR contains the one-use secret. Refuse overwrites and create owner-only on the Pi.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            code = create_pairing_code(db, minutes)
            uri = "orion://pair?" + urlencode({"v": "1", "hub": origin, "code": code})
            qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage).save(output)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
