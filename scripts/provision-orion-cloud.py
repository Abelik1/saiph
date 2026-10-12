#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validate resources before generating private mesh-only Seafile/Immich stacks."""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
from pathlib import Path
from urllib.request import urlopen


def preflight(root, *, memory_mb=None, free_bytes=None):
    if memory_mb is None and os.name == "nt":
        import ctypes
        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), *[(field, ctypes.c_ulonglong) for field in ("total", "available", "page", "available_page", "virtual", "available_virtual", "extended")]]
        state = Memory(); state.length = ctypes.sizeof(state)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
            raise ValueError("Desktop memory capacity could not be checked.")
        memory_mb = state.total // 1024 ** 2
    elif memory_mb is None:
        fields = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
        memory_mb = int(fields["MemTotal"].split()[0]) // 1024
    if free_bytes is None:
        ancestor = Path(root)
        while not ancestor.exists():
            ancestor = ancestor.parent
        free_bytes = shutil.disk_usage(ancestor).free
    if memory_mb < 7600:
        raise ValueError("Cloud deployment needs at least 8 GB RAM for Seafile and Immich; no services were changed.")
    if free_bytes < 50 * 1024 ** 3:
        raise ValueError("Cloud deployment needs at least 50 GB free SSD space; no services were changed.")


def fetch(url):
    with urlopen(url, timeout=30) as response:
        data = response.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError("Upstream compose file was unexpectedly large.")
    return data


def private_file(path, data):
    if path.exists():
        raise ValueError("Existing Cloud configuration is retained; review upgrades separately.")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data if isinstance(data, bytes) else data.encode())
    if os.name == "nt":
        account = os.environ.get("USERNAME")
        if not account or subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{account}:(F)"], capture_output=True, timeout=10).returncode:
            path.unlink()
            raise ValueError("Cloud configuration permissions could not be secured.")


def validate_compose(document, mesh, expected):
    seen = set()
    for service in document["services"].values():
        if service.get("network_mode") == "host" or service.get("privileged"):
            raise ValueError("Cloud containers must use private bridge networks.")
        for port in service.get("ports", []):
            if port.get("host_ip") != mesh or port.get("protocol", "tcp") != "tcp":
                raise ValueError("A Cloud listener was not bound exclusively to the mesh.")
            seen.add(int(port["published"]))
    if seen != set(expected):
        raise ValueError("Unexpected Cloud listener configuration.")


