# SPDX-License-Identifier: AGPL-3.0-or-later
"""Native desktop shell. Qt owns the window; services own application state."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import Future, TimeoutError as FutureTimeout
from random import randrange
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PySide6.QtCore import QEvent, QProcess, QTimer, QUrl, Qt, QLockFile, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QPushButton, QSystemTrayIcon, QVBoxLayout
from .api import ApiServer, replay_inbox
from .automation import Automation
from .db_health import check as check_databases
from .modules import edition
from .dashboard_view import dashboard_view, prepare_web_engine
from .desktop_bridge import DesktopBridge
from .frame_feed import SCHEME as FRAME_SCHEME, frame_handler
from .paths import app_data_dir
from .platform import beep, qt_platform_for_background_clipboard, set_startup
from .updater import start_update
APP_MODEL_ID = 'OrionMini.Desktop'
# The dashboard's darkest ground (--background). Qt paints it wherever the page
# has not drawn yet, so resizing or first show never flashes white.
DASHBOARD_GROUND = '#040916'
# A safety-net refresh for state nothing announced. Phone, Cloud, camera, screen
# and every bridge action announce their own changes immediately.
REFRESH_TICKS = 3
# Moving or resizing the window holds periodic refreshes until it settles, so
# a full snapshot never stalls the GUI thread under the pointer.
SETTLE_MS = 400

def resource_root():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))

def app_icon() -> QIcon:
    return QIcon(str(resource_root() / 'assets' / 'orion-mini-icon.ico'))

def claim_taskbar_identity() -> None:
    """Without an explicit model id Windows shows the host interpreter's icon."""
    if os.name != 'nt':
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_MODEL_ID)
    except (AttributeError, OSError):
        pass

def apply_startup_setting(workspace):
    """Re-apply start at sign-in; a refusal is reported, never fatal at launch.

    Linux refuses with ValueError when the installed launcher is missing (an
    extracted archive run directly) or an unrelated autostart entry exists."""
    try:
        set_startup(bool(workspace.settings['start_with_windows']))
    except ValueError as error:
        workspace.store.save('job', {'kind': 'startup', 'status': 'failed', 'error': str(error)})
    except OSError:
        workspace.store.save('job', {'kind': 'startup', 'status': 'failed', 'error': 'This computer denied the startup setting. Check Settings → General.'})

