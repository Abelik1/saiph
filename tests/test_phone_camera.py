# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone camera without a self-hosted Hub: USB or wireless debugging only.

Synthetic serials, addresses and tool output; no real adb, scrcpy or phone."""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from orion_mini import camera as camera_module
from orion_mini import phone_debugging
from orion_mini.camera import Camera
from orion_mini.phone_debugging import PhoneDebugging, lan_address, pairing_code, parse_devices

DEVICES = """List of devices attached
SYNTHUSB01             device usb:1-2 product:synth model:Synthetic_Phone_8 device:synth transport_id:1
192.168.50.20:41234    device product:synth model:Wifi_Phone device:synth transport_id:2
adb-SYNTH02-AbCdEf._adb-tls-connect._tcp device product:synth model:Mdns_Phone transport_id:3
SYNTHLOCKED            unauthorized usb:1-3 transport_id:4
SYNTHNOPERM            no permissions (missing udev rules? user is in the plugdev group); see [http://developer.android.com/tools/device.html] usb:1-4
SYNTHOFF               offline transport_id:5
bad;serial             device model:Injected
* daemon started successfully
"""


class Result(SimpleNamespace):
    pass


class FakeAdb:
    """Records every argv; answers like adb/scrcpy/tasklist would."""
    def __init__(self, devices=DEVICES, sdk='33', version='scrcpy 3.3.4 <https://github.com/Genymobile/scrcpy>',
                 pair='Successfully paired to 192.168.50.20:37000 [guid=adb-SYNTH]', connect='connected to 192.168.50.20:41234'):
        self.calls = []
        self.devices, self.sdk, self.version, self.pair, self.connect = devices, sdk, version, pair, connect

    def __call__(self, argv, **options):
        assert isinstance(argv, list) and 'shell' not in options  # Never through a command shell.
        self.calls.append(argv)
        if argv[1:] == ['--version']:
            return Result(returncode=0, stdout=self.version, stderr='')
        if argv[1:] == ['devices', '-l']:
            return Result(returncode=0, stdout=self.devices, stderr='')
        if argv[-2:] == ['getprop', 'ro.build.version.sdk']:
            return Result(returncode=0, stdout=self.sdk + '\n', stderr='')
        if argv[1] == 'pair':
            return Result(returncode=0 if 'Successfully' in self.pair else 1, stdout=self.pair, stderr='')
        if argv[1] == 'connect':
            return Result(returncode=0, stdout=self.connect, stderr='')
        if argv[0] == 'tasklist':
            return Result(returncode=0, stdout='INFO: No tasks are running.', stderr='')
        raise AssertionError(argv)


class Process:
    def __init__(self, argv, **options):
        self.argv, self.options, self.code = argv, options, None

    def poll(self):
        return self.code

    def terminate(self):
        self.code = 0

    def kill(self):
        self.code = -9

    def wait(self, timeout=None):
        return self.code


@pytest.fixture
def tools(tmp_path, monkeypatch):
    """A scrcpy release folder with adb beside it, as the upstream archives ship."""
    folder = tmp_path / 'scrcpy-release'
    folder.mkdir()
    scrcpy = folder / ('scrcpy.exe' if os.name == 'nt' else 'scrcpy')
    adb = folder / ('adb.exe' if os.name == 'nt' else 'adb')
    for path in (scrcpy, adb):
        path.write_bytes(b'synthetic executable')
    found = {'scrcpy': str(scrcpy), 'adb': None}
    monkeypatch.setattr(camera_module, 'tool_path', lambda name, configured=None: found[name])
    monkeypatch.setattr(phone_debugging, 'tool_path', lambda name, configured=None: found[name])
    return SimpleNamespace(scrcpy=str(scrcpy), adb=str(adb))


def hosted_workspace(**camera):
    """Saiph Cloud / no Hub: the self-hosted phone roster is empty."""
    return SimpleNamespace(settings={'link': {'camera': {'enabled': True, **camera}}},
                           phone=SimpleNamespace(snapshot=lambda: {'devices': [], 'status': 'Unpaired'}))


def make_camera(workspace, run, system='linux', sink=True):
    started = []

    def popen(argv, **options):
        started.append(Process(argv, **options))
        return started[-1]
    def no_hub_worker():
        raise AssertionError('A Hub-less camera must not need Saiph pairing.')
    instance = Camera(workspace, system=system, popen=popen, run=run, worker_factory=no_hub_worker,
                      verify_sink=lambda path: sink and path == '/dev/video10')
    return instance, started


def test_parse_devices_reports_usb_wifi_and_consent_states_and_ignores_malformed_lines():
    rows = parse_devices(DEVICES)
    assert rows == [
        {'serial': 'SYNTHUSB01', 'state': 'ready', 'model': 'Synthetic Phone 8', 'connection': 'usb'},
        {'serial': '192.168.50.20:41234', 'state': 'ready', 'model': 'Wifi Phone', 'connection': 'wifi'},
        {'serial': 'adb-SYNTH02-AbCdEf._adb-tls-connect._tcp', 'state': 'ready', 'model': 'Mdns Phone', 'connection': 'wifi'},
        {'serial': 'SYNTHLOCKED', 'state': 'unauthorized', 'model': 'Android phone', 'connection': 'usb'},
        {'serial': 'SYNTHNOPERM', 'state': 'no_permission', 'model': 'Android phone', 'connection': 'usb'},
        {'serial': 'SYNTHOFF', 'state': 'offline', 'model': 'Android phone', 'connection': 'usb'},
    ]
    assert parse_devices('') == [] and parse_devices(None) == []


@pytest.mark.parametrize('value,expected', [
    ('192.168.1.20:37123', '192.168.1.20:37123'), (' 10.0.0.7:5555 ', '10.0.0.7:5555'),
    ('172.20.1.2:40000', '172.20.1.2:40000'), ('[fe80::1]:5555', '[fe80::1]:5555'),
])
def test_wireless_debugging_accepts_local_network_addresses(value, expected):
    assert lan_address(value) == expected


@pytest.mark.parametrize('value', ['8.8.8.8:5555', '127.0.0.1:5555', '0.0.0.0:5555', 'phone.example.invalid:5555',
                                   '192.168.1.20', '192.168.1.20:0', '192.168.1.20:70000', '192.168.1.20:5555;calc',
                                   '-s 192.168.1.20:5555', None, 5555, '1' * 80])
def test_wireless_debugging_refuses_internet_loopback_and_malformed_addresses(value):
    with pytest.raises(ValueError):
        lan_address(value)


def test_pairing_code_is_exactly_six_digits():
    assert pairing_code('123 456') == '123456'
    for value in ('12345', '1234567', 'abcdef', None, 123456):
        with pytest.raises(ValueError, match='six-digit'):
            pairing_code(value)


def test_pair_and_connect_run_fixed_adb_commands_and_report_failures_plainly():
    run = FakeAdb()
    debugging = PhoneDebugging('synthetic-adb', run=run)
    assert debugging.pair('192.168.50.20:37000', '123456') == {'paired': True}
    assert debugging.connect('192.168.50.20:41234') == {'connected': True, 'serial': '192.168.50.20:41234'}
    assert run.calls == [['synthetic-adb', 'pair', '192.168.50.20:37000', '123456'],
                         ['synthetic-adb', 'connect', '192.168.50.20:41234']]
    with pytest.raises(ValueError, match='same Wi-Fi'):
        PhoneDebugging('synthetic-adb', run=FakeAdb(pair='Failed: Unable to start pairing client.')).pair('192.168.50.20:37000', '123456')
    for answer in ('failed to connect to 192.168.50.20:41234', 'failed to authenticate to 192.168.50.20:41234',
                   'cannot connect to 192.168.50.20:41234: No route to host'):
        with pytest.raises(ValueError, match='Wireless debugging'):
            PhoneDebugging('synthetic-adb', run=FakeAdb(connect=answer)).connect('192.168.50.20:41234')
    with pytest.raises(ValueError, match='Install scrcpy'):
        PhoneDebugging(None).pair('192.168.50.20:37000', '123456')


def test_hosted_user_starts_the_camera_over_usb_without_a_hub_or_saiph_pairing(tools):
    run = FakeAdb()
    workspace = hosted_workspace(v4l2_sink='/dev/video10', facing='back')
    instance, started = make_camera(workspace, run)
    assert instance.status()['available'] is True
    listed = instance.debug_devices()
    assert listed['adb'] is True and [row['serial'] for row in listed['devices']][:3] == [
        'SYNTHUSB01', '192.168.50.20:41234', 'adb-SYNTH02-AbCdEf._adb-tls-connect._tcp']
    assert started == []  # Listing never starts capture.
    status = instance.start(serial='SYNTHUSB01')
    assert status['running'] is True and status['serial'] == 'SYNTHUSB01' and status['device_id'] is None
    (process,) = started
    assert process.argv[:3] == [tools.scrcpy, '--serial', 'SYNTHUSB01']
    assert '--video-source=camera' in process.argv and '--camera-facing=back' in process.argv
    assert process.argv[-2:] == ['--v4l2-sink=/dev/video10', '--no-playback']
    assert process.options['env']['ADB'] == tools.adb  # adb shipped beside scrcpy.
    instance._check_session()  # No Hub roster: the session must not stop for that.
    assert instance.status()['running'] is True
    with pytest.raises(ValueError, match='Stop the current'):
        instance.start(serial='192.168.50.20:41234')
    assert instance.stop() == {'stopped': True} and process.code == 0
    assert instance.status()['running'] is False


def test_wireless_phone_starts_and_a_crashed_session_explains_what_to_do(tools):
    instance, started = make_camera(hosted_workspace(v4l2_sink='/dev/video10'), FakeAdb())
    instance.start(serial='192.168.50.20:41234')
    started[0].code = 1
    instance._check_session()
    status = instance.status()
    assert status['running'] is False and 'connected and unlocked' in status['message']


@pytest.mark.parametrize('serial,message', [
    ('SYNTHLOCKED', 'tap Allow'), ('SYNTHNOPERM', 'udev'), ('SYNTHOFF', 'offline'),
    ('SYNTHGONE', 'no longer connected'), ('bad;serial', 'Choose a phone'),
])
def test_camera_refuses_phones_that_have_not_allowed_this_computer(tools, serial, message):
    instance, started = make_camera(hosted_workspace(v4l2_sink='/dev/video10'), FakeAdb())
    with pytest.raises(ValueError, match=message):
        instance.start(serial=serial)
    assert started == []


def test_camera_needs_android_12_and_a_camera_capable_scrcpy(tools):
    instance, started = make_camera(hosted_workspace(v4l2_sink='/dev/video10'), FakeAdb(sdk='30'))
    with pytest.raises(ValueError, match='Android 12'):
        instance.start(serial='SYNTHUSB01')
    old, _ = make_camera(hosted_workspace(v4l2_sink='/dev/video10'), FakeAdb(version='scrcpy 1.25 <https://github.com/Genymobile/scrcpy>'))
    status = old.status()
    assert status['available'] is False and status['can_preview'] is False and '2.2 or later' in status['message']
    with pytest.raises(ValueError, match='2.2 or later'):
        old.start(serial='SYNTHUSB01')
    assert started == []


def test_start_requires_exactly_one_phone_and_respects_the_off_switch(tools):
    instance, started = make_camera(hosted_workspace(v4l2_sink='/dev/video10'), FakeAdb())
    for arguments in ({}, {'device_id': 'phone', 'serial': 'SYNTHUSB01'}):
        with pytest.raises(ValueError, match='one phone'):
            instance.start(**arguments)
    with pytest.raises(ValueError):
        instance.start(serial='SYNTHUSB01', preview='yes')
    off, _ = make_camera(hosted_workspace(v4l2_sink='/dev/video10', enabled=False), FakeAdb())
    with pytest.raises(ValueError, match='switched off'):
        off.start(serial='SYNTHUSB01')
    assert started == []


def test_windows_preview_opens_only_the_scrcpy_window_for_obs_setup(tools):
    """Before OBS is configured there is no camera window to choose in OBS; the preview provides it."""
    run = FakeAdb()
    instance, started = make_camera(hosted_workspace(), run, system='win32')
    status = instance.status()
    assert status['available'] is False and status['can_preview'] is True
    with pytest.raises(ValueError, match='one-time phone camera setup'):
        instance.start(serial='SYNTHUSB01')
    status = instance.start(serial='SYNTHUSB01', preview=True)
    assert status['running'] is True and status['mode'] == 'preview' and 'preview window' in status['message']
    (process,) = started
    assert process.argv[-2:] == ['--window-title', camera_module.WINDOW_TITLE]
    assert not any('obs' in str(part).lower() for part in process.argv)
    assert not any(call[0] == 'tasklist' for call in run.calls)  # OBS is not involved in a preview.
    instance.stop()


def test_self_hosted_paired_phone_path_is_unchanged(tools):
    run = FakeAdb()

    class Worker:
        adb = None

        def paired_serial(self, device_id):
            assert device_id == 'synthetic-device'
            return 'SYNTHUSB01'
    workspace = SimpleNamespace(settings={'link': {'camera': {'enabled': True, 'v4l2_sink': '/dev/video10'}}},
                                phone=SimpleNamespace(snapshot=lambda: {'devices': [{'id': 'synthetic-device', 'online': True}]}))
    started = []
    instance = Camera(workspace, system='linux', popen=lambda argv, **options: started.append(Process(argv, **options)) or started[-1],
                      run=run, worker_factory=Worker, verify_sink=lambda path: True)
    status = instance.start('synthetic-device')
    assert status['device_id'] == 'synthetic-device' and started[0].argv[:3] == [tools.scrcpy, '--serial', 'SYNTHUSB01']
    assert started[0].options['env']['ADB'] == tools.adb  # Worker without adb falls back to scrcpy's adb.
    workspace.phone = SimpleNamespace(snapshot=lambda: {'devices': [{'id': 'synthetic-device', 'online': False}]})
    instance._check_session()
    assert instance.status()['running'] is False and 'online and paired' in instance.status()['message']


def test_desktop_bridge_accepts_one_phone_and_runs_debugging_actions_off_the_ui_thread():
    pytest.importorskip('PySide6')
    import json
    from orion_mini.desktop_bridge import DesktopBridge
    calls, packets, background = [], [], []
    fake = SimpleNamespace(start=lambda *args: calls.append(('start', args)), debug_devices=lambda: calls.append(('devices',)),
                           pair=lambda *args: calls.append(('pair', args)), connect=lambda *args: calls.append(('connect', args)))
    obj = SimpleNamespace(window=SimpleNamespace(workspace=SimpleNamespace(camera=fake), pump_jobs=lambda: None),
                          response=SimpleNamespace(emit=lambda value: packets.append(json.loads(value))),
                          changed=SimpleNamespace(emit=lambda: None), background=lambda request, fn: background.append(fn))
    for method, args in [('camera.start', {'serial': 'SYNTHUSB01'}), ('camera.start', {'device_id': 'phone', 'preview': True}),
                         ('camera.devices', {}), ('camera.pair', {'address': '192.168.50.20:37000', 'code': '123456'}),
                         ('camera.connect', {'address': '192.168.50.20:41234'})]:
        DesktopBridge.request(obj, 'request', method, json.dumps(args))
    assert not packets and len(background) == 5
    for job in background:
        job()
    assert calls == [('start', (None, 'SYNTHUSB01', False)), ('start', ('phone', None, True)), ('devices',),
                     ('pair', ('192.168.50.20:37000', '123456')), ('connect', ('192.168.50.20:41234',))]
    background.clear()
    for method, args in [('camera.start', {}), ('camera.start', {'serial': 'A', 'device_id': 'B'}),
                         ('camera.start', {'serial': 'A', 'preview': 'yes'}), ('camera.start', {'serial': 'A', 'command': 'x'}),
                         ('camera.devices', {'adb': 'C:/other.exe'}), ('camera.connect', {'address': 'x', 'adb': 'y'})]:
        DesktopBridge.request(obj, 'request', method, json.dumps(args))
    assert not background and len(packets) == 6 and all(packet['ok'] is False for packet in packets)
