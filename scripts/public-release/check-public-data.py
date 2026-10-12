# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reject reviewed identifying tokens without putting the identifiers in source."""
from __future__ import annotations
import argparse
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import subprocess

# Populated with fingerprints of the previously reviewed private identifiers.
# These are a narrow regression guard, not encryption or a complete privacy scan.
DENIED_FINGERPRINTS = frozenset({
    "5612e2abc6d2f2fc8dbe252971abf55e0f175a0e156e4bef852167f2e2dab7ef",
    "68e7c76139a0f553000644dcdfe89a90835153b16d33dba38cf77a25c4244571",
    "eefa7a69b79f2c5ea63f50d576e367e4c1296bc4ba6df1176ac94e9c31817541",
    "f396d161611a5c0c749bd201e6ddb11f3ba5125fbba5bc07a5bd77cfca28c179",
})
WORDS = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


@lru_cache(maxsize=32768)
def fingerprint(value: str) -> str:
    return hashlib.sha256(value.casefold().encode("utf-8")).hexdigest()


def identifying(content: str, fingerprints: frozenset[str]) -> bool:
    for match in WORDS.finditer(content.casefold()):
        value = match.group()
        if fingerprint(value) in fingerprints:
            return True
        if "-" in value and any(fingerprint(part) in fingerprints for part in value.split("-")):
            return True
    return False


def scan_files(root: Path, files: list[str], fingerprints=DENIED_FINGERPRINTS) -> list[str]:
    findings = []
    for name in files:
        path = root / name
        if not path.is_file() or path.is_symlink():
            continue
        try:
            content = path.read_text(encoding="utf-8-sig")
        except UnicodeError:
            continue
        if identifying(content, fingerprints):
            findings.append(name)
    return sorted(findings)


def scan_history(root: Path, fingerprints=DENIED_FINGERPRINTS) -> tuple[list[dict], list[str]]:
    # Inspect complete blobs across every locally fetched ref, not only HEAD's
    # diffs. Deleted files and unmerged branches remain publication blockers.
    objects = subprocess.check_output(["git", "rev-list", "--objects", "--all"], cwd=root).decode().splitlines()
    findings = []
    with subprocess.Popen(["git", "cat-file", "--batch"], cwd=root,
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE) as process:
        for entry in objects:
            oid, _, path = entry.partition(" ")
            process.stdin.write((oid + "\n").encode("ascii"))
            process.stdin.flush()
            header = process.stdout.readline().decode("ascii").split()
            if len(header) != 3:
                raise ValueError("Cannot inspect complete Git object history")
            raw = process.stdout.read(int(header[2]))
            if process.stdout.read(1) != b"\n":
                raise ValueError("Incomplete Git object")
            if header[1] != "blob":
                continue
            try:
                content = raw.decode("utf-8-sig")
            except UnicodeError:
                continue
            if identifying(content, fingerprints):
                findings.append({"blob": oid, "path": path})
        process.stdin.close()
        if process.wait() != 0:
            raise ValueError("Git history inspection failed")
    commits = set()
    for item in findings:
        commits.update(subprocess.check_output([
            "git", "log", "--all", "--format=%H", "--find-object=" + item["blob"],
        ], cwd=root).decode().splitlines())
    return findings, sorted(commits)


def check(root: Path, history: bool = False, fingerprints=DENIED_FINGERPRINTS) -> dict:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    findings = scan_files(root, [name for name in tracked if name], fingerprints)
    blobs, commits = scan_history(root, fingerprints) if history else ([], [])
    return {"schema": 2, "ready": not findings and not blobs, "files": findings,
            "history_checked": history, "history_blobs": blobs, "history_commits": commits,
            "scope": "Reviewed identifier tokens and hyphen components only; credentials, other personal data, binaries and remote-only refs require separate review."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--history", action="store_true", help="Inspect complete blobs across all locally fetched refs")
    args = parser.parse_args()
    result = check(args.root.resolve(), args.history)
    print(json.dumps(result, indent=2))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