class MainWindow(QMainWindow):
    phone_changed = Signal()
    clipboard_received = Signal(str, object)
    cloud_sign_in_completed = Signal()
    update_checked = Signal(str)
    restart_requested = Signal()
    automation_requested = Signal(object)
    security_alert = Signal(str)
    phone_alert = Signal(str, str)
    send_files_requested = Signal(object)
    open_phone_app_requested = Signal(str)
    ring_requested = Signal(str)
    open_phone_requested = Signal()

    def __init__(self, data_dir=None, bootstrap=True):
        super().__init__()
        Workspace = self.workspace_class()
        self.workspace = Workspace(Path(data_dir) if data_dir else app_data_dir())
        self.setWindowTitle('Saiph')
        self.resize(1320, 900)
        self.setMinimumSize(940, 650)
        self.setWindowIcon(app_icon())
        self.processes = {}
        self.hosted_started = False
        self.buffers = {}
        self.popups = {}
        self.preview_popup = None
        self.closing = False
        self.cloud_sign_in_completed.connect(self.return_from_cloud_sign_in)
        if bootstrap:
            self.workspace.bootstrap()
            apply_startup_setting(self.workspace)
        for job in self.workspace.store.all('job'):
            if job['status'] == 'running':
                self.workspace.store.save('job', {**job, 'status': 'interrupted', 'progress': 'Stopped during the previous session; resume when ready.'})
        ground = QColor(DASHBOARD_GROUND)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, ground)
        self.setPalette(palette)
        self.bridge = DesktopBridge(self)
        # Chromium in its own natively composited child window (dashboard_view.py),
        # with the bridge as the web channel's only object.
        self.view = dashboard_view(self.bridge, DASHBOARD_GROUND, self)
        # Live camera and phone-screen pictures travel as bytes (frame_feed.py).
        self.frame_handler = frame_handler(self.bridge.feeds, self)
        profile = self.view.profile()
        previous = profile.urlSchemeHandler(FRAME_SCHEME)
        if previous is not None:
            profile.removeUrlSchemeHandler(previous)
        profile.installUrlSchemeHandler(FRAME_SCHEME, self.frame_handler)
        self.phone_changed.connect(self.bridge.changed)
        from .phone import PhoneRuntime
        self.phone_runtime = PhoneRuntime(self.workspace, self.phone_changed.emit, clipboard_received=self.clipboard_received.emit)
        self.workspace.phone_runtime = self.phone_runtime
        if getattr(self.workspace, 'call_audio', None) is not None:
            self.workspace.call_audio.changed = self.phone_changed.emit
        from .cloud_client import CloudSupervisor
        self.cloud_supervisor = CloudSupervisor(self.workspace.root / 'cloud-client')
        if not os.environ.get('ORION_MINI_TEST'):
            from .clipboard import QtClipboard
            self.clipboard_adapter = QtClipboard(self.phone_runtime)
            self.clipboard_received.connect(self.clipboard_adapter.write)
            self.phone_runtime.start()
        self.view.files_dropped.connect(self.handle_dropped_files)
        self.view.drag_changed.connect(self.bridge.dragging)
        self.setCentralWidget(self.view.widget)
        dashboard = self.dashboard_path()
        if not dashboard.exists():
            self.view.setHtml('<h1>Saiph needs its dashboard build</h1><p>Run npm --prefix frontend run build, then reopen Saiph.</p>')
        else:
            self.view.load(QUrl.fromLocalFile(str(dashboard)))
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip('Saiph')
        menu = QMenu(self)
        show = menu.addAction('Open Saiph')
        show.triggered.connect(self.showNormal)
        # Phone quick controls, rebuilt from current state each time the menu opens.
        self.phone_menu = menu.addMenu('Phone')
        self.phone_menu.aboutToShow.connect(self.fill_phone_menu)
        from .package_updates import current as packaged_release
        update_action = menu.addAction('Check for updates' if packaged_release() else 'Update and rebuild')
        update_action.triggered.connect(self.update_from_tray)
        quit_action = menu.addAction('Quit')
        quit_action.triggered.connect(self.quit_app)
        self.tray.setContextMenu(menu)
        self.update_checked.connect(lambda message: self.tray.showMessage('Saiph', message, QSystemTrayIcon.Information, 10000))
        self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.Trigger else None)
        if not os.environ.get('ORION_MINI_TEST'):
            self.tray.show()
        # The live phone screen opens in its own window; the tray turns red while camera or screen is live.
        from .phone_screen_window import PhoneScreenWindowController
        self.phone_screen_window = PhoneScreenWindowController(self.workspace, self.tray, self.windowIcon(), self)
        # Device-list changes are announced from the hosted worker thread; the
        # signal delivers them to the tray on the GUI thread.
        self.security_alert.connect(lambda message: self.tray.showMessage('Saiph security', message, QSystemTrayIcon.Warning, 15000))
        self.workspace.security_alert = self.security_alert.emit
        # Hosted incoming and missed calls, from the hosted worker thread.
        self.phone_alert.connect(lambda title, text: self.tray.showMessage(title, text, QSystemTrayIcon.Information, 15000))
        self.workspace.phone_alert = self.phone_alert.emit
        if not os.environ.get('ORION_MINI_TEST'):
            # Adding devices requires Windows Hello where it is set up. The handle
            # is read here, on the GUI thread; prompts run on worker threads.
            from .user_presence import UserPresence
            window_handle = int(self.winId())
            self.workspace.user_presence = UserPresence(lambda: window_handle)
            if sys.platform == 'win32':
                # Unread phone notifications on the taskbar button (Settings → Phone → Taskbar badge).
                from .taskbar_badge import TaskbarBadge, unread_count
                self.taskbar_badge = TaskbarBadge(window_handle)
                self.badge_timer = QTimer(self)
                self.badge_timer.timeout.connect(lambda: self.taskbar_badge.show(unread_count(self.workspace.store, self.workspace.settings)))
                self.badge_timer.start(5000)
            threading.Thread(target=self.workspace.user_presence.status, name='orion-user-presence', daemon=True).start()
            # Sends only after the owner agrees; a no-op otherwise.
            counter = getattr(self.workspace, 'usage_counter', None)
            if counter is not None:
                counter.start()
        self.restart_requested.connect(self.restart_app)
        self.workspace.request_restart = self.restart_requested.emit
        # Send to phone from a file manager arrives on the API thread; confirm on the GUI thread.
        self.send_files_requested.connect(self.confirm_send_files)
        self.workspace.request_send_files = self.send_files_requested.emit
        self.open_phone_app_requested.connect(self.open_phone_app)
        self.ring_requested.connect(self.ring_computer)
        self.workspace.ring_requested = self.ring_requested.emit
        # A clicked Saiph Cloud notification toast, from the notifier's thread.
        self.open_phone_requested.connect(self.open_phone_page)
        self.workspace.request_open_phone = self.open_phone_requested.emit
        self.workspace.request_open_phone_app = self.open_phone_app_requested.emit
        self.automation_requested.connect(self.run_automation)
        self.workspace.automation_call = Automation(self.workspace, self.run_on_gui, self.bridge.changed.emit)
        self.api = ApiServer(self.workspace, 0 if os.environ.get('ORION_MINI_TEST') else None)
        self.workspace.api_info = self.api.start()
        self.ticks = 0
        self.settling = QTimer(self)
        self.settling.setSingleShot(True)
        self.settling.setInterval(SETTLE_MS)
        # Once a move settles, Chromium learns the view's new screen position (popups).
        self.settling.timeout.connect(self.view.window_moved)
        self.tick = QTimer(self)
        self.tick.timeout.connect(self.on_tick)
        self.tick.start(1000)
        self.watch = QTimer(self)
        self.watch.timeout.connect(self.scan)
        self.watch.start(30000)
        self.calendar_thread = None
        self.calendar_timer = QTimer(self)
        self.calendar_timer.timeout.connect(self.refresh_calendar)
        self.calendar_timer.start(10 * 60 * 1000)
        QTimer.singleShot(3000, self.refresh_calendar)
        self.hub_thread = None
        self.hub_timer = QTimer(self)
        self.hub_timer.timeout.connect(self.refresh_hub)
        self.hub_timer.start(60 * 1000)
        QTimer.singleShot(4000, self.refresh_hub)
        if not os.environ.get('ORION_MINI_TEST'):
            # Look for a desktop update soon after start-up, then every six hours.
            # Idle cost is one timer; a found update lights the footer's Update button.
            from .update_schedule import CHECK_INTERVAL_MS, FIRST_CHECK_MS
            self.update_timer = QTimer(self)
            self.update_timer.timeout.connect(self.bridge.updates.start_background_check)
            self.update_timer.start(CHECK_INTERVAL_MS)
            QTimer.singleShot(FIRST_CHECK_MS, self.bridge.updates.start_background_check)
        self.scan()
        self.pump_jobs()

    def workspace_class(self):
        """The Workspace add-on's window subclass replaces this and the hooks below."""
        from .link_service import LinkWorkspace
        return LinkWorkspace

    def dashboard_path(self):
        return resource_root() / 'frontend' / 'dist' / 'index.html'

    def handle_dropped_files(self, paths):
        pass

    def scan(self):
        pass

    def refresh_calendar(self):
        pass

    def refresh_hub(self):
        if os.environ.get('ORION_MINI_TEST') or not self.workspace.hub_ready():
            return
        if self.hub_thread and self.hub_thread.is_alive():
            return
        self.hub_thread = threading.Thread(target=self.workspace.sync_hub, name='orion-hub', daemon=True)
        self.hub_thread.start()

    def ensure_hosted(self):
        """Load the opt-in hosted preview only once its setting is turned on."""
        if self.hosted_started or os.environ.get('ORION_MINI_TEST'):
            return
        hosted = self.workspace.settings.get('hosted')
        if not (isinstance(hosted, dict) and hosted.get('enabled') is True) or not hasattr(self.workspace, 'hosted_controller'):
            return
        try:
            controller = self.workspace.hosted_controller()
        except ValueError:
            return
        self.hosted_started = True
        # One echo/repeat cache for Link and hosted clipboard deliveries.
        controller.clipboard_cache = self.phone_runtime.clipboard_cache
        controller.clipboard_sink = self.clipboard_received.emit
        controller.sign_in_completed = self.cloud_sign_in_completed.emit
        from .clipboard import GuardedClipboardDelivery
        controller.clipboard_dispatch = lambda mime, data, guard: self.clipboard_received.emit(mime, GuardedClipboardDelivery(data, guard))
        audio = getattr(self.workspace, 'call_audio', None)
        def call_state(state, pause=self.phone_runtime.call_pause.call):
            pause(state)  # Same media pause as Link calls.
            if audio is not None:
                audio.call_state(state)  # Bluetooth audio route on this computer; nothing goes to the Cloud.
        controller.call_state = call_state
        controller.changed = self.bridge.changed.emit
        controller.start()

    def return_from_cloud_sign_in(self):
        if not self.closing:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def on_tick(self):
        if not os.environ.get('ORION_MINI_TEST'):
            self.cloud_supervisor.poll()
            self.ensure_hosted()
        if self.workspace.show_enrollment:
            self.workspace.show_enrollment = False
            self.showNormal()
            self.raise_()
            self.activateWindow()
        self.ticks += 1
        if self.ticks % REFRESH_TICKS == 0 and self.dashboard_visible() and not self.settling.isActive():
            self.bridge.changed.emit()

    def dashboard_visible(self):
        """A hidden or minimised dashboard needs no periodic refresh; it gets one on return."""
        return self.isVisible() and not self.isMinimized()

    def hold_refresh(self):
        settling = getattr(self, 'settling', None)  # Absent while the window is still being built.
        if settling is not None:
            settling.start()

    def refresh_now(self):
        bridge = getattr(self, 'bridge', None)
        if bridge is not None:
            bridge.changed.emit()

    def dashboard_shown(self, shown: bool) -> None:
        """Hidden or minimised, the page is told it is hidden (its timers stop) and
        the bridge holds change notices; on return, one refresh catches up."""
        view, bridge = getattr(self, 'view', None), getattr(self, 'bridge', None)
        if view is not None:
            view.set_shown(shown)
        if shown and bridge is not None:
            bridge.resume()

    def moveEvent(self, event):
        self.hold_refresh()
        super().moveEvent(event)

    def resizeEvent(self, event):
        self.hold_refresh()
        super().resizeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        view = getattr(self, 'view', None)
        if view is not None:
            view.widget.setFocus()  # Keys reach the page without a first click.
        self.dashboard_shown(not self.isMinimized())
        self.refresh_now()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.dashboard_shown(False)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            self.dashboard_shown(self.isVisible() and not self.isMinimized())
            if not self.isMinimized():
                self.refresh_now()

    def preview_urgent_popup(self, stage=0):
        raise ValueError('This action requires the private Workspace edition.')

    def pump_jobs(self):
        pass

    def cancel_job(self, job_id):
        raise ValueError('This action requires the private Workspace edition.')

    @staticmethod
    def stop_process(process):
        pid = int(process.processId())
        if pid > 0 and os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
        process.kill()

    def update_and_rebuild(self):
        """Hand over to the update script, then close so it can replace the built app."""
        start_update()
        QTimer.singleShot(400, self.quit_app)
        return {'ok': True}

    def open_phone_page(self):
        self.workspace.phone_reveal = getattr(self.workspace, 'phone_reveal', 0) + 1  # The page switches to Phone.
        self.showNormal(); self.raise_(); self.activateWindow()
        self.bridge.changed.emit()

    def ring_computer(self, phone_name):
        """Find this computer: an alert sound for up to 30 seconds and a window with Stop."""
        from PySide6.QtWidgets import QMessageBox
        from .platform import beep
        if getattr(self, 'ring_box', None):
            return
        box = self.ring_box = QMessageBox(QMessageBox.Icon.Information, 'Saiph', f'{phone_name} is looking for this computer.', QMessageBox.StandardButton.NoButton, self)
        box.addButton('Stop', QMessageBox.ButtonRole.AcceptRole)
        timer = QTimer(self); timer.setInterval(1200); ticks = {'left': 25}
        def ring():
            ticks['left'] -= 1
            if ticks['left'] <= 0:
                box.done(0)
                return
            try:
                beep(urgent=True)
            except Exception:
                pass
        def finished(_result):
            timer.stop(); timer.deleteLater(); self.ring_box = None
        timer.timeout.connect(ring)
        box.finished.connect(finished)
        self.showNormal(); self.raise_(); self.activateWindow()
        box.open(); ring(); timer.start()

    def open_phone_app(self, package, attempts=0):
        """A pinned phone app: mirror it over the local network (docs/PHONE_SCREEN.md).

        Phones that offer the phone screen get a Cloud-delivered session offer that
        launches the app; other online phones get the same local session with a code to
        scan. scrcpy over authorised debugging is used only in the opt-in USB debugging
        mode (Settings → Advanced)."""
        from .phone_settings import flag
        devices = (self.workspace.state().get('phone') or {}).get('devices', [])
        online = [d for d in devices if d.get('online')]
        screens = [d for d in online if 'screen' in (d.get('screen') or [])]
        usb = flag(self.workspace.settings, 'usb_debugging')
        if not screens and not usb:
            # No scrcpy unless the owner opted in: any online phone gets a local session (QR in Phone → Apps).
            screens = online[:1]
        if screens:
            self.workspace.screen.reveal += 1  # The page opens Phone → Apps for this session.
            self.showNormal(); self.raise_(); self.activateWindow()
            def mirror():
                try:
                    self.workspace.screen.open_app(screens[0]['id'], package)
                except Exception as error:
                    self.update_checked.emit(str(error))
            threading.Thread(target=mirror, name='orion-phone-screen', daemon=True).start()
            return
        phones = [d for d in online if 'battery' in d.get('capabilities', [])] if usb else []
        if not phones:
            if attempts < 7:
                QTimer.singleShot(4000, lambda: self.open_phone_app(package, attempts + 1))
            else:
                self.tray.showMessage('Saiph', 'Your phone is offline. The app was not opened.', QSystemTrayIcon.Warning, 10000)
            return
        def run():
            try:
                from .adb_worker import AdbWorker
                from .phone_apps import open_app
                worker = AdbWorker()
                open_app(worker.adb, worker.paired_serial(phones[0]['id']), package)
            except Exception as error:
                self.update_checked.emit(str(error))
        threading.Thread(target=run, name='orion-phone-app', daemon=True).start()

    def confirm_send_files(self, paths, attempts=0):
        """The owner chooses the phone and confirms; nothing is sent before that."""
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        from .send_files import describe_files, targets, validate
        try:
            paths = validate(list(paths))
        except (ValueError, OSError) as error:
            self.tray.showMessage('Saiph', str(error), QSystemTrayIcon.Warning, 10000)
            return
        devices = targets(self.workspace.state())
        if not devices and attempts < 7:
            # The phone link may still be connecting just after start-up.
            QTimer.singleShot(4000, lambda: self.confirm_send_files(paths, attempts + 1))
            return
        if not devices:
            self.tray.showMessage('Saiph', 'Your phone is offline. Nothing was sent.', QSystemTrayIcon.Warning, 10000)
            return
        what = describe_files(paths)
        if len(devices) == 1:
            device = devices[0]
            if QMessageBox.question(self, 'Send to phone', f'Send {what} to {device["name"]}?') != QMessageBox.StandardButton.Yes:
                return
        else:
            names = [d['name'] for d in devices]
            name, chosen = QInputDialog.getItem(self, 'Send to phone', f'Send {what} to:', names, 0, False)
            if not chosen:
                return
            device = devices[names.index(name)]
        def run():
            for path in paths:
                try:
                    self.workspace.dispatch('phone.file.send', {'device_id': device['id'], 'path': path, 'notify': True})
                except Exception as error:
                    self.update_checked.emit(f'{Path(path).name}: {error}')
        threading.Thread(target=run, name='orion-send-files', daemon=True).start()

    def fill_phone_menu(self):
        from .tray_menu import phone_entries
        self.phone_menu.clear()
        try:
            rows = phone_entries(self.workspace.state())
        except Exception:
            rows = [('Phone status unavailable', None, None)]
        for label, method, args in rows:
            action = self.phone_menu.addAction(label)
            if method is None:
                action.setEnabled(False)
            else:
                action.triggered.connect(lambda _checked=False, m=method, a=args: self.tray_phone_action(m, a))

    def tray_phone_action(self, method, args):
        if method == 'window.show':
            self.showNormal(); self.activateWindow(); return
        if method == 'phone.file.choose':
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getOpenFileName(self, 'Send a file to your phone')
            if not path:
                return
            method, args = 'phone.file.send', {**args, 'path': path, 'notify': True}
        def run():
            try:
                self.workspace.dispatch(method, args)
            except Exception as error:
                self.update_checked.emit(str(error))  # Shown as a tray message.
        threading.Thread(target=run, name='orion-tray-phone', daemon=True).start()

    def update_from_tray(self):
        from .package_updates import current
        if current():
            self.showNormal()

            def check_package():
                try:
                    result = self.bridge.updates.check()  # Also lights the footer's Update button.
                    reason = result.get('reason')
                    message = ('Sign in to your Saiph account to check for updates.' if reason == 'cloud_signed_out'
                               else 'Your Saiph account does not offer desktop updates yet. Download the latest version from your account.'
                               if reason in ('cloud_unavailable', 'cloud_manual', 'cloud_unofficial')
                               else f"Saiph {result['release']['version']} is available. Select Update at the bottom of the Saiph window to install it." if result['available']
                               else 'You have the latest version.' if result.get('source') == 'cloud'
                               else 'You have the latest build available on your server.')
                except (OSError, ValueError, RuntimeError):
                    message = 'Updates are temporarily unavailable. Check Settings when your server is reachable.'
                self.update_checked.emit(message)
            threading.Thread(target=check_package, name='orion-update-check', daemon=True).start()
            return
        try:
            self.update_and_rebuild()
        except Exception as error:
            self.tray.showMessage('Saiph', f'Update did not start: {error}', QSystemTrayIcon.Warning, 10000)

    def run_on_gui(self, work, timeout=30):
        """Run work on the Qt thread from a non-GUI thread and wait for its result."""
        future = Future()
        self.automation_requested.emit((work, future))
        try:
            return future.result(timeout)
        except FutureTimeout:
            raise TimeoutError() from None

    def run_automation(self, item):
        work, future = item
        if not future.set_running_or_notify_cancel():
            return
        try:
            future.set_result(work())
        except Exception as error:
            future.set_exception(error)

    def restart_app(self):
        """Relaunch this same build once this instance has released its profile lock."""
        command = [sys.executable, *sys.argv[1:]] if getattr(sys, 'frozen', False) else [sys.executable, '-m', 'orion_mini', *sys.argv[1:]]
        env = {key: value for key, value in os.environ.items() if not key.startswith('_PYI') and key != '_MEIPASS2'}
        env['ORION_RELAUNCH_WAIT'] = '1'
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
        subprocess.Popen(command, env=env, cwd=os.getcwd(), creationflags=flags, close_fds=True,
                         start_new_session=sys.platform != 'win32')
        QTimer.singleShot(200, self.quit_app)

    def quit_app(self):
        self.closing = True
        self.workspace.camera.stop()
        self.workspace.screen.stop()
        self.phone_screen_window.shutdown()
        self.workspace.microphone.stop()
        self.phone_runtime.stop()
        hosted = getattr(self.workspace, '_hosted', None)
        if hosted is not None:
            hosted.stop()
        self.cloud_supervisor.stop()
        self.tick.stop()
        self.watch.stop()
        self.calendar_timer.stop()
        self.hub_timer.stop()
        self.api.stop()
        for job_id, process in list(self.processes.items()):
            job = self.workspace.store.get('job', job_id)
            self.workspace.store.save('job', {**job, 'status': 'interrupted', 'progress': 'App closed; resume from checkpoints'})
            self.stop_process(process)
            process.waitForFinished(1500)
        QApplication.instance().quit()

    def closeEvent(self, event):
        if self.workspace.settings.get('close_to_tray', True) and self.tray.isVisible():
            event.ignore()
            self.hide()
            return
        self.quit_app()
        event.accept()

