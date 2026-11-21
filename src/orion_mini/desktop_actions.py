# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared desktop operation validation, independent of the GUI framework."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys
from contextlib import nullcontext

READ_ONLY_HOSTED = frozenset({"hosted.approvals", "hosted.requests", "hosted.link.status", "hosted.request.inspect",
                              "hosted.join.inspect", "hosted.join.account.inspect"})

class DesktopActions:
    def request(self, request_id: str, method: str, arguments: str):
        try:
            args = json.loads(arguments)
            if not isinstance(args, dict):
                raise ValueError("Expected an object.")
            if method == 'state':
                if set(args) - {'revision'} or ('revision' in args and
                        (not isinstance(args['revision'], str) or len(args['revision']) != 64
                         or any(c not in '0123456789abcdef' for c in args['revision']))):
                    raise ValueError('Invalid dashboard revision.')
                # Build a fresh snapshot: consent, connection and security state
                # must never be served from a stale timer cache. Only omit the
                # megabyte response when this page already has these exact bytes.
                store = getattr(self.window.workspace, 'store', None)
                with store.reading() if hasattr(store, 'reading') else nullcontext():
                    snapshot = self.window.workspace.dispatch('state', {})
                updates = getattr(self, 'updates', None)
                if updates is not None:
                    snapshot = {**snapshot, 'app_update': updates.status()}
                body = json.dumps(snapshot)
                revision = hashlib.sha256(body.encode()).hexdigest()
                packet = {'id': request_id, 'ok': True, 'revision': revision}
                if args.get('revision') == revision:
                    packet['unchanged'] = True
                    self.response.emit(json.dumps(packet))
                else:
                    self.response.emit(json.dumps(packet)[:-1] + ', "result": ' + body + '}')
                self.window.pump_jobs()
                return
            from .usage import BRIDGE_FEATURES, record
            if method == 'usage.screen':
                if set(args) != {'screen'} or not isinstance(args['screen'], str):
                    raise ValueError('Unknown screen.')
                action = self.window.workspace.usage_counter.screen_action(args['screen'])
                self.background(request_id, action, changed=False)
                return
            if method in BRIDGE_FEATURES:
                record(self.window.workspace, BRIDGE_FEATURES[method])
            if method == "app.update.check":
                if args:
                    raise ValueError("Check for updates takes no options.")
                self.background(request_id, self.updates.check)
                return
            elif method == "app.update.download":
                # Download and verify only. Installing is the separate Restart to update step.
                if set(args) != {"release"}:
                    raise ValueError("Choose an offered update.")
                self.background(request_id, lambda: self.updates.download(args["release"]))
                return
            elif method == "app.update.progress":
                from .package_updates import progress
                result = progress()
            elif method == "app.update.restart":
                if args:
                    raise ValueError("Restart to update takes no options.")
                self.background(request_id, self.updates.restart_to_update)
                return
            elif method == "app.update.now":
                # The footer's Update button: check again, download, verify, install, restart.
                if args:
                    raise ValueError("Update takes no options.")
                self.background(request_id, self.updates.update_now)
                return
            elif method == "enrollment.export":
                path, _ = self.dialogs.getSaveFileName(self.window, "Save a private invitation for another device", filter="Saiph invitation (*.orion-enrollment)")
                if path:
                    self.background(request_id, lambda: self.window.workspace.dispatch(method, {"path": path})); return
                result = {"cancelled": True}
            elif method == "enrollment.choose":
                path, _ = self.dialogs.getOpenFileName(self.window, "Open your server invitation", filter="Saiph invitation (*.orion-enrollment)")
                result = self.window.workspace.dispatch("enrollment.import", {"path": path}) if path else {"cancelled": True}
            elif method in {"enrollment.approve", "enrollment.qr", "hub.pair", "components.install", "components.sign_in"}:
                self.background(request_id, lambda: self.window.workspace.dispatch(method, args)); return
            elif method in {"continuity.open","continuity.copy"}:
                from .continuity import validate_handoff, received_file_handoff
                row=self.window.workspace.store.get('handoff',args['id'])
                if method=='continuity.open' and row['kind']=='file':
                    self.open_target(received_file_handoff(self.window.workspace,args['id']))
                else:
                    item=validate_handoff({'kind':row['kind'],'value':row['value']})
                    if method=='continuity.open' and item['kind']=='link':self.open_target(item['value'])
                    elif method=='continuity.copy' and item['kind']=='text':self.clipboard.setText(item['value'])
                    else:raise ValueError('This handoff does not support that action.')
                result={'ok':True}
            elif method=='continuity.platform':
                actions={'find':'https://www.google.com/android/find/','lock':'ms-settings:signinoptions'}
                if args.get('action') not in actions:raise ValueError('Unknown platform action.')
                self.open_target(actions[args['action']]);result={'opened':True}
            elif method == 'cloud.open':
                from .cloud import ensure_layout
                folders = {'root': '', 'Shared': 'Shared', 'Documents': 'Documents', 'Recordings': 'Recordings'}
                if args.get('folder') not in folders:
                    raise ValueError('Choose a Saiph Cloud folder.')
                if args['folder'] == 'Recordings' and not self.window.workspace.workspace_enabled:
                    raise ValueError('Recording transcription belongs to optional Workspace.')
                folder = ensure_layout(self.window.workspace.settings, personal=self.window.workspace.workspace_enabled) / folders[args['folder']]
                self.open_target(folder)
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
                folder = self.dialogs.getExistingDirectory(self.window, 'Choose a folder for your Cloud library')
                if folder:
                    chosen = {'folder': folder, 'libraries': list(args['libraries'])}
                    self.background(request_id, lambda: self.window.workspace.dispatch(method, chosen)); return
                result = {'cancelled': True}
            elif method == 'camera.session':
                if set(args) not in ({'preview'}, {'preview', 'resolution', 'fps', 'quality'}) or type(args['preview']) is not bool:
                    raise ValueError('Choose a camera session.')
                if 'fps' in args and (type(args['fps']) is not int or args['fps'] not in (15,20,30)
                        or type(args['resolution']) is not str or args['resolution'] not in ('720p','1080p')
                        or type(args['quality']) is not str or args['quality'] not in ('standard','high')):
                    raise ValueError('Choose a supported camera resolution, frame rate and image quality.')
                self.background(request_id,lambda:self.window.workspace.camera.start_local(**args));return
            elif method == 'camera.cancel_invite':
                if set(args) != {'session'} or not isinstance(args['session'],str) or len(args['session']) != 32:
                    raise ValueError('Choose a camera invitation.')
                self.background(request_id,lambda:self.window.workspace.camera.local.cancel_invite(args['session']));return
            elif method == 'camera.offer':
                # Web content names the session and phone only; the invitation never crosses the bridge.
                if (set(args) != {'session', 'device_id'} or not isinstance(args['session'], str) or len(args['session']) != 32
                        or not isinstance(args['device_id'], str) or not 0 < len(args['device_id']) <= 64):
                    raise ValueError('Choose a phone for the camera.')
                self.background(request_id,lambda:self.window.workspace.camera.offer_to_phone(args['session'], args['device_id']));return
            elif method == 'camera.frame':
                if args:raise ValueError('Unknown camera action.')
                result=self.window.workspace.camera.local.latest()
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
                self.open_target('https://github.com/Genymobile/scrcpy/blob/master/doc/camera.md');result={'opened':True}
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
                self.open_target('https://vb-audio.com/Cable/' if sys.platform == 'win32' else 'https://github.com/Genymobile/scrcpy/blob/v3.3.4/doc/audio.md#source')
                result={'opened':True}
            elif method in {"hosted.setup_root", "hosted.approve", "hosted.revoke", "hosted.sign_out", "hosted.file.save", "hosted.file.retry", "hosted.file.dismiss", "hosted.firewall.open", "hosted.root_code", "hosted.configure", "hosted.forget", "hosted.enable", "hosted.request.inspect", "hosted.sign_in", "hosted.notification.dismiss", "hosted.notification", "hosted.join.inspect", "hosted.join", "hosted.join.request", "hosted.requests", "hosted.link.start", "hosted.link.status", "hosted.link.stop", "hosted.link.approve", "hosted.join.account.inspect", "hosted.join.account", "hosted.approvals", "hosted.request.deny", "hosted.request.block"}:
                # Questions the page asks on a timer change nothing; answering them must
                # not make the page rebuild the whole snapshot as well.
                self.background(request_id, lambda: self.window.workspace.dispatch(method, args),
                                changed=method not in READ_ONLY_HOSTED); return
            elif method == "hosted.file.choose":
                path, _ = self.dialogs.getOpenFileName(self.window, "Send a file with Saiph Cloud")
                if path:
                    self.background(request_id, lambda: self.window.workspace.dispatch("hosted.file.send", {"target": args.get("target"), "path": path})); return
                result = {"cancelled": True}
            elif method in {"phone.file.choose","continuity.file.choose"}:
                path, _ = self.dialogs.getOpenFileName(self.window,"Send a file")
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
                self.clipboard.setText(code); result = {"copied": True}
            elif method == "setup.open":
                # Official release pages only, from a fixed list.
                from .setup_guide import LINKS
                if set(args) != {"link"} or args["link"] not in LINKS:raise ValueError("Unknown setup link.")
                self.open_target(LINKS[args["link"]]);result={"opened":True}
            elif method == "help.open":
                from .phone_settings import HELP_LINKS
                if set(args) != {"link"} or args["link"] not in HELP_LINKS:raise ValueError("Unknown help link.")
                self.open_target(HELP_LINKS[args["link"]]);result={"opened":True}
            elif method == "phone.files.folder":
                # Settings → Phone → Transferred files: the folder received files are saved in.
                from .phone_settings import received_folder
                folder=received_folder(self.window.workspace.settings);folder.mkdir(mode=0o700,parents=True,exist_ok=True)
                self.open_target(folder);result={"opened":True,"path":str(folder)}
            elif method == "phone.sms.attachment.open":
                row=self.window.workspace.phone_features._attachment(args)
                self.open_target(Path(row["path"]));result={"opened":True}
            elif method == "phone.file.open":
                row=self.window.workspace.store.get("phone_file",args["id"])
                if not row.get("path") or not Path(row["path"]).is_file():raise ValueError("This file is unavailable.")
                self.open_target(Path(row["path"]).parent);result={"opened":True}
            elif method == "phone.photo.drag":
                self.photo_drag(request_id,args);return
            elif method in {"phone.apps", "phone.app.open"}:
                # Default: the phone's own app list and screen over the local network (no adb).
                if method=="phone.apps" and (set(args)!={"device_id"} or not isinstance(args["device_id"],str)):
                    raise ValueError("Choose a phone.")
                if method=="phone.app.open" and (set(args)-{"name"}!={"device_id","package"} or not isinstance(args["device_id"],str)):
                    raise ValueError("Choose an app from the list.")
                screen=self.window.workspace.screen
                if method=="phone.apps":
                    self.background(request_id,lambda:screen.apps(args["device_id"]),changed=False);return
                self.background(request_id,lambda:screen.open_app(args["device_id"],args["package"],args.get("name","")));return
            elif method in {"phone.apps.legacy", "phone.app.open.legacy"}:
                # Advanced: scrcpy windows over the phone's authorised USB/wireless debugging,
                # only after the owner opted in under Settings → Advanced.
                from .phone_settings import flag
                if not flag(self.window.workspace.settings, "usb_debugging"):
                    raise ValueError("Turn on USB debugging in Settings → Advanced to use separate scrcpy windows.")
                def apps():
                    from .adb_worker import AdbWorker
                    from .phone_apps import list_apps, open_app
                    worker=AdbWorker();serial=worker.paired_serial(args["device_id"])
                    if method=="phone.apps.legacy":return list_apps(worker.adb,serial)
                    return open_app(worker.adb,serial,args.get("package"),args.get("name",""))
                self.background(request_id,apps);return
            elif method == "screen.session":
                if (set(args)-{"device_id"}!={"resolution","fps","quality"}
                        or ("device_id" in args and not isinstance(args["device_id"],str))):
                    raise ValueError("Choose a phone screen session.")
                screen=self.window.workspace.screen
                self.background(request_id,lambda:screen.start(args.get("device_id"),"",args["resolution"],args["fps"],args["quality"]));return
            elif method == "screen.cancel_invite":
                if set(args)!={"session"} or not isinstance(args["session"],str) or len(args["session"])!=32:
                    raise ValueError("Choose a phone screen invitation.")
                result=self.window.workspace.screen.session.cancel_invite(args["session"])
            elif method == "screen.invite":
                # A session started elsewhere (Mirror screen, a pinned app): its QR for the Apps tab.
                if args:raise ValueError("Unknown phone screen action.")
                result=self.window.workspace.screen.session.current_invite()
            elif method == "screen.frame":
                if args:raise ValueError("Unknown phone screen action.")
                result=self.window.workspace.screen.session.latest()
            elif method == "screen.input":
                if set(args)!={"event"}:raise ValueError("Unsupported phone screen input.")
                screen=self.window.workspace.screen.session
                self.background(request_id,lambda:screen.input(args["event"]),changed=False);return
            elif method == "screen.stop":
                if args:raise ValueError("Unknown phone screen action.")
                result=self.window.workspace.screen.stop()
            elif method == "phone.app.pin":
                from .phone_apps import pin
                result=pin(args.get("package"),args.get("name",""))
            elif method == "phone.app.icons":
                if set(args)!={"device_id","packages"} or not isinstance(args["device_id"],str):
                    raise ValueError("Choose apps from the list.")
                screen=self.window.workspace.screen
                self.background(request_id,lambda:screen.icons(args["device_id"],args["packages"]),changed=False);return
            elif method == "phone.app.favorite":
                if set(args)!={"device_id","package","pinned"} or not isinstance(args["device_id"],str):
                    raise ValueError("Choose an app from the list.")
                result=self.window.workspace.screen.pin(args["device_id"],args["package"],args["pinned"])
            elif method == "screen.window":
                if args:raise ValueError("Unknown phone screen action.")
                result=self.window.workspace.screen.raise_window()
            elif method == "phone.mirror":
                # Only the explicit USB debugging mode uses scrcpy; normal use is the local phone screen.
                from .phone_settings import flag
                if not flag(self.window.workspace.settings, "usb_debugging"):
                    raise ValueError("Phone screen uses your local network. Choose Mirror screen on the Phone page.")
                def mirror():
                    from .adb_worker import AdbWorker
                    from .phone_features import mirror_phone
                    worker=AdbWorker();serial=worker.paired_serial(args["device_id"])
                    return mirror_phone(worker.adb,serial)
                self.background(request_id,mirror);return
            elif method == "dialog.directory":
                path = self.dialogs.getExistingDirectory(self.window, args.get("title", "Choose folder"))
                result = {"path": path}
            elif method == "dialog.file":
                path, _ = self.dialogs.getOpenFileName(self.window, args.get("title", "Choose file"), filter=args.get("filter", "All files (*.*)"))
                result = {"path": path}
            elif method == "job.cancel":
                self.window.cancel_job(args["id"]); result = {"ok": True}
            elif method == "app.update":
                result = self.window.update_and_rebuild()
            elif method == "reminder.preview_urgent":
                self.window.preview_urgent_popup(int(args.get("stage", 0) or 0)); result = {"ok": True}
            elif method == "transcript.open_folder":
                result = self.window.workspace.dispatch(method, args)
                self.open_target(Path(result["path"]))
            else:
                result = self.window.workspace.dispatch(method, args)
                if method == "settings.save" and "start_with_windows" in args:
                    self.set_startup(bool(args["start_with_windows"]))
            self.response.emit(json.dumps({"id": request_id, "ok": True, "result": result}))
            # Reading a preview frame does not change app state. Broadcasting
            # changed here makes every frame request rebuild the full dashboard
            # state on the GUI thread, starving the next frame behind that work.
            if method not in {"state", "transcript.read", "search", "email.read", "camera.frame", "screen.frame", "usage.screen", "phone.app.icons"}:
                self.changed.emit()
            self.window.pump_jobs()
        except Exception as error:
            self.response.emit(json.dumps({"id": request_id, "ok": False, "error": str(error)}))
