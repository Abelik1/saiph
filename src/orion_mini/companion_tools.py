# SPDX-License-Identifier: AGPL-3.0-or-later
"""Discover standard tools or the checksum-verified private portable installs."""
from __future__ import annotations
import os
from pathlib import Path
import shutil


def tool_path(name, configured=None):
    if name not in {"adb", "restic", "scrcpy", "deskflow-core", "deskflow"}:
        raise ValueError("Unknown Saiph companion tool.")
    if configured:
        path = Path(configured).expanduser()
        return str(path) if path.is_file() else None
    standard = shutil.which(name)
    if standard:
        return standard
    if name == "adb" and os.environ.get("ANDROID_HOME"):
        candidate = Path(os.environ["ANDROID_HOME"]) / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
        if candidate.is_file():
            return str(candidate)
    if os.name != "nt":
        return None
    package = {"adb": "scrcpy", "deskflow-core": "deskflow"}.get(name, name)
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "OrionMini" / "tools" / package
    versions = sorted(root.iterdir(), key=lambda p: tuple(int(x) for x in p.name.split('.') if x.isdigit()), reverse=True) if root.is_dir() else []
    for version in versions:
        if not (version / "orion-upstream.json").is_file():
            continue
        candidates = list(version.rglob(name + ".exe"))
        if candidates:
            return str(candidates[0])
    installed = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Deskflow" / (name + ".exe")
    return str(installed) if package == "deskflow" and installed.is_file() else None
