# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import sys

import pytest

from orion_mini import modules


def add_on(tmp_path, monkeypatch, body):
    package = tmp_path / "orion_workspace"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "edition.py").write_text(body, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in ("orion_workspace", "orion_workspace.edition"):
        monkeypatch.delitem(sys.modules, name, raising=False)


def test_link_only_without_the_add_on(monkeypatch):
    # Hide an add-on that a developer may have installed alongside Saiph.
    monkeypatch.setitem(sys.modules, "orion_workspace", None)
    monkeypatch.delitem(sys.modules, "orion_workspace.edition", raising=False)
    assert modules.edition() is None and not modules.workspace_installed()


def test_installed_add_on_is_loaded(tmp_path, monkeypatch):
    add_on(tmp_path, monkeypatch, "def window_class(): return 'window'\ndef worker_main(): return 0\n")
    assert modules.edition().window_class() == "window" and modules.workspace_installed()


def test_broken_add_on_is_reported_not_hidden(tmp_path, monkeypatch):
    add_on(tmp_path, monkeypatch, "import missing_private_dependency\n")
    with pytest.raises(ModuleNotFoundError):
        modules.edition()


@pytest.mark.parametrize("manifest", [None, {"profile": "link", "schema": 1}, {"profile": "workspace", "schema": 1, "extra": 1}])
def test_bundles_need_an_explicit_workspace_profile(tmp_path, monkeypatch, manifest):
    add_on(tmp_path, monkeypatch, "def window_class(): return 'window'\n")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    if manifest is not None:
        (bundle / "distribution-profile.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    assert modules.edition() is None
    (bundle / "distribution-profile.json").write_text(json.dumps({"profile": "workspace", "schema": 1}), encoding="utf-8")
    assert modules.edition() is not None
