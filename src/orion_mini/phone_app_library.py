# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone app tiles on this computer: icons from the phone, pins and local open counts.

Icons come only from the phone, over the sealed Saiph Cloud events in
`hosted_features.py` (`apps.icons.request` / `apps.icons`), and only as small
static PNG or WebP images. Every image is checked here before it is stored or
shown: format signature, exact container size, no animation, and 16-128 pixel
sides read from the image header. They are cached by package and app version,
so a phone sends an icon again only after that app updates.

"Most used" counts how often this computer opened each app, kept locally per
phone. Saiph on Android does not hold the usage-access permission, so the phone
contributes no usage history.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import threading
import time
from pathlib import Path

from . import session_offer

ICON_MAX_BYTES = 12_000
ICON_MIN_SIDE, ICON_MAX_SIDE = 16, 128
MAX_ICON_REQUEST = 24
MAX_VERSION = (1 << 53) - 1
MAX_CACHED_ICONS = 600
MAX_PINNED = 24
MAX_COUNTED = 400
MAX_DEVICES = 8
CHECK_SECONDS = 6 * 3600  # Ask the phone again whether an app's icon changed at most this often.
ASK_SECONDS = 20  # An unanswered icon request is repeated after this long.
_PNG = b'\x89PNG\r\n\x1a\n'


def icon_format(data) -> tuple[str, int, int]:
    """('png' | 'webp', width, height) of one small static icon; ValueError for anything else."""
    if type(data) is not bytes or not 26 <= len(data) <= ICON_MAX_BYTES:
        raise ValueError('Invalid app icon.')
    if data.startswith(_PNG):
        if data[12:16] != b'IHDR' or struct.unpack('>I', data[8:12])[0] != 13 or not data.endswith(b'IEND\xaeB`\x82'):
            raise ValueError('Invalid app icon.')
        if b'acTL' in data:  # Animated PNG.
            raise ValueError('Invalid app icon.')
        kind, (width, height) = 'png', struct.unpack('>II', data[16:24])
    elif data[:4] == b'RIFF' and data[8:12] == b'WEBP' and len(data) >= 30:
        if struct.unpack('<I', data[4:8])[0] != len(data) - 8:
            raise ValueError('Invalid app icon.')
        chunk = data[12:16]
        if chunk == b'VP8 ':
            if data[23:26] != b'\x9d\x01\x2a':
                raise ValueError('Invalid app icon.')
            width, height = (v & 0x3FFF for v in struct.unpack('<HH', data[26:30]))
        elif chunk == b'VP8L':
            if data[20] != 0x2F:
                raise ValueError('Invalid app icon.')
            bits = int.from_bytes(data[21:25], 'little')
            width, height = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        elif chunk == b'VP8X':
            if data[20] & 0x02:  # Animation flag.
                raise ValueError('Invalid app icon.')
            width, height = int.from_bytes(data[24:27], 'little') + 1, int.from_bytes(data[27:30], 'little') + 1
        else:
            raise ValueError('Invalid app icon.')
        kind = 'webp'
    else:
        raise ValueError('Invalid app icon.')
    if not (ICON_MIN_SIDE <= width <= ICON_MAX_SIDE and ICON_MIN_SIDE <= height <= ICON_MAX_SIDE):
        raise ValueError('Invalid app icon.')
    return kind, width, height


def data_uri(data: bytes) -> str:
    kind = icon_format(data)[0]
    return f'data:image/{kind};base64,' + base64.b64encode(data).decode('ascii')


def _version(value) -> int:
    if type(value) is not int or not 0 <= value <= MAX_VERSION:
        raise ValueError('Invalid app version.')
    return value


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, separators=(',', ':')), encoding='utf-8')
    os.replace(temporary, path)


