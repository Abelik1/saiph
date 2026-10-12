# SPDX-License-Identifier: AGPL-3.0-or-later
import importlib.util
from pathlib import Path
import subprocess
import pytest

path = Path(__file__).resolve().parents[1] / "scripts/public-release/check-public-data.py"
spec = importlib.util.spec_from_file_location("public_data", path)
public_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(public_data)

SYNTHETIC = ("synthetic-fixture-private", "syntheticowner123")
DENIED = frozenset(public_data.fingerprint(value) for value in SYNTHETIC)


@pytest.mark.parametrize("value", SYNTHETIC)
def test_rejects_identifying_tokens_without_echoing_values(tmp_path, value):
    (tmp_path / "fixture.txt").write_text(value.swapcase(), encoding="utf-8")
    assert public_data.scan_files(tmp_path, ["fixture.txt"], DENIED) == ["fixture.txt"]


def test_hyphen_components_are_checked_and_neutral_fixtures_pass(tmp_path):
    fixture = tmp_path / "fixture.txt"
    fixture.write_text("prefix-SyntheticOwner123-suffix", encoding="utf-8")
    assert public_data.scan_files(tmp_path, ["fixture.txt"], DENIED) == ["fixture.txt"]
    fixture.write_text("schedule-agent Synthetic workshop inbox.read", encoding="utf-8")
    assert public_data.scan_files(tmp_path, ["fixture.txt"], DENIED) == []


def test_history_still_blocks_removed_files_on_an_unmerged_branch(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path).decode().strip()
    git("init", "-q")
    git("config", "user.name", "Synthetic Test")
    git("config", "user.email", "test@example.invalid")
    fixture = tmp_path / "fixture.txt"
    fixture.write_text("Synthetic workshop", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "neutral fixture")
    base = git("rev-parse", "HEAD")
    git("checkout", "-qb", "unmerged-fixture")
    fixture.write_text(SYNTHETIC[0].swapcase(), encoding="utf-8")
    git("commit", "-qam", "synthetic identifying fixture")
    introduced = git("rev-parse", "HEAD")
    git("rm", "fixture.txt")
    git("commit", "-qm", "remove fixture")
    git("checkout", "--detach", base)
    assert public_data.check(tmp_path, fingerprints=DENIED)["ready"]
    result = public_data.check(tmp_path, history=True, fingerprints=DENIED)
    assert not result["ready"] and result["files"] == []
    assert introduced in result["history_commits"]
    assert result["history_blobs"][0]["path"] == "fixture.txt"
    assert all(value not in str(result) for value in SYNTHETIC)
