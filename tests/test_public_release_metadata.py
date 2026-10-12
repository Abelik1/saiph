# SPDX-License-Identifier: AGPL-3.0-or-later
"""Final release byte manifests must reject unsafe inputs and track public source."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_checksums", ROOT / "scripts/public-release/release-checksums.py")
checksums = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checksums)


def test_manifest_tracks_final_bytes_and_exact_source(tmp_path):
    artifact = tmp_path / "Saiph-0.1.0-beta.1.exe"
    artifact.write_bytes(b"synthetic signed-artifact placeholder")
    commit = "a" * 40
    checksums.record(tmp_path, commit)
    metadata = json.loads((tmp_path / "release-source.json").read_text())
    assert metadata["source_commit"] == commit
    assert metadata["artifacts"] == [{"file": artifact.name, "bytes": artifact.stat().st_size,
                                      "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}]
    assert "release-source.json" in (tmp_path / "SHA256SUMS").read_text()
    artifact.write_bytes(b"changed after signing")
    checksums.record(tmp_path, commit)
    assert json.loads((tmp_path / "release-source.json").read_text()) != metadata


def test_checksum_metadata_rejects_empty_tree_and_noncommit(tmp_path):
    with pytest.raises(ValueError, match="No release artifacts"):
        checksums.record(tmp_path, "a" * 40)
    (tmp_path / "artifact.exe").write_bytes(b"fixture")
    with pytest.raises(ValueError, match="full public Git commit"):
        checksums.record(tmp_path, "HEAD")
    (tmp_path / "nested").mkdir()
    with pytest.raises(ValueError, match="regular files only"):
        checksums.record(tmp_path, "a" * 40)


def test_verify_detects_changed_artifact_source_and_checksum(tmp_path):
    artifact = tmp_path / 'artifact.exe'
    artifact.write_bytes(b'fixture')
    checksums.record(tmp_path, 'a' * 40)
    assert checksums.verify(tmp_path, 'a' * 40)['source_commit'] == 'a' * 40
    with pytest.raises(ValueError, match='no longer match'):
        checksums.verify(tmp_path, 'b' * 40)
    artifact.write_bytes(b'changed')
    with pytest.raises(ValueError, match='no longer match'):
        checksums.verify(tmp_path, 'a' * 40)
    checksums.record(tmp_path, 'a' * 40)
    (tmp_path / 'SHA256SUMS').write_text('wrong')
    with pytest.raises(ValueError, match='SHA256SUMS'):
        checksums.verify(tmp_path, 'a' * 40)


def test_verify_rejects_extra_unrecorded_artifact(tmp_path):
    (tmp_path / 'artifact.exe').write_bytes(b'fixture')
    checksums.record(tmp_path, 'a' * 40)
    (tmp_path / 'unreviewed.exe').write_bytes(b'extra')
    with pytest.raises(ValueError, match='no longer match'):
        checksums.verify(tmp_path, 'a' * 40)


@pytest.mark.parametrize("order", ["case-sensitive", "case-insensitive"])
def test_verify_accepts_other_platform_order_without_rewriting_evidence(tmp_path, order):
    (tmp_path / "Saiph-preview.exe").write_bytes(b"synthetic binary")
    (tmp_path / "build-evidence.json").write_text("{}")
    commit = "c" * 40
    checksums.record(tmp_path, commit)
    metadata = json.loads((tmp_path / "release-source.json").read_text())
    metadata["artifacts"].sort(key=lambda item: item["file"].casefold() if order == "case-insensitive" else item["file"])
    source_bytes = (json.dumps(metadata, indent=2) + "\n").encode()
    (tmp_path / "release-source.json").write_bytes(source_bytes)
    sums = checksums.checksum_text(metadata, source_bytes)
    (tmp_path / "SHA256SUMS").write_text(sums, encoding="utf-8")
    checksums.verify(tmp_path, commit)
    assert (tmp_path / "release-source.json").read_bytes() == source_bytes
    # Duplicate records cannot disappear through order normalization.
    metadata["artifacts"].append(dict(metadata["artifacts"][0]))
    (tmp_path / "release-source.json").write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError, match="no longer match"):
        checksums.verify(tmp_path, commit)