def compose(directory, *args):
    result = subprocess.run(["docker", "compose", "--project-directory", str(directory), "-f", str(directory / "upstream.yml"), "-f", str(directory / "mesh.yml"), *args], capture_output=True, timeout=1800)
    if result.returncode:
        raise ValueError("Docker Cloud operation failed; inspect private service state locally.")
    return result.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("LOCALAPPDATA", "/opt")) / "OrionCloud")
    parser.add_argument("--mesh", required=True, help="Explicit mesh IPv4 address of the owner-selected data host")
    parser.add_argument("--immich-version", default="v3.3.0")
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not ipaddress.ip_address(args.mesh) in ipaddress.ip_network("100.64.0.0/10"):
        raise ValueError("Run the provisioner on the mesh-joined data host.")
    if not re.fullmatch(r"v\d+\.\d+\.\d+", args.immich_version) or not re.fullmatch(r"[^\s=]+@[^\s=]+", args.admin_email):
        raise ValueError("Choose a release version and valid local administrator email.")
    preflight(args.root)
    if not shutil.which("docker"):
        raise ValueError("Install the official Docker Engine and Compose plugin first; no services were changed.")
    backend = subprocess.run(["docker", "info", "--format", "{{json .MemTotal}} {{json .OSType}}"], capture_output=True, timeout=30)
    if backend.returncode or b'"linux"' not in backend.stdout:
        raise ValueError("Start the existing Docker Linux backend first; no services were changed.")
    if int(backend.stdout.split()[0]) < 7600 * 1024 ** 2:
        raise ValueError("Docker Linux needs at least 8 GB RAM for the two data services; no services were changed.")
    # Secrets must never be generated under a source checkout.
    if any((parent / ".git").exists() for parent in (args.root, *args.root.parents)):
        raise ValueError("Cloud service data must live outside source repositories.")
    args.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    specifications = [
        ("seafile", "https://manual.seafile.com/13.0/repo/docker/ce/seafile-server.yml", 8080, "seafile", 80),
        ("immich", f"https://github.com/immich-app/immich/releases/download/{args.immich_version}/docker-compose.yml", 2283, "immich-server", 2283),
    ]
    directories = []
    for name, url, published, service, internal in specifications:
        directory = args.root / name
        directory.mkdir(mode=0o700)
        content = fetch(url)
        private_file(directory / "upstream.yml", content)
        override = f"services:\n  {service}:\n    ports: !override\n      - '{args.mesh}:{published}:{internal}'\n"
        # Windows NTFS bind mounts cannot store PostgreSQL data. Linux-backed
        # named volumes retain Unix permissions and live inside Docker's WSL disk.
        if os.name == "nt":
            if name == "immich":
                override += "    volumes: !override\n      - immich-photos:/data\n"
            volumes = ("seafile-data", "seafile-mysql") if name == "seafile" else ("immich-photos", "immich-postgres")
            override += "volumes:\n" + "".join(f"  {volume}:\n" for volume in volumes)
        private_file(directory / "mesh.yml", override)
        secret = lambda: secrets.token_hex(32)
        if name == "seafile":
            variables = {"SEAFILE_SERVER_HOSTNAME": f"{args.mesh}:8080", "SEAFILE_SERVER_PROTOCOL": "http",
                         "TIME_ZONE": "Europe/London", "ENABLE_SEADOC": "false", "ENABLE_NOTIFICATION_SERVER": "false",
                         "SEAFILE_VOLUME": "seafile-data" if os.name == "nt" else str(directory / "data"), "SEAFILE_MYSQL_VOLUME": "seafile-mysql" if os.name == "nt" else str(directory / "mysql"),
                         "SEAFILE_MYSQL_DB_PASSWORD": secret(), "INIT_SEAFILE_MYSQL_ROOT_PASSWORD": secret(),
                         "INIT_SEAFILE_ADMIN_EMAIL": args.admin_email, "INIT_SEAFILE_ADMIN_PASSWORD": secret(),
                         "JWT_PRIVATE_KEY": secret(), "REDIS_PASSWORD": secret(), "SEAFILE_REDIS_IMAGE": "redis:7.4-alpine"}
        else:
            variables = {"UPLOAD_LOCATION": "immich-photos" if os.name == "nt" else str(directory / "photos"), "DB_DATA_LOCATION": "immich-postgres" if os.name == "nt" else str(directory / "postgres"),
                         "IMMICH_VERSION": args.immich_version, "DB_PASSWORD": secret(), "DB_USERNAME": "postgres", "DB_DATABASE_NAME": "immich", "TZ": "Europe/London"}
        private_file(directory / ".env", "".join(f"{key}={value}\n" for key, value in variables.items()))
        private_file(directory / "upstream-source.json", json.dumps({"url": url, "sha256": hashlib.sha256(content).hexdigest()}, indent=2))
        canonical = json.loads(compose(directory, "config", "--format", "json"))
        validate_compose(canonical, args.mesh, [published])
        directories.append(directory)
    if args.apply:
        for directory in directories:
            compose(directory, "up", "-d", "--wait")
    print("Mesh-only Cloud configurations validated." + (" Services started." if args.apply else " Run with --apply on a suitable host to start services."))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        # Fixed messages only; never echo upstream output or private .env values.
        print(str(error) if isinstance(error, ValueError) else "Cloud provisioning failed before completion.")
        raise SystemExit(1)
