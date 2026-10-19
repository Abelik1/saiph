# SPDX-License-Identifier: AGPL-3.0-or-later
"""rendering.json: presentation diagnostics chosen at start-up, default unchanged."""
import json

import pytest

from orion_mini import rendering


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ("QT_D3D_NO_FLIP", "QSG_RHI_BACKEND", "QSG_RENDER_LOOP", "SAIPH_DASHBOARD_HOST"):
        monkeypatch.delenv(name, raising=False)


def test_without_a_file_everything_stays_as_shipped(tmp_path):
    import os
    choice = rendering.apply(rendering.load(tmp_path))
    assert choice == rendering.DEFAULT and choice["host"] == "native"
    assert not {"QT_D3D_NO_FLIP", "QSG_RHI_BACKEND", "QSG_RENDER_LOOP"} & set(os.environ)


def test_each_known_choice_sets_only_its_qt_switch(tmp_path):
    import os
    (tmp_path / "rendering.json").write_text(json.dumps({"present": "noflip", "backend": "opengl", "loop": "basic", "host": "widget"}))
    choice = rendering.apply(rendering.load(tmp_path))
    assert (os.environ["QT_D3D_NO_FLIP"], os.environ["QSG_RHI_BACKEND"], os.environ["QSG_RENDER_LOOP"]) == ("1", "opengl", "basic")
    assert choice["host"] == "widget" and rendering.active()["host"] == "widget"


@pytest.mark.parametrize("content", ['{"backend": "vulkan; calc.exe"}', '{"present": true}', "not json", '["noflip"]'])
def test_unknown_or_malformed_values_are_ignored(tmp_path, content):
    import os
    (tmp_path / "rendering.json").write_text(content)
    assert rendering.apply(rendering.load(tmp_path)) == rendering.DEFAULT
    assert "QSG_RHI_BACKEND" not in os.environ
