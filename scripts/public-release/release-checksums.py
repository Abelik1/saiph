#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Record final artifact bytes and exact public source commit; never signs files."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re


def artifacts(directory: Path, source_commit: str):
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", source_commit):
        raise ValueError("An exact full public Git commit ID is required")
    directory = directory.resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("Artifact directory is required")
    records = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if path.name in {"SHA256SUMS", "release-source.json"}:
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError("Artifact directory must contain regular files only")
        if re.search(r"[\x00-\x1f\x7f\\]", path.name) or path.name.startswith(" "):
            raise ValueError("Unsafe checksum filename")
        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError("Artifact changed during hashing")
        records.append({"file": path.name, "bytes": after.st_size, "sha256": digest.hexdigest()})
    if not records:
        raise ValueError("No release artifacts found")
    return {"schema": 1, "source_commit": source_commit, "artifacts": records}


def checksum_text(metadata, source_bytes):
    source_digest = hashlib.sha256(source_bytes).hexdigest()
    return ("".join(f"{item['sha256']}  {item['file']}\n" for item in metadata['artifacts'])
            + f"{source_digest}  release-source.json\n")


def record(directory: Path, source_commit: str):
    metadata = artifacts(directory, source_commit)
    source_path = directory / "release-source.json"
    sums_path = directory / "SHA256SUMS"
    if source_path.is_symlink() or sums_path.is_symlink():
        raise ValueError("Metadata outputs must not be symbolic links")
    source_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    sums_path.write_text(checksum_text(metadata, source_path.read_bytes()), encoding="utf-8")
    return metadata


def verify(directory: Path, source_commit: str):
    """Fail if any final byte, filename, metadata or expected public source ID changed."""
    expected = artifacts(directory, source_commit)
    source_path, sums_path = directory / 'release-source.json', directory / 'SHA256SUMS'
    if any(path.is_symlink() or not path.is_file() for path in (source_path, sums_path)):
        raise ValueError('Both regular release metadata files are required')
    source_bytes = source_path.read_bytes()
    recorded = json.loads(source_bytes)
    # Old manifests used host Path ordering: Windows folds case, Linux does not.
    # Compare the full records independently of their order, retaining every
    # duplicate and validating checksum text against the original signed bytes.
    normalized = dict(recorded)
    normalized['artifacts'] = sorted(recorded.get('artifacts', []), key=lambda item: item['file'])
    if normalized != expected:
        raise ValueError('Release artifacts/source no longer match recorded metadata')
    if sums_path.read_text(encoding='utf-8') != checksum_text(recorded, source_bytes):
        raise ValueError('SHA256SUMS does not match the final files')
    return expected


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--verify", action="store_true", help="Check existing metadata without rewriting it")
    arguments = parser.parse_args()
    (verify if arguments.verify else record)(arguments.directory, arguments.source_commit)
