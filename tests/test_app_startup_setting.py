# SPDX-License-Identifier: AGPL-3.0-or-later
"""Launch survives a refused start-at-sign-in setting."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from orion_mini import app


def workspace(enabled=True):
    return SimpleNamespace(settings={'start_with_windows': enabled}, store=Mock())


@pytest.mark.parametrize('message', [
    # Physical acceptance: a fresh Linux profile without ~/.local/bin/orion
    # exited at every launch with this unhandled error.
    'Install Saiph before enabling session startup.',
    'An unrelated startup entry was preserved. Review startup in Advanced.',
])
def test_refused_startup_is_recorded_not_fatal(monkeypatch, message):
    monkeypatch.setattr(app, 'set_startup', Mock(side_effect=ValueError(message)))
    profile = workspace()
    app.apply_startup_setting(profile)
    profile.store.save.assert_called_once_with('job', {'kind': 'startup', 'status': 'failed', 'error': message})


def test_denied_startup_keeps_generic_message(monkeypatch):
    monkeypatch.setattr(app, 'set_startup', Mock(side_effect=PermissionError('private native detail')))
    profile = workspace()
    app.apply_startup_setting(profile)
    job = profile.store.save.call_args.args[1]
    assert job['status'] == 'failed' and 'private native detail' not in job['error']


def test_applied_startup_records_nothing(monkeypatch):
    applied = Mock()
    monkeypatch.setattr(app, 'set_startup', applied)
    profile = workspace(False)
    app.apply_startup_setting(profile)
    applied.assert_called_once_with(False)
    profile.store.save.assert_not_called()
