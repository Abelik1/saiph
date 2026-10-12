# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Android build the phone updates itself from.

Only a paired device can read it, and Android itself refuses an update signed
with a different certificate from the installed app, so a replaced file on the
Pi cannot take over the phone. The sha256 lets the phone check what arrived.
"""
from __future__ import annotations
import hashlib, json, os, shutil
from pathlib import Path
from .security import now_iso

MAX_APK_BYTES=200_000_000

def release_dir(data:Path)->Path: return data/"releases"/"android"

def latest(data:Path)->dict|None:
    meta=release_dir(data)/"release.json"
    if not meta.exists() or not (release_dir(data)/"orion.apk").exists(): return None
    return json.loads(meta.read_text(encoding="utf-8"))

def publish(data:Path, apk:Path, version_code:int, version_name:str)->dict:
    if version_code<1: raise ValueError("version code must be a positive integer")
    size=apk.stat().st_size
    if size>MAX_APK_BYTES: raise ValueError("APK is larger than 200 MB")
    with apk.open("rb") as f:
        if f.read(4)!=b"PK\x03\x04": raise ValueError("Not an APK (expected a zip file)")
    current=latest(data)
    if current and version_code<=current["version_code"]:
        raise ValueError(f"Version code {version_code} is not newer than the published {current['version_code']}; Android will not install it as an update")
    folder=release_dir(data); folder.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(); tmp=folder/"orion.apk.part"
    with apk.open("rb") as src, tmp.open("wb") as dst:
        for chunk in iter(lambda: src.read(1<<20), b""): digest.update(chunk); dst.write(chunk)
    release={"version_code":version_code,"version_name":version_name,"sha256":digest.hexdigest(),"size":size,"published_at":now_iso()}
    # The APK first, then the metadata that points at it: a reader never sees
    # a version number for a file that is not there yet.
    os.replace(tmp,folder/"orion.apk")
    meta_tmp=folder/"release.json.part"; meta_tmp.write_text(json.dumps(release),encoding="utf-8"); os.replace(meta_tmp,folder/"release.json")
    return release
