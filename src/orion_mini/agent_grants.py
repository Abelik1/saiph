# SPDX-License-Identifier: AGPL-3.0-or-later
"""Trusted desktop broker: renew delegate files without giving an agent device keys."""
from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import hub_client
from .storage import read_json, write_json

# Pairing never authorizes a delegate. Owners must configure each name and scope.
DEFAULT_GRANTS = {}
SCOPES = frozenset({"devices.read", "notifications.read", "sms.read", "actions.propose",
                    "inbox.read", "inbox.propose", "inbox.result"})
NAME = re.compile(r"[a-z][a-z0-9-]{0,63}")
_lock = threading.Lock()


def ensure(root: Path, config: dict, grants=None):
    """Called inside the trusted desktop, never as an agent tool or model prompt."""
    if not config.get("device_id") or not (root / "hub-device-key.pem").is_file():
        return {"configured": False}
    selected = config.get("delegate_grants", DEFAULT_GRANTS) if grants is None else grants
    if not isinstance(selected, dict):
        raise ValueError("Use an explicit mapping of delegate names to scopes")
    # Validate the entire opt-in before issuing anything or constructing a path.
    for name, scopes in selected.items():
        if (not isinstance(name, str) or not NAME.fullmatch(name)
                or not isinstance(scopes, list) or not scopes
                or any(not isinstance(scope, str) for scope in scopes)
                or len(scopes) != len(set(scopes)) or not set(scopes) <= SCOPES):
            raise ValueError("Use a configured least-privilege delegate")
    renewed = []
    with _lock:
        for name, scopes in selected.items():
            path = root / "agent-grants" / (name + ".json")
            saved = read_json(path, {}) or {}
            try:
                expires = datetime.fromisoformat(saved["expires_at"])
                if saved.get("owner_device_id") == config["device_id"] and saved.get("base_url") == config.get("base_url") and saved.get("scopes") == sorted(scopes) and \
                        expires > datetime.now(timezone.utc) + timedelta(days=7):
                    continue
            except (ValueError, KeyError, TypeError):
                pass
            grant = hub_client.signed(root, config, "/v1/agents/grants", "POST", {"name": name, "scopes": scopes, "days": 30})
            # Credentials remain private app data. Return only renewal names.
            write_json(path, {**grant, "base_url": config["base_url"], "owner_device_id": config["device_id"]})
            try:
                path.chmod(0o600)
            except OSError:
                pass
            if saved.get("id"):
                try:
                    hub_client.signed(root, config, "/v1/agents/grants/" + saved["id"], "DELETE")
                except (OSError, ValueError, RuntimeError):
                    # The old delegate still expires; failure cannot widen authority.
                    pass
            renewed.append(name)
    return {"configured": True, "renewed": renewed}
