# SPDX-License-Identifier: AGPL-3.0-or-later
"""The app's own startup entry names Saiph.exe, even after an older updater relaunched OrionMini.exe."""
import sys

from orion_mini import startup


def test_compatibility_copy_records_the_saiph_executable(tmp_path, monkeypatch):
    app = tmp_path / 'releases/0.1.0-beta.5/app'; app.mkdir(parents=True)
    for name in ('Saiph.exe', 'OrionMini.exe'):
        (app / name).write_bytes(b'MZ synthetic')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    for running in ('Saiph.exe', 'OrionMini.exe'):
        monkeypatch.setattr(sys, 'executable', str(app / running))
        assert startup.startup_command() == f'"{app / "Saiph.exe"}"'


def test_pre_rename_release_keeps_its_own_executable(tmp_path, monkeypatch):
    app = tmp_path / 'releases/0.1.0-beta.4/app'; app.mkdir(parents=True)
    (app / 'OrionMini.exe').write_bytes(b'MZ synthetic')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(app / 'OrionMini.exe'))
    assert startup.startup_command() == f'"{app / "OrionMini.exe"}"'
