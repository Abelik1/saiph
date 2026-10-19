# SPDX-License-Identifier: AGPL-3.0-or-later
"""The footer Update button's state: six-hourly quiet checks, one-click update, Settings parity."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from orion_mini import package_updates, update_schedule
from orion_mini.desktop_bridge import DesktopBridge
from orion_mini.update_schedule import DesktopUpdates

RELEASE = {'schema': 1, 'platform': 'windows-x86_64', 'profile': 'link', 'build': 12,
           'version': '0.1.0-beta.12', 'sha256': 'a' * 64, 'bytes': 1234}
INSTALLED = {**RELEASE, 'build': 11, 'version': '0.1.0-beta.11'}


class Service:
    """Synthetic package_updates: records calls, answers like the real module."""

    def __init__(self, monkeypatch, *, release=RELEASE):
        self.release, self.calls = release, []
        self.check_error = self.stage_error = self.install_error = None
        monkeypatch.setattr(package_updates, 'current', lambda: INSTALLED)
        monkeypatch.setattr(package_updates, 'source_for', lambda workspace: 'feed')
        monkeypatch.setattr(package_updates, 'check', self.check)
        monkeypatch.setattr(package_updates, 'stage', self.stage)
        monkeypatch.setattr(package_updates, 'install', self.install)

    def check(self, root, config, *, cloud):
        self.calls.append(('check', cloud))
        if self.check_error:
            raise self.check_error
        return {'supported': True, 'available': self.release is not None, 'current': INSTALLED,
                'release': self.release, 'notes': 'Faster photo sync.' if self.release else '', 'source': 'cloud'}

    def stage(self, root, config, offered, *, cloud):
        self.calls.append(('stage', offered['build']))
        if self.stage_error:
            raise self.stage_error
        # Linux stages the archive inside the .run: another description than the offer.
        return {'staged': True, 'path': '/staged/file', 'release': {**offered, 'sha256': 'b' * 64}}

    def install(self, root, staged):
        self.calls.append(('install', staged['release']['sha256']))
        if self.install_error:
            raise self.install_error
        return {'started': True}


def updates(**kwargs):
    events = {'changed': 0, 'restart': 0}
    workspace = SimpleNamespace(root=Path('/profile'), settings={'hub': {'paired': False}})
    value = DesktopUpdates(workspace, changed=lambda: events.__setitem__('changed', events['changed'] + 1),
                           restart=lambda: events.__setitem__('restart', events['restart'] + 1),
                           clock=lambda: 1_700_000_000, **kwargs)
    return value, events


def test_schedule_is_a_short_start_up_delay_then_every_six_hours():
    assert update_schedule.CHECK_INTERVAL_MS == 6 * 60 * 60 * 1000
    assert 30_000 <= update_schedule.FIRST_CHECK_MS <= 5 * 60 * 1000
    # Qt timers take a signed 32-bit interval.
    assert update_schedule.CHECK_INTERVAL_MS < 2 ** 31


def test_window_starts_the_schedule_outside_tests_only():
    source = (Path(update_schedule.__file__).parent / 'app.py').read_text(encoding='utf-8')
    block = source[source.index('from .update_schedule import'):source.index('self.scan()', source.index('from .update_schedule import'))]
    assert 'self.update_timer.start(CHECK_INTERVAL_MS)' in block
    assert 'QTimer.singleShot(FIRST_CHECK_MS, self.bridge.updates.start_background_check)' in block
    before = source[:source.index('from .update_schedule import')]
    guard = before.rindex("if not os.environ.get('ORION_MINI_TEST'):")
    # Only comments between the test-session guard and the schedule.
    assert all(line.strip().startswith('#') or not line.strip() for line in before[guard:].splitlines()[1:])


def test_starts_with_no_button(monkeypatch):
    Service(monkeypatch)
    value, events = updates()
    assert value.status() == {'state': 'none', 'release': None, 'version': None, 'bytes': None, 'notes': '', 'source': None,
                              'error': '', 'checked_at': None}
    assert json.loads(json.dumps(value.status())) == value.status()
    assert events['changed'] == 0


def test_background_check_lights_the_button_and_never_downloads(monkeypatch):
    service = Service(monkeypatch)
    value, events = updates()
    assert value.background_check() is True
    assert service.calls == [('check', 'feed')]
    status = value.status()
    assert (status['state'], status['version'], status['bytes'], status['notes']) == ('available', '0.1.0-beta.12', 1234, 'Faster photo sync.')
    assert status['checked_at'] == 1_700_000_000
    # Settings → Updates can offer the download the footer found.
    assert status['release'] == RELEASE
    assert events == {'changed': 1, 'restart': 0}


def test_background_check_without_an_update_keeps_the_button_hidden(monkeypatch):
    Service(monkeypatch, release=None)
    value, _ = updates()
    assert value.background_check() is True
    assert value.status()['state'] == 'none'


@pytest.mark.parametrize('error', [OSError('offline'), ValueError('Invalid desktop release metadata'), RuntimeError('x')])
def test_background_check_failures_are_quiet_and_keep_the_last_answer(monkeypatch, error):
    service = Service(monkeypatch)
    value, _ = updates()
    value.background_check()
    service.check_error = error
    assert value.background_check() is False
    assert value.status()['state'] == 'available'
    assert value.status()['error'] == ''


def test_development_builds_never_ask(monkeypatch):
    service = Service(monkeypatch)
    monkeypatch.setattr(package_updates, 'current', lambda: None)
    value, events = updates()
    assert value.background_check() is False
    assert service.calls == [] and events['changed'] == 0


def test_signed_out_or_unavailable_account_shows_no_button(monkeypatch):
    Service(monkeypatch)
    monkeypatch.setattr(package_updates, 'check', lambda root, config, cloud: {
        'supported': False, 'available': False, 'current': INSTALLED, 'release': None, 'reason': 'cloud_unavailable'})
    value, _ = updates()
    value.background_check()
    assert value.status()['state'] == 'none'


def test_background_check_skips_while_an_update_is_running(monkeypatch):
    service = Service(monkeypatch)
    value, _ = updates()
    value.work.acquire()
    try:
        assert value.background_check() is False
    finally:
        value.work.release()
    assert service.calls == []


def test_button_checks_again_downloads_verifies_installs_and_restarts(monkeypatch):
    service = Service(monkeypatch)
    value, events = updates()
    value.background_check()
    seen = []
    value.changed = lambda: seen.append(value.status()['state'])
    assert value.update_now() == {'started': True, 'version': '0.1.0-beta.12'}
    assert service.calls == [('check', 'feed'), ('check', 'feed'), ('stage', 12), ('install', 'b' * 64)]
    assert seen == ['checking', 'downloading', 'ready', 'installing']
    assert events['restart'] == 1


def test_button_finds_the_update_withdrawn_and_hides(monkeypatch):
    service = Service(monkeypatch)
    value, events = updates()
    value.background_check()
    service.release = None
    assert value.update_now()['started'] is False
    assert value.status()['state'] == 'none'
    assert ('stage', 12) not in service.calls and events['restart'] == 0


def test_button_reports_a_signed_out_account_without_downloading(monkeypatch):
    service = Service(monkeypatch)
    value, _ = updates()
    value.background_check()
    monkeypatch.setattr(package_updates, 'check', lambda root, config, cloud: {
        'supported': False, 'available': False, 'current': INSTALLED, 'release': None, 'reason': 'cloud_signed_out'})
    assert value.update_now() == {'started': False, 'result': {'supported': False, 'available': False, 'current': INSTALLED,
                                                               'release': None, 'reason': 'cloud_signed_out'}}
    assert not [call for call in service.calls if call[0] == 'stage']


@pytest.mark.parametrize('stage', ['check', 'stage', 'install'])
def test_button_failure_shows_failed_and_a_retry_succeeds(monkeypatch, stage):
    service = Service(monkeypatch)
    value, events = updates()
    value.background_check()
    message = 'Desktop update could not be verified. Existing application and data were retained.'
    setattr(service, stage + '_error', ValueError(message))
    with pytest.raises(ValueError):
        value.update_now()
    status = value.status()
    assert status['state'] == 'failed' and status['error'] == message
    assert events['restart'] == 0
    # A later quiet check keeps the failure visible until the person retries.
    setattr(service, stage + '_error', None)
    value.background_check()
    assert value.status()['state'] == 'failed'
    assert value.update_now()['started'] is True
    assert events['restart'] == 1


def test_unexpected_failures_show_a_plain_message(monkeypatch):
    service = Service(monkeypatch)
    value, _ = updates()
    service.stage_error = OSError('C:\\Users\\someone\\private path')
    with pytest.raises(OSError):
        value.update_now()
    assert value.status()['error'] == update_schedule.FAILED


def test_one_update_at_a_time(monkeypatch):
    Service(monkeypatch)
    value, _ = updates()
    value.work.acquire()
    try:
        for action in (value.update_now, value.check, value.restart_to_update, lambda: value.download(RELEASE)):
            with pytest.raises(update_schedule.Busy):
                action()
    finally:
        value.work.release()


def test_settings_download_then_restart_share_the_footer_state(monkeypatch):
    service = Service(monkeypatch)
    value, events = updates()
    assert value.check()['available'] is True
    assert value.status()['state'] == 'available'
    with pytest.raises(ValueError, match='Download the update first'):
        value.restart_to_update()
    assert value.download(RELEASE) == {'staged': True, 'version': '0.1.0-beta.12'}
    assert value.status()['state'] == 'ready'
    # A quiet check of the same release keeps the downloaded update ready.
    value.background_check()
    assert value.status()['state'] == 'ready'
    assert value.restart_to_update() == {'started': True}
    assert value.status()['state'] == 'installing' and events['restart'] == 1
    assert service.calls[-1] == ('install', 'b' * 64)


def test_footer_reuses_a_verified_download_for_the_same_release(monkeypatch):
    service = Service(monkeypatch)
    value, _ = updates()
    value.check()
    value.download(RELEASE)
    service.calls.clear()
    assert value.update_now()['started'] is True
    assert service.calls == [('check', 'feed'), ('install', 'b' * 64)]


def test_footer_downloads_again_when_a_newer_release_replaced_the_download(monkeypatch):
    service = Service(monkeypatch)
    value, _ = updates()
    value.check()
    value.download(RELEASE)
    service.release = {**RELEASE, 'build': 13, 'version': '0.1.0-beta.13', 'sha256': 'c' * 64}
    service.calls.clear()
    value.update_now()
    assert service.calls == [('check', 'feed'), ('stage', 13), ('install', 'b' * 64)]


def test_settings_download_failure_is_shared_with_the_footer(monkeypatch):
    service = Service(monkeypatch)
    value, _ = updates()
    value.check()
    service.stage_error = ValueError('Desktop download is incomplete or damaged')
    with pytest.raises(ValueError):
        value.download(RELEASE)
    assert value.status()['state'] == 'failed'
    # Checking again from Settings is a retry: the offer returns.
    value.check()
    assert value.status()['state'] == 'available'


def test_installer_handoff_failure_keeps_saiph_running(monkeypatch):
    service = Service(monkeypatch)
    value, events = updates()
    service.install_error = ValueError('The update installer could not start. Saiph is still running.')
    with pytest.raises(ValueError):
        value.update_now()
    assert value.status()['state'] == 'failed' and events['restart'] == 0


# Bridge: the page reaches this state through app.update.* and the dashboard snapshot.

def bridge(value):
    packets, background = [], []
    snapshot = {'app_version': '0.1.0-beta.11'}
    workspace = SimpleNamespace(dispatch=lambda method, args: dict(snapshot), store=None)
    obj = SimpleNamespace(window=SimpleNamespace(workspace=workspace, pump_jobs=lambda: None),
                          response=SimpleNamespace(emit=lambda packet: packets.append(json.loads(packet))),
                          changed=SimpleNamespace(emit=lambda: None), updates=value,
                          background=lambda request, fn: background.append(fn))
    return obj, packets, background


def test_bridge_routes_the_footer_and_settings_actions(monkeypatch):
    service = Service(monkeypatch)
    value, events = updates()
    obj, packets, background = bridge(value)
    DesktopBridge.request(obj, 'check', 'app.update.check', '{}')
    assert background.pop()()['available'] is True
    DesktopBridge.request(obj, 'now', 'app.update.now', '{}')
    assert background.pop()() == {'started': True, 'version': '0.1.0-beta.12'}
    assert events['restart'] == 1 and service.calls[-1][0] == 'install'


@pytest.mark.parametrize('method,args', [('app.update.now', {'release': RELEASE}), ('app.update.check', {'url': 'https://x.invalid'}),
                                         ('app.update.restart', {'path': 'C:/x.exe'}), ('app.update.download', {})])
def test_bridge_refuses_page_supplied_options(monkeypatch, method, args):
    Service(monkeypatch)
    value, _ = updates()
    obj, packets, background = bridge(value)
    DesktopBridge.request(obj, 'request', method, json.dumps(args))
    assert packets[-1]['ok'] is False and not background


def test_dashboard_snapshot_carries_the_update_state(monkeypatch):
    Service(monkeypatch)
    value, _ = updates()
    value.background_check()
    obj, packets, _ = bridge(value)
    DesktopBridge.request(obj, 'state', 'state', '{}')
    assert packets[-1]['result']['app_update']['state'] == 'available'
    assert packets[-1]['result']['app_update']['version'] == '0.1.0-beta.12'
    assert packets[-1]['result']['app_version'] == '0.1.0-beta.11'
