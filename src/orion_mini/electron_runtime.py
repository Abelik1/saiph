# SPDX-License-Identifier: AGPL-3.0-or-later
"""Full Link desktop runtime and native adapters, without a Qt GUI or event loop."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

from .desktop_actions import DesktopActions
from .link_service import LinkWorkspace
from .update_schedule import DesktopUpdates, FIRST_CHECK_MS, CHECK_INTERVAL_MS


class Emitter:
    def __init__(self, action):
        self.emit = action


class NativeDialogs:
    def __init__(self, native):
        self.native = native
    def getOpenFileName(self, _parent, title, filter='All files (*.*)'):
        return self.native('dialog.open', {'title': title, 'filter': filter}), ''
    def getSaveFileName(self, _parent, title, filter='All files (*.*)'):
        return self.native('dialog.save', {'title': title, 'filter': filter}), ''
    def getExistingDirectory(self, _parent, title):
        return self.native('dialog.directory', {'title': title})


class ElectronRuntime(DesktopActions):
    def __init__(self, root, native, emit, *, isolated=False, window_handle=0, binary=None):
        self.isolated, self.native, self.emit, self.binary = isolated, native, emit, binary
        self.workspace = LinkWorkspace(root)
        self.window = self
        self.closing = False
        self.visible = True
        self.started = time.monotonic()
        self.next_update = self.started + FIRST_CHECK_MS / 1000
        self.executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix='saiph-action')
        self.response = Emitter(lambda packet: emit(json.loads(packet)))
        self.changed = Emitter(self.announce)
        self.dialogs = NativeDialogs(native)
        self.clipboard = SimpleNamespace(setText=lambda text: native('clipboard.text', {'text': text}))
        self.updates = DesktopUpdates(self.workspace, changed=self.announce, restart=lambda: native('app.quit', {}))
        self.deliveries = {}
        self.delivery_lock = threading.RLock()
        self.stop_event = threading.Event()
        self._threads = []
        self.hub_thread = None
        self.hosted_started = False
        self.workspace.request_restart = lambda: self.native('app.restart', {})
        self.workspace.request_show_window = lambda: self.native('window.show', {})
        self.workspace.request_open_phone = self.open_phone_page
        self.workspace.request_open_phone_app = self.open_phone_app
        self.workspace.request_send_files = self.confirm_send_files
        # The window stays until Stop or its timeout: never make the caller, the Cloud or Hub event loop, wait for it.
        self.workspace.ring_requested = lambda phone: self.executor.submit(self.native, 'ring', {'phone': str(phone)[:100]})
        self.workspace.camera_requested = self.answer_camera_request
        self.workspace.security_alert = lambda message: self.notify('Saiph security', message)
        self.workspace.phone_alert = self.notify
        from .phone import PhoneRuntime
        self.phone_runtime = PhoneRuntime(self.workspace, self.announce, clipboard_received=self.clipboard_received)
        self.workspace.phone_runtime = self.phone_runtime
        self.workspace.call_audio.changed = self.announce
        from .cloud_client import CloudSupervisor
        self.cloud_supervisor = CloudSupervisor(root / 'cloud-client')
        from .automation import Automation
        self.workspace.automation_call = Automation(self.workspace, lambda work: work(), self.announce)
        from .user_presence import UserPresence
        if not isolated:
            self.workspace.user_presence = UserPresence(lambda: window_handle)
        self.workspace.screen.window = 'closed'
        self.workspace.screen.show_window = self.raise_screen
        self.screen_subscription = self.workspace.screen.session.subscribe(
            frame=lambda *_: self.preview('screen'), state=lambda state: self.screen_state(state))
        self.workspace.camera.local.notify = lambda kind: self.preview('camera') if kind == 'frame' else self.announce()
        from . import platform
        self._previous_open = getattr(platform, '_desktop_open', None)
        platform._desktop_open = self.open_target
        self._previous_beep = getattr(platform, '_desktop_beep', None)
        platform._desktop_beep = lambda urgent=False: self.native('beep', {})

    def start(self):
        if not self.isolated:
            from .api import ApiServer
            self.workspace.bootstrap()
            try:
                self.set_startup(bool(self.workspace.settings.get('start_with_windows', True)))
            except (OSError, ValueError):
                self.workspace.store.save('job', {'kind': 'startup', 'status': 'failed', 'error': 'This computer denied the startup preference. Check Settings → General.'})
            self.api = ApiServer(self.workspace)
            self.workspace.api_info = self.api.start()
            self.phone_runtime.start()
            self.workspace.usage_counter.start()
            from .usage import install_crash_counter
            install_crash_counter(self.workspace)
            self.executor.submit(self.workspace.user_presence.status)
        for job in self.workspace.store.all('job'):
            if job.get('status') == 'running':
                self.workspace.store.save('job', {**job, 'status': 'interrupted', 'progress': 'Stopped during the previous session; resume when ready.'})
        thread = threading.Thread(target=self._tick, name='saiph-desktop-timer', daemon=True)
        thread.start()
        self._threads.append(thread)
        self.announce()

    def native_call(self, method, args):
        return self.native(method, args)

    def background(self, request_id, action, *, changed=True):
        def run():
            try:
                self.emit({'id': request_id, 'ok': True, 'result': action()})
            except Exception as error:
                self.emit({'id': request_id, 'ok': False, 'error': str(error)})
            if changed:
                self.announce()
        self.executor.submit(run)

    def announce(self):
        if self.closing:
            return
        from .taskbar_badge import unread_count
        settings = self.workspace.settings
        self.emit({'type': 'changed'})
        self.emit({'type': 'shell', 'settings': {
            'close_to_tray': bool(settings.get('close_to_tray', True)),
            'clipboard': not self.isolated and (settings.get('link') or {}).get('clipboard') is not False,
            'unread': unread_count(self.workspace.store, settings),
            'live': self.workspace.screen.session.state == 'live' or self.workspace.camera.local.state == 'live',
            'camera_live': self.workspace.camera.local.state == 'live',
            'screen_live': self.workspace.screen.session.state == 'live',
        }})

    def _tick(self):
        ticks = 0
        while not self.stop_event.wait(1):
            ticks += 1
            try:
                if not self.isolated:
                    self.cloud_supervisor.poll()
                    self.ensure_hosted()
                    if ticks % 60 == 4 and self.workspace.hub_ready() and not (self.hub_thread and self.hub_thread.is_alive()):
                        self.hub_thread = threading.Thread(target=self.workspace.sync_hub, name='saiph-hub', daemon=True)
                        self.hub_thread.start()
                    if time.monotonic() >= self.next_update:
                        self.next_update = time.monotonic() + CHECK_INTERVAL_MS / 1000
                        self.updates.start_background_check()
                if self.workspace.show_enrollment:
                    self.workspace.show_enrollment = False
                    self.native('window.show', {})
                if ticks % 3 == 0 and self.visible:
                    self.announce()
                self.screen_state(self.workspace.screen.session.status())
            except Exception:
                self.notify('Saiph', 'A background check did not finish. Saiph will retry.')

    def ensure_hosted(self):
        if self.hosted_started or not (self.workspace.settings.get('hosted') or {}).get('enabled'):
            return
        controller = self.workspace.hosted_controller()
        self.hosted_started = True
        controller.clipboard_cache = self.phone_runtime.clipboard_cache
        controller.clipboard_sink = self.clipboard_received
        controller.sign_in_completed = lambda: self.native('window.show', {})
        from .clipboard import GuardedClipboardDelivery
        controller.clipboard_dispatch = lambda mime, data, guard: self.clipboard_received(mime, GuardedClipboardDelivery(data, guard))
        def call_state(state):
            self.phone_runtime.call_pause.call(state)
            self.workspace.call_audio.call_state(state)
        controller.call_state = call_state
        controller.changed = self.announce
        controller.start()

    def preview(self, source):
        session = self.workspace.camera.local if source == 'camera' else self.workspace.screen.session
        data = session.jpeg()
        if not data or not self.binary:
            return
        metadata = session.describe()
        self.binary.publish(source, {'kind': 'frame', 'source': source, 'session': session.session, **metadata}, data)
        self.emit({'type': 'frame', 'source': source, **metadata})

    def screen_state(self, state):
        if state.get('state') == 'live':
            self.emit({'type': 'screen', 'status': {**state, 'session': self.workspace.screen.session.session}})
            self.workspace.screen.window = 'open'
        elif self.workspace.screen.window == 'open':
            self.workspace.screen.window = 'closed'
            self.emit({'type': 'screen', 'status': state})

    def raise_screen(self):
        if self.workspace.screen.session.state != 'live':
            raise ValueError('Start the phone screen first.')
        self.native('screen.show', {})
        return {'shown': True}

    def clipboard_received(self, mime, data):
        from .clipboard import GuardedClipboardDelivery
        from .images import png_bytes
        guarded = isinstance(data, GuardedClipboardDelivery)
        guard = data.authorized if guarded else lambda: True
        raw = data.data if guarded else data
        if (self.workspace.settings.get('link') or {}).get('clipboard') is False or not guard() or self.isolated:
            return
        prepared = raw if mime == 'text/plain' else png_bytes(raw)
        delivered_mime = mime if mime == 'text/plain' else 'image/png'
        token = uuid4().hex
        with self.delivery_lock:
            self.deliveries[token] = (time.monotonic() + 30, guard)
        self.phone_runtime.clipboard_cache.received(mime, raw)
        self.phone_runtime.clipboard_cache.received(delivered_mime, prepared, alias=True)
        hosted = getattr(self.workspace, '_hosted', None)
        if guarded and hosted:
            hosted.clipboard_cache.received(mime, raw)
            hosted.clipboard_cache.received(delivered_mime, prepared, alias=True)
        try:
            self.binary.publish(token, {'kind': 'clipboard', 'token': token, 'mime': delivered_mime}, prepared)
            self.native('clipboard.write', {'token': token, 'mime': delivered_mime})
        finally:
            with self.delivery_lock:
                self.deliveries.pop(token, None)

    def authorize_clipboard(self, token):
        with self.delivery_lock:
            item = self.deliveries.get(token)
        return bool(item and item[0] > time.monotonic() and item[1]()
                    and (self.workspace.settings.get('link') or {}).get('clipboard') is not False)

    def binary_received(self, header, data):
        if self.isolated or header.get('kind') != 'clipboard.local':
            return
        mime = header.get('mime')
        hosted = getattr(self.workspace, '_hosted', None)
        if mime == 'clear':
            if hosted:
                hosted.clear_local_clipboard()
            return
        if mime not in {'text/plain', 'image/png', 'image/jpeg', 'image/webp'} or len(data) > 16 * 1024 * 1024:
            return
        if mime != 'text/plain':
            from .images import png_bytes
            data, mime = png_bytes(data), 'image/png'
        self.phone_runtime.local_clipboard(mime, data)
        if hosted:
            hosted.local_clipboard(mime, data)

    def open_target(self, value):
        return self.native('open', {'path': str(value.resolve())} if isinstance(value, Path) else {'url': str(value)})

    def set_startup(self, enabled):
        if self.isolated:
            return
        from .platform import set_startup
        return set_startup(enabled)

    def notify(self, title, text):
        self.emit({'type': 'notification', 'title': str(title)[:100], 'text': str(text)[:2000]})

    def pump_jobs(self):
        pass  # Link has no private Workspace job executor.

    def cancel_job(self, _job):
        raise ValueError('This action requires the private Workspace edition.')

    def preview_urgent_popup(self, _stage):
        raise ValueError('This action requires the private Workspace edition.')

    def update_and_rebuild(self):
        from .updater import start_update
        start_update()
        self.native('app.quit', {})
        return {'ok': True}

    def open_phone_page(self):
        self.workspace.phone_reveal += 1
        self.native('window.show', {})
        self.announce()

    def open_phone_app(self, package, attempts=0):
        from .session_offer import valid_package
        if not valid_package(package):
            raise ValueError('Choose a phone app.')
        from .phone_settings import flag
        devices = self.workspace.phone_snapshot().get('devices', [])
        online = [d for d in devices if d.get('online')]
        screens = [d for d in online if 'screen' in (d.get('screen') or [])]
        usb = flag(self.workspace.settings, 'usb_debugging')
        if not screens and not usb:
            screens = online[:1]
        if screens:
            self.workspace.screen.reveal += 1
            self.native('window.show', {})
            self.executor.submit(self.workspace.screen.open_app, screens[0]['id'], package)
            return
        if usb and online:
            from .adb_worker import AdbWorker
            from .phone_apps import open_app
            worker = AdbWorker()
            self.executor.submit(open_app, worker.adb, worker.paired_serial(online[0]['id']), package)
        elif attempts < 7:
            timer = threading.Timer(4, lambda: self.open_phone_app(package, attempts + 1) if not self.closing else None)
            timer.daemon = True
            timer.start()
        else:
            self.notify('Saiph', 'Your phone is offline. The app was not opened.')

    def answer_camera_request(self, device, phone_name):
        """A phone asked to be the webcam: Accept starts a camera session and sends it to that phone."""
        def ask():
            if self.native('camera.request', {'phone': str(phone_name)[:100]}) is not True:
                return
            camera = self.workspace.camera
            try:
                code = camera.start_local(preview=not camera.status().get('integrated_available', False))
                camera.offer_to_phone(code['session'], device)
            except Exception as error:
                self.notify('Saiph', f'The webcam could not start: {error}')
            self.announce()
        self.executor.submit(ask)

    def confirm_send_files(self, paths, attempts=0):
        from .send_files import validate, targets, describe_files
        paths = validate(list(paths))
        devices = targets(self.workspace.state())
        if not devices:
            if attempts < 7:
                timer = threading.Timer(4, lambda: self.confirm_send_files(paths, attempts + 1) if not self.closing else None)
                timer.daemon = True
                timer.start()
            else:
                self.notify('Saiph', 'Your phone is offline. Nothing was sent.')
            return
        chosen = self.native('send.confirm', {'description': describe_files(paths), 'devices': [d['name'] for d in devices]})
        if type(chosen) is not int or not 0 <= chosen < len(devices):
            return
        def send():
            for path in paths:
                try:
                    self.workspace.dispatch('phone.file.send', {'device_id': devices[chosen]['id'], 'path': path, 'notify': True})
                except Exception:
                    self.notify('Saiph', 'A file could not be sent. Check the transfer list.')
        self.executor.submit(send)

    def photo_original(self, request_id, method, args):
        if set(args) != {'device_id', 'photo_id'} or not all(isinstance(v, str) and v for v in args.values()):
            raise ValueError('Choose a photo from a paired phone.')
        def original():
            features = self.workspace.phone_features
            with features.lock:
                features.photo_request(args['device_id'], args['photo_id'], 'prefetch')
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and not self.closing:
                row = features.photo_cached(args['device_id'], args['photo_id'])
                if row:
                    return self.native_photo('photo.copy' if method == 'phone.photo.copy' else 'photo.view', row['path'])
                time.sleep(0.1)
            raise ValueError('Your phone has not sent the original yet. Try again when it is connected.')
        self.background(request_id, original)

    def photo_drag(self, request_id, args):
        def drag():
            self.workspace.dispatch('phone.photo.prefetch', args)
            row = self.workspace.phone_features.photo_cached(args['device_id'], args['photo_id'])
            return self.native_photo('photo.drag', row['path']) if row else {'preparing': True, 'ready': False}
        self.background(request_id, drag)

    def native_photo(self, method, path):
        width, height = self.validate_photo(path)
        args = {'path': path, 'width': width, 'height': height}
        if method != 'photo.view':
            from .images import png_bytes
            token = uuid4().hex
            self.binary.publish(token, {'kind': 'image', 'token': token}, png_bytes(Path(path).read_bytes()))
            args['token'] = token
        return self.native(method, args)

    @staticmethod
    def validate_photo(value):
        from .images import decoded
        file = Path(value)
        if not file.is_file() or file.stat().st_size > 64 * 1024 * 1024:
            raise ValueError('The original image is too large.')
        with decoded(file.read_bytes(), orient=True) as image:
            return image.size

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.stop_event.set()
        self.screen_subscription()
        for action in (self.workspace.camera.stop, self.workspace.screen.stop, self.workspace.microphone.stop,
                       self.phone_runtime.stop, self.cloud_supervisor.stop):
            try:
                action()
            except Exception:
                pass
        hosted = getattr(self.workspace, '_hosted', None)
        if hosted:
            hosted.stop()
        api = getattr(self, 'api', None)
        if api:
            api.stop()
        counter = getattr(self.workspace, 'usage_counter', None)
        if counter and hasattr(counter, 'stop'):
            counter.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
        from . import platform
        platform._desktop_open = self._previous_open
        platform._desktop_beep = self._previous_beep
