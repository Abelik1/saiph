# SPDX-License-Identifier: AGPL-3.0-or-later
"""Desktop phone state and a single signed mesh loop, independent of the window."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
import time
from uuid import uuid4

from .hub_client import signed
from .link_client import LinkClient
from .clipboard import PendingClipboard, RecentClipboard, envelope
from .peer import PeerServer, fetch
from .peer import MAX_CLIPBOARD
from .adb_worker import AdbWorker
from .continuity import Continuity
from .agent_grants import ensure as ensure_grants
from .phone_features import MAX_FILE
from .codes import verification_code
from .callpause import CallPause

MESH_ORIGIN = "http://100.64.0.1:8765"
LOW_BATTERY = 20  # Alert once at or below this level; re-arm after charging or above RECOVERED.
RECOVERED = 30

def capabilities(settings):
    result = ['notifications', 'files', 'handoff', 'focus']
    if (settings.get('link') or {}).get('clipboard',True):result.append('clipboard')
    if (settings.get('cloud') or {}).get('enabled', True): result.append('cloud.files')
    if ((settings.get('link') or {}).get('remote') or {}).get('enabled') is True: result.append('remote')
    return result

def notification_id(device: str, key: str) -> str:
    return hashlib.sha256((device + "\0" + key).encode()).hexdigest()

class PhoneState:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.devices: list[dict] = []
        self.status = "Unpaired"
        self.error = ""
        self.connected = False

    def snapshot(self):
        with self.lock:
            devices = [{**d, "online": self.connected and d.get("online", False)} for d in self.devices]
            state = {"devices": devices, "status": self.status, "error": self.error}
        notices = [{**n, "code": verification_code(n.get("title"), n.get("text"))} for n in self.store.all("phone_notification")[:1000]]
        return {**state, "notifications": notices}

    def restore(self, state: dict):
        current = {notification_id(n["device_id"], n["key"]): n for n in state["notifications"]}
        from .models import utc_now
        with self.store.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            old=connection.execute("SELECT id FROM records WHERE kind='phone_notification'").fetchall()
            connection.executemany("DELETE FROM records WHERE kind='phone_notification' AND id=?",((ident,) for (ident,) in old if ident not in current))
            connection.executemany('INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data',
                (('phone_notification',ident,json.dumps({**item,'id':ident,'updated_at':utc_now()})) for ident,item in current.items()))
        with self.lock:self.devices = state["devices"]

    def event(self, event: dict):
        kind, source, body = event["type"], event["source"], event["payload"]
        with self.lock:
            if kind == "battery":
                for device in self.devices:
                    if device["id"] == source:
                        device["battery"] = {**body, "updated_at": event["created_at"]}
            elif kind == "notification.upsert":
                return self.store.save("phone_notification", {**body, "device_id": source, "id": notification_id(source, body["key"])})
            elif kind == "notification.remove":
                self.store.delete("phone_notification", notification_id(source, body["key"]))
            elif kind == "notification.sync":
                keys = set(body["keys"])
                for row in self.store.all("phone_notification"):
                    if row["device_id"] == source and row["key"] not in keys:
                        self.store.delete("phone_notification", row["id"])
        return None

def _windows_notification_display_name():
    # desktop-notifier falls back to its app_name as the toast identity for
    # unpackaged Windows processes. Preserve that old identity and its settings.
    from desktop_notifier.backends.winrt import CoreApplication, register_hkey
    register_hkey(app_id=CoreApplication.id or "Orion Mini", app_name="Saiph")


class NativeNotifications:
    """Notification contents go to the OS renderer only. No library payload logging."""
    def __init__(self, command):
        import logging
        # The upstream backend's DEBUG representation includes message text.
        logging.getLogger("desktop_notifier").setLevel(logging.CRITICAL + 1)
        from desktop_notifier import DesktopNotifier
        import sys
        self.notifier = DesktopNotifier(app_name="Orion Mini" if sys.platform == "win32" else "Saiph", notification_limit=100)
        if sys.platform == "win32":
            _windows_notification_display_name()
            self.notifier.app_name = "Saiph"
        self.command = command
        self.copy = None  # Set by the runtime: places a verification code on the clipboard.
        self.ids = {}
        self.suppressed = set()

    async def show(self, row):
        from desktop_notifier import Button, ReplyField
        key = notification_id(row["device_id"], row["key"])
        await self.clear(key)
        def invoke(operation, **extra):
            try:
                self.command(row, operation, **extra)
            except ValueError:
                pass  # Stale/offline native actions never execute later unexpectedly.
        code = verification_code(row.get("title"), row.get("text")) if self.copy else None
        buttons = [Button(title="Copy " + code, on_pressed=lambda: self.copy(code))] if code else []
        buttons += [Button(title=a["label"], on_pressed=lambda index=a["index"]: invoke("action", index=index)) for a in row["actions"][:4 - len(buttons)]]
        # All platforms support buttons; Linux inline reply is unavailable. The feed
        # remains the reply editor there, while Windows uses its native input field.
        import sys
        reply = ReplyField(on_replied=lambda text: invoke("reply", text=text, reply_key=row["reply_key"])) if row.get("reply_key") and sys.platform == "win32" else None
        token = object()
        def dismissed():
            if token not in self.suppressed:
                invoke("dismiss")
        ident = await self.notifier.send(title=row["app"] + " · " + row["title"], message=row["text"],
                                         buttons=buttons, reply_field=reply, on_clicked=lambda: invoke("open"),
                                         on_dismissed=dismissed, thread=key)
        self.ids[key] = (ident, token)

    async def clear(self, key):
        old = self.ids.pop(key, None)
        if old:
            self.suppressed.add(old[1])
            await self.notifier.clear(old[0])
            # Keep delayed callbacks suppressed, bounded by active/recent notices.
            if len(self.suppressed) > 2000:
                self.suppressed = {old[1]}

    async def announce(self, title, message, buttons=(), clicked=None):
        from desktop_notifier import Button
        await self.notifier.send(title=title, message=message, on_clicked=clicked,
                                 buttons=[Button(title=label, on_pressed=action) for label, action in buttons])

    async def reconcile(self, current):
        for key in set(self.ids) - current:
            await self.clear(key)

class PhoneRuntime:
    def __init__(self, workspace, changed=lambda: None, notifier_factory=NativeNotifications, clipboard_received=lambda *_: None, worker_factory=AdbWorker):
        self.workspace, self.state, self.changed = workspace, workspace.phone, changed
        self.notifier_factory = notifier_factory
        self.thread = None
        self.loop = None
        self.client = None
        self.stop_requested = threading.Event()
        self.clipboard_received = clipboard_received
        self.clipboard_cache = RecentClipboard()
        self.pending_clipboard = PendingClipboard()
        self.clipboard_publication = None
        self.clipboard_flush_lock = asyncio.Lock()
        self.peer = None
        self.worker_factory = worker_factory
        self.features = workspace.phone_features
        self.features.changed = changed
        self.features.capture_ready = self.capture_ready
        self.features.photo_new = self.photo_new
        self.native = None
        self.low_battery = set()
        self.copied_codes = set()  # (notification, code) already copied automatically.
        self.call_pause = CallPause(workspace.settings)
        self.continuity = Continuity(workspace,self.publish)

    def battery_notice(self, source, body):
        """A one-time low-battery message for a phone that is draining, or None."""
        if (self.workspace.settings.get('link') or {}).get('battery_alerts') is False:
            return None
        level, charging = body.get('battery_level'), body.get('is_charging')
        if type(level) is not int or not isinstance(charging, bool):
            return None
        if charging or level >= RECOVERED:
            self.low_battery.discard(source)
            return None
        if level > LOW_BATTERY or source in self.low_battery:
            return None
        self.low_battery.add(source)
        with self.state.lock:
            name = next((d['name'] for d in self.state.devices if d['id'] == source), 'Your phone')
        return f'{name} battery is low ({level}%). Charge it soon.'

    def copy_code(self, code):
        """A verification code from the phone, placed on this computer's clipboard."""
        if not isinstance(code, str) or not code.isdigit() or not 4 <= len(code) <= 8:
            return
        self.clipboard_cache.claim('text/plain', code.encode())
        self.clipboard_received('text/plain', code.encode())

    def photo_new(self, row):
        """A screenshot or photo just taken on the phone: offer Copy and Save. Nothing transfers until clicked."""
        if (self.workspace.settings.get('link') or {}).get('new_photo_notices') is False:
            return
        if not self.native or not self.loop or self.continuity.focus.quiet:
            return
        with self.state.lock:
            name = next((d['name'] for d in self.state.devices if d['id'] == row['device_id']), 'your phone')
        kind = 'screenshot' if 'screenshot' in str(row.get('name', '')).lower() else 'photo'
        def act(mode):
            try:
                self.features.photo_request(row['device_id'], row['photo_id'], mode)
            except ValueError:
                pass  # Offline: the notice simply does nothing now.
        buttons = [('Copy', lambda: act('copy')), ('Save', lambda: act('save'))]
        asyncio.run_coroutine_threadsafe(self.native.announce(f'New {kind} from {name}', 'Copy it to paste here, or save it to Downloads.', buttons), self.loop)

    def capture_ready(self, row, mime, data):
        """A photo taken on the phone for this computer: ready to paste, with a notice."""
        # Mark it as already synced, so it is not sent straight back to the phone.
        self.clipboard_cache.claim(mime, data)
        self.clipboard_received(mime, data)
        with self.state.lock:
            name = next((d['name'] for d in self.state.devices if d['id'] == row['device_id']), 'your phone')
        if self.native and self.loop:
            asyncio.run_coroutine_threadsafe(self.native.announce('Photo ready to paste', f'From {name}. Paste it into any app with Ctrl+V.'), self.loop)
        self.changed()

    def publish(self, event):
        if not self.client or not self.loop or not self.state.connected:raise ValueError('Connection is unavailable. This action has not been sent.')
        if event['type']=='handoff':
            targets={d['id'] for d in self.state.snapshot()['devices'] if d.get('online') and 'handoff' in d.get('capabilities',[])}
            if not set(event.get('targets',[]))<=targets:raise ValueError('This device is unavailable for Handoff.')
        self.loop.call_soon_threadsafe(self.client.publish,event)

    def local_clipboard(self, mime, data):
        config = self.workspace.settings.get('hub') or {}
        owner = config.get('device_id') if config.get('paired') else None
        if not owner or (self.workspace.settings.get('link') or {}).get('clipboard') is False:
            self.pending_clipboard.clear(); return
        digest = hashlib.sha256(data).hexdigest()
        if self.clipboard_cache.contains_digest(mime, digest):
            self.pending_clipboard.clear()
            if self.loop: self.loop.call_soon_threadsafe(self.discard_superseded_clipboard, mime, digest)
            return
        # Preserve the existing online oversized-clipboard file path. Offline
        # retry holds at most 16 MiB; it never retains a large file in RAM.
        limit = MAX_FILE if self.state.connected else self.pending_clipboard.MAX_BYTES
        if not self.pending_clipboard.replace(owner, mime, data, max_bytes=limit):
            if self.loop: self.loop.call_soon_threadsafe(self.discard_superseded_clipboard, mime, digest)
            self.state.error = 'Clipboard content is too large to hold for automatic retry.'
            self.changed(); return
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.flush_clipboard(), self.loop)

    def discard_clipboard_publication(self):
        publication = self.clipboard_publication
        if publication:
            publication[0].discard(publication[1])
            self.clipboard_publication = None

    def discard_superseded_clipboard(self, mime, digest):
        if self.clipboard_publication and self.clipboard_publication[3:] != (mime, digest):
            self.discard_clipboard_publication()

    def reconcile_clipboard_publication(self):
        publication = self.clipboard_publication
        config = self.workspace.settings.get('hub') or {}
        if publication and (not config.get('paired') or config.get('device_id') != publication[2] or
                            (self.workspace.settings.get('link') or {}).get('clipboard') is False):
            self.discard_clipboard_publication()

    async def flush_clipboard(self):
        async with self.clipboard_flush_lock:
            self.reconcile_clipboard_publication()
            change = self.pending_clipboard.current()
            if not change: return
            self.discard_clipboard_publication()
            config = self.workspace.settings.get('hub') or {}
            if not config.get('paired') or config.get('device_id') != change.owner or (self.workspace.settings.get('link') or {}).get('clipboard') is False:
                self.pending_clipboard.clear(); return
            if not self.state.connected:
                if len(change.data) > self.pending_clipboard.MAX_BYTES: self.pending_clipboard.clear()
                return
            if not self.client or self.client.device_id != change.owner: return
            kind = 'file.offer' if len(change.data) > MAX_CLIPBOARD else 'clipboard'
            capability = 'files' if kind == 'file.offer' else 'clipboard'
            def targets():
                with self.state.lock:
                    return [d['id'] for d in self.state.devices if d.get('online') and capability in d.get('capabilities',[]) and d['id'] != change.owner]
            if not targets(): return
            try:
                if kind == 'file.offer':
                    suffix = {'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}.get(change.mime,'txt')
                    payload = await asyncio.to_thread(self.features.offer_bytes,change.mime,change.data,'Clipboard.'+suffix)
                else:
                    payload = await asyncio.to_thread(envelope, change.mime, change.data, change.digest, self.peer)
                if not self.state.connected or not self.client or self.client.device_id != change.owner: return
                live_config = self.workspace.settings.get('hub') or {}
                if not live_config.get('paired') or live_config.get('device_id') != change.owner or (self.workspace.settings.get('link') or {}).get('clipboard') is False:
                    self.pending_clipboard.clear(); return
                selected = targets()
                if not selected: return
                def publish():
                    event_id = str(uuid4())
                    self.client.publish({'id':event_id,'type':kind,'targets':selected,'ttl_seconds':300 if kind=='file.offer' else 30,'payload':payload})
                    self.clipboard_publication = (self.client, event_id, change.owner, change.mime, change.digest)
                    # The published value replaces the last synced one.
                    self.clipboard_cache.claim(change.mime, change.data)
                self.pending_clipboard.commit(change, publish)
            except ValueError:
                self.state.error = 'Clipboard content needs a direct file transfer.'; self.changed()
            except (OSError, RuntimeError):
                self.state.error = 'Clipboard sharing will retry automatically.'; self.changed()

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=lambda: asyncio.run(self.run()), name="orion-link", daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_requested.set()
        self.pending_clipboard.clear()
        if self.thread:
            self.thread.join(timeout=3)
        self.features.stop()

    def command(self, row, operation, **extra):
        if not self.client or not self.loop or not self.state.connected:
            raise ValueError("Your phone is offline. This action has not been sent.")
        current = self.state.snapshot()
        phone = next((d for d in current["devices"] if d["id"] == row["device_id"] and d.get("online") and "notifications" in d.get("capabilities", [])), None)
        if phone is None:
            raise ValueError("Notification access is unavailable on this phone.")
        if operation not in {"action", "reply", "dismiss", "open"}:
            raise ValueError("Unknown notification action.")
        payload = {"key": row["key"], "operation": operation, **extra}
        event = {"id": str(uuid4()), "type": "notification.command", "ttl_seconds": 30,
                 "targets": [row["device_id"]], "payload": payload}
        self.loop.call_soon_threadsafe(self.client.publish, event)
        return {"queued": True, "id": event["id"]}

    async def refresh_auxiliary(self, mesh):
        """Retry optional HTTP state without holding up incoming Link ACKs."""
        try:
            shared = await asyncio.to_thread(signed, self.workspace.root, mesh, '/v1/link/continuity')
            if shared.get('focus'):
                self.workspace.store.save('focus_plan', {'id':'shared','plan':shared['focus']['payload'],'source':shared['focus']['source']})
            if shared.get('dnd'):
                from .continuity import validate_dnd
                dnd = shared['dnd']
                if self.continuity.remember_dnd(validate_dnd({'active': dnd['active'], 'changed_at': dnd['changed_at']}), dnd['source']):
                    self.continuity.apply()
            self.continuity.last_plan = None
            if getattr(self.workspace, 'workspace_enabled', False) is True:
                await asyncio.to_thread(ensure_grants, self.workspace.root, mesh)
            return True
        except (OSError, ValueError, RuntimeError):
            self.state.error = 'Some continuity features will retry automatically.'
            self.changed()
            return False

    async def run(self):
        self.loop = asyncio.get_running_loop()
        native = None
        try:
            native = self.native = self.notifier_factory(self.command)
            if native is not None:
                native.copy = self.copy_code
        except Exception:
            self.state.error = "Native notifications are unavailable; phone items remain in Saiph."
        running = None
        config_id = None
        auxiliary = None
        next_config_attempt = 0
        next_enrollment = 0
        component_poll = None
        worker = self.worker_factory(); next_worker = next_peer = next_focus = next_local = next_auxiliary = next_deskflow = next_dnd = next_hotspot = 0
        while not self.stop_requested.is_set():
            components = getattr(self.workspace, 'components', None)
            if components and not os.environ.get('ORION_MINI_TEST'):
                if component_poll is None or component_poll.done():
                    if component_poll:
                        await asyncio.gather(component_poll, return_exceptions=True)
                    component_poll = asyncio.create_task(asyncio.to_thread(components.poll))
            approved = getattr(self.workspace, 'enrollment_approved', None)
            if approved and time.monotonic() >= next_enrollment:
                next_enrollment = time.monotonic() + 15
                try:
                    await asyncio.to_thread(self.workspace.complete_enrollment, approved)
                except (OSError, ValueError, RuntimeError):
                    pass  # The approved invitation retries privately until expiry.
                self.changed()
            config = self.workspace.settings.get("hub") or {}
            identity = config.get("device_id") if config.get("paired") else None
            if not (self.workspace.root / "hub-device-key.pem").exists():
                identity = None
            selected_config = (identity, config.get("base_url", ""))
            if selected_config != config_id or (running and running.done()) or (identity and running is None and time.monotonic() >= next_config_attempt):
                if auxiliary:
                    auxiliary.cancel(); await asyncio.gather(auxiliary, return_exceptions=True); auxiliary = None
                next_auxiliary = 0
                if running:
                    self.discard_clipboard_publication()
                    running.cancel(); await asyncio.gather(running, return_exceptions=True)
                config_id = selected_config
                if self.peer:
                    await asyncio.to_thread(self.peer.stop); self.peer = None
                self.state.connected = False
                if identity:
                    mesh = dict(config)
                    def status(frame):
                        if frame["op"] == "welcome":
                            self.state.connected = True; self.state.status = "Online"
                        elif frame["op"] == "reconnecting":
                            self.state.connected = False; self.state.status = "Reconnecting automatically"
                        elif frame["op"] == "presence":
                            batteries = {d["id"]: d.get("battery") for d in self.state.devices}
                            self.state.devices = [{**d, "battery": batteries.get(d["id"])} for d in frame["devices"]]
                        elif frame["op"] == "error":
                            self.state.error = "The phone action could not be delivered."
                        self.changed()
                    async def connected():
                        nonlocal next_auxiliary
                        snapshot = await asyncio.to_thread(signed, self.workspace.root, mesh, "/v1/link/phone")
                        await asyncio.to_thread(self.state.restore,snapshot)
                        await asyncio.to_thread(self.features.restore,snapshot)
                        self.features.start(mesh)
                        next_auxiliary = 0
                        if native:
                            try:
                                await native.reconcile({n["id"] for n in self.state.snapshot()["notifications"]})
                            except Exception:
                                self.state.error = "Native notification reconciliation failed."
                        self.changed()
                    async def event(frame):
                        if await asyncio.to_thread(self.continuity.event,frame):self.changed();return
                        remote = getattr(self.workspace, 'remote', None)
                        if remote and await asyncio.to_thread(remote.event,frame):self.changed();return
                        if frame['type'] == 'call.state' and isinstance(frame['payload'], dict):
                            await asyncio.to_thread(self.call_pause.call, frame['payload'].get('state'))
                        if await asyncio.to_thread(self.features.event,frame,mesh):
                            self.changed();return
                        if frame['type'] == 'clipboard':
                            if (self.workspace.settings.get('link') or {}).get('clipboard') is False: return
                            body = frame['payload']; mime = body['mime']
                            data = body['text'].encode() if 'text' in body else await asyncio.to_thread(fetch,self.workspace.root,mesh,frame['source'],body)
                            if (self.workspace.settings.get('link') or {}).get('clipboard') is not False and self.clipboard_cache.claim(mime,data):
                                self.pending_clipboard.clear()
                                self.discard_clipboard_publication()
                                self.clipboard_received(mime,data)
                            return
                        notice = self.battery_notice(frame['source'], frame['payload']) if frame['type'] == 'battery' else None
                        if notice and native and not self.continuity.focus.quiet:
                            try: await native.announce('Phone battery low', notice)
                            except Exception: pass
                        row = self.state.event(frame)
                        if row and (self.workspace.settings.get('link') or {}).get('auto_copy_codes') is True:
                            code = verification_code(row.get('title'), row.get('text'))
                            # Updates to the same notification must not overwrite the clipboard again.
                            if code and (row['id'], code) not in self.copied_codes:
                                self.copied_codes = {*list(self.copied_codes)[-99:], (row['id'], code)}
                                self.copy_code(code)
                        if native:
                            try:
                                if row and not row.get("silent") and not self.continuity.focus.quiet:
                                    await native.show(row)
                                else:
                                    await native.reconcile({n["id"] for n in self.state.snapshot()["notifications"]})
                            except Exception:
                                self.state.error = "Native notification delivery failed; the item remains in Saiph."
                        self.changed()
                    try:
                        self.client = await asyncio.to_thread(LinkClient, self.workspace.root, identity, mesh["base_url"], event, status,
                                                             capabilities=capabilities(self.workspace.settings), on_connected=connected)
                        running = asyncio.create_task(self.client.run())
                    except (OSError, ValueError, KeyError):
                        self.client = None; running = None
                        next_config_attempt = time.monotonic() + 15
                        self.state.status = "Server setup needs attention"
                        self.state.error = "The saved server must be reachable over your private network."
                        self.changed()
                else:
                    self.client = None; self.state.status = "Pair this computer in Settings"
            if time.monotonic() >= next_focus:
                if self.client:self.client.capabilities=capabilities(self.workspace.settings)
                try:await asyncio.to_thread(self.continuity.tick,publish=self.state.connected)
                except (OSError,ValueError,RuntimeError):self.state.error='Quiet hours are temporarily unavailable.'
                next_focus=time.monotonic()+15
            if time.monotonic() >= next_dnd:
                # Short interval: a Do Not Disturb change should reach the phone promptly.
                try:
                    if await asyncio.to_thread(self.continuity.poll_dnd, publish=self.state.connected): self.changed()
                except (OSError, ValueError, RuntimeError): pass
                next_dnd = time.monotonic() + 3
            if identity and self.state.connected:
                await self.flush_clipboard()
                if auxiliary and auxiliary.done():
                    succeeded = auxiliary.result(); auxiliary = None
                    next_auxiliary = time.monotonic() + (3600 if succeeded else 30)
                if auxiliary is None and time.monotonic() >= next_auxiliary:
                    auxiliary = asyncio.create_task(self.refresh_auxiliary(dict(config)))
                if not self.peer and time.monotonic() >= next_peer:
                    try: self.peer = await asyncio.to_thread(PeerServer,self.workspace.root,dict(config))
                    except (OSError,ValueError): next_peer = time.monotonic() + 15
                if worker and time.monotonic() >= next_worker:
                    # Device discovery/launch is isolated from the mesh receive loop.
                    asyncio.create_task(asyncio.to_thread(worker.poll,{d['id'] for d in self.state.devices}))
                    next_worker = time.monotonic() + 15
            if identity and getattr(self.workspace, 'hotspot', None) and time.monotonic() >= next_hotspot and not os.environ.get('ORION_MINI_TEST'):
                if await asyncio.to_thread(self.workspace.hotspot.poll, self.state.connected): self.changed()
                next_hotspot = time.monotonic() + 15
            if getattr(self.workspace, 'deskflow', None) and time.monotonic() >= next_deskflow:
                await asyncio.to_thread(self.workspace.deskflow.poll)
                next_deskflow = time.monotonic() + 15
            if not os.environ.get('ORION_MINI_TEST') and time.monotonic() >= next_local:
                if getattr(self.workspace, 'recordings', None):
                    try:await asyncio.to_thread(self.workspace.recordings.scan)
                    except (OSError,ValueError):self.state.error='Cloud recording import will retry automatically.'
                if getattr(self.workspace, 'backups', None):self.workspace.backups.poll()
                next_local=time.monotonic()+30
            await asyncio.sleep(.5)
            # Expire the memory-only value even while the transport is offline.
            self.reconcile_clipboard_publication()
            held = self.pending_clipboard.current()
            if held and (not self.state.connected and len(held.data) > self.pending_clipboard.MAX_BYTES or
                         (self.workspace.settings.get('link') or {}).get('clipboard') is False or
                         not (self.workspace.settings.get('hub') or {}).get('paired') or
                         (self.workspace.settings.get('hub') or {}).get('device_id') != held.owner):
                self.pending_clipboard.clear()
        if running:
            self.discard_clipboard_publication()
            running.cancel(); await asyncio.gather(running, return_exceptions=True)
        if auxiliary:
            auxiliary.cancel(); await asyncio.gather(auxiliary, return_exceptions=True)
        if component_poll:
            component_poll.cancel(); await asyncio.gather(component_poll, return_exceptions=True)
        self.state.connected = False
        if self.peer: await asyncio.to_thread(self.peer.stop); self.peer = None
        if getattr(self.workspace, 'deskflow', None): await asyncio.to_thread(self.workspace.deskflow.stop)
