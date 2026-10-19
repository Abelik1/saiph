# SPDX-License-Identifier: AGPL-3.0-or-later
"""Received files and saved photos share one folder: Downloads → Saiph, wherever Downloads is."""
from pathlib import Path

from orion_mini import paths, phone_settings


def test_linux_follows_xdg_download_dir_from_the_environment_or_user_dirs(tmp_path):
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    assert paths.downloads_dir(home, platform="linux", environ={}) == home / "Downloads"
    (home / ".config" / "user-dirs.dirs").write_text('# synthetic\nXDG_DOWNLOAD_DIR="$HOME/Téléchargements"\n', encoding="utf-8")
    assert paths.received_dir(home, platform="linux", environ={}) == home / "Téléchargements" / "Saiph"
    assert paths.downloads_dir(home, platform="linux", environ={"XDG_DOWNLOAD_DIR": str(tmp_path / "elsewhere")}) == tmp_path / "elsewhere"
    # Pointing at home itself means "no Downloads folder": fall back rather than fill home.
    assert paths.downloads_dir(home, platform="linux", environ={"XDG_DOWNLOAD_DIR": "$HOME/"}) == home / "Downloads"
    config = tmp_path / "config"
    config.mkdir()
    (config / "user-dirs.dirs").write_text(f'XDG_DOWNLOAD_DIR="{(tmp_path / "dl").as_posix()}"\n', encoding="utf-8")
    assert paths.downloads_dir(home, platform="linux", environ={"XDG_CONFIG_HOME": str(config)}) == tmp_path / "dl"


def test_explicit_home_on_windows_and_macos_uses_its_downloads(tmp_path):
    assert paths.downloads_dir(tmp_path, platform="win32") == tmp_path / "Downloads"
    assert paths.received_dir(tmp_path, platform="darwin") == tmp_path / "Downloads" / "Saiph"


def test_an_overridden_home_never_reaches_the_accounts_real_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert paths.received_dir() == tmp_path / "Downloads" / "Saiph"
    assert phone_settings.received_folder({"hosted": {"enabled": True}}) == tmp_path / "Downloads" / "Saiph"
