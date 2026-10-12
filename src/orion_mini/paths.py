# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

from pathlib import Path
import os
from platformdirs import user_data_path


APP_DATA = user_data_path("OrionMini", appauthor=False)


def app_data_dir() -> Path:
    path = Path(os.environ.get("ORION_MINI_DATA_DIR", str(APP_DATA)))
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def registry_path() -> Path:
    return app_data_dir() / "orion-mini.sqlite3"


def github_roots() -> list[Path]:
    """Folders that hold the owner's repositories, on whichever computer this is.

    Computers keep them on different drives, so nothing assumes one location.
    ORION_GITHUB_ROOT wins; a source checkout's own parent folder comes next."""
    candidates = [os.environ.get("ORION_GITHUB_ROOT", "")]
    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "pyproject.toml").is_file():
        candidates.append(str(checkout.parent))
    home = Path.home()
    candidates += ["E:/Documents/Github", str(home / "Documents" / "Github"), str(home / "Downloads" / "Github"),
                   str(home / "source" / "repos"), str(home / "Github")]
    roots: list[Path] = []
    for value in candidates:
        if value and Path(value).is_dir() and Path(value).resolve() not in roots:
            roots.append(Path(value).resolve())
    return roots


def find_repo(name: str) -> Path | None:
    return next((root / name for root in github_roots() if (root / name).is_dir()), None)
