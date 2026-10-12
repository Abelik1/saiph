# SPDX-License-Identifier: AGPL-3.0-or-later
"""Installed build components; never inferred from another user's profile.

Saiph is the Link edition. A separately installed private Workspace add-on
(the ``orion_workspace`` package) may supply personal tools by exposing
``orion_workspace.edition`` with ``window_class()`` and ``worker_main()``.
Public source and bundles never contain it.
"""
from __future__ import annotations
import importlib
import json
import sys
from pathlib import Path

EDITION = 'orion_workspace.edition'


def _bundle_selects_workspace() -> bool:
    # Packaged builds carry a deliberate, immutable selection outside user settings.
    bundle = getattr(sys, '_MEIPASS', None)
    if not isinstance(bundle, str) or not Path(bundle).is_absolute():
        return False
    try:
        manifest = json.loads((Path(bundle) / 'distribution-profile.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return (isinstance(manifest, dict) and set(manifest) == {'profile', 'schema'}
            and manifest['profile'] == 'workspace' and type(manifest['schema']) is int and manifest['schema'] == 1)


def edition():
    """Return the installed Workspace add-on module, or None for Link only."""
    if getattr(sys, 'frozen', False) and not _bundle_selects_workspace():
        return None
    try:
        return importlib.import_module(EDITION)
    except ModuleNotFoundError as error:
        # Only the add-on's own absence means Link; a broken add-on must fail loudly.
        if error.name in {'orion_workspace', EDITION}:
            return None
        raise


def workspace_installed() -> bool:
    return edition() is not None


def module_state(installed: bool) -> dict:
    return {'workspace': {'installed': installed, 'enabled': installed}}
