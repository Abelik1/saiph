# SPDX-License-Identifier: AGPL-3.0-or-later
"""Opt-in local automation of the same actions the app's own controls call.

Off unless ``automation.json`` in the data folder contains ``{"enabled": true}``;
it is re-read on every call, so deleting it switches automation off at once.
Only the allowlisted actions below are reachable, never SMS or calls. Each runs
exactly where the desktop bridge runs it: background actions on the caller's
thread, the rest on the Qt GUI thread.
"""
from __future__ import annotations

import json
from pathlib import Path

# The bridge already runs these off the GUI thread.
BACKGROUND = frozenset({"phone.photo.save", "phone.photo.prefetch", "phone.file.send"})
# The bridge runs these on the GUI thread; state() must only be read there.
GUI = frozenset({"state", "phone.notification"})
ALLOWED = BACKGROUND | GUI


def enabled(root: Path) -> bool:
    try:
        value = json.loads((Path(root) / "automation.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(value, dict) and value.get("enabled") is True


class Automation:
    def __init__(self, workspace, run_on_gui, changed=lambda: None):
        self.workspace, self.run_on_gui, self.changed = workspace, run_on_gui, changed

    def __call__(self, method: str, args: dict):
        if not enabled(self.workspace.root):
            raise PermissionError('Automation is off. Create automation.json containing {"enabled": true} to allow it.')
        if method not in ALLOWED:
            raise PermissionError("This action is not available to automation.")
        work = lambda: self.workspace.dispatch(method, args)
        try:
            return work() if method in BACKGROUND else self.run_on_gui(work)
        finally:
            if method != "state":
                self.changed()
