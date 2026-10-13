# SPDX-License-Identifier: AGPL-3.0-or-later
from types import SimpleNamespace

import pytest

from orion_mini import setup_guide


def workspace(tmp_path, **settings):
    return SimpleNamespace(root=tmp_path, settings={"hub": {"paired": False}, **settings})


def test_guide_shows_only_until_connected_or_completed(tmp_path):
    assert setup_guide.status(workspace(tmp_path))["show"] is True
    assert setup_guide.status(workspace(tmp_path, setup={"completed": True}))["show"] is False
    paired = setup_guide.status(workspace(tmp_path, hub={"paired": True}))
    assert paired["show"] is False and paired["mode"] == "hub"  # Existing users are not interrupted.
    (tmp_path / "hosted" / "identity").mkdir(parents=True)
    hosted = setup_guide.status(workspace(tmp_path))
    assert hosted["show"] is False and hosted["mode"] == "hosted"


def test_linux_helpers_report_the_package_to_install(monkeypatch):
    monkeypatch.setattr(setup_guide.sys, "platform", "linux")
    monkeypatch.setattr(setup_guide.shutil, "which", lambda name: "/usr/bin/xdotool" if name == "xdotool" else None)
    result = setup_guide.tools()
    assert result["linux"]["xdotool"]["found"] is True
    assert result["linux"]["bluetoothctl"] == {"found": False, "package": "bluez", "purpose": "Lock when your phone leaves"}
    assert set(result["tools"]) == {"scrcpy", "deskflow"}


def test_links_are_official_release_pages_only():
    assert all(url.startswith("https://") for url in setup_guide.LINKS.values())
    assert setup_guide.validate_options({"completed": True}) == {"completed": True}
    for options in ({"completed": "yes"}, {"step": 3}):
        with pytest.raises(ValueError):
            setup_guide.validate_options(options)


def test_settings_save_records_completion(tmp_path):
    from orion_mini.link_service import LinkWorkspace
    service = LinkWorkspace(tmp_path)
    assert service.state()["setup"]["show"] is True
    service.dispatch("settings.save", {"setup": {"completed": True}})
    assert service.state()["setup"]["show"] is False
    with pytest.raises(ValueError):
        service.dispatch("settings.save", {"setup": {"completed": 1}})
