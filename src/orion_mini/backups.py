# SPDX-License-Identifier: AGPL-3.0-or-later
"""Automatic restic device-to-Pi/offsite backups with private credentials and output."""
from __future__ import annotations

import os
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

from .storage import read_json, write_json


def configure(root: Path, sources, *, repository="sftp:pi:/srv/orion-backups/desktop", offsite=None, executable="restic"):
    """One-time local bootstrap. Never exports the password in its return value."""
    directory = root / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    password = directory / "password"
    if not password.exists():
        fd = os.open(password, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(secrets.token_urlsafe(48) + "\n")
        if os.name == "nt":
            # ACL inheritance can be broader than this user's private app data.
            account = os.environ.get("USERNAME")
            if not account:
                raise ValueError("Backup password permissions could not be secured.")
            result = subprocess.run(["icacls", str(password), "/inheritance:r", "/grant:r", f"{account}:(F)"], capture_output=True, timeout=10)
            if result.returncode:
                password.unlink()
                raise ValueError("Backup password permissions could not be secured.")
    paths = [str(Path(path).expanduser().resolve()) for path in sources]
    if not paths or not all(Path(path).exists() for path in paths):
        raise ValueError("Choose existing backup source folders.")
    targets = [{"name": "pi", "repository": repository, "password_file": str(password)}]
    if offsite:
        if not isinstance(offsite, dict) or set(offsite) != {"repository", "password_file", "environment_file"}:
            raise ValueError("Offsite backup needs its existing repository and private credential files.")
        targets.append({"name": "offsite", **offsite})
    value = {"enabled": True, "executable": executable, "sources": paths, "targets": targets, "interval_seconds": 86400}
    write_json(directory / "config.json", value)
    return {"configured": True, "offsite": bool(offsite), "password_file": str(password)}


class BackupRunner:
    def __init__(self, root, *, run=subprocess.run, clock=time.time):
        self.root, self.run, self.clock = Path(root), run, clock
        self.lock = threading.Lock()
        self.thread = None

    def status(self):
        path = self.root / "backups" / "config.json"
        return {"configured": path.exists(), **read_json(self.root / "backups" / "status.json", {"targets": {}})}

    def poll(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.once, name="orion-backup", daemon=True)
        self.thread.start()

    def once(self):
        if not self.lock.acquire(blocking=False):
            return
        try:
            directory = self.root / "backups"
            config = read_json(directory / "config.json", {})
            if not config.get("enabled"):
                return
            status = read_json(directory / "status.json", {"targets": {}})
            executable = config.get("executable", "restic")
            if not shutil.which(executable) and not Path(executable).is_file():
                status["error"] = "Restic is not installed on this computer."
                write_json(directory / "status.json", status)
                return
            for target in config.get("targets", []):
                name = target["name"]
                previous = status["targets"].get(name, {})
                if self.clock() < previous.get("retry_at", 0):
                    continue
                if self.clock() - previous.get("completed_at", 0) < max(3600, int(config.get("interval_seconds", 86400))):
                    continue
                record = {"started_at": self.clock(), "ok": False, **({"completed_at": previous["completed_at"]} if previous.get("completed_at") else {})}
                status["targets"][name] = record
                write_json(directory / "status.json", status)
                try:
                    env = dict(os.environ)
                    # This private JSON maps provider env variable names to values;
                    # credentials never appear as command arguments or in status.
                    credential_file = target.get("environment_file")
                    if credential_file:
                        additions = read_json(Path(credential_file), {})
                        if not isinstance(additions, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in additions.items()):
                            raise ValueError()
                        env.update(additions)
                    password = Path(target["password_file"])
                    if not password.is_file():
                        raise ValueError()
                    env["RESTIC_PASSWORD_FILE"] = str(password)
                    env.pop("RESTIC_PASSWORD", None)
                    env.pop("RESTIC_PASSWORD_COMMAND", None)
                    env["RESTIC_REPOSITORY"] = target["repository"]
                    base = [executable, "--quiet", "-o", "sftp.args=-oBatchMode=yes -oConnectTimeout=15"]
                    # Some Windows profile/storage layouts reject restic's
                    # atomic cache renames. The cache is optional; encrypted
                    # repository writes retain their normal upstream behavior.
                    if os.name == "nt":
                        base.append("--no-cache")
                    def call(*arguments):
                        result = self.run([*base, *arguments], capture_output=True, timeout=7200, env=env,
                                          **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
                        if result.returncode:
                            raise ValueError()
                    # init refuses to overwrite an existing repository, including
                    # repositories encrypted with a different password.
                    probe = self.run([*base, "cat", "config"], capture_output=True, timeout=60, env=env,
                                     **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
                    if probe.returncode:
                        call("init")
                    sources = config.get("sources", [])
                    if not sources or not all(Path(source).exists() for source in sources):
                        raise ValueError()
                    snapshots = directory / "snapshots"
                    snapshots.mkdir(exist_ok=True)
                    for name in ("workspace.sqlite3", "orion-mini.sqlite3"):
                        source = self.root / name
                        if source.is_file():
                            with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True, timeout=10) as source_db, sqlite3.connect(snapshots / (source.stem + ".snapshot.sqlite3")) as target_db:
                                source_db.backup(target_db)
                    call("backup", "--tag", "orion", "--exclude", "*.tmp", "--exclude", "*.partial",
                         "--exclude", "**/workspace.sqlite3*", "--exclude", "**/orion-mini.sqlite3*", "--", *sources)
                    # No automatic destructive retention/prune. Snapshots remain
                    # available for the owner's first restore/capacity review.
                    record.update(ok=True, completed_at=self.clock(), retry_at=self.clock() + max(3600, int(config.get("interval_seconds", 86400))))
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    record.update(error="Backup could not complete; retrying automatically.", retry_at=self.clock() + 900)
                write_json(directory / "status.json", status)
        finally:
            self.lock.release()
