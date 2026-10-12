# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from orion_hub import phone_backup
from test_acceptance import headers, pair
from test_link import client, hub


@pytest.fixture
def backup(hub, tmp_path, monkeypatch):
    root = tmp_path / "phone-backup"
    root.mkdir()
    repositories = tmp_path / "encrypted-repos"
    repositories.mkdir()
    config = {"repository_path": str(repositories), "max_size": 1024**2, "max_accounts": 2, "reserve_bytes": 256 * 1024**2}
    (root / "config.json").write_text(json.dumps(config))
    monkeypatch.setenv("ORION_PHONE_BACKUP_DATA", str(root))
    monkeypatch.setattr(phone_backup.shutil, "disk_usage", lambda _: SimpleNamespace(free=100 * 1024**3))
    c = client(hub)
    key, device = pair(hub, c)
    return hub, c, key, device, root, config


def request(backup, body=None, **extra):
    _, c, key, device, *_ = backup
    path = "/v1/link/backups/bootstrap"
    raw = json.dumps(body or {}).encode()
    return c.post(path, content=raw, headers={**headers(key, device, "POST", path, raw), **extra})


def test_signed_bootstrap_is_idempotent_private_and_isolated_to_existing_device(backup, caplog):
    hub, c, key, device, root, _ = backup
    first = request(backup)
    assert first.status_code == 200 and first.headers["cache-control"] == "no-store"
    target = first.json()["targets"][0]
    assert target["repository"] == phone_backup.ORIGIN + "/" + phone_backup.username(device) + "/"
    assert target["backend_environment"]["RESTIC_REST_USERNAME"] == phone_backup.username(device)
    secret = target["backend_environment"]["RESTIC_REST_PASSWORD"]
    assert len(secret) >= 32 and target["repository_password"] != secret
    assert request(backup).json() == first.json()
    another_key, another = pair(hub, c)
    second = request((hub, c, another_key, another, root)).json()["targets"][0]
    assert second["repository"] != target["repository"] and second["repository_password"] != target["repository_password"]
    auth = (root / "auth.htpasswd").read_text()
    assert secret not in auth and secret not in caplog.text and target["repository_password"] not in caplog.text
    import bcrypt
    assert bcrypt.checkpw(secret.encode(), auth.splitlines()[next(i for i, line in enumerate(auth.splitlines()) if line.startswith(phone_backup.username(device)))].split(":", 1)[1].encode())


def test_bootstrap_refuses_unsigned_browser_delegate_and_supplied_paths(backup):
    hub, c, _, device, root, _ = backup
    path = "/v1/link/backups/bootstrap"
    assert c.post(path, json={}).status_code == 401
    assert request(backup, {"repository": "rest:http://elsewhere/"}).status_code == 400
    assert request(backup, **{"Origin": "http://100.64.0.1"}).status_code == 403
    assert request(backup, **{"Cookie": "orion_session=not-a-device"}).status_code == 403
    from orion_hub import agent_api
    grant = agent_api.issue(hub.DB, {"id": device}, {"name": "reader"})
    assert c.post(path, json={}, headers={"Authorization": "Bearer " + grant["token"]}).status_code == 401
    from fastapi.testclient import TestClient
    public = TestClient(hub.app, base_url="http://127.0.0.1:8765", client=("100.64.0.2", 9))
    assert public.post(path, json={}).status_code == 403
    assert not (root / "credentials.json").exists()


def test_capacity_and_free_space_fail_before_issuing_another_credential(backup):
    hub, c, key, device, root, config = backup
    config["max_accounts"] = 1
    (root / "config.json").write_text(json.dumps(config))
    assert request(backup).status_code == 200
    other_key, other = pair(hub, c)
    assert request((hub, c, other_key, other, root)).status_code == 503
    with pytest.raises(ValueError, match="free space"):
        phone_backup.bootstrap(hub.DB, device, free=lambda _: SimpleNamespace(free=0))
    assert set(json.loads((root / "credentials.json").read_text())) == {device}


