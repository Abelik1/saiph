# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phones this computer may debug over USB or Android wireless debugging.

The phone camera uses this when the phone is not reachable through a self-hosted
Hub, for example with Saiph Hosted. It needs no Hub, Saiph pairing or Tailscale:
Android itself asks the phone's owner to allow this computer (the USB debugging
prompt, or a one-time wireless debugging pairing code). Listing, pairing and
connecting never start anything on the phone; capture starts only from an
explicit local camera action.
"""
from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import re
import subprocess

from .companion_tools import tool_path

SERIAL = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:\[\]-]{0,199}')
_MODEL = re.compile(r'[^A-Za-z0-9 ._-]')
_STATES = {'device': 'ready', 'unauthorized': 'unauthorized', 'offline': 'offline',
           'authorizing': 'unauthorized', 'no': 'no_permission'}


def adb_path(scrcpy=None):
    """Standard/SDK/portable adb first, else the adb shipped beside scrcpy.

    scrcpy's Windows and Linux release archives include adb next to the scrcpy
    executable, so a user who only unpacked scrcpy still has a working adb."""
    found = tool_path('adb')
    if found:
        return found
    if scrcpy:
        beside = Path(scrcpy).parent / ('adb.exe' if os.name == 'nt' else 'adb')
        if beside.is_file():
            return str(beside)
    return None


def connection_kind(serial):
    if '._adb-tls-connect._tcp' in serial or '._adb._tcp' in serial or re.fullmatch(r'.+:[0-9]{1,5}', serial):
        return 'wifi'
    return 'usb'


def parse_devices(output):
    """Parse `adb devices -l`. Unknown or malformed lines are ignored."""
    rows = []
    for line in (output or '').splitlines()[1:]:
        fields = line.split()
        if len(fields) < 2 or not SERIAL.fullmatch(fields[0]) or fields[1] not in _STATES:
            continue
        details = dict(field.split(':', 1) for field in fields[2:] if ':' in field)
        model = _MODEL.sub('', details.get('model', '').replace('_', ' '))[:60].strip()
        rows.append({'serial': fields[0], 'state': _STATES[fields[1]], 'model': model or 'Android phone',
                     'connection': connection_kind(fields[0])})
    return rows[:20]


def lan_address(value):
    """Return host:port for a phone on the local network, or raise ValueError.

    Only private or link-local addresses are accepted: wireless debugging is meant
    for a phone on the same Wi-Fi, never a host on the internet."""
    message = ('Enter the IP address and port shown on your phone under Wireless debugging, '
               'for example 192.168.1.20:37123.')
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError(message)
    text = value.strip()
    match = re.fullmatch(r'\[([0-9A-Fa-f:.%a-zA-Z0-9]+)\]:([0-9]{1,5})|([0-9.]+):([0-9]{1,5})', text)
    if not match:
        raise ValueError(message)
    host, port = (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
    try:
        address = ipaddress.ip_address(host.split('%', 1)[0])
    except ValueError:
        raise ValueError(message) from None
    if not 0 < int(port) < 65536:
        raise ValueError(message)
    if address.is_loopback or address.is_unspecified or address.is_multicast or not (address.is_private or address.is_link_local):
        raise ValueError('Use the address of a phone on your own Wi-Fi network (it usually starts with 192.168, 10 or 172).')
    return f'[{host}]:{int(port)}' if address.version == 6 else f'{address}:{int(port)}'


def pairing_code(value):
    code = re.sub(r'\s', '', value) if isinstance(value, str) else ''
    if not re.fullmatch(r'[0-9]{6}', code):
        raise ValueError('Enter the six-digit Wi-Fi pairing code shown on your phone.')
    return code


class PhoneDebugging:
    def __init__(self, adb, run=subprocess.run):
        self.adb, self.run = adb, run

    def _adb(self, *args, timeout=10):
        if not self.adb:
            raise ValueError('adb was not found. Install scrcpy (it includes adb), then try again.')
        try:
            result = self.run([self.adb, *args], capture_output=True, text=True, timeout=timeout,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        except (OSError, subprocess.SubprocessError):
            raise ValueError('adb did not respond. Try again, or restart the phone and computer.') from None
        return result.returncode, (result.stdout or '') + (result.stderr or '')

    def devices(self):
        if not self.adb:
            return []
        code, output = self._adb('devices', '-l')
        return parse_devices(output) if code == 0 else []

    def ready(self, serial):
        """Return the listed phone only when it has allowed this computer."""
        if not isinstance(serial, str) or not SERIAL.fullmatch(serial):
            raise ValueError('Choose a phone from the list.')
        row = next((row for row in self.devices() if row['serial'] == serial), None)
        if row is None:
            raise ValueError('That phone is no longer connected. Reconnect it, then choose Find my phone again.')
        if row['state'] == 'unauthorized':
            raise ValueError('Unlock your phone and tap Allow on the debugging prompt, then try again.')
        if row['state'] == 'no_permission':
            raise ValueError('This computer may not use the phone over USB yet. On Linux, install your '
                             "distribution's android-udev rules, reconnect the cable and try again.")
        if row['state'] != 'ready':
            raise ValueError('The phone is offline for debugging. Unlock it, reconnect and try again.')
        return row

    def pair(self, address, code):
        address, code = lan_address(address), pairing_code(code)
        status, output = self._adb('pair', address, code, timeout=30)
        if status != 0 or 'successfully paired' not in output.lower():
            raise ValueError('Pairing did not work. Check that the phone and this computer are on the same Wi-Fi. '
                             'The code and address change each time you open “Pair device with pairing code”, '
                             'so use the ones on the phone now.')
        return {'paired': True}

    def connect(self, address):
        address = lan_address(address)
        status, output = self._adb('connect', address, timeout=20)
        text = output.lower()
        if status != 0 or not re.search(r'\bconnected to\b', text) or re.search(r'fail|cannot|unable', text):
            raise ValueError('Could not connect. Use the IP address and port at the top of the Wireless debugging '
                             'screen (not the pairing port), and pair this computer first if you have not.')
        return {'connected': True, 'serial': address}
