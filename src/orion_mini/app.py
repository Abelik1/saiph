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
from PySide6.QtGui import QAction, QCursor, QIcon
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QPushButton, QSystemTrayIcon, QVBoxLayout
from .api import ApiServer, replay_inbox
from .automation import Automation
from .db_health import check as check_databases
from .modules import edition
from .desktop_bridge import DesktopBridge
from .paths import app_data_dir
from .platform import beep, qt_platform_for_background_clipboard, set_startup
from .updater import start_update
APP_MODEL_ID = 'OrionMini.Desktop'

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

class LocalPage(QWebEnginePage):

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        return url.isLocalFile() or url.scheme() in {'qrc', 'about'}

class DashboardView(QWebEngineView):
    """A web page cannot see a Windows file path, and Chromium answers a dropped
    file by navigating away from the dashboard. So Qt takes the drop first and
    hands the real paths to the page over the same channel everything else uses."""
    files_dropped = Signal(list)
    drag_changed = Signal(bool)
    DRAG_EVENTS = {QEvent.DragEnter, QEvent.DragMove, QEvent.DragLeave, QEvent.Drop}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.render_widget = None
        self.dragging = False
        self.loadFinished.connect(lambda _ok: self.watch_render_widget())

    def watch_render_widget(self):
        """Chromium renders into a child widget that owns its own drop handling,
        and replaces it across loads, so re-attach whenever it changes."""
        widget = self.focusProxy()
        if widget is not None and widget is not self.render_widget:
            self.render_widget = widget
            widget.installEventFilter(self)

    def event(self, event):
        if event.type() in {QEvent.ChildAdded, QEvent.ChildPolished}:
            self.watch_render_widget()
        return super().event(event)

    @staticmethod
    def local_files(mime) -> list[str]:
        return [url.toLocalFile() for url in mime.urls() if url.isLocalFile()] if mime.hasUrls() else []

    def set_dragging(self, active: bool) -> None:
        """Hovering repeats a move event many times a second; the page only needs
        to hear when the answer actually changes."""
        if active != self.dragging:
            self.dragging = active
            self.drag_changed.emit(active)

    def handle_drag(self, event) -> bool:
        """Answer one drag event; True means Chromium never sees it."""
        if event.type() == QEvent.DragLeave:
            self.set_dragging(False)
            return False
        files = self.local_files(event.mimeData())
        if not files:
            return False
        event.setDropAction(Qt.CopyAction)
        event.accept()
        dropping = event.type() == QEvent.Drop
        self.set_dragging(not dropping)
        if dropping:
            self.files_dropped.emit(files)
        return True

    def eventFilter(self, watched, event):
        if watched is self.render_widget and event.type() in self.DRAG_EVENTS and self.handle_drag(event):
            return True
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event):
        self.handle_drag(event)

    def dragMoveEvent(self, event):
        self.handle_drag(event)

    def dragLeaveEvent(self, event):
        self.handle_drag(event)

    def dropEvent(self, event):
        self.handle_drag(event)

