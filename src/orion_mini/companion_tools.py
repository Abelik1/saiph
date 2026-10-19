# SPDX-License-Identifier: AGPL-3.0-or-later
"""Discover standard tools or the checksum-verified private portable installs."""
from __future__ import annotations
import os
from pathlib import Path
import shutil


def _sdk_adb(roots):
    executable = "adb.exe" if os.name == "nt" else "adb"
    for root in filter(None, roots):
        candidate = Path(root) / "platform-tools" / executable
        if candidate.is_file():
            return str(candidate)
    return None


def default_sdk_roots():
    """Android Studio's default SDK folders. An installed Saiph has no SDK of its
    own, so without these a computer whose adb is not on PATH could never start
    the phone's clipboard helper."""
    if os.name == "nt":
        return [str(Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Android" / "Sdk")]
    return [str(Path.home() / "Android" / "Sdk"), str(Path.home() / "Library" / "Android" / "sdk")]


def locations_fingerprint():
    """Modification times of every folder a tool lookup searches.

    A running app's PATH never changes, so a newly installed tool can only
    appear by one of these folders changing. Comparing a few dozen folder times
    costs milliseconds; a full lookup walks PATH for each tool (about 0.5 s)."""
    folders = [entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    folders += [str(Path(value) / "platform-tools") for value in
                (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"), *default_sdk_roots()) if value]
    if os.name == "nt":
        tools = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "OrionMini" / "tools"
        folders.append(str(tools))
        for package in ("scrcpy", "deskflow"):
            root = tools / package
            folders.append(str(root))
            try:
                folders += sorted(str(version) for version in root.iterdir() if version.is_dir())
            except OSError:
                pass
        folders.append(str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Deskflow"))
    fingerprint = []
    for folder in folders:
        try:
            fingerprint.append((folder, os.stat(folder).st_mtime_ns))
        except OSError:
            fingerprint.append((folder, None))
    return tuple(fingerprint)


def tool_path(name, configured=None):
    if name not in {"adb", "restic", "scrcpy", "deskflow-core", "deskflow"}:
        raise ValueError("Unknown Saiph companion tool.")
    if configured:
        path = Path(configured).expanduser()
        return str(path) if path.is_file() else None
    standard = shutil.which(name)
    if standard:
        return standard
    if name == "adb":
        configured_sdk = _sdk_adb([os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT")])
        if configured_sdk:
            return configured_sdk
    if os.name != "nt":
        return _sdk_adb(default_sdk_roots()) if name == "adb" else None
    package = {"adb": "scrcpy", "deskflow-core": "deskflow"}.get(name, name)
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "OrionMini" / "tools" / package
    versions = sorted(root.iterdir(), key=lambda p: tuple(int(x) for x in p.name.split('.') if x.isdigit()), reverse=True) if root.is_dir() else []
    for version in versions:
        if not (version / "orion-upstream.json").is_file():
            continue
        candidates = list(version.rglob(name + ".exe"))
        if candidates:
            return str(candidates[0])
    if name == "adb":
        # Saiph's checksum-verified portable copy wins; the default SDK folder is the last guess.
        return _sdk_adb(default_sdk_roots())
    installed = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Deskflow" / (name + ".exe")
    return str(installed) if package == "deskflow" and installed.is_file() else None
