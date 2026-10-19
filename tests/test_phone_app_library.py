# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apps grid data: phone app icons (validation, cache, sealed protocol), pins and open counts.

Synthetic images and the in-memory Hosted relay only (docs/PHONE_SCREEN.md)."""
import base64
import json
import struct
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage, QImageWriter

from orion_mini.hosted_features import FeatureError, apps_icons_request_payload, read_apps_icons
from orion_mini.phone_app_library import (ICON_MAX_BYTES, MAX_PINNED, AppLibrary, AppPreferences, IconCache, data_uri,
                                          icon_format)
from orion_mini.phone_screen import PhoneScreen
from orion_mini.screen_session import ScreenSession
from test_hosted_phone import hosted  # noqa: F401  (fixture)
from test_phone_screen import advertise


def encoded(kind='PNG', side=96, quality=-1):
    image = QImage(side, side, QImage.Format.Format_ARGB32)
    image.fill(0xFF3366CC)
    output = QBuffer()
    output.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(output, kind, quality)
    return bytes(output.data())


def webp_header(chunk, body):
    payload = b'WEBP' + chunk + struct.pack('<I', len(body)) + body
    return b'RIFF' + struct.pack('<I', len(payload)) + payload


def vp8x(width, height, flags=0):
    body = bytes([flags, 0, 0, 0]) + (width - 1).to_bytes(3, 'little') + (height - 1).to_bytes(3, 'little')
    return webp_header(b'VP8X', body + bytes(8))


# ------------------------------------------------------------------ validation
def test_png_icons_are_read_from_their_header():
    assert icon_format(encoded('PNG', 96)) == ('png', 96, 96)
    assert data_uri(encoded('PNG', 48)).startswith('data:image/png;base64,')


@pytest.mark.skipif(b'webp' not in [bytes(f) for f in QImageWriter.supportedImageFormats()], reason='Qt WebP writer absent')
def test_webp_icons_are_read_from_their_header():
    assert icon_format(encoded('WEBP', 96, 80)) == ('webp', 96, 96)


def test_crafted_webp_containers_are_checked():
    assert icon_format(vp8x(64, 64)) == ('webp', 64, 64)
    for bad in [vp8x(64, 64, flags=0x02),  # animated
                vp8x(256, 64), vp8x(8, 8),  # too large / too small
                vp8x(64, 64)[:-1],  # RIFF size disagrees with the data
                webp_header(b'ALPH', bytes(20))]:
        with pytest.raises(ValueError):
            icon_format(bad)


def test_icons_must_be_small_static_images():
    png = encoded('PNG', 96)
    for bad in [b'', b'GIF89a' + bytes(40), png[:-12], encoded('PNG', 256), encoded('PNG', 8),
                png[:-12] + b'acTL' + png[-12:], encoded('JPEG', 96), bytes(ICON_MAX_BYTES + 1), 'text']:
        with pytest.raises(ValueError):
            icon_format(bad)


# ------------------------------------------------------------------ cache
def test_icon_cache_is_keyed_by_package_and_version(tmp_path):
    cache = IconCache(tmp_path)
    first, second = encoded('PNG', 96), encoded('PNG', 64)
    cache.store('com.example.mail', 7, first)
    assert cache.version('com.example.mail') == 7 and cache.uri('com.example.mail') == data_uri(first)
    cache.store('com.example.mail', 8, second)
    files = sorted(p.name for p in (tmp_path / 'phone-app-icons').iterdir())
    assert len(files) == 2 and 'index.json' in files  # The old version's file is gone.
    reopened = IconCache(tmp_path)
    assert reopened.version('com.example.mail') == 8 and reopened.uri('com.example.mail') == data_uri(second)
    with pytest.raises(ValueError):
        cache.store('not a package', 1, first)
    with pytest.raises(ValueError):
        cache.store('com.example.mail', -1, first)


def test_a_tampered_cached_icon_is_dropped(tmp_path):
    cache = IconCache(tmp_path)
    cache.store('com.example.mail', 1, encoded('PNG', 96))
    [name] = [p for p in (tmp_path / 'phone-app-icons').iterdir() if p.suffix == '.png']
    name.write_bytes(b'<svg onload=alert(1)>')
    assert IconCache(tmp_path).uri('com.example.mail') is None


def test_library_asks_only_for_missing_or_unchecked_icons():
    clock = SimpleNamespace(now=1000.0)
    library = AppLibrary(None, clock=lambda: clock.now)
    asked = []
    result = library.lookup('phone', ['com.example.a', 'com.example.b'], asked.append)
    assert result == {'icons': {}, 'pending': ['com.example.a', 'com.example.b']}
    assert asked == [[{'package': 'com.example.a', 'version': 0}, {'package': 'com.example.b', 'version': 0}]]
    # Repeated reads within the answer window do not ask again.
    library.lookup('phone', ['com.example.a', 'com.example.b'], asked.append)
    assert len(asked) == 1
    library.receive('phone', [('com.example.a', 3, encoded('PNG', 96))], ['com.example.b'])
    result = library.lookup('phone', ['com.example.a', 'com.example.b'], asked.append)
    assert set(result['icons']) == {'com.example.a'} and result['pending'] == [] and len(asked) == 1
    clock.now += 7 * 3600  # Later the phone is asked whether the icon changed, with the cached version.
    library.lookup('phone', ['com.example.a'], asked.append)
    assert asked[-1] == [{'package': 'com.example.a', 'version': 3}]
    with pytest.raises(ValueError):
        library.lookup('phone', ['com.example.a', 'com.example.a'], asked.append)
    with pytest.raises(ValueError):
        library.lookup('phone', ['bad name'], asked.append)


# ------------------------------------------------------------------ pins and counts
def test_pins_and_open_counts_are_local_and_bounded(tmp_path):
    prefs = AppPreferences(tmp_path, clock=lambda: 50)
    prefs.pin('phone', 'com.example.maps', True)
    prefs.pin('phone', 'com.example.mail', True)
    prefs.pin('phone', 'com.example.maps', False)
    for _ in range(3):
        prefs.opened('phone', 'com.example.mail')
    prefs.opened('other', 'com.example.chat')
    reopened = AppPreferences(tmp_path).view('phone')
    assert reopened['pinned'] == ['com.example.mail'] and reopened['usage'] == {'com.example.mail': 3}
    assert AppPreferences(tmp_path).view('other')['usage'] == {'com.example.chat': 1}
    for index in range(MAX_PINNED - 1):
        prefs.pin('phone', f'com.example.app{index}', True)
    with pytest.raises(ValueError):
        prefs.pin('phone', 'com.example.extra', True)
    with pytest.raises(ValueError):
        prefs.pin('phone', 'com.example.mail', 'yes')
    (tmp_path / 'phone-apps.json').write_text(json.dumps({'version': 1, 'devices': {'phone': {'pinned': ['x y', 'com.ok.app'],
                                                         'opens': {'com.ok.app': [True, 1], 'bad': [1, 1]}}}}))
    assert AppPreferences(tmp_path).view('phone') == {'pinned': ['com.ok.app'], 'usage': {}, 'recent': {}}


def test_opening_an_app_counts_it_and_the_list_carries_pins(tmp_path):
    screen = PhoneScreen(SimpleNamespace(root=tmp_path), session=ScreenSession(addresses=lambda: ['192.168.1.7']))
    screen.session.start = lambda **kwargs: {'session': 'a' * 32, 'modules': [], 'delivered': False}
    screen.open_app('phone', 'com.example.mail')
    screen.pin('phone', 'com.example.mail', True)
    result = screen.apps('phone')
    assert result['usage'] == {'com.example.mail': 1} and result['pinned'] == ['com.example.mail'] and result['icons'] is False


# ------------------------------------------------------------------ sealed protocol
def test_icon_request_and_answer_shapes_are_exact():
    assert apps_icons_request_payload([{'package': 'com.example.a', 'version': 0}]) == {
        'type': 'apps.icons.request', 'apps': [{'package': 'com.example.a', 'version': 0}]}
    for rows in [[], [{'package': 'com.example.a', 'version': 0}] * 2, [{'package': 'bad', 'version': 0}],
                 [{'package': 'com.example.a', 'version': True}], [{'package': f'com.example.a{i}', 'version': 0} for i in range(25)]]:
        with pytest.raises(FeatureError):
            apps_icons_request_payload(rows)
    data = base64.b64encode(encoded('PNG', 96)).decode()
    good = {'type': 'apps.icons', 'icons': [{'package': 'com.example.a', 'version': 4, 'data': data}], 'same': ['com.example.b']}
    icons, same = read_apps_icons(good)
    assert icons[0][:2] == ('com.example.a', 4) and same == ['com.example.b']
    svg = base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg"/>' + bytes(40)).decode()
    for changes in [{'extra': 1}, {'same': ['com.example.a']},  # duplicate package
                    {'icons': [{'package': 'com.example.a', 'version': 4, 'data': svg}]},
                    {'icons': [{'package': 'com.example.a', 'version': 4, 'data': data + '!'}]},
                    {'icons': [{'package': 'com.example.a', 'version': 4, 'data': 'A' * 16_004}]},
                    {'icons': [{'package': 'com.example.a', 'version': 4, 'data': data, 'name': 'x'}]}]:
        with pytest.raises(FeatureError):
            read_apps_icons({**good, **changes})


def test_icons_travel_sealed_and_only_answer_this_computers_request(hosted, tmp_path):
    h = hosted
    advertise(h)
    png = encoded('PNG', 96)
    answer = {'type': 'apps.icons', 'icons': [{'package': 'com.example.mail', 'version': 9,
                                               'data': base64.b64encode(png).decode()}], 'same': []}
    h.send(answer)  # Unsolicited: refused.
    assert h.controller.take_app_icons(h.device) == ([], [])
    screen = PhoneScreen(SimpleNamespace(_active_hosted=lambda: h.controller, root=tmp_path),
                         session=ScreenSession(addresses=lambda: ['192.168.1.7']))
    assert screen.icons(h.device, ['com.example.mail', 'com.example.maps']) == {
        'icons': {}, 'pending': ['com.example.mail', 'com.example.maps']}
    h.controller.step()
    assert h.received() == [{'type': 'apps.icons.request', 'apps': [{'package': 'com.example.mail', 'version': 0},
                                                                     {'package': 'com.example.maps', 'version': 0}]}]
    h.send({**answer, 'icons': [{**answer['icons'][0], 'package': 'com.example.other'}]})  # Not asked for.
    h.send(answer)
    h.send({'type': 'apps.icons', 'icons': [], 'same': ['com.example.maps']})
    result = screen.icons(h.device, ['com.example.mail', 'com.example.maps'])
    assert result == {'icons': {'com.example.mail': data_uri(png)}, 'pending': []}
    # Cached on disk by package and version for the next run.
    assert IconCache(tmp_path).version('com.example.mail') == 9