class MainWindow(QMainWindow):
    phone_changed = Signal()
    clipboard_received = Signal(str, object)
    update_checked = Signal(str)
    restart_requested = Signal()
    automation_requested = Signal(object)
    security_alert = Signal(str)
    send_files_requested = Signal(object)
    open_phone_app_requested = Signal(str)
    ring_requested = Signal(str)

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
        if bootstrap:
            self.workspace.bootstrap()
            try:
                set_startup(bool(self.workspace.settings['start_with_windows']))
            except OSError:
                self.workspace.store.save('job', {'kind': 'startup', 'status': 'failed', 'error': 'This computer denied the startup setting. Check Settings → Advanced.'})
        for job in self.workspace.store.all('job'):
            if job['status'] == 'running':
                self.workspace.store.save('job', {**job, 'status': 'interrupted', 'progress': 'Stopped during the previous session; resume when ready.'})
        self.view = DashboardView(self)
        self.view.setPage(LocalPage(self.view))
        self.channel = QWebChannel(self.view.page())
        self.bridge = DesktopBridge(self)
        self.channel.registerObject('orionMini', self.bridge)
        self.phone_changed.connect(self.bridge.changed)
        from .phone import PhoneRuntime
        self.phone_runtime = PhoneRuntime(self.workspace, self.phone_changed.emit, clipboard_received=self.clipboard_received.emit)
        self.workspace.phone_runtime = self.phone_runtime
        from .cloud_client import CloudSupervisor
        self.cloud_supervisor = CloudSupervisor(self.workspace.root / 'cloud-client')
        if not os.environ.get('ORION_MINI_TEST'):
            from .clipboard import QtClipboard
            self.clipboard_adapter = QtClipboard(self.phone_runtime)
            self.clipboard_received.connect(self.clipboard_adapter.write)
            self.phone_runtime.start()
        self.view.page().setWebChannel(self.channel)
        self.view.files_dropped.connect(self.handle_dropped_files)
        self.view.drag_changed.connect(self.bridge.dragging)
        self.setCentralWidget(self.view)
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
        # Device-list changes are announced from the hosted worker thread; the
        # signal delivers them to the tray on the GUI thread.
        self.security_alert.connect(lambda message: self.tray.showMessage('Saiph security', message, QSystemTrayIcon.Warning, 15000))
        self.workspace.security_alert = self.security_alert.emit
        if not os.environ.get('ORION_MINI_TEST'):
            # Adding devices requires Windows Hello where it is set up. The handle
            # is read here, on the GUI thread; prompts run on worker threads.
            from .user_presence import UserPresence
            window_handle = int(self.winId())
            self.workspace.user_presence = UserPresence(lambda: window_handle)
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
        self.workspace.request_open_phone_app = self.open_phone_app_requested.emit
        self.automation_requested.connect(self.run_automation)
        self.workspace.automation_call = Automation(self.workspace, self.run_on_gui, self.bridge.changed.emit)
        self.api = ApiServer(self.workspace, 0 if os.environ.get('ORION_MINI_TEST') else None)
        self.workspace.api_info = self.api.start()
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
        controller.changed = self.bridge.changed.emit
        controller.start()

    def on_tick(self):
        if not os.environ.get('ORION_MINI_TEST'):
            self.cloud_supervisor.poll()
            self.ensure_hosted()
        if self.workspace.show_enrollment:
            self.workspace.show_enrollment = False
            self.showNormal()
            self.raise_()
            self.activateWindow()
        self.bridge.changed.emit()

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
        """A pinned phone app: open it from the first online phone over authorised debugging."""
        phones = [d for d in (self.workspace.state().get('phone') or {}).get('devices', []) if d.get('online') and 'battery' in d.get('capabilities', [])]
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
        from .send_files import targets, validate
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
        count = f'{len(paths)} file' + ('' if len(paths) == 1 else 's')
        if len(devices) == 1:
            device = devices[0]
            if QMessageBox.question(self, 'Send to phone', f'Send {count} to {device["name"]}?') != QMessageBox.StandardButton.Yes:
                return
        else:
            names = [d['name'] for d in devices]
            name, chosen = QInputDialog.getItem(self, 'Send to phone', f'Send {count} to:', names, 0, False)
            if not chosen:
                return
            device = devices[names.index(name)]
        def run():
            for path in paths:
                try:
                    self.workspace.dispatch('phone.file.send', {'device_id': device['id'], 'path': path})
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
        if method == 'phone.file.choose':
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getOpenFileName(self, 'Send a file to your phone')
            if not path:
                return
            method, args = 'phone.file.send', {**args, 'path': path}
        def run():
            try:
                self.workspace.dispatch(method, args)
            except Exception as error:
                self.update_checked.emit(str(error))  # Shown as a tray message.
        threading.Thread(target=run, name='orion-tray-phone', daemon=True).start()

    def update_from_tray(self):
        from .package_updates import current, check
        if current():
            self.showNormal()

            def check_package():
                try:
                    result = check(self.workspace.root, dict(self.workspace.settings['hub']))
                    message = f"Saiph {result['release']['version']} is available. Open Settings to install it." if result['available'] else 'You have the latest build available on your server.'
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
