# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared phone and enrollment operations for both desktop editions."""
from __future__ import annotations
import json
import os
import re
import subprocess
import threading
import time
from functools import lru_cache
from pathlib import Path
from . import hub_client
from .models import utc_now
from .storage import write_json
from .user_presence import confirm as confirm_user

# Opt-in Saiph Hosted preview. Every method refuses work unless the hosted
# setting is on; with it off, self-hosted behaviour is unchanged.
HOSTED_METHODS = frozenset({'hosted.configure', 'hosted.enable', 'hosted.sign_in', 'hosted.sign_out', 'hosted.setup_root',
                            'hosted.root_code', 'hosted.request.inspect', 'hosted.approve', 'hosted.revoke', 'hosted.forget',
                            'hosted.notification.dismiss', 'hosted.file.send', 'hosted.file.save'})
_HOSTED_OFF = {'available': False, 'enabled': False, 'status': 'off', 'identity': False}


@lru_cache(maxsize=1)
def hosted_available() -> bool:
    """Hosted needs the optional `hosted` extras (Tink, Authlib)."""
    from importlib.util import find_spec
    return all(find_spec(name) is not None for name in ('tink', 'authlib'))


CORE_METHODS = frozenset({'cloud.info', 'cloud.setup', 'cloud.client.open', 'cloud.client.install', 'components.sign_in', 'state', 'hub.pair', 'hub.test', 'phone.sms.send', 'continuity.handoff', 'continuity.dnd', 'deskflow.restart', 'hotspot.connect', 'enrollment.import', 'continuity.dismiss', 'enrollment.cancel', 'components.install', 'hub.decide', 'enrollment.export', 'enrollment.qr', 'phone.call', 'phone.ring', 'phone.media', 'phone.contacts.search', 'phone.sms.compose', 'phone.ringer', 'phone.dial', 'phone.calls.log', 'phone.photo.prefetch', 'phone.sms.open', 'enrollment.approve', 'phone.photo.save', 'phone.file.send', 'phone.notification', 'hub.refresh'}) | HOSTED_METHODS

