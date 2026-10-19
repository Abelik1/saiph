# SPDX-License-Identifier: AGPL-3.0-or-later
"""How the dashboard reaches the screen, chosen once at start-up.

Chromium's own frames stayed intact (docs/DESKTOP_PERFORMANCE.md) while blocks,
stripes and pixelation were seen on screen, so these switches cover the way Qt
and Windows present those frames. `rendering.json` in the profile picks them;
without it everything stays as shipped. They are diagnostics for comparing
presentation paths on a real computer, not user preferences:

    {"present": "noflip"}        Direct3D blit swap chain instead of flip model
    {"backend": "opengl"}        Qt Quick on OpenGL instead of Direct3D 11
    {"loop": "basic"}            Qt Quick renders on the GUI thread
    {"host": "widget"}           the dashboard in a QWebEngineView widget (before beta.37)

Keys combine. Unknown keys or values are ignored, never applied.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CHOICES = {
    "present": ("flip", "noflip"),
    "backend": ("default", "d3d11", "opengl"),
    "loop": ("default", "threaded", "basic"),
    "host": ("native", "widget"),
}
DEFAULT = {name: values[0] for name, values in CHOICES.items()}
_active = dict(DEFAULT)


def load(root) -> dict:
    """The validated choice in `root/rendering.json`, or the shipped default."""
    try:
        raw = json.loads((Path(root) / "rendering.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    choice = dict(DEFAULT)
    if isinstance(raw, dict):
        for name, values in CHOICES.items():
            if raw.get(name) in values:
                choice[name] = raw[name]
    override = os.environ.get("SAIPH_DASHBOARD_HOST")  # Test harnesses.
    if override in CHOICES["host"]:
        choice["host"] = override
    return choice


def apply(choice: dict) -> dict:
    """Set Qt's own switches for `choice`; must run before QApplication exists."""
    global _active
    if choice.get("present") == "noflip":
        os.environ["QT_D3D_NO_FLIP"] = "1"
    if choice.get("backend") in ("d3d11", "opengl"):
        os.environ["QSG_RHI_BACKEND"] = choice["backend"]
    if choice.get("loop") in ("threaded", "basic"):
        os.environ["QSG_RENDER_LOOP"] = choice["loop"]
    _active = dict(choice)
    return _active


def active() -> dict:
    return dict(_active)
