# SPDX-License-Identifier: AGPL-3.0-or-later
"""Startup data failures stop before any window, store or service opens."""
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QMessageBox

from orion_mini import app


@pytest.mark.parametrize("preservation_error", [False, True])
def test_failed_data_check_stops_before_opening_profile(monkeypatch, tmp_path, preservation_error):
    application = Mock()
    monkeypatch.setattr(app, "QApplication", lambda args: application)
    monkeypatch.setattr(app, "QLockFile", lambda path: Mock(tryLock=lambda timeout: True))
    monkeypatch.setattr(app, "claim_taskbar_identity", lambda: None)
    monkeypatch.setattr(app, "qt_platform_for_background_clipboard", lambda: None)
    monkeypatch.setattr(app, "app_icon", lambda: None)
    monkeypatch.setattr(app, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(app.sys, "argv", ["saiph"])
    window = Mock(side_effect=AssertionError("A failed profile must never open"))
    monkeypatch.setattr(app, "MainWindow", window)
    warning = Mock()
    monkeypatch.setattr(QMessageBox, "warning", warning)
    private_error = "private provider data must not appear in the warning"
    check = Mock(side_effect=OSError(private_error)) if preservation_error else Mock(return_value={
        "results": {"workspace.sqlite3": "failed", "orion-mini.sqlite3": "missing"},
        "preserved": {"workspace.sqlite3": str(tmp_path / "db-quarantine" / "synthetic")},
    })
    monkeypatch.setattr(app, "check_databases", check)

    assert app.main() == 2
    check.assert_called_once_with(tmp_path)
    window.assert_not_called()
    application.exec.assert_not_called()
    warning.assert_called_once()
    message = warning.call_args.args[2]
    assert "Do not delete your profile" in message
    assert private_error not in message
