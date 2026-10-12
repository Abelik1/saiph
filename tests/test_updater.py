# SPDX-License-Identifier: AGPL-3.0-or-later
from orion_mini import updater
import sys
import pytest


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows source updater console')
def test_start_update_launches_visible_script_for_this_process(monkeypatch, tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "build.ps1").write_text("", encoding="utf-8")
    monkeypatch.setenv("ORION_MINI_DATA_DIR", str(tmp_path / "data"))
    calls = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args, **kw: calls.append((args, kw)))
    script = updater.start_update(tmp_path, pid=1234)
    args, kw = calls[0]
    assert args[args.index("-AppPid") + 1] == "1234"
    assert args[args.index("-Root") + 1] == str(tmp_path)
    assert args[args.index("-File") + 1] == str(script)
    assert kw["creationflags"] & updater.subprocess.CREATE_NEW_CONSOLE
    text = script.read_text(encoding="utf-8-sig")
    assert r"scripts\build.ps1" in text and "git pull --ff-only" in text


@pytest.mark.skipif(sys.platform == 'win32', reason='Linux source updater guidance')
def test_linux_source_update_requires_explicit_checkout_rebuild(tmp_path):
    with pytest.raises(ValueError, match='bootstrap-orion-linux.sh'):
        updater.start_update(tmp_path)


def test_source_checkout_requires_build_script(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "find_repo", lambda name: tmp_path)
    monkeypatch.setattr(updater, "__file__", str(tmp_path / "a" / "b" / "c.py"))
    assert updater.source_checkout() is None
