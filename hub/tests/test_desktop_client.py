# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Windows client's signing must match what the hub verifies."""
import importlib, importlib.util, json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

CLIENT = Path(__file__).resolve().parents[2] / "src" / "orion_mini" / "hub_client.py"


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    monkeypatch.setenv("ORION_HUB_DATA", str(tmp_path / "hub"))
    monkeypatch.setenv("ORION_HUB_AUTOMATIONS", str(tmp_path / "automations.json"))
    import orion_hub.app as hub
    hub = importlib.reload(hub)
    hub.PAIR_ATTEMPTS.clear()
    monkeypatch.syspath_prepend(str(CLIENT.parent.parent))
    spec = importlib.util.spec_from_file_location("orion_mini.hub_client", CLIENT)
    client = importlib.util.module_from_spec(spec); spec.loader.exec_module(client)
    http = TestClient(hub.app)

    def request(url, path, method="GET", body=None, headers=None, timeout=20):
        r = http.request(method, path, content=json.dumps(body, separators=(",", ":")).encode() if body is not None else None,
                         headers={**({"Content-Type": "application/json"} if body is not None else {}), **(headers or {})})
        if r.status_code >= 400: raise RuntimeError(f"Orion Hub returned HTTP {r.status_code}.")
        return r.json()
    monkeypatch.setattr(client, "_request", request)
    return hub, client, tmp_path / "desktop"


def test_desktop_pairs_and_makes_signed_requests(desktop):
    hub, client, root = desktop
    from orion_hub.security import create_pairing_code
    config = client.pair(root, "https://orion.example.com", create_pairing_code(hub.DB), "desk")
    assert config["paired"] and config["device_id"].startswith("dev_")
    assert (root / "hub-device-key.pem").exists()
    assert "tasks" in client.signed(root, config, "/v1/dashboard")
    task = client.signed(root, config, "/v1/tasks", "POST", {"title": "from desktop"})
    assert task["title"] == "from desktop"


def test_desktop_refuses_plain_http_and_unpaired_use(desktop):
    _, client, root = desktop
    with pytest.raises(ValueError, match="HTTPS"):
        client.pair(root, "http://orion.example.com", "12345678")
    with pytest.raises(ValueError, match="Pair"):
        client.signed(root, {}, "/v1/dashboard")

def test_desktop_pairs_on_the_mesh_without_a_new_identity_contract(desktop):
    hub, client, root = desktop
    from orion_hub.security import create_pairing_code
    config = client.pair(root, "http://100.64.0.1:8765", create_pairing_code(hub.DB))
    assert config["paired"]
    assert "tasks" in client.signed(root, config, "/v1/dashboard")


def test_desktop_key_is_separate_from_other_devices(desktop):
    hub, client, root = desktop
    from orion_hub.security import create_pairing_code
    first = client.pair(root, "https://orion.example.com", create_pairing_code(hub.DB))
    other = client.pair(root.parent / "phone", "https://orion.example.com", create_pairing_code(hub.DB))
    keys = {r["public_key_der_b64"] for r in hub.DB.rows("SELECT public_key_der_b64 FROM devices")}
    assert len(keys) == 2
    # One device's id with another's key must fail.
    with pytest.raises(RuntimeError, match="401"):
        client.signed(root, {**first, "device_id": other["device_id"]}, "/v1/dashboard")


def test_desktop_reads_and_decides_the_shared_inbox(desktop, monkeypatch):
    hub, client, root = desktop
    monkeypatch.setattr(hub, "push_data", lambda db, data: 1)
    from orion_hub.security import create_pairing_code
    desk = client.pair(root, "https://orion.example.com", create_pairing_code(hub.DB), "desktop")
    laptop = client.pair(root.parent / "laptop", "https://orion.example.com", create_pairing_code(hub.DB), "laptop")
    client.signed(root, desk, "/v1/inbox", "POST", {"id": "cal-seminar", "kind": "proposal", "title": "Seminar",
                                                    "proposal": {"events": [{"title": "Seminar", "start": "2026-11-16"}]}})
    assert client.decide(root.parent / "laptop", laptop, "cal-seminar", "accept")["changed"]
    # The query string is part of what is signed.
    accepted = client.inbox(root, desk, "accepted")
    assert [(row["id"], row["decided_by"]) for row in accepted] == [("cal-seminar", "laptop")]
    assert client.inbox(root, desk, "new") == []
