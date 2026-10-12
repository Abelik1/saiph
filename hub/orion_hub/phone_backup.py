# SPDX-License-Identifier: AGPL-3.0-or-later
"""Standard restic service credentials subordinate to existing paired devices."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

ORIGIN = "rest:http://100.64.0.1:8768"
SERVICE = "orion-phone-rest.service"
DEFAULT_DIRECTORY = Path("/var/lib/orion-phone-backup")
_REGISTRY_LOCK = threading.RLock()


def directory():
    return Path(os.environ.get("ORION_PHONE_BACKUP_DATA", str(DEFAULT_DIRECTORY)))


def configuration():
    root = directory()
    raw = json.loads((root / "config.json").read_text())
    if set(raw) != {"repository_path", "max_size", "max_accounts", "reserve_bytes"}:
        raise ValueError("Phone backup configuration is invalid")
    if not isinstance(raw["repository_path"], str) or not Path(raw["repository_path"]).is_absolute():
        raise ValueError("Phone backup configuration is invalid")
    for key, lower, upper in (("max_size", 1024**2, 16 * 1024**3), ("max_accounts", 1, 16),
                              ("reserve_bytes", 256 * 1024**2, 1024**4)):
        if type(raw[key]) is not int or not lower <= raw[key] <= upper:
            raise ValueError("Phone backup configuration is invalid")
    return root, raw


def _accounts(root):
    path = root / "credentials.json"
    if not path.exists():
        return {}
    if path.stat().st_size > 1024**2:
        raise ValueError("Phone backup registry is invalid")
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict) or len(raw) > 100:
        raise ValueError("Phone backup registry is invalid")
    for device, account in raw.items():
        if not isinstance(device, str) or not isinstance(account, dict) or \
                set(account) != {"username", "backend_password", "repository_password", "bcrypt", "revoked"} or \
                account["username"] != username(device) or type(account["revoked"]) is not bool or \
                any(not isinstance(account[key], str) or not 32 <= len(account[key]) <= 128 or
                    any(c in account[key] for c in "\r\n\0") for key in ("backend_password", "repository_password", "bcrypt")):
            raise ValueError("Phone backup registry is invalid")
    return raw


def username(device_id):
    return "orion-" + hashlib.sha256(device_id.encode()).hexdigest()[:32]


@contextmanager
def _lock(root):
    with _REGISTRY_LOCK:
        if os.name == "nt":
            yield
            return
        import fcntl
        fd = os.open(root / ".registry.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            owner = root.stat()
            actual = os.fstat(fd)
            if (actual.st_uid, actual.st_gid) != (owner.st_uid, owner.st_gid):
                os.fchown(fd, owner.st_uid, owner.st_gid)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def _write(path, value, mode=0o600):
    """Atomic private metadata; retain the installed directory owner/group."""
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    try:
        if os.name != "nt":
            owner = path.parent.stat()
            actual = os.fstat(fd)
            if (actual.st_uid, actual.st_gid) != (owner.st_uid, owner.st_gid):
                os.fchown(fd, owner.st_uid, owner.st_gid)
            os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as handle:
            fd = None
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if fd is not None:
            os.close(fd)
        temporary.unlink(missing_ok=True)


def _auth(root, accounts, connection):
    live = {row[0] for row in connection.execute("SELECT id FROM devices")}
    body = "".join(account["username"] + ":" + account["bcrypt"] + "\n"
                   for device, account in sorted(accounts.items()) if device in live and not account["revoked"])
    _write(root / "auth.htpasswd", body, 0o640)


def bootstrap(db, device_id, *, free=shutil.disk_usage):
    root, config = configuration()
    with _lock(root), db.connect() as connection:
        # Serializes filesystem credential changes with bootstrap, revoke and
        # private registry snapshots across hub and owner CLI processes.
        connection.execute("BEGIN IMMEDIATE")
        if not connection.execute("SELECT id FROM devices WHERE id=?", (device_id,)).fetchone():
            raise ValueError("Backup owner was revoked")
        accounts = _accounts(root)
        account = accounts.get(device_id)
        if account and account["revoked"]:
            raise ValueError("Backup owner was revoked")
        live = {row[0] for row in connection.execute("SELECT id FROM devices")}
        active = sum(device in live and not row["revoked"] for device, row in accounts.items())
        required = active + (account is None)
        if required > config["max_accounts"] or len(accounts) >= 100 and account is None:
            raise ValueError("Phone backup account capacity is full")
        # Existing repositories already consume their allocated quota; do not
        # charge that quota again whenever the phone refreshes configuration.
        if free(config["repository_path"]).free < config["reserve_bytes"] + (config["max_size"] if account is None else 0):
            raise ValueError("Phone backup storage has insufficient free space")
        if account is None:
            import bcrypt
            password = secrets.token_urlsafe(32)
            account = {"username": username(device_id), "backend_password": password,
                       "repository_password": secrets.token_urlsafe(48),
                       "bcrypt": bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode(), "revoked": False}
            accounts[device_id] = account
            _write(root / "credentials.json", json.dumps(accounts, separators=(",", ":")) + "\n")
        _auth(root, accounts, connection)
    return {"targets": [{"name": "pi", "repository": ORIGIN + "/" + account["username"] + "/",
                         "repository_password": account["repository_password"],
                         "backend_environment": {"RESTIC_REST_USERNAME": account["username"],
                                                 "RESTIC_REST_PASSWORD": account["backend_password"]}}],
            "interval_seconds": 86400}


def _service(action, run):
    try:
        result = run(["systemctl", action, SERVICE], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("Phone backup service control failed") from None
    if result.returncode:
        raise ValueError("Phone backup service control failed")


def revoke(db, device_id, *, run=subprocess.run):
    """The existing sudo owner CLI cuts active backup access before deleting pairing."""
    if not (directory() / "config.json").exists():
        db.execute("DELETE FROM devices WHERE id=?", (device_id,))
        return
    if os.name != "nt" and os.geteuid() != 0:
        raise ValueError("Use sudo orion-hub revoke to revoke phone backup access")
    root, _ = configuration()
    with _lock(root), db.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        accounts = _accounts(root)
        # A manual stop suppresses systemd auto-restart and terminates in-flight
        # transfers. Any later failure intentionally leaves backup access closed.
        _service("stop", run)
        connection.execute("DELETE FROM devices WHERE id=?", (device_id,))
        if device_id in accounts:
            accounts[device_id]["revoked"] = True
            _write(root / "credentials.json", json.dumps(accounts, separators=(",", ":")) + "\n")
        _auth(root, accounts, connection)
    try:
        _service("start", run)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise ValueError("Device revoked; phone backup service could not restart") from None


def reconcile(db):
    """Startup/helper reconciliation removes grants for devices deleted outside CLI."""
    if not (directory() / "config.json").exists():
        return
    root, _ = configuration()
    # The root service pre-start helper needs read access to Hub data only.
    # Registry locking serializes it with bootstrap/revoke without mounting the
    # hub database writable inside the rest-server service sandbox.
    with _lock(root):
        connection=sqlite3.connect(f"file:{db.path.as_posix()}?mode=ro",uri=True,timeout=15)
        try:
            connection.execute("BEGIN")
            _auth(root,_accounts(root),connection)
        finally:
            connection.close()


def main():
    import argparse
    from types import SimpleNamespace
    parser = argparse.ArgumentParser(description="Fixed phone backup authentication reconciliation")
    parser.add_argument("--reconcile", action="store_true", required=True)
    parser.add_argument("--data", type=Path, default=Path("/var/lib/orion-hub"))
    args = parser.parse_args()
    try:
        reconcile(SimpleNamespace(path=args.data / "orion-hub.sqlite3"))
    except (OSError, ValueError):
        raise SystemExit("Private phone backup authentication could not be reconciled") from None


if __name__ == "__main__":
    main()