def test_concurrent_same_device_bootstrap_creates_one_standard_account(backup):
    hub, _, _, device, root, _ = backup
    with ThreadPoolExecutor(2) as pool:
        result = list(pool.map(lambda _: phone_backup.bootstrap(hub.DB, device), range(2)))
    assert result[0] == result[1]
    assert len(json.loads((root / "credentials.json").read_text())) == 1
    assert len((root / "auth.htpasswd").read_text().splitlines()) == 1


def test_revoke_stops_active_access_removes_hash_preserves_recovery_and_frees_account_slot(backup, monkeypatch):
    monkeypatch.setattr(phone_backup.os, 'geteuid', lambda: 0, raising=False)
    hub, c, _, device, root, config = backup
    config["max_accounts"] = 1
    (root / "config.json").write_text(json.dumps(config))
    original = request(backup).json()
    calls = []
    def run(args, **kwargs):
        assert kwargs["capture_output"] and "timeout" in kwargs
        calls.append(args)
        if args[1] == "stop":
            assert hub.DB.row("SELECT id FROM devices WHERE id=?", (device,))
        else:
            assert hub.DB.row("SELECT id FROM devices WHERE id=?", (device,)) is None
            assert phone_backup.username(device) not in (root / "auth.htpasswd").read_text()
        return SimpleNamespace(returncode=0)
    phone_backup.revoke(hub.DB, device, run=run)
    assert calls == [["systemctl", "stop", phone_backup.SERVICE], ["systemctl", "start", phone_backup.SERVICE]]
    retained = json.loads((root / "credentials.json").read_text())[device]
    assert retained["revoked"] and retained["repository_password"] == original["targets"][0]["repository_password"]
    key, replacement = pair(hub, c)
    assert request((hub, c, key, replacement, root)).status_code == 200
    with pytest.raises(ValueError, match="revoked"):
        phone_backup.bootstrap(hub.DB, device)


def test_service_control_failure_never_claims_revocation_or_reopens_stale_auth(backup, monkeypatch):
    monkeypatch.setattr(phone_backup.os, 'geteuid', lambda: 0, raising=False)
    hub, _, _, device, root, _ = backup
    assert request(backup).status_code == 200
    with pytest.raises(ValueError, match="control failed"):
        phone_backup.revoke(hub.DB, device, run=lambda *args, **kwargs: SimpleNamespace(returncode=1))
    assert hub.DB.row("SELECT id FROM devices WHERE id=?", (device,))
    calls = []
    def run(args, **kwargs):
        calls.append(args[1])
        return SimpleNamespace(returncode=int(args[1] == "start"))
    with pytest.raises(ValueError, match="Device revoked"):
        phone_backup.revoke(hub.DB, device, run=run)
    assert calls == ["stop", "start"] and not (root / "auth.htpasswd").read_text()
    assert hub.DB.row("SELECT id FROM devices WHERE id=?", (device,)) is None


def test_reconciliation_filters_pairings_removed_outside_owner_cli(backup):
    hub, _, _, device, root, _ = backup
    assert request(backup).status_code == 200
    hub.DB.execute("DELETE FROM devices WHERE id=?", (device,))
    phone_backup.reconcile(hub.DB)
    assert not (root / "auth.htpasswd").read_text()


@pytest.mark.skipif(phone_backup.os.name == 'nt', reason='Unix administrator boundary')
def test_non_owner_cannot_revoke_or_control_backup_service(backup, monkeypatch):
    hub, _, _, device, _, _ = backup
    monkeypatch.setattr(phone_backup.os, 'geteuid', lambda: 1000)
    calls = []
    with pytest.raises(ValueError, match='sudo'):
        phone_backup.revoke(hub.DB, device, run=lambda *args, **kwargs: calls.append(args))
    assert not calls
    assert hub.DB.row('SELECT id FROM devices WHERE id=?', (device,))
