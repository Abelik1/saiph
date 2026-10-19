# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

from pathlib import Path
import os
import shlex
import sys
from platformdirs import user_data_path


APP_DATA = user_data_path("OrionMini", appauthor=False)


def app_data_dir() -> Path:
    path = Path(os.environ.get("ORION_MINI_DATA_DIR", str(APP_DATA)))
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def _known_folder(identifier: str) -> Path | None:
    """A Windows Known Folder path, such as Downloads after the owner moved it to another drive."""
    import ctypes
    from ctypes import wintypes
    import uuid

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    folder = GUID.from_buffer_copy(uuid.UUID(identifier).bytes_le)
    result = ctypes.c_wchar_p()
    if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder), 0, None, ctypes.byref(result)) != 0:
        return None
    try:
        return Path(result.value) if result.value else None
    finally:
        ctypes.windll.ole32.CoTaskMemFree(result)


FOLDERID_DOWNLOADS = "374DE290-123F-4565-9164-39C4925E467B"
FOLDERID_PROFILE = "5E6C858F-0E22-4760-9AFE-EA3317B67173"


def _xdg_downloads(home: Path, environ) -> Path | None:
    """XDG_DOWNLOAD_DIR from the environment or user-dirs.dirs; None when unset or pointing at home itself."""
    value = environ.get("XDG_DOWNLOAD_DIR", "")
    if not value:
        config = Path(environ.get("XDG_CONFIG_HOME") or home / ".config") / "user-dirs.dirs"
        try:
            lines = config.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            lines = []
        for line in lines:
            key, _, raw = line.strip().partition("=")
            if key == "XDG_DOWNLOAD_DIR":
                try:
                    value = "".join(shlex.split(raw))
                except ValueError:
                    value = ""
    if value.startswith("$HOME"):
        value = str(home) + value[len("$HOME"):]
    path = Path(value) if value else None
    if path is None or not path.is_absolute() or path == home:
        return None
    return path


def downloads_dir(home: Path | None = None, *, platform: str = sys.platform, environ=None) -> Path:
    """The owner's Downloads folder: the Known Folder on Windows, XDG_DOWNLOAD_DIR on Linux.

    An explicit home reads only its own user-dirs.dirs unless an environment is given."""
    known = None
    if environ is None:
        environ = os.environ if home is None else {}
    if home is None:
        home = Path.home()
        if platform == "win32":
            try:
                # Only for the signed-in profile: an overridden home (tests, portable
                # profiles) keeps its own Downloads rather than the account's.
                if _known_folder(FOLDERID_PROFILE) == home:
                    known = _known_folder(FOLDERID_DOWNLOADS)
            except (OSError, AttributeError, ValueError):
                known = None
        elif platform.startswith("linux") and _account_home() in (None, home):
            known = _xdg_downloads(home, environ)
    elif platform.startswith("linux"):
        known = _xdg_downloads(home, environ)
    return known or home / "Downloads"


def _account_home() -> Path | None:
    try:
        import pwd
        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (ImportError, KeyError, OSError):
        return None


def received_dir(home: Path | None = None, **options) -> Path:
    """The one folder every received file and saved photo goes to: Downloads → Saiph."""
    return downloads_dir(home, **options) / "Saiph"


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
