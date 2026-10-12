#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run the exported desktop unit suite without private integration harnesses."""
from pathlib import Path
import os
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[2]
    if not (root / "LICENSE").is_file():
        raise SystemExit("Run this check in the public export, not the private monorepo.")
    environment = dict(os.environ)
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    environment["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(root / "hub")))
    command = [sys.executable, "-m", "pytest", "tests", "-q",
               "--ignore=tests/e2e", "--ignore=tests/integration"]
    return subprocess.run(command, cwd=root, env=environment, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
