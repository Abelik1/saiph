# SPDX-License-Identifier: AGPL-3.0-or-later
import base64, hashlib, importlib, time, uuid

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from orion_hub import releases

APK = b"PK\x03\x04" + b"fake apk body" * 1000


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setenv("ORION_HUB_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("ORION_HUB_AUTOMATIONS", str(tmp_path / "automations.json"))
    import orion_hub.app as mod
    mod = importlib.reload(mod)
    mod.PAIR_ATTEMPTS.clear()
    return mod


def apk(tmp_path, content=APK):
    path = tmp_path / f"{uuid.uuid4().hex}.apk"; path.write_bytes(content); return path


def signed_get(client, hub, path):
    from orion_hub.security import create_pairing_code
    key = ec.generate_private_key(ec.SECP256R1())
    pub = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    device = client.post("/v1/pairing/claim", json={"code": create_pairing_code(hub.DB), "name": "phone", "public_key_der_b64": pub}).json()["device_id"]
    ts, nonce = str(int(time.time())), str(uuid.uuid4())
    sig = base64.b64encode(key.sign(f"GET\n{path}\n{ts}\n{nonce}\n{hashlib.sha256(b'').hexdigest()}".encode(), ec.ECDSA(hashes.SHA256()))).decode()
    return client.get(path, headers={"X-Orion-Device-Id": device, "X-Orion-Timestamp": ts, "X-Orion-Nonce": nonce, "X-Orion-Signature": sig})


def test_publish_records_version_and_hash(tmp_path):
    r = releases.publish(tmp_path, apk(tmp_path), 5, "0.1.0")
    assert r["sha256"] == hashlib.sha256(APK).hexdigest() and r["size"] == len(APK)
    assert releases.latest(tmp_path)["version_code"] == 5
    assert (releases.release_dir(tmp_path) / "orion.apk").read_bytes() == APK


def test_publish_refuses_same_or_older_version(tmp_path):
    releases.publish(tmp_path, apk(tmp_path), 5, "0.1.0")
    for code in (5, 4):
        with pytest.raises(ValueError, match="not newer"):
            releases.publish(tmp_path, apk(tmp_path, APK + b"x"), code, "0.0.9")
    assert releases.latest(tmp_path)["version_code"] == 5


def test_publish_refuses_a_file_that_is_not_an_apk(tmp_path):
    with pytest.raises(ValueError, match="Not an APK"):
        releases.publish(tmp_path, apk(tmp_path, b"<html>oops</html>"), 1, "0.1.0")
    assert releases.latest(tmp_path) is None


def test_phone_reads_release_and_downloads_apk(hub, tmp_path):
    client = TestClient(hub.app)
    assert signed_get(client, hub, "/v1/app/android").json() == {"release": None}
    assert signed_get(client, hub, "/v1/app/android/apk").status_code == 404
    releases.publish(hub.DATA, apk(tmp_path), 7, "0.2.0")
    assert signed_get(client, hub, "/v1/app/android").json()["release"]["version_code"] == 7
    r = signed_get(client, hub, "/v1/app/android/apk")
    assert r.status_code == 200 and r.content == APK
    assert r.headers["content-type"] == "application/vnd.android.package-archive"
    assert r.headers["x-orion-sha256"] == hashlib.sha256(APK).hexdigest()


def test_unpaired_client_cannot_see_or_download_the_apk(hub, tmp_path):
    releases.publish(hub.DATA, apk(tmp_path), 7, "0.2.0")
    client = TestClient(hub.app)
    assert client.get("/v1/app/android").status_code == 401
    assert client.get("/v1/app/android/apk").status_code == 401


def test_backup_is_a_readable_copy_and_old_ones_are_pruned(tmp_path):
    import sqlite3
    from orion_hub.cli import backup_database
    from orion_hub.db import Database
    db = Database(tmp_path / "orion-hub.sqlite3")
    db.execute("INSERT INTO devices(id,name,public_key_der_b64,created_at) VALUES('d','phone','k','now')")
    folder = tmp_path / "backups"; folder.mkdir()
    for day in range(1, 5): (folder / f"orion-hub-2026010{day}-000000.sqlite3").write_bytes(b"old")
    copy = backup_database(tmp_path, keep=2)
    check = sqlite3.connect(copy)
    assert check.execute("SELECT name FROM devices").fetchone() == ("phone",)
    assert check.execute("PRAGMA journal_mode").fetchone() == ("delete",)
    check.close()
    assert sorted(p.name for p in folder.iterdir()) == ["orion-hub-20260104-000000.sqlite3", copy.name]
