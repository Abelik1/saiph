# SPDX-License-Identifier: AGPL-3.0-or-later
"""Private enrollment artifacts for the existing expiring device pairing flow."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import qrcode
import qrcode.image.svg

from .pairing_qr import validate_origin
from .security import create_pairing_code


def validate_login_server(value):
    if value is None or value == "":
        return None
    u = urlsplit(value)
    if any(ord(ch) <= 32 for ch in value) or not (u.scheme == "https" and u.hostname and u.username is None and u.password is None
            and u.path in {"", "/"} and not u.query and not u.fragment
            and (u.port is None or 1 <= u.port <= 65535)):
        raise ValueError("Use a trusted HTTPS mesh control origin")
    return value.rstrip("/")


def configured_origin():
    address = os.environ.get("ORION_HUB_MESH_IP", "")
    if not address:
        raise ValueError("Configure the server mesh before creating an invitation")
    host = f"[{address}]" if ":" in address else address
    return validate_origin(f"http://{host}:{os.environ.get('ORION_HUB_PORT', '8765')}")


def create_enrollment(db, minutes=10):
    origin = configured_origin()
    controller = validate_login_server(os.environ.get('ORION_MESH_LOGIN_SERVER'))
    expires = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat().replace('+00:00', 'Z')
    return {'format': 'orion-enrollment', 'version': 1, 'hub': origin,
            'code': create_pairing_code(db, minutes), 'expires_at': expires, 'mesh_login_server': controller}


def write_enrollment(db, target: Path, minutes=10, origin=None, login_server=None):
    origin = validate_origin(origin or configured_origin())
    login_server = validate_login_server(login_server)
    if target.suffix != ".orion-enrollment" or not 1 <= minutes <= 60:
        raise ValueError("Use a new .orion-enrollment path and a 1–60 minute expiry")
    qr = target.with_suffix(".svg")
    # Reserve both private files before creating a code; never overwrite an
    # existing artifact, including a symbolic link supplied as the destination.
    opened = []
    try:
        for path in (target, qr):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            opened.append((path, fd))
        expires = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")
        code = create_pairing_code(db, minutes)
        artifact = {"format": "orion-enrollment", "version": 1, "hub": origin, "code": code,
                    "expires_at": expires,
                    "mesh_login_server": login_server}
        query = {"v": "1", "hub": origin, "code": code}
        if login_server:
            query["mesh_login_server"] = login_server
        with os.fdopen(opened[0][1], "w", encoding="utf-8") as output:
            opened[0] = (target, None)
            output.write(json.dumps(artifact, separators=(",", ":")) + "\n")
            output.flush(); os.fsync(output.fileno())
        with os.fdopen(opened[1][1], "wb") as output:
            opened[1] = (qr, None)
            qrcode.make("orion://pair?" + urlencode(query), image_factory=qrcode.image.svg.SvgPathImage).save(output)
            output.flush(); os.fsync(output.fileno())
    except BaseException:
        for path, fd in opened:
            if fd is not None: os.close(fd)
            path.unlink(missing_ok=True)
        raise
