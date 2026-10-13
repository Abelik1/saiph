# SPDX-License-Identifier: AGPL-3.0-or-later
"""Send to phone from File Explorer, GNOME Files or Dolphin (`--send-files <paths…>`).

The shell passes selected file paths on the command line. A running Saiph receives
them through its authenticated local API; the owner then confirms the phone in a
dialog before anything is sent."""
from __future__ import annotations

from pathlib import Path

from .phone_features import MAX_FILE

MAX_FILES = 20


def validate(paths):
    """Existing regular files only, as absolute paths; at most 20, each up to 2 GB."""
    if not isinstance(paths, list) or not 0 < len(paths) <= MAX_FILES or any(not isinstance(p, str) or not p or len(p) > 4096 for p in paths):
        raise ValueError(f"Choose between 1 and {MAX_FILES} files to send.")
    result = []
    for value in paths:
        path = Path(value).resolve()
        if not path.is_file():
            raise ValueError("Only files can be sent to your phone. Folders stay on this computer.")
        if path.stat().st_size > MAX_FILE:
            raise ValueError("Each file can be up to 2 GB.")
        if str(path) not in result:
            result.append(str(path))
    return result


def targets(state):
    """Online paired devices, other than this computer, that accept files."""
    own = (state.get("settings") or {}).get("hub", {}).get("device_id")
    devices = (state.get("phone") or {}).get("devices", [])
    return [d for d in devices if d.get("online") and d.get("id") != own and "files" in d.get("capabilities", [])]


def arguments(argv):
    """Split `--send-files a b c` off the command line. Returns (remaining argv, paths or None)."""
    if "--send-files" not in argv:
        return argv, None
    index = argv.index("--send-files")
    return argv[:index], [str(Path(p).resolve()) for p in argv[index + 1:]]


def forward(root, paths):
    """Hand the paths to an already running Saiph. True when it accepted them."""
    from .enrollment import forward_local
    return forward_local(root, "/v1/phone/send", {"paths": paths})
