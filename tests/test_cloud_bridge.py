# SPDX-License-Identifier: AGPL-3.0-or-later
"""One-time Cloud setup accepts destinations only from the native folder picker."""
import json
import pytest
from types import SimpleNamespace

from orion_mini.desktop_bridge import DesktopBridge


def bridge():
    packets, calls, background = [], [], []
    workspace = SimpleNamespace(dispatch=lambda method,args: calls.append((method,args)) or {"state":"prepared"})
    obj = SimpleNamespace(window=SimpleNamespace(workspace=workspace,pump_jobs=lambda:None), response=SimpleNamespace(emit=lambda value:packets.append(json.loads(value))),changed=SimpleNamespace(emit=lambda:None),background=lambda request,fn:background.append(fn))
    return obj, packets, calls, background


def test_cloud_setup_uses_native_approved_folder(monkeypatch):
    obj, packets, calls, background = bridge()
    monkeypatch.setattr('orion_mini.desktop_bridge.QFileDialog.getExistingDirectory',lambda *args:'C:/Selected Cloud')
    DesktopBridge.request(obj,'request','cloud.setup',json.dumps({'libraries':['selected-library']}))
    assert not packets and not calls and len(background)==1
    background[0]()
    assert calls==[('cloud.setup',{'libraries':['selected-library'],'folder':'C:/Selected Cloud'})]


def test_cloud_setup_cancel_never_dispatches_or_provisions(monkeypatch):
    obj, packets, calls, background = bridge()
    monkeypatch.setattr('orion_mini.desktop_bridge.QFileDialog.getExistingDirectory',lambda *args:'')
    DesktopBridge.request(obj,'request','cloud.setup',json.dumps({'libraries':['selected-library']}))
    assert packets[0]['result']=={'cancelled':True}
    assert not calls and not background


def test_cloud_setup_rejects_web_supplied_folder_before_picker(monkeypatch):
    obj, packets, calls, background = bridge()
    monkeypatch.setattr('orion_mini.desktop_bridge.QFileDialog.getExistingDirectory',lambda *args:(_ for _ in ()).throw(AssertionError('picker must not open')))
    DesktopBridge.request(obj,'request','cloud.setup',json.dumps({'libraries':['selected-library'],'folder':'C:/Unapproved'}))
    assert packets[0]['ok'] is False
    assert not calls and not background


def test_cloud_management_is_finite_and_runs_off_ui_thread():
    for method in ['cloud.info','cloud.client.open','cloud.client.install']:
        obj, packets, calls, background = bridge()
        DesktopBridge.request(obj,'request',method,'{}')
        assert not packets and not calls and len(background)==1
        background[0]()
        assert calls==[(method,{})]


def test_cloud_installation_refuses_web_supplied_commands_or_urls():
    obj,packets,calls,background=bridge()
    DesktopBridge.request(obj,'request','cloud.client.install',json.dumps({'url':'https://untrusted.invalid/client.exe'}))
    assert packets[0]['ok'] is False and not calls and not background


def test_cloud_update_check_uses_the_account_source_and_restart_needs_a_download(monkeypatch, tmp_path):
    obj, packets, calls, background = bridge()
    workspace = obj.window.workspace
    workspace.root = tmp_path
    workspace.settings = {'hub': {'paired': True}}
    workspace.hosted_blocks_self_hosted = lambda: True
    workspace.hosted_controller = lambda: SimpleNamespace(update_feed=lambda: 'cloud_unavailable')
    from orion_mini.update_schedule import DesktopUpdates
    obj.updates = DesktopUpdates(workspace)
    checks = []
    monkeypatch.setattr('orion_mini.package_updates.check',
        lambda root, config, **kwargs: checks.append(kwargs) or {'reason': 'cloud_unavailable'})
    DesktopBridge.request(obj, 'check', 'app.update.check', '{}')
    background.pop()()
    assert checks == [{'cloud': 'cloud_unavailable'}]
    DesktopBridge.request(obj, 'restart', 'app.update.restart', '{}')
    with pytest.raises(ValueError, match='Download the update first'):
        background.pop()()