class LinkOperations:
    def hosted_controller(self):
        """Created on first use only; importing it needs the hosted extras."""
        controller = getattr(self, '_hosted', None)
        if controller is None:
            if not hosted_available():
                raise ValueError('This build does not include Saiph Hosted.')
            from .hosted_runtime import HostedController
            controller = self._hosted = HostedController(self)
        return controller

    def hosted_blocks_self_hosted(self) -> bool:
        """A device is either self-hosted or hosted, never both."""
        settings = self.settings.get('hosted')
        if isinstance(settings, dict) and settings.get('enabled') is True:
            return True
        return (self.root / 'hosted' / 'identity').exists()

    def hosted_state(self) -> dict:
        settings = self.settings.get('hosted')
        if not (isinstance(settings, dict) and settings) and not (self.root / 'hosted').exists():
            return {**_HOSTED_OFF, 'available': hosted_available()}
        if not hosted_available():
            return dict(_HOSTED_OFF)
        return {'available': True, **self.hosted_controller().snapshot()}

    def _refuse_if_hosted(self):
        if self.hosted_blocks_self_hosted():
            raise ValueError('This computer uses Saiph Hosted. A device uses either Saiph Hosted or a self-hosted Hub, '
                             'never both. Turn off and forget Saiph Hosted first.')

    def cloud_client(self):
        from .cloud_client import SeafileClient
        return SeafileClient(private_root=self.root / 'cloud-client')

    def cloud_status(self):
        """Inspect on a worker; UI snapshots never wait for Task Scheduler/SQLite."""
        from .cloud_client import status, installation_supported
        if not hasattr(self, '_cloud_status_lock'):
            self._cloud_status_lock = threading.Lock()
        cached = getattr(self, '_cloud_status_cache', None)
        now = time.monotonic()
        if (cached is None or now - cached[0] >= 15) and self._cloud_status_lock.acquire(blocking=False):
            def probe():
                try:
                    self._cloud_status_cache = (time.monotonic(), status(self.root / 'cloud-client'))
                finally:
                    self._cloud_status_lock.release()
            threading.Thread(target=probe, name='OrionCloudInspection', daemon=True).start()
        return {**(dict(cached[1]) if cached else {'installed': False, 'profile_present': False,
            'inspection_complete': False, 'prepared': False, 'selected_libraries': 0, 'state': 'inspection_pending'}),
            'installation_supported': installation_supported()}

    def complete_enrollment(self, invitation_id):
        if not self._pairing_lock.acquire(blocking=False):
            return {"waiting": True}
        try:
            if self.settings.get("hub", {}).get("paired"):
                raise ValueError("This computer is already paired. Your existing server stays configured.")
            self._refuse_if_hosted()
            item = self.invitations.approved(invitation_id)
            if self.enrollment_approved != invitation_id:
                raise ValueError("Approve the invitation before pairing this computer.")
            try:
                config = hub_client.pair(self.root, item["hub"], item["code"], self.settings["machine"]["name"])
            except (OSError, ValueError, RuntimeError):
                raise RuntimeError("Setup is waiting for your server. Complete network sign-in; Saiph will retry automatically while the invitation is valid.") from None
            self.settings["hub"] = config
            write_json(self.connections_path, {key: self.settings[key] for key in ("ai", "email", "hub")})
            self.save(); self.invitations.clear(invitation_id); self.enrollment_approved = None
            return {"ok": True}
        finally:
            self._pairing_lock.release()

    def hub_inbox(self) -> dict:
        """The last copy of Orion Hub's inbox: notices and calendar proposals shared with the phone."""
        try:
            return self.store.get("hub", "inbox")
        except ValueError:
            return {"items": [], "synced_at": None, "error": ""}

    def hub_ready(self) -> bool:
        hub = self.settings.get("hub") or {}
        return bool(hub.get("paired") and hub.get("device_id"))

    def sync_hub(self) -> dict:
        """Blocking network call; the desktop runs it off the UI thread."""
        try:
            result = {"id": "inbox", "items": hub_client.inbox(self.root, self.settings["hub"])[:100],
                      "synced_at": utc_now(), "error": ""}
        except (ValueError, RuntimeError) as error:
            result = {**self.hub_inbox(), "id": "inbox", "error": str(error)}
        return self.store.save("hub", result)

    def dispatch_link(self, method, args):
        if method in {'cloud.client.install', 'cloud.setup'}:
            if not self._cloud_action_lock.acquire(blocking=False):
                raise ValueError('File sync setup is already running. Wait for it to finish before making another change.')
            try:
                return self._dispatch_link(method, args)
            finally:
                self._cloud_action_lock.release()
        return self._dispatch_link(method, args)

    def _dispatch_link(self, method, args):
        if method == 'state':
            return self.state()
        if method in HOSTED_METHODS:
            return self._dispatch_hosted(method, args if isinstance(args, dict) else {})
        if method == 'cloud.client.open':
            return self.cloud_client().open()
        if method == 'cloud.client.install':
            if args:
                raise ValueError('Choose the supported file sync installation.')
            result = self.cloud_client().install(consent=True)
            self._cloud_status_cache = None
            return result
        if method == 'cloud.info':
            try:
                result = hub_client.signed(self.root, self.settings.get('hub', {}), '/v1/link/cloud')
                if (not isinstance(result, dict) or type(result.get('configured')) is not bool
                        or result.get('state') not in {'not_configured', 'available', 'provisioned', 'needs_attention'}
                        or not isinstance(result.get('libraries'), list) or len(result['libraries']) > 100):
                    raise ValueError
                from uuid import UUID
                libraries = []
                for library in result['libraries']:
                    if (not isinstance(library, dict) or set(library) != {'id', 'name', 'permission'}
                            or str(UUID(library['id'])) != library['id']
                            or not isinstance(library['name'], str) or len(library['name']) > 200
                            or library['permission'] not in {'r', 'rw'}):
                        raise ValueError
                    libraries.append(library)
                return {'configured': result['configured'], 'state': result['state'], 'libraries': libraries}
            except (OSError, ValueError, RuntimeError, TypeError, KeyError, AttributeError):
                raise ValueError('Your server could not prepare file sync. Existing local files and profiles are unchanged.') from None
        if method == 'cloud.setup':
            from .cloud_client import _plain_path, paired_profile
            from uuid import UUID
            try:
                if not isinstance(args, dict) or set(args) != {'folder', 'libraries'}:
                    raise ValueError
                libraries = args['libraries']
                if (not isinstance(libraries, list) or len(libraries) != 1
                        or not isinstance(libraries[0], str) or str(UUID(libraries[0])) != libraries[0]):
                    raise ValueError
                folder = _plain_path(Path(args['folder']), directory=True)
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                raise ValueError('Choose one shared library and approve its existing local folder.') from None
            client = self.cloud_client()
            status = client.detect()
            if not status.installed:
                raise ValueError('Install the official Seafile client before file sync setup.')
            if not status.inspection_complete:
                raise ValueError('The existing file sync profile needs inspection. It was kept unchanged.')
            for binding in status._bindings:
                if binding.library_id == libraries[0] and binding.folder == folder:
                    return {'state': 'existing_binding', 'needs_library_link': False}
            if status.profile_present or status.prepared:
                raise ValueError('Manage the existing file sync profile before adding another account. It was kept unchanged.')
            try:
                result = hub_client.signed(self.root, self.settings.get('hub', {}), '/v1/link/cloud/profile', 'POST', {'libraries': libraries})
                profile = paired_profile(result, libraries[0])
            except (OSError, ValueError, RuntimeError):
                raise ValueError('Your server could not prepare file sync. Existing local files and profiles are unchanged.') from None
            result = client.setup(profile, folder)
            if result['state'] in {'existing_binding', 'link_requested'}:
                self.settings['cloud'] = {**self.settings.get('cloud', {}), 'path': str(folder), 'enabled': True}
                self.save()
            self._cloud_status_cache = None
            return result
        if method in {'phone.sms.open', 'phone.sms.send', 'phone.call', 'phone.ring', 'phone.media', 'phone.contacts.search', 'phone.sms.compose',
                      'phone.ringer', 'phone.dial', 'phone.calls.log', 'phone.photo.save', 'phone.photo.prefetch', 'phone.file.send'}:
            return self.phone_features.dispatch(method, args)
        if method == 'continuity.handoff':
            if not self.phone_runtime:
                raise ValueError('Connection is unavailable.')
            return self.phone_runtime.continuity.handoff(args['target'], args['kind'], args['value'])
        if method == 'continuity.dnd':
            if not isinstance(args, dict) or set(args) != {'active'} or type(args['active']) is not bool:
                raise ValueError('Do Not Disturb is on or off.')
            if not self.phone_runtime:
                raise ValueError('Connection is unavailable.')
            return self.phone_runtime.continuity.set_dnd(args['active'])
        if method == 'hotspot.connect':
            if args:
                raise ValueError('Unknown hotspot action.')
            return self.hotspot.connect()
        if method == 'deskflow.restart':
            if args:
                raise ValueError('Unknown Deskflow action.')
            if (self.settings.get('link') or {}).get('deskflow', {}).get('enabled', False) is not True:
                raise ValueError('Turn on keyboard and mouse sharing first.')
            return self.deskflow.restart()
        if method == 'continuity.dismiss':
            self.store.delete('handoff', args['id'])
            return {'ok': True}
        if method == 'phone.notification':
            if self.phone_runtime is None:
                raise ValueError('Phone connection is unavailable.')
            row = self.store.get('phone_notification', str(args['id']))
            allowed = {key: args[key] for key in ('index', 'text', 'reply_key') if key in args}
            return self.phone_runtime.command(row, str(args['operation']), **allowed)
        if method == 'enrollment.qr':
            from .enrollment import pairing_qr, parse_invitation
            if args:
                raise ValueError('Choose Show pairing QR to add a device.')
            if not self.hub_ready():
                raise ValueError('Pair this computer with your server before adding a device.')
            # A pairing code adds a device to the Hub; the person must be present.
            confirm_user(self, 'show a pairing code for a new device')
            try:
                # Same signed Hub invitation as the file flow; shown on screen, never saved.
                artifact = hub_client.signed(self.root, self.settings['hub'], '/v1/link/enrollment', 'POST', {})
                return pairing_qr(parse_invitation(json.dumps(artifact).encode()))
            except (OSError, ValueError, RuntimeError, ImportError):
                raise ValueError('The pairing QR could not be created. Your existing pairing is unchanged.') from None
        if method == 'enrollment.export':
            from .enrollment import parse_invitation
            target = Path(args['path'])
            if target.suffix.lower() != '.orion-enrollment':
                raise ValueError('Choose a new private Saiph invitation file.')
            confirm_user(self, 'save a pairing invitation for a new device')
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as output:
                    # Tighten the empty file before requesting/writing a code.
                    if os.name == 'nt':
                        system = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32'
                        options = {'capture_output': True, 'creationflags': subprocess.CREATE_NO_WINDOW, 'timeout': 10}
                        identity = subprocess.run([str(system / 'whoami.exe'), '/user', '/fo', 'csv', '/nh'], **options)
                        sids = re.findall(rb'"(S-1-[0-9-]+)"', identity.stdout)
                        if identity.returncode or len(sids) != 1:
                            raise ValueError('Private invitation permissions could not be secured.')
                        principal = '*' + sids[0].decode('ascii') + ':(F)'
                        if subprocess.run([str(system / 'icacls.exe'), str(target), '/inheritance:r', '/grant:r', principal], **options).returncode:
                            raise ValueError('Private invitation permissions could not be secured.')
                    artifact = hub_client.signed(self.root, self.settings['hub'], '/v1/link/enrollment', 'POST', {})
                    parse_invitation(json.dumps(artifact).encode())
                    output.write(json.dumps(artifact))
                    output.flush()
                    os.fsync(output.fileno())
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                target.unlink(missing_ok=True)
                raise ValueError('The private invitation could not be created. Your existing pairing is unchanged.') from None
            return {'created': True}
        if method == 'enrollment.import':
            self._refuse_if_hosted()
            if self._pairing_lock.locked():
                raise ValueError('Pairing is already in progress. Wait for setup to finish.')
            result = self.invitations.import_file(args.get('path'))
            self.enrollment_approved = None
            self.show_enrollment = True
            return result
        if method == 'enrollment.cancel':
            if self._pairing_lock.locked():
                raise ValueError('Pairing is already in progress. Wait for setup to finish.')
            self.invitations.clear(args.get('id'))
            self.enrollment_approved = None
            return {'ok': True}
        if method == 'enrollment.approve':
            if self.settings.get('hub', {}).get('paired'):
                raise ValueError('This computer is already paired. Your existing server stays configured.')
            self._refuse_if_hosted()
            self.invitations.approved(args.get('id'))
            self.enrollment_approved = args.get('id')
            return self.complete_enrollment(args.get('id'))
        if method == 'components.install':
            return self.components.install()
        if method == 'components.sign_in':
            item = self.invitations.approved(args.get('id'))
            return self.components.sign_in(item['mesh_login_server'])
        if method == 'hub.pair':
            self._refuse_if_hosted()
            config = hub_client.pair(self.root, args.get('base_url', ''), args.get('code', ''), args.get('name', 'Saiph desktop'))
            self.settings['hub'] = config
            write_json(self.connections_path, {key: self.settings[key] for key in ('ai', 'email', 'hub')})
            self.save()
            return {'ok': True, 'base_url': config['base_url']}
        if method == 'hub.decide':
            if args.get('decision') not in {'accept', 'dismiss', 'done'}:
                raise ValueError('Unknown decision.')
            decided = hub_client.decide(self.root, self.settings.get('hub', {}), str(args['id']), args['decision'])
            self.sync_hub()
            return decided
        if method == 'hub.refresh':
            return self.sync_hub()
        if method == 'hub.test':
            return hub_client.signed(self.root, self.settings.get('hub', {}), '/v1/dashboard')
        return {"ok": True}

    def _dispatch_hosted(self, method, args):
        controller = self.hosted_controller()
        if method == 'hosted.configure':
            return controller.configure(args)
        if method == 'hosted.enable':
            return controller.set_enabled(args.get('enabled'))
        if method == 'hosted.sign_in':
            return controller.sign_in()
        if method == 'hosted.sign_out':
            return controller.sign_out()
        if method == 'hosted.setup_root':
            return controller.setup_root()
        if method == 'hosted.root_code':
            return controller.root_code()
        if method == 'hosted.request.inspect':
            return controller.inspect_request(args.get('code'))
        if method == 'hosted.approve':
            return controller.approve(args.get('code'), args.get('label'), args.get('confirmed'))
        if method == 'hosted.revoke':
            return controller.revoke(args.get('device_id'))
        if method == 'hosted.forget':
            return controller.forget(args.get('confirm'))
        if method == 'hosted.notification.dismiss':
            return controller.dismiss_notification(args.get('id'))
        if method == 'hosted.file.send':
            return controller.send_file(args.get('path'), args.get('target'))
        if method == 'hosted.file.save':
            return controller.save_offer(args.get('id'))
        raise ValueError('Unknown hosted action.')
