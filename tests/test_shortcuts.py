# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pinned taskbar entry only resolves when the shortcut declares the app identity."""
import sys
from pathlib import Path
import pytest

from orion_mini.app import APP_MODEL_ID
from orion_mini.startup import read_shortcut_model_id, write_shortcut

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows COM shortcuts')


def test_shortcut_keeps_target_arguments_icon_and_identity(tmp_path: Path):
    icon = tmp_path / "orion.ico"
    icon.write_bytes(b"\x00")
    link = write_shortcut(tmp_path / "Orion Mini.lnk", Path(sys.executable), "-m orion_mini",
                          icon, tmp_path, APP_MODEL_ID)
    assert read_shortcut_model_id(link) == APP_MODEL_ID
    stored = link.read_bytes()
    for value in (str(Path(sys.executable)), "-m orion_mini", str(icon), APP_MODEL_ID):
        # A .lnk keeps its target path in the ANSI LinkInfo block and the rest as UTF-16.
        assert value.encode("utf-16-le") in stored or value.encode() in stored, value


def test_shortcut_without_identity_stays_empty(tmp_path: Path):
    link = write_shortcut(tmp_path / "Plain.lnk", Path(sys.executable))
    assert link.is_file() and read_shortcut_model_id(link) == ""