def main():
    if '--cloud-rpc-worker' in sys.argv:
        if sys.argv[1:] != ['--cloud-rpc-worker']:
            return 2
        from .cloud_client import rpc_worker_main
        return rpc_worker_main()
    if '--worker' in sys.argv:
        addon = edition()
        if addon is None:
            return 2
        sys.argv.remove('--worker')
        return addon.worker_main()
    from .send_files import arguments as send_arguments
    sys.argv, send_paths = send_arguments(sys.argv)
    phone_app = None
    if '--open-phone-app' in sys.argv:
        index = sys.argv.index('--open-phone-app')
        if index + 1 >= len(sys.argv):
            return 2
        phone_app = sys.argv[index + 1]
        del sys.argv[index:index + 2]
    invitation = None
    if '--enrollment' in sys.argv:
        index = sys.argv.index('--enrollment')
        if index + 1 >= len(sys.argv):
            return 2
        invitation = sys.argv[index + 1]
        del sys.argv[index:index + 2]
    claim_taskbar_identity()
    qt_platform = qt_platform_for_background_clipboard()
    if qt_platform:
        os.environ['QT_QPA_PLATFORM'] = qt_platform
    prepare_web_engine(app_data_dir())
    app = QApplication(sys.argv)
    app.setApplicationName('Orion Mini')
    app.setApplicationDisplayName('Saiph')
    if sys.platform.startswith('linux'):
        app.setDesktopFileName('orion' if sys.platform.startswith('linux') and getattr(sys, 'frozen', False) else 'orion-mini')
    app.setWindowIcon(app_icon())
    lock = QLockFile(str(app_data_dir() / 'app.lock'))
    # A requested restart starts before the old instance exits; wait for its lock.
    relaunch = os.environ.pop('ORION_RELAUNCH_WAIT', None)
    if not lock.tryLock(30000 if relaunch else 100):
        if invitation:
            from .enrollment import forward_invitation
            return 0 if forward_invitation(app_data_dir(), invitation) else 2
        if send_paths:
            from .send_files import forward
            return 0 if forward(app_data_dir(), send_paths) else 2
        if phone_app:
            from .enrollment import forward_local
            return 0 if forward_local(app_data_dir(), '/v1/phone/app', {'package': phone_app}) else 2
        return 0
    app.setQuitOnLastWindowClosed(False)
    # Detection only, before any store opens: preserve evidence, never repair.
    try:
        health = check_databases(app_data_dir())
    except OSError:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(None, 'Saiph data check',
                            'Saiph could not check or preserve its databases. Your profile has not been opened. '
                            'Check disk space and folder permissions, then reopen Saiph. Do not delete your profile.')
        return 2
    if any(result == 'failed' for result in health['results'].values()):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(None, 'Saiph data check',
                            'A Saiph database failed its integrity check. A private copy was kept in '
                            + ', '.join(health['preserved'].values())
                            + '. Do not delete your profile; restore from a backup or repair a copy, then reopen Saiph.')
        return 2
    addon = edition()
    window = (addon.window_class() if addon else MainWindow)(bootstrap=not bool(os.environ.get('ORION_MINI_TEST')))
    if invitation:
        try:
            window.workspace.dispatch('enrollment.import', {'path': invitation})
        except (OSError, ValueError):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(window, 'Server invitation', 'This invitation could not be opened or has expired. Ask your server for a fresh one.')
    window.show()
    if phone_app:
        QTimer.singleShot(4000, lambda: window.open_phone_app(phone_app))
    if send_paths:
        # Started from Send to while Saiph was closed: ask once the phone link has had time to connect.
        QTimer.singleShot(4000, lambda: window.confirm_send_files(send_paths))
    return app.exec()
