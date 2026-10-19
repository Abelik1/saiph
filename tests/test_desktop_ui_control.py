# SPDX-License-Identifier: AGPL-3.0-or-later
"""Control-session boundaries, without starting Qt or touching an owner profile."""
import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location("desktop_ui", Path(__file__).resolve().parents[1] / "scripts" / "desktop-ui.py")
desktop_ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop_ui)


def dashboard(tmp_path):
    built = tmp_path / "dashboard" / "index.html"
    built.parent.mkdir()
    built.write_text("<html></html>", encoding="utf-8")
    return built


def test_new_session_uses_fresh_profile_and_local_endpoint(tmp_path, monkeypatch):
    directory = tmp_path / "session"
    session = desktop_ui.create_session(directory, dashboard(tmp_path), live=False)
    assert session["mode"] == "isolated"
    assert session["endpoint"].startswith("http://127.0.0.1:")
    assert Path(session["profile"]) == directory / "profile"
    assert len(session["nonce"]) == 48
    desktop_ui.write_session(directory, session)
    assert json.loads((directory / "session.json").read_text()) == session
    for key in ("ORION_MINI_DATA_DIR", "QTWEBENGINE_REMOTE_DEBUGGING", "QTWEBENGINE_CHROMIUM_FLAGS",
                "ORION_MINI_TEST", "QT_QPA_PLATFORM", "TEMP", "TMP", "TMPDIR"):
        monkeypatch.setenv(key, "previous-value")
    desktop_ui.environment(directory, session, show=False)
    import os
    assert os.environ["ORION_MINI_TEST"] == "1"
    assert os.environ["ORION_MINI_DATA_DIR"] == session["profile"]
    assert os.environ["QTWEBENGINE_REMOTE_DEBUGGING"].startswith("127.0.0.1:")
    assert "--remote-allow-origins=*" not in os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]
    assert "--no-sandbox" not in os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]
    assert "--disable-gpu" in os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]


def test_existing_directory_is_never_reused_or_modified(tmp_path):
    directory = tmp_path / "existing-profile"
    directory.mkdir()
    sentinel = directory / "settings.json"
    sentinel.write_text('{"owner": "synthetic fixture"}', encoding="utf-8")
    with pytest.raises(FileExistsError):
        desktop_ui.create_session(directory, dashboard(tmp_path), live=True)
    assert sentinel.read_text() == '{"owner": "synthetic fixture"}'
    assert list(directory.iterdir()) == [sentinel]


def test_live_mode_removes_test_bypass_and_offscreen_setting(tmp_path, monkeypatch):
    import os
    directory = tmp_path / "live-session"
    session = desktop_ui.create_session(directory, dashboard(tmp_path), live=True)
    for key in ("ORION_MINI_DATA_DIR", "QTWEBENGINE_REMOTE_DEBUGGING", "QTWEBENGINE_CHROMIUM_FLAGS",
                "ORION_MINI_TEST", "QT_QPA_PLATFORM", "TEMP", "TMP", "TMPDIR"):
        monkeypatch.setenv(key, "previous-value")
    desktop_ui.environment(directory, session, show=True)
    assert session["mode"] == "live"
    assert "ORION_MINI_TEST" not in os.environ
    assert "QT_QPA_PLATFORM" not in os.environ
    assert os.environ["ORION_MINI_DATA_DIR"] == session["profile"]
    assert "--disable-gpu" not in os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]


def test_missing_dashboard_does_not_create_a_profile(tmp_path):
    with pytest.raises(FileNotFoundError):
        desktop_ui.create_session(tmp_path / "session", tmp_path / "missing" / "index.html", live=False)
    assert not (tmp_path / "session").exists()


def test_existing_profile_requires_live_and_preserves_settings(tmp_path):
    profile = tmp_path / "authorized-profile"
    profile.mkdir()
    settings = profile / "settings.json"
    original = '{"machine":{"name":"Synthetic existing desktop"},"start_with_windows":true}'
    settings.write_text(original, encoding="utf-8")
    built = dashboard(tmp_path)
    session_dir = tmp_path / "session"
    with pytest.raises(ValueError, match="--live"):
        desktop_ui.create_session(session_dir, built, False, profile)
    assert not session_dir.exists()
    session = desktop_ui.create_session(session_dir, built, True, profile)
    assert session["profile"] == str(profile.resolve())
    assert session["existing_profile"] is True
    assert session["mode"] == "live"
    assert settings.read_text(encoding="utf-8") == original
    assert list(profile.iterdir()) == [settings]
    assert not (session_dir / "profile").exists()


def test_invalid_existing_profile_never_creates_session(tmp_path):
    profile = tmp_path / "not-a-profile"
    profile.mkdir()
    session_dir = tmp_path / "session"
    with pytest.raises(ValueError, match="settings.json"):
        desktop_ui.create_session(session_dir, dashboard(tmp_path), True, profile)
    assert not session_dir.exists()
