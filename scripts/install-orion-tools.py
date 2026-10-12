#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Install unmodified upstream portable tools with pinned publisher hashes."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
import shutil
from pathlib import Path
import stat
from urllib.request import urlopen
from zipfile import ZipFile

TOOLS = {
    "restic": ("0.19.1", "https://github.com/restic/restic/releases/download/v0.19.1/restic_0.19.1_windows_amd64.zip", "da948ad707ed690426473aaba2046cd61f8f90f6f0e7dab6be0d5796531de67d", "https://github.com/restic/restic/blob/v0.19.1/LICENSE"),
    "scrcpy": ("5.0.1", "https://github.com/Genymobile/scrcpy/releases/download/v5.0.1/scrcpy-win64-v5.0.1.zip", "b12a2c4ee8be317422451fc7dcf8ee20a71b5ea7ef9ad73ddd825a25316227a5", "https://github.com/Genymobile/scrcpy/blob/v5.0.1/LICENSE"),
    "deskflow": ("1.27.0", "https://github.com/deskflow/deskflow/releases/download/v1.27.0/deskflow-1.27.0-win-x64-portable.zip", "8d19004cc3625623489d96580c1b58fd13ee78185689907fd4478595f93fab9a", "https://github.com/deskflow/deskflow/blob/v1.27.0/LICENSE"),
}


def install(root, name):
    version, url, expected, license_url = TOOLS[name]
    destination = Path(root) / name / version
    marker = destination / "orion-upstream.json"
    if marker.is_file() and json.loads(marker.read_text()).get("sha256") == expected:
        return destination
    with urlopen(url, timeout=60) as response:
        data = response.read(100 * 1024 * 1024 + 1)
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Upstream portable tool checksum did not match.")
    destination.mkdir(parents=True, exist_ok=True)
    with ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            target = destination / member.filename.replace("\\", "/")
            if not target.resolve().is_relative_to(destination.resolve()) or stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError("Unsafe path in upstream portable archive.")
        archive.extractall(destination)
    if name == "restic":
        original = next(destination.glob("*.exe"))
        if original.name != "restic.exe":
            shutil.copy2(original, destination / "restic.exe")
    marker.write_text(json.dumps({"name": name, "version": version, "url": url, "sha256": expected, "license": license_url}, indent=2) + "\n")
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(os.environ["LOCALAPPDATA"]) / "OrionMini" / "tools")
    parser.add_argument("tools", choices=TOOLS, nargs="+")
    args = parser.parse_args()
    if os.name != "nt":
        raise ValueError("This installer contains Windows builds; use distribution packages on Linux.")
    for name in args.tools:
        install(args.root, name)
        print(name + " " + TOOLS[name][0] + " installed; publisher checksum verified.")


if __name__ == "__main__":
    main()