class IconCache:
    """Icons by package and app version, on disk under the profile (or in memory without one)."""

    def __init__(self, root: Path | None, clock=time.time):
        self.folder = Path(root) / 'phone-app-icons' if root is not None else None
        self.clock = clock
        self.lock = threading.RLock()
        self.index = None  # package -> {"version", "file", "used"}
        self.memory = {}  # file -> bytes (and the whole cache when there is no folder)
        self.uris = {}

    def _load(self):
        if self.index is not None:
            return
        self.index = {}
        if self.folder is None:
            return
        try:
            raw = json.loads((self.folder / 'index.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        if type(raw) is not dict:
            return
        for package, row in list(raw.items())[:MAX_CACHED_ICONS]:
            if (session_offer.valid_package(package) and type(row) is dict and set(row) == {'version', 'file', 'used'}
                    and type(row['version']) is int and 0 <= row['version'] <= MAX_VERSION
                    and type(row['file']) is str and row['file'] == self._name(package, row['version'], row['file'][-4:])
                    and type(row['used']) in (int, float)):
                self.index[package] = row

    @staticmethod
    def _name(package, version, suffix):
        if suffix not in ('.png', 'webp'):
            return ''
        return hashlib.sha256(f'{package}:{version}'.encode()).hexdigest()[:32] + ('.png' if suffix == '.png' else '.webp')

    def _save(self):
        if self.folder is not None:
            try:
                _write_json(self.folder / 'index.json', self.index)
            except OSError:
                pass

    def store(self, package, version, data) -> None:
        if not session_offer.valid_package(package):
            raise ValueError('Invalid app icon.')
        kind = icon_format(data)[0]
        version = _version(version)
        name = self._name(package, version, '.png' if kind == 'png' else 'webp')
        with self.lock:
            self._load()
            previous = self.index.get(package)
            if previous and previous['file'] != name:
                self._forget(previous['file'])
            if self.folder is not None:
                try:
                    self.folder.mkdir(parents=True, exist_ok=True)
                    (self.folder / name).write_bytes(data)
                except OSError:
                    self.memory[name] = data
            else:
                self.memory[name] = data
            self.index[package] = {'version': version, 'file': name, 'used': self.clock()}
            self.uris.pop(name, None)
            while len(self.index) > MAX_CACHED_ICONS:
                oldest = min(self.index, key=lambda key: self.index[key]['used'])
                self._forget(self.index.pop(oldest)['file'])
            self._save()

    def _forget(self, name):
        self.memory.pop(name, None)
        self.uris.pop(name, None)
        if self.folder is not None:
            try:
                (self.folder / name).unlink()
            except OSError:
                pass

    def version(self, package):
        with self.lock:
            self._load()
            row = self.index.get(package)
            return row['version'] if row else None

    def uri(self, package):
        """The cached icon as a data URI, re-validated when read from disk; None when absent."""
        with self.lock:
            self._load()
            row = self.index.get(package)
            if row is None:
                return None
            name = row['file']
            if name in self.uris:
                return self.uris[name]
            data = self.memory.get(name)
            if data is None and self.folder is not None:
                try:
                    data = (self.folder / name).read_bytes()
                except OSError:
                    data = None
            try:
                value = data_uri(data)
            except ValueError:
                self.index.pop(package, None)
                self._forget(name)
                self._save()
                return None
            row['used'] = self.clock()
            self.uris[name] = value
            if len(self.uris) > MAX_CACHED_ICONS:
                self.uris.pop(next(iter(self.uris)))
            return value


class AppPreferences:
    """Pinned apps and local open counts per phone, in `phone-apps.json`."""

    def __init__(self, root: Path | None, clock=time.time):
        self.path = Path(root) / 'phone-apps.json' if root is not None else None
        self.clock = clock
        self.lock = threading.RLock()
        self.devices = None

    @staticmethod
    def _device(device_id):
        if type(device_id) is not str or not 0 < len(device_id) <= 64 or not device_id.isprintable():
            raise ValueError('Choose a phone.')
        return device_id

    def _load(self):
        if self.devices is not None:
            return
        self.devices = {}
        if self.path is None:
            return
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        rows = raw.get('devices') if type(raw) is dict and raw.get('version') == 1 else None
        if type(rows) is not dict:
            return
        for device, row in list(rows.items())[:MAX_DEVICES]:
            try:
                self._device(device)
            except ValueError:
                continue
            if type(row) is not dict:
                continue
            pinned = [p for p in row.get('pinned', []) if session_offer.valid_package(p)][:MAX_PINNED] if type(row.get('pinned')) is list else []
            opens = {}
            if type(row.get('opens')) is dict:
                for package, value in list(row['opens'].items())[:MAX_COUNTED]:
                    if (session_offer.valid_package(package) and type(value) is list and len(value) == 2
                            and type(value[0]) is int and 0 < value[0] <= 1_000_000 and type(value[1]) in (int, float)):
                        opens[package] = value
            self.devices[device] = {'pinned': list(dict.fromkeys(pinned)), 'opens': opens}

    def _save(self):
        if self.path is not None:
            try:
                _write_json(self.path, {'version': 1, 'devices': self.devices})
            except OSError:
                pass

    def _row(self, device_id):
        self._load()
        device = self._device(device_id)
        if device not in self.devices:
            if len(self.devices) >= MAX_DEVICES:
                stale = min(self.devices, key=lambda key: max([v[1] for v in self.devices[key]['opens'].values()] or [0]))
                self.devices.pop(stale)
            self.devices[device] = {'pinned': [], 'opens': {}}
        return self.devices[device]

    def view(self, device_id) -> dict:
        with self.lock:
            self._load()
            row = self.devices.get(self._device(device_id)) or {'pinned': [], 'opens': {}}
            return {'pinned': list(row['pinned']), 'usage': {package: value[0] for package, value in row['opens'].items()},
                    'recent': {package: value[1] for package, value in row['opens'].items()}}

    def pin(self, device_id, package, pinned) -> dict:
        if not session_offer.valid_package(package) or type(pinned) is not bool:
            raise ValueError('Choose an app from the list.')
        with self.lock:
            row = self._row(device_id)
            rows = [p for p in row['pinned'] if p != package]
            if pinned:
                if len(rows) >= MAX_PINNED:
                    raise ValueError(f'You can pin up to {MAX_PINNED} apps. Unpin one first.')
                rows.append(package)
            row['pinned'] = rows
            self._save()
            return {'pinned': list(rows)}

    def opened(self, device_id, package) -> None:
        if not session_offer.valid_package(package):
            return
        with self.lock:
            row = self._row(device_id)
            count = row['opens'].get(package, [0, 0])[0]
            row['opens'][package] = [min(count + 1, 1_000_000), round(self.clock())]
            while len(row['opens']) > MAX_COUNTED:
                least = min(row['opens'], key=lambda key: (row['opens'][key][0], row['opens'][key][1]))
                row['opens'].pop(least)
            self._save()


class AppLibrary:
    """Icons, pins and counts for the Apps grid; icon requests go to the phone through `controller`."""

    def __init__(self, root: Path | None, clock=time.time):
        self.clock = clock
        self.icons = IconCache(root, clock)
        self.preferences = AppPreferences(root, clock)
        self.lock = threading.Lock()
        self.checked = {}  # (device, package) -> when the phone last confirmed or sent this icon
        self.asked = {}  # (device, package) -> when this computer last asked

    def receive(self, device_id, icons, same) -> None:
        now = self.clock()
        for package, version, data in icons:
            try:
                self.icons.store(package, version, data)
            except ValueError:
                continue
            with self.lock:
                self.checked[(device_id, package)] = now
        with self.lock:
            for package in same:
                self.checked[(device_id, package)] = now

    def lookup(self, device_id, packages, request=None) -> dict:
        """Cached icons now; asks the phone (through `request(rows)`) for missing or unchecked ones."""
        if (type(packages) is not list or not 0 < len(packages) <= 60 or len(set(map(str, packages))) != len(packages)
                or not all(session_offer.valid_package(p) for p in packages)):
            raise ValueError('Choose apps from the list.')
        now = self.clock()
        result, ask, pending = {}, [], []
        for package in packages:
            uri = self.icons.uri(package)
            if uri is not None:
                result[package] = uri
            if request is None:
                continue
            key = (device_id, package)
            with self.lock:
                fresh = now - self.checked.get(key, -CHECK_SECONDS) < CHECK_SECONDS
                waiting = now - self.asked.get(key, -ASK_SECONDS) < ASK_SECONDS
            if not fresh and not waiting and len(ask) < MAX_ICON_REQUEST:
                ask.append({'package': package, 'version': self.icons.version(package) or 0})
            if uri is None and not fresh:
                pending.append(package)
        if ask:
            try:
                request(ask)
            except (ValueError, OSError):
                ask = []
            with self.lock:
                for row in ask:
                    self.asked[(device_id, row['package'])] = now
        return {'icons': result, 'pending': pending}
