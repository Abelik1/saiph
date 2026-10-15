# SPDX-License-Identifier: AGPL-3.0-or-later
"""Finite request/response boundary for the local dashboard."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot, QMimeData, QMimeDatabase, QUrl, QTimer, Qt
from PySide6.QtGui import QDrag, QImageIOHandler, QImageReader
from PySide6.QtWidgets import QFileDialog, QApplication

from .platform import set_startup, open_target


class DesktopBridge(QObject):
    response = Signal(str)
    changed = Signal()
    # Windows drops arrive at Qt, never at the page, so they travel back down this way.
    dropped = Signal(str)
    dragging = Signal(bool)
    completed = Signal(str)
    update_ready = Signal()
    photo_prepared = Signal(str, object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.completed.connect(self.finish)
        self.photo_prepared.connect(self.finish_photo)
        self.update_ready.connect(lambda: QTimer.singleShot(700, self.window.quit_app))

    @Slot(str)
    def finish(self, packet):
        self.response.emit(packet)
        self.changed.emit()
        self.window.pump_jobs()

    def background(self, request_id, action):
        def run():
            try: packet={"id":request_id,"ok":True,"result":action()}
            except Exception as error: packet={"id":request_id,"ok":False,"error":str(error)}
            self.completed.emit(json.dumps(packet))
        threading.Thread(target=run,name="orion-phone-action",daemon=True).start()

    def photo_original(self, request_id, method, args):
        if set(args) != {"device_id", "photo_id"} or not all(isinstance(value, str) and value for value in args.values()):
            raise ValueError("Choose a photo from a paired phone.")
        def prepare():
            try:
                features = self.window.workspace.phone_features
                with features.lock:
                    features.photo_request(args["device_id"], args["photo_id"], "prefetch")
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    row = features.photo_cached(args["device_id"], args["photo_id"])
                    if row:
                        result, clipboard = self.prepare_photo(row, method == "phone.photo.copy")
                        self.photo_prepared.emit(json.dumps({"id": request_id, "result": result}), clipboard)
                        return
                    time.sleep(0.1)
                raise ValueError("Your phone has not sent the original yet. Try again when it is connected.")
            except Exception as error:
                self.completed.emit(json.dumps({"id": request_id, "ok": False, "error": str(error)}))
        threading.Thread(target=prepare, name="orion-photo-original", daemon=True).start()

    @staticmethod
    def prepare_photo(row, copying):
        # Decode and read bytes away from the GUI thread. Only clipboard ownership
        # crosses back to Qt's GUI thread, including for large phone originals.
        path = Path(row["path"])
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        if not reader.canRead():
            raise ValueError("This image format cannot be opened here. Save the original to open it in another app.")
        size = reader.size()
        if reader.transformation() & QImageIOHandler.Transformation.TransformationRotate90:
            size.transpose()
        result = {"url": QUrl.fromLocalFile(str(path)).toString(), "width": size.width(), "height": size.height(), "size": path.stat().st_size}
        if not copying:
            return result, None
        image = reader.read()
        if image.isNull():
            raise ValueError("The original image could not be copied. Try saving it instead.")
        mime = QMimeDatabase().mimeTypeForFile(str(path)).name()
        encoded = path.read_bytes() if mime.startswith("image/") else None
        return {"copied": True, "width": image.width(), "height": image.height()}, (image, mime, encoded)

    @Slot(str, object)
    def finish_photo(self, raw, clipboard):
        packet = json.loads(raw)
        try:
            if clipboard is not None:
                image, mime, encoded = clipboard
                data = QMimeData()
                data.setImageData(image)
                if encoded is not None:
                    data.setData(mime, encoded)
                QApplication.clipboard().setMimeData(data)
            self.finish(json.dumps({"id": packet["id"], "ok": True, "result": packet["result"]}))
        except Exception as error:
            self.finish(json.dumps({"id": packet["id"], "ok": False, "error": str(error)}))

    def photo_drag(self, request_id, args):
        workspace = self.window.workspace
        workspace.dispatch("phone.photo.prefetch", args)
        timer = QTimer(self)
        timer.setInterval(100)
        deadline = time.monotonic() + 30
        def poll():
            try:
                row = workspace.phone_features.photo_cached(args["device_id"],args["photo_id"])
                held = bool(QApplication.mouseButtons() & Qt.MouseButton.LeftButton)
                if row and held:
                    timer.stop(); timer.deleteLater()
                    data=QMimeData();data.setUrls([QUrl.fromLocalFile(row["path"])])
                    drag=QDrag(self.window);drag.setMimeData(data);drag.exec()
                    result={"dragged":True}
                elif not held or time.monotonic() >= deadline:
                    timer.stop(); timer.deleteLater(); result={"preparing":not bool(row),"ready":bool(row)}
                else:return
                self.finish(json.dumps({"id":request_id,"ok":True,"result":result}))
            except Exception as error:
                timer.stop(); timer.deleteLater()
                self.finish(json.dumps({"id":request_id,"ok":False,"error":str(error)}))
        timer.timeout.connect(poll)
        timer.start()

    @Slot(str, str, str)
    def request(self, request_id: str, method: str, arguments: str):
        try:
            args = json.loads(arguments)
            if not isinstance(args, dict):
                raise ValueError("Expected an object.")
            from .usage import BRIDGE_FEATURES, record
            if method in BRIDGE_FEATURES:
                record(self.window.workspace, BRIDGE_FEATURES[method])
            if method == "app.update.check":
                from .package_updates import check
                self.background(request_id, lambda: check(self.window.workspace.root, dict(self.window.workspace.settings['hub'])))
                return
            elif method == "app.update.install":
                from .package_updates import stage, install
                def install_update():
                    workspace = self.window.workspace
                    staged = stage(workspace.root, dict(workspace.settings['hub']), args.get('release'))
                    result = install(workspace.root, staged)
                    self.update_ready.emit()
                    return result
                self.background(request_id, install_update)
                return
            elif method == "enrollment.export":
                path, _ = QFileDialog.getSaveFileName(self.window, "Save a private invitation for another device", filter="Saiph invitation (*.orion-enrollment)")
                if path:
                    self.background(request_id, lambda: self.window.workspace.dispatch(method, {"path": path})); return
                result = {"cancelled": True}
            elif method == "enrollment.choose":
                path, _ = QFileDialog.getOpenFileName(self.window, "Open your server invitation", filter="Saiph invitation (*.orion-enrollment)")
                result = self.window.workspace.dispatch("enrollment.import", {"path": path}) if path else {"cancelled": True}
            elif method in {"enrollment.approve", "enrollment.qr", "hub.pair", "components.install", "components.sign_in"}:
                self.background(request_id, lambda: self.window.workspace.dispatch(method, args)); return
            elif method in {"continuity.open","continuity.copy"}:
                from .continuity import validate_handoff, received_file_handoff
                row=self.window.workspace.store.get('handoff',args['id'])
                if method=='continuity.open' and row['kind']=='file':
                    open_target(received_file_handoff(self.window.workspace,args['id']))
                else:
                    item=validate_handoff({'kind':row['kind'],'value':row['value']})
                    if method=='continuity.open' and item['kind']=='link':open_target(item['value'])
                    elif method=='continuity.copy' and item['kind']=='text':QApplication.clipboard().setText(item['value'])
                    else:raise ValueError('This handoff does not support that action.')
                result={'ok':True}
            elif method=='continuity.platform':
                actions={'find':'https://www.google.com/android/find/','lock':'ms-settings:signinoptions'}
                if args.get('action') not in actions:raise ValueError('Unknown platform action.')
                open_target(actions[args['action']]);result={'opened':True}
            elif method == 'cloud.open':
                from .cloud import ensure_layout
                folders = {'root': '', 'Shared': 'Shared', 'Documents': 'Documents', 'Recordings': 'Recordings'}
                if args.get('folder') not in folders:
                    raise ValueError('Choose a Saiph Cloud folder.')
                if args['folder'] == 'Recordings' and not self.window.workspace.workspace_enabled:
                    raise ValueError('Recording transcription belongs to optional Workspace.')
                folder = ensure_layout(self.window.workspace.settings, personal=self.window.workspace.workspace_enabled) / folders[args['folder']]
                open_target(folder)
                result = {'opened': True}
            elif method in {'cloud.info', 'cloud.client.open', 'cloud.client.install'}:
                if args:
                    raise ValueError('Choose a supported file sync action.')
                self.background(request_id, lambda: self.window.workspace.dispatch(method, {})); return
            elif method == 'cloud.setup':
                if set(args) != {'libraries'} or not isinstance(args['libraries'], list) or len(args['libraries']) != 1 or not isinstance(args['libraries'][0], str):
                    raise ValueError('Choose one library for this computer.')
                # Only this native picker can approve the local folder. Web
                # content cannot supply a destination or credential fields.
                folder = QFileDialog.getExistingDirectory(self.window, 'Choose a folder for your Cloud library')
                if folder:
                    chosen = {'folder': folder, 'libraries': list(args['libraries'])}
                    self.background(request_id, lambda: self.window.workspace.dispatch(method, chosen)); return
                result = {'cancelled': True}
            elif method == 'camera.start':
                # A self-hosted paired phone (device_id) or a phone allowed over USB/wireless debugging (serial).
                if not isinstance(args, dict) or set(args) - {'device_id', 'serial', 'preview'} or len(set(args) & {'device_id', 'serial'}) != 1 \
                        or not all(isinstance(args[key], str) for key in set(args) & {'device_id', 'serial'}) or type(args.get('preview', False)) is not bool:
                    raise ValueError('Choose one phone for the camera.')
                self.background(request_id,lambda:self.window.workspace.camera.start(args.get('device_id'), args.get('serial'), args.get('preview', False)));return
            elif method == 'camera.devices':
                if args:raise ValueError('Unknown camera action.')
                self.background(request_id,self.window.workspace.camera.debug_devices);return
            elif method == 'camera.pair':
                if set(args) != {'address', 'code'}:raise ValueError('Enter the pairing address and code from your phone.')
                self.background(request_id,lambda:self.window.workspace.camera.pair(args['address'], args['code']));return
            elif method == 'camera.connect':
                if set(args) != {'address'}:raise ValueError('Enter the address from your phone.')
                self.background(request_id,lambda:self.window.workspace.camera.connect(args['address']));return
            elif method == 'camera.stop':
                self.background(request_id,self.window.workspace.camera.stop);return
            elif method == 'camera.status':
                result=self.window.workspace.camera.status()
            elif method == 'camera.help':
                open_target('https://github.com/Genymobile/scrcpy/blob/master/doc/camera.md');result={'opened':True}
            elif method == 'microphone.start':
                if set(args) != {'device_id'} or not isinstance(args['device_id'], str):
                    raise ValueError('Choose a paired phone.')
                self.background(request_id, lambda: self.window.workspace.microphone.start(args['device_id']));return
            elif method == 'microphone.stop':
                if args:raise ValueError('Unknown microphone action.')
                self.background(request_id, self.window.workspace.microphone.stop);return
            elif method == 'microphone.mute':
                if set(args) != {'muted'} or type(args['muted']) is not bool:
                    raise ValueError('Phone microphone mute is on or off.')
                self.background(request_id, lambda: self.window.workspace.microphone.mute(args['muted']));return
            elif method == 'microphone.help':
                if args:raise ValueError('Unknown microphone action.')
                open_target('https://vb-audio.com/Cable/' if sys.platform == 'win32' else 'https://github.com/Genymobile/scrcpy/blob/v3.3.4/doc/audio.md#source')
                result={'opened':True}
            elif method in {"hosted.setup_root", "hosted.approve", "hosted.revoke", "hosted.sign_out", "hosted.file.save", "hosted.root_code", "hosted.configure", "hosted.forget", "hosted.enable", "hosted.request.inspect", "hosted.sign_in", "hosted.notification.dismiss", "hosted.join.inspect", "hosted.join", "hosted.join.request", "hosted.requests"}:
                self.background(request_id, lambda: self.window.workspace.dispatch(method, args)); return
            elif method == "hosted.file.choose":
                path, _ = QFileDialog.getOpenFileName(self.window, "Send a file with Saiph Hosted")
                if path:
                    self.background(request_id, lambda: self.window.workspace.dispatch("hosted.file.send", {"target": args.get("target"), "path": path})); return
                result = {"cancelled": True}
            elif method in {"phone.file.choose","continuity.file.choose"}:
                path, _ = QFileDialog.getOpenFileName(self.window,"Send a file")
                if path:
                    self.background(request_id,lambda:self.window.workspace.dispatch("phone.file.send",{**args,"path":path}));return
                result={"cancelled":True}
            elif method in {"phone.photo.view", "phone.photo.copy"}:
                self.photo_original(request_id, method, args);return
            elif method in {"phone.file.send","phone.photo.save","phone.photo.prefetch"}:
                self.background(request_id,lambda:self.window.workspace.dispatch(method,args));return
            elif method == "phone.code.copy":
                from .codes import verification_code
                row = self.window.workspace.store.get("phone_notification", str(args["id"]))
                code = verification_code(row.get("title"), row.get("text"))
                if not code: raise ValueError("This notification has no verification code.")
                QApplication.clipboard().setText(code); result = {"copied": True}
            elif method == "setup.open":
                # Official release pages only, from a fixed list.
                from .setup_guide import LINKS
                if set(args) != {"link"} or args["link"] not in LINKS:raise ValueError("Unknown setup link.")
                open_target(LINKS[args["link"]]);result={"opened":True}
            elif method == "phone.sms.attachment.open":
                row=self.window.workspace.phone_features._attachment(args)
                open_target(Path(row["path"]));result={"opened":True}
            elif method == "phone.file.open":
                row=self.window.workspace.store.get("phone_file",args["id"])
                if not row.get("path") or not Path(row["path"]).is_file():raise ValueError("This file is unavailable.")
                open_target(Path(row["path"]).parent);result={"opened":True}
            elif method == "phone.photo.drag":
                self.photo_drag(request_id,args);return
            elif method in {"phone.apps", "phone.app.open"}:
                def apps():
                    from .adb_worker import AdbWorker
                    from .phone_apps import list_apps, open_app
                    worker=AdbWorker();serial=worker.paired_serial(args["device_id"])
                    if method=="phone.apps":return list_apps(worker.adb,serial)
                    return open_app(worker.adb,serial,args.get("package"),args.get("name",""))
                self.background(request_id,apps);return
            elif method == "phone.app.pin":
                from .phone_apps import pin
                result=pin(args.get("package"),args.get("name",""))
            elif method == "phone.mirror":
                def mirror():
                    from .adb_worker import AdbWorker
                    from .phone_features import mirror_phone
                    worker=AdbWorker();serial=worker.paired_serial(args["device_id"])
                    return mirror_phone(worker.adb,serial)
                self.background(request_id,mirror);return
            elif method == "dialog.directory":
                path = QFileDialog.getExistingDirectory(self.window, args.get("title", "Choose folder"))
                result = {"path": path}
            elif method == "dialog.file":
                path, _ = QFileDialog.getOpenFileName(self.window, args.get("title", "Choose file"), filter=args.get("filter", "All files (*.*)"))
                result = {"path": path}
            elif method == "job.cancel":
                self.window.cancel_job(args["id"]); result = {"ok": True}
            elif method == "app.update":
                result = self.window.update_and_rebuild()
            elif method == "reminder.preview_urgent":
                self.window.preview_urgent_popup(int(args.get("stage", 0) or 0)); result = {"ok": True}
            elif method == "transcript.open_folder":
                result = self.window.workspace.dispatch(method, args)
                open_target(Path(result["path"]))
            else:
                result = self.window.workspace.dispatch(method, args)
                if method == "settings.save" and "start_with_windows" in args:
                    set_startup(bool(args["start_with_windows"]))
            self.response.emit(json.dumps({"id": request_id, "ok": True, "result": result}))
            if method not in {"state", "transcript.read", "search", "email.read"}:
                self.changed.emit()
            self.window.pump_jobs()
        except Exception as error:
            self.response.emit(json.dumps({"id": request_id, "ok": False, "error": str(error)}))
