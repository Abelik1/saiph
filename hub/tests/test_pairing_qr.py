# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from orion_hub import cli, pairing_qr
from orion_hub.db import Database
from orion_hub.security import consume_pairing_code


def test_qr_reuses_one_use_code_and_does_not_print_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ORION_HUB_DATA", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["orion-hub", "pair", "--qr", str(tmp_path / "pair.svg")])
    actual_make = pairing_qr.qrcode.make
    captured = []

    def make(uri, **kwargs):
        captured.append(uri)
        return actual_make(uri, **kwargs)

    monkeypatch.setattr(pairing_qr.qrcode, "make", make)
    cli.main()
    uri = urlsplit(captured[0])
    args = parse_qs(uri.query)
    assert (uri.scheme, uri.netloc) == ("orion", "pair")
    assert args["hub"] == [pairing_qr.DEFAULT_ORIGIN] and args["v"] == ["1"]
    assert args["hub"] == ["http://100.64.0.1:8765"]  # Galaxy deliberately disables mesh DNS.
    code = args["code"][0]
    assert len(code) == 8 and code.isdecimal()
    assert code not in capsys.readouterr().out
    assert b"<svg" in (tmp_path / "pair.svg").read_bytes()
    db = Database(tmp_path / "orion-hub.sqlite3")
    assert consume_pairing_code(db, code)
    assert not consume_pairing_code(db, code)


@pytest.mark.parametrize("origin", ["http://attacker.example:8765", "http://pi.orion.internal:8765@attacker.example:8765",
                                  "http://pi.orion.internal:8765/v1", "http://pi.orion.internal:8765?code=12345678",
                                  "https://pi.orion.internal:8765", "http://pi.orion.internal:8765#bad"])
def test_rejects_non_mesh_origins_before_creating_codes(tmp_path, origin):
    db = Database(tmp_path / "hub.sqlite3")
    with pytest.raises(ValueError):
        pairing_qr.write_pairing_qr(db, tmp_path / "pair.svg", 10, origin)
    assert not db.rows("SELECT * FROM pairing_codes")


def test_qr_refuses_overwrite_and_unsupported_format(tmp_path):
    db = Database(tmp_path / "hub.sqlite3")
    target = tmp_path / "pair.svg"; target.write_text("existing")
    with pytest.raises(FileExistsError):
        pairing_qr.write_pairing_qr(db, target, 10)
    assert target.read_text() == "existing"
    with pytest.raises(ValueError):
        pairing_qr.write_pairing_qr(db, tmp_path / "pair.txt", 10)
    assert not db.rows("SELECT * FROM pairing_codes")
