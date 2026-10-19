# SPDX-License-Identifier: AGPL-3.0-or-later
"""Native checks through the running Saiph app and disposable acceptance phone pad.

Requires PySide6, authorized USB debugging, and the separately built/installed
acceptance-phone-pad APK. Does not update Saiph, modify pairing, or operate SMS,
calls, capture, reboot, or network controls. Results contain synthetic metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage, QColor, QTextDocument
from PySide6.QtWidgets import QApplication, QTextEdit

PACKAGE = 'ie.orion.acceptance.pad'
NOTICE = 'ORION-ACCEPTANCE-NOTICE'
spec = importlib.util.spec_from_file_location('desktop_call', Path(__file__).with_name('desktop-call.py'))
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)
from orion_mini.platform import qt_platform_for_background_clipboard  # noqa: E402  (src path set by desktop-call)


def same_pixels(image, expected):
    """Pixel equality; QImage == also compares colour spaces, and a pasted PNG arrives tagged sRGB."""
    image = image.convertToFormat(QImage.Format.Format_RGB32)
    image.setColorSpace(expected.colorSpace())
    return image == expected


class NativeEditor(QTextEdit):
    """Rich editor endpoint that explicitly accepts clipboard image MIME data."""
    def canInsertFromMimeData(self, source):
        return source.hasImage() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        if source.hasImage():
            value = source.imageData()
            if hasattr(value, 'toImage'):
                value = value.toImage()
            if isinstance(value, QImage) and not value.isNull():
                url = QUrl('acceptance:clipboard-image')
                self.document().addResource(QTextDocument.ResourceType.ImageResource, url, value)
                self.textCursor().insertImage(url.toString())
                return
        super().insertFromMimeData(source)


class Run:
    def __init__(self, args):
        self.args = args
        self.root = args.output.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.tag = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
        # GNOME/Wayland lets only the focused client set or read the clipboard, so an
        # unfocused native Wayland editor silently drops copies. Use the app's choice.
        platform = qt_platform_for_background_clipboard()
        if platform and not QApplication.instance():
            os.environ['QT_QPA_PLATFORM'] = platform
        self.app = QApplication.instance() or QApplication([])
        self.editor = NativeEditor()
        self.editor.setWindowTitle('Saiph automated acceptance — synthetic fixtures')
        self.editor.resize(640, 260)
        self.editor.show()
        self.app.processEvents()
        self.results = []

    def shell(self, *args):
        # Qt owns these synthetic Windows clipboard images via delayed native
        # rendering. Keep its GUI alive while ADB operates the phone; otherwise
        # Saiph can time out requesting pixels from this blocked fixture owner.
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(subprocess.run,
                [self.args.adb, '-s', self.args.serial, 'shell', shlex.join(map(str, args))],
                capture_output=True, text=True, encoding='utf-8', timeout=25)
            while not future.done():
                self.app.processEvents()
                time.sleep(.01)
            result = future.result()
        if result.returncode or 'SecurityException' in result.stdout or 'Error:' in result.stdout:
            raise RuntimeError('ADB fixture command failed')
        return result.stdout

    def wait(self, work, timeout=25):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            value = work()
            if value:
                return value
            time.sleep(.25)
        raise TimeoutError('Fixture endpoint did not match before deadline')

    def status(self):
        raw = self.shell('content', 'call', '--uri', f'content://{PACKAGE}.fixtures', '--method', 'status')
        match = re.search(r'result=(\{.*\})', raw)
        if not match:
            raise RuntimeError('Pad status unavailable')
        return json.JSONDecoder().raw_decode(match.group(1))[0]

    def pad(self, command, **extras):
        before = self.status().get('completed_at', 0)
        # A prior share gesture can leave Saiph's chooser above this activity in
        # the helper's task. Delivering an intent to the covered Pad still runs
        # copy commands, but Android correctly denies its background paste/read.
        # Return to the visible native endpoint before issuing any new command.
        self.shell('am', 'start', '-W', '--activity-clear-top', '-n', PACKAGE + '/.Pad')
        self.shell('content', 'call', '--uri', f'content://{PACKAGE}.fixtures', '--method', 'command', '--arg', json.dumps({'command': command, **extras}))
        def completed():
            s = self.status()
            return s if s.get('completed_at', 0) > before and s.get('completed_action') == command else None
        result = self.wait(completed)
        if result.get('error'):
            raise RuntimeError('Pad endpoint error: ' + result['error'])
        return result

    def result(self, case, status='pass', **evidence):
        row = {'time_utc': datetime.now(timezone.utc).isoformat(), 'case': case, 'status': status, **evidence}
        self.results.append(row)
        (self.root / ('automated-results-' + self.tag + '.json')).write_text(json.dumps(self.results, indent=2) + '\n')
        print(json.dumps(row), flush=True)

    def copy_text(self, text):
        self.editor.setPlainText(text)
        self.editor.selectAll()
        self.editor.copy()
        self.app.processEvents()

    def pasted_text(self, text):
        self.editor.clear()
        self.editor.paste()
        return self.editor.toPlainText() == text

    @staticmethod
    def image():
        image = QImage(240, 160, QImage.Format.Format_RGB32)
        for y in range(160):
            for x in range(240):
                image.setPixelColor(x, y, QColor('#26b6cb' if (x//20+y//20) % 2 else '#293541'))
        return image

    def pasted_image(self):
        self.editor.clear()
        self.editor.paste()
        block = self.editor.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.charFormat().isImageFormat():
                    fmt = fragment.charFormat().toImageFormat()
                    value = self.editor.document().resource(QTextDocument.ResourceType.ImageResource, QUrl(fmt.name()))
                    if hasattr(value, 'toImage'):
                        value = value.toImage()
                    if isinstance(value, QImage) and same_pixels(value, self.image()):
                        return True
                iterator += 1
            block = block.next()
        return False

    def clipboard(self):
        for step, letter in enumerate(('A', 'B', 'A'), 1):
            text = f'ORION-AUTO-LAPTOP-{letter}-{self.tag}'
            self.copy_text(text)
            self.wait(lambda: self.pad('paste_text', value=text).get('text_match'))
            self.result('TEXT-LP-' + letter, endpoint='native Android EditText paste', step=step)
        for step, letter in enumerate(('A', 'B', 'A'), 1):
            text = f'ORION-AUTO-PHONE-{letter}-{self.tag}'
            self.pad('copy_text', value=text)
            self.wait(lambda: self.pasted_text(text))
            self.result('TEXT-PL-' + letter, endpoint='native Qt QTextEdit paste', step=step)

    def images(self):
        self.app.clipboard().setImage(self.image())
        self.app.processEvents()
        self.wait(lambda: self.pad('paste_image').get('image_match'))
        self.result('IMAGE-LP', endpoint='Android clipboard URI decoded bitmap', every_pixel_matches=True)
        # Change value/type before copying the same pixels back: an unchanged
        # most-recent image is deliberately suppressed as a clipboard echo.
        separator = 'ORION-IMAGE-SEPARATOR-' + self.tag
        self.pad('copy_text', value=separator)
        self.wait(lambda: self.pasted_text(separator))
        self.pad('copy_image')
        self.wait(self.pasted_image)
        self.result('IMAGE-PL', endpoint='image pasted into native Qt QTextEdit', every_pixel_matches=True)

    def tap_label(self, label, timeout=15):
        path = '/sdcard/orion-acceptance-ui.xml'
        def attempt():
            self.shell('uiautomator', 'dump', path)
            # Parse in memory. Never save or print the owner's screen contents.
            xml = self.shell('cat', path)
            for node in ET.fromstring(xml).iter('node'):
                if node.get('text') == label:
                    coords = list(map(int, re.findall(r'\d+', node.get('bounds', ''))))
                    if len(coords) == 4:
                        self.shell('input', 'tap', (coords[0]+coords[2])//2, (coords[1]+coords[3])//2)
                        return True
            return False
        try:
            return self.wait(attempt, timeout)
        finally:
            self.shell('rm', '-f', path)

    def files(self, phone, machine):
        name = 'ORION-AUTO-LAPTOP-' + self.tag + '.txt'
        path = self.root / name
        path.write_bytes(b'Orion automated laptop-to-phone file fixture\nSynthetic content only.\n')
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
        desktop.call('phone.file.send', {'device_id': phone['id'], 'path': str(path)})
        remote = '/sdcard/Download/Orion/' + name
        self.wait(lambda: expected in self.shell('sh', '-c', 'test -f ' + shlex.quote(remote) + ' && sha256sum ' + shlex.quote(remote) + ' || true'), timeout=40)
        self.result('FILE-LP', sha256=expected, name_preserved=True)
        self.receive_file(machine)

    def receive_file(self, machine):
        name = 'ORION-AUTO-PHONE-' + self.tag + '.txt'
        fixture = self.pad('share_file', name=name)
        self.tap_label(machine)
        self.tap_label('Send a file')
        def received():
            state = desktop.call('state')
            rows = [r for r in state.get('phone_features', {}).get('files', []) if r.get('name') == name and r.get('path')]
            if len(rows) != 1:
                return None
            path = Path(rows[0]['path'])
            return path if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == fixture['fixture_sha256'] else None
        self.wait(received, timeout=45)
        self.result('FILE-PL', sha256=fixture['fixture_sha256'], name_preserved=True, one_receipt=True)

    def notification(self):
        self.pad('notification')
        def fixture_row():
            return next((n for n in desktop.call('state')['phone'].get('notifications', []) if n.get('title') == NOTICE), None)
        row = self.wait(fixture_row)
        self.result('NOTIFY-FEED', fixture_arrived=True)
        mark = next(a for a in row.get('actions', []) if a.get('label') == 'Mark fixture')
        desktop.call('phone.notification', {'id': row['id'], 'operation': 'action', 'index': mark['index']})
        self.wait(lambda: self.status().get('mark_count') == 1)
        self.result('NOTIFY-ACTION', invocation_count=1)
        desktop.call('phone.notification', {'id': row['id'], 'operation': 'reply', 'reply_key': row['reply_key'], 'text': 'ORION-FIXTURE-REPLY'})
        def replied():
            s = self.status()
            return s.get('reply_count') == 1 and s.get('reply_match')
        self.wait(replied)
        self.result('NOTIFY-REPLY', invocation_count=1, synthetic_reply_matches=True)
        desktop.call('phone.notification', {'id': row['id'], 'operation': 'dismiss'})
        self.wait(lambda: self.status().get('active_notifications') == 0 and fixture_row() is None)
        final = self.status()
        if final.get('mark_count') != 1 or final.get('reply_count') != 1:
            raise RuntimeError('Fixture action count changed unexpectedly')
        self.result('NOTIFY-DISMISS', phone_removed=True, desktop_feed_removed=True, action_count=1, reply_count=1)

    def execute(self):
        with desktop.temporary_automation():
            state = desktop.call('state')
            phone = next(d for d in state['phone']['devices'] if d.get('online') and 'battery' in d.get('capabilities', []) and 'files' in d.get('capabilities', []))
            local_id = state['settings']['hub']['device_id']
            local_device = next(d for d in state['phone']['devices'] if d['id'] == local_id)
            machine = local_device['name']
            self.shell('pm', 'grant', PACKAGE, 'android.permission.POST_NOTIFICATIONS')
            self.shell('am', 'start', '-W', '-n', PACKAGE + '/.Pad')
            self.wait(self.status)
            current = 'SETUP'
            try:
                suites = [('CLIPBOARD', self.clipboard), ('IMAGE', self.images), ('FILE', lambda: self.files(phone, machine)), ('NOTIFY', self.notification)]
                if self.args.only == 'receive':
                    suites = [('FILE-PL', lambda: self.receive_file(machine))]
                for current, work in suites:
                    if self.args.only not in ('all', 'receive', current.lower()):
                        continue
                    work()
            except (Exception, SystemExit) as error:
                self.result(current, status='failed', error_type=type(error).__name__, detail=str(error)[:200])
                raise
            finally:
                try:
                    self.pad('cleanup')
                finally:
                    self.editor.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--only', choices=('all', 'clipboard', 'image', 'file', 'receive', 'notify'), default='all')
    Run(parser.parse_args()).execute()
