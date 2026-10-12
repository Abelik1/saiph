# SPDX-License-Identifier: AGPL-3.0-or-later
import json

from orion_hub.db import Database
from orion_hub.diagnostics import snapshot


def test_support_snapshot_excludes_keys_tokens_names_and_content(tmp_path):
    db = Database(tmp_path / "orion-hub.sqlite3")
    db.execute("INSERT INTO devices(id,name,public_key_der_b64,push_token,created_at) VALUES(?,?,?,?,?)",
               ("dev_test", "PRIVATE_NAME", "PRIVATE_KEY", "PRIVATE_TOKEN", "now"))
    db.execute("INSERT INTO inbox(id,kind,source,title,body,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
               ("test-item", "notice", "test", "PRIVATE_TITLE", "PRIVATE_BODY", "new", "now", "now"))
    (tmp_path / "firebase-service-account.json").write_text("PRIVATE_SECRET")
    result = snapshot(tmp_path)
    assert result["integrity"] == "ok" and result["counts"]["devices"] == 1 and result["counts"]["inbox"] == 1
    assert "PRIVATE" not in json.dumps(result)
