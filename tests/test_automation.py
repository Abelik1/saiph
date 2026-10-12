# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import threading
from types import SimpleNamespace

import pytest

from orion_mini.api import app_call, handle
from orion_mini.automation import Automation


def setup(tmp_path, enabled=True):
    if enabled is not None:
        (tmp_path / "automation.json").write_text(json.dumps({"enabled": enabled}), encoding="utf-8")
    calls = []
    workspace = SimpleNamespace(root=tmp_path, dispatch=lambda method, args: calls.append((method, args, threading.current_thread().name)) or {"ok": method})
    gui = []
    def run_on_gui(work):
        gui.append(True)
        return work()
    changed = []
    return workspace, Automation(workspace, run_on_gui, lambda: changed.append(True)), calls, gui, changed


@pytest.mark.parametrize("enabled", [None, False])
def test_automation_is_off_without_explicit_opt_in(tmp_path, enabled):
    _, automation, calls, _, _ = setup(tmp_path, enabled)
    with pytest.raises(PermissionError, match="off"):
        automation("state", {})
    assert not calls


@pytest.mark.parametrize("method", ["phone.sms.send", "phone.call", "settings.save", "hub.pair", "enrollment.export"])
def test_only_allowlisted_actions_are_reachable(tmp_path, method):
    _, automation, calls, _, _ = setup(tmp_path)
    with pytest.raises(PermissionError, match="not available"):
        automation(method, {})
    assert not calls


def test_actions_run_where_the_bridge_runs_them(tmp_path):
    _, automation, calls, gui, changed = setup(tmp_path)
    assert automation("phone.photo.save", {"device_id": "phone", "photo_id": "17"}) == {"ok": "phone.photo.save"}
    assert not gui and changed == [True]
    assert automation("state", {}) == {"ok": "state"}
    assert gui == [True] and changed == [True]
    assert automation("phone.notification", {"id": "n"}) == {"ok": "phone.notification"}
    assert gui == [True, True] and changed == [True, True]
    assert [c[0] for c in calls] == ["phone.photo.save", "state", "phone.notification"]


def test_http_shape_errors_and_inbox_isolation(tmp_path):
    workspace, automation, calls, _, _ = setup(tmp_path)
    assert app_call(SimpleNamespace(), {"method": "state"})[0] == 503
    workspace.automation_call = automation
    assert app_call(workspace, {"method": "state"}) == (200, {"result": {"ok": "state"}})
    assert app_call(workspace, {"method": "state", "extra": 1})[0] == 400
    assert app_call(workspace, {"method": "phone.call"})[0] == 403
    def failing(method, args): raise ValueError("Saiph is offline. This action has not been sent.")
    workspace.automation_call = failing
    assert app_call(workspace, {"method": "phone.photo.save"}) == (400, {"error": "failed", "message": "Saiph is offline. This action has not been sent."})
    # Offline inbox replay goes through handle(), which has no app actions.
    workspace.plugins = SimpleNamespace(entries=[], describe=lambda entry: entry)
    assert handle(workspace, "POST", "/v1/app/call", {"method": "state"})[0] == 404
