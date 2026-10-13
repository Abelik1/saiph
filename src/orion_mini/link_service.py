# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone/continuity service for the default install, without personal Workspace."""
from __future__ import annotations

import platform
import threading
from pathlib import Path

from .components import Components
from .camera import Camera, validate_options as validate_camera_options
from .microphone import Microphone, validate_options as validate_microphone_options
from .continuity import validate_plan
from .deskflow import Deskflow
from .enrollment import Invitations
from .hotspot import Hotspot, validate_options as validate_hotspot_options
from .remote import Remote, validate_options as validate_remote_options
from .link_operations import CORE_METHODS, LinkOperations
from .modules import module_state
from .package_updates import status as update_status
from .phone import PhoneState
from .phone_features import PhoneFeatures
from .storage import Store, read_json, write_json
from .user_presence import status as user_verification


class UninstalledWorkspace:
    """The local API can report availability without loading personal plugins."""
    entries = ()

    def ticker(self, _entries):
        return []

    def __getattr__(self, _name):
        raise LookupError('Install the optional Workspace edition to use personal tools.')


class LinkWorkspace(LinkOperations):
    workspace_enabled = False

    def __init__(self, root: Path):
        self.root = root
        self.store = Store(root)
        self.settings_path = root / 'settings.json'
        self.connections_path = root / 'connections.json'
        saved = read_json(self.settings_path, {})
        # Preserve settings from an optional edition for switching back later.
        self.settings = {
            'projects': [], 'selected_project': '', 'plugins': [], 'watched_folders': [], 'watched_media': [],
            'start_with_windows': True, 'close_to_tray': True,
            'ai': {'provider': '', 'model': '', 'credential_source': ''}, 'email': {},
            'default_attention': 'noticeable', 'transcription': {'model': 'turbo', 'device': 'auto'},
            'sleep_plan': {'hour': 23, 'minute': 0},
            'hub': {'base_url': '', 'device_id': '', 'paired': False}, **saved,
        }
        self.settings.update({k: v for k, v in read_json(self.connections_path, {}).items() if k in {'ai', 'email', 'hub'}})
        machine = self.settings.get('machine') or {}
        self.settings['machine'] = {'name': machine.get('name') or platform.node() or 'This computer',
                                    'features': {'sleep_plan': False, 'activity_breaks': False, 'calendar': False}}
        self.phone = PhoneState(self.store)
        self.phone_runtime = None
        self.invitations = Invitations()
        self.enrollment_approved = None
        self._pairing_lock = threading.Lock()
        self._cloud_action_lock = threading.Lock()
        self.show_enrollment = False
        self.components = Components()
        self.phone_features = PhoneFeatures(self)
        self.plugins = UninstalledWorkspace()
        self.api_info = {'running': False, 'url': '', 'error': '', 'discovery': str(root / 'api.json')}
        self.deskflow = Deskflow(root, self.settings, default_enabled=False)
        self.hotspot = Hotspot(self.settings)
        self.remote = Remote(self, self._remote_publish)
        self.settings['link']={**self.settings.get('link',{}),'camera':{'enabled':False,**(self.settings.get('link',{}).get('camera') or {})}}
        self.camera = Camera(self)
        self.microphone = Microphone(self)

    def save(self):
        # Do not overwrite the owner's personal feature choices when using Link.
        settings = dict(self.settings)
        previous = read_json(self.settings_path, {}).get('machine') or {}
        if 'features' in previous:
            settings['machine'] = {**settings['machine'], 'features': previous['features']}
        write_json(self.settings_path, settings)

    def bootstrap(self):
        self.save()

    def state(self):
        invitation = self.invitations.status()
        return {'modules': module_state(False), 'settings': self.settings, 'update_status': update_status(self.root), 'cloud_status': self.cloud_status(),
                'enrollment': {**invitation, 'approved': invitation['id'] is not None and self.enrollment_approved == invitation['id']},
                'components': self.components.snapshot(), 'phone': self.phone.snapshot(),
                'phone_features': self.phone_features.snapshot(), 'handoffs': self.store.all('handoff')[:100],
                'deskflow': {**self.deskflow.status(), 'setup': self.deskflow.setup()}, 'dnd': self.dnd_status(), 'hotspot': self.hotspot.status(), 'remote': self.remote.status(), 'camera': self.camera.status(), 'microphone': self.microphone.status(),
                'api': self.api_info, 'hub_inbox': self.hub_inbox(), 'hosted': self.hosted_state(), 'user_verification': user_verification(self),
                'projects': [], 'transcripts': [], 'reminders': [], 'tasks': [], 'jobs': [],
                'messages': [], 'emails': [], 'providers': [], 'skills': [], 'plugins': [], 'ticker': [],
                'google': {'signed_in': False}, 'calendar': {'events': [], 'synced_at': None, 'error': ''},
                'agenda': {'items': []}, 'backup_status': {'configured': False}}

    def _remote_publish(self, event):
        if not self.phone_runtime:
            raise ValueError('Connection is unavailable.')
        self.phone_runtime.publish(event)

    def dnd_status(self):
        runtime = self.phone_runtime
        if runtime is not None:
            return runtime.continuity.dnd_status()
        return {'enabled': (self.settings.get('link') or {}).get('dnd_sync', True) is not False, 'active': False, 'source': '', 'changed_at': None, 'quiet': False}

    def dispatch(self, method, args):
        if method in CORE_METHODS:
            return self.dispatch_link(method, args)
        if method != 'settings.save':
            raise ValueError('Install the optional Workspace edition to use personal tools.')
        if not isinstance(args, dict) or set(args) - {'start_with_windows', 'close_to_tray', 'machine', 'hub', 'cloud', 'link'}:
            raise ValueError('This setting belongs to the optional Workspace edition.')
        for flag in ('start_with_windows', 'close_to_tray'):
            if flag in args and type(args[flag]) is not bool:
                raise ValueError('This preference is on or off.')
        if 'machine' in args:
            machine = args['machine']
            if not isinstance(machine, dict) or set(machine) - {'name', 'features'} or not isinstance(machine.get('name'), str):
                raise ValueError('Choose a computer name; personal reminders require Workspace.')
            name = machine['name'].strip()
            if not name or len(name) > 40 or machine.get('features', {}) not in ({}, self.settings['machine']['features']):
                raise ValueError('Choose a computer name; personal reminders require Workspace.')
            args = {**args, 'machine': {**self.settings['machine'], 'name': name}}
        if 'cloud' in args:
            cloud = args['cloud']
            if not isinstance(cloud, dict) or set(cloud) - {'path', 'enabled'}:
                raise ValueError('Recording transcription belongs to optional Workspace.')
            if 'enabled' in cloud and type(cloud['enabled']) is not bool:
                raise ValueError('Cloud is on or off.')
            if 'path' in cloud and (not isinstance(cloud['path'], str) or len(cloud['path']) > 4096):
                raise ValueError('Choose a local Cloud folder.')
            args = {**args, 'cloud': {**self.settings.get('cloud', {}), **cloud}}
        if 'link' in args:
            link = args['link']
            if not isinstance(link, dict) or set(link) - {'focus', 'dnd_sync', 'auto_copy_codes', 'battery_alerts', 'pause_media_on_calls', 'new_photo_notices', 'clipboard', 'timezone', 'wake_hour', 'wake_minute', 'camera', 'microphone', 'deskflow', 'hotspot', 'remote'}:
                raise ValueError('Unknown continuity preference.')
            for flag in ('focus', 'dnd_sync', 'auto_copy_codes', 'battery_alerts', 'pause_media_on_calls', 'new_photo_notices', 'clipboard'):
                if flag in link and type(link[flag]) is not bool:
                    raise ValueError('Continuity preferences are on or off.')
            if 'deskflow' in link:
                options = link['deskflow']
                if not isinstance(options, dict) or set(options) - {'enabled', 'role', 'desktop', 'local', 'executable', 'certificate'}:
                    raise ValueError('Unknown Deskflow preference.')
                if 'enabled' in options and type(options['enabled']) is not bool:
                    raise ValueError('Deskflow is on or off.')
                if options.get('role', 'desktop') not in {'desktop', 'laptop'}:
                    raise ValueError('Choose a known computer role.')
                from .peer import mesh_address
                for key in ('desktop', 'local'):
                    if key in options:
                        mesh_address(options[key])
                if any(key in options and (not isinstance(options[key], str) or len(options[key]) > 4096 or any(c in options[key] for c in '\r\n\0')) for key in ('executable', 'certificate')):
                    raise ValueError('Choose local Deskflow configuration files.')
                link = {**link, 'deskflow': {**(self.settings.get('link', {}).get('deskflow') or {}), **options}}
            if 'remote' in link:
                link = {**link, 'remote': validate_remote_options(link['remote'], self.settings.get('link', {}).get('remote') or {})}
            if 'hotspot' in link:
                link = {**link, 'hotspot': {**(self.settings.get('link', {}).get('hotspot') or {}), **validate_hotspot_options(link['hotspot'])}}
            if 'camera' in link:
                options=validate_camera_options(link['camera'])
                link={**link,'camera':{**(self.settings.get('link',{}).get('camera') or {}),**options}}
            if 'microphone' in link:
                options = validate_microphone_options(link['microphone'])
                link = {**link, 'microphone': {**(self.settings.get('link', {}).get('microphone') or {}), **options}}
            link = {**self.settings.get('link', {}), **link}
            validate_plan({'enabled': link.get('focus', True), 'timezone': link.get('timezone', 'Europe/London'),
                           'start_hour': self.settings['sleep_plan']['hour'], 'start_minute': self.settings['sleep_plan']['minute'],
                           'end_hour': link.get('wake_hour', 7), 'end_minute': link.get('wake_minute', 0)})
            args = {**args, 'link': link}
        if 'hub' in args:
            raise ValueError('Use an invitation to change server setup.')
        self.settings.update(args)
        if not (self.settings.get('link') or {}).get('deskflow', {}).get('enabled', False):
            self.deskflow.stop()
        if (self.settings.get('link') or {}).get('camera', {}).get('enabled') is False:
            self.camera.stop()
        if not (self.settings.get('link') or {}).get('microphone', {}).get('enabled', False):
            self.microphone.stop()
        self.save()
        return {'ok': True}
