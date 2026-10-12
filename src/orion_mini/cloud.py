# SPDX-License-Identifier: AGPL-3.0-or-later
"""Local Cloud layout and restart-safe, stable recording import. No content logging."""
from __future__ import annotations
import hashlib
import time
from pathlib import Path
from uuid import uuid4
LAYOUT = ('Documents', 'Screenshots/Phone', 'Shared')
PERSONAL_LAYOUT = ()
MEDIA_SUFFIXES = {'.mp4', '.mkv', '.mov', '.avi', '.webm', '.wmv', '.m4v', '.mpg', '.mpeg', '.flv', '.mp3', '.m4a', '.wav', '.flac', '.aac', '.ogg', '.opus', '.wma', '.aiff'}

def cloud_root(settings: dict) -> Path:
    return Path((settings.get('cloud') or {}).get('path') or Path.home() / 'Cloud').expanduser()

def ensure_layout(settings: dict, *, personal=False) -> Path:
    root = cloud_root(settings)
    for relative in LAYOUT + (PERSONAL_LAYOUT if personal else ()):
        (root / relative).mkdir(parents=True, exist_ok=True)
    return root
