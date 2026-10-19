# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from orion_mini.link_service import LinkWorkspace


@pytest.mark.parametrize('change', ['clear', 'disable-enable'])
def test_queued_screen_count_cannot_restore_cleared_or_disabled_summary(tmp_path, change):
    workspace = LinkWorkspace(tmp_path)
    queued = workspace.usage_counter.screen_action('photos')
    if change == 'clear':
        workspace.insights.clear()
    else:
        workspace.insights.set_enabled(False)
        workspace.insights.set_enabled(True)
    queued()
    assert workspace.store.all('insight_day') == []
    workspace.usage_counter.screen_action('photos')()
    assert workspace.store.all('insight_day')[0]['features'] == {'screen_photos':1}


def test_queued_screen_count_cannot_reappear_after_usage_consent_withdrawal(tmp_path):
    workspace = LinkWorkspace(tmp_path)
    workspace.usage_counter.set_consent(True)
    queued = workspace.usage_counter.screen_action('photos')
    workspace.usage_counter.set_consent(False)
    workspace.usage_counter.set_consent(True)
    queued()
    assert workspace.store.all('usage_day') == []
    workspace.usage_counter.screen_action('photos')()
    assert workspace.store.all('usage_day')[0]['features'] == {'screen_photos':1}
