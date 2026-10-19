# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Phone → Apps tab: the phone's screen and apps over the local network.

The default path needs no USB, adb or scrcpy (docs/PHONE_SCREEN.md). The offer is
delivered over Saiph Cloud to an approved phone that advertises "screen"; a QR is
always available as the fallback (self-hosted Hub phones, older phones). App lists
come from the phone's own launcher query over Cloud ("apps"), or over a live screen
session. The scrcpy window remains an optional advanced path when the owner has
authorised debugging (`phone_apps.py`).

The Apps grid adds app icons from the phone (Cloud only), pins and local open
counts (`phone_app_library.py`). A live session is shown in its own native window
when the Qt shell provides one (`phone_screen_window.py`); closing it stops sharing.
"""
from __future__ import annotations

from .phone_app_library import AppLibrary
from .screen_session import ScreenSession
from . import session_offer


class PhoneScreen:
    def __init__(self, workspace, *, session=None):
        self.workspace = workspace
        self.session = session or ScreenSession()
        self.reveal = 0  # Raised by pinned-app shortcuts so the page shows Phone → Apps.
        self.library = AppLibrary(getattr(workspace, 'root', None))
        # Set by the Qt shell: 'closed' or 'open' when a native window exists; the page embeds otherwise.
        self.window = 'unavailable'
        self.show_window = None

    def _hosted(self, device_id, capability):
        """The Saiph Cloud controller when `device_id` is a Cloud phone offering `capability`."""
        active = getattr(self.workspace, '_active_hosted', None)
        controller = active() if active is not None else None
        if (device_id is None or controller is None or not controller.is_phone(device_id)
                or capability not in controller.screen_capabilities(device_id)):
            return None
        return controller

    def start(self, device_id=None, launch='', resolution='1080p', fps=20, quality='high'):
        if device_id is not None and type(device_id) is not str:
            raise ValueError('Choose a phone.')
        controller = self._hosted(device_id, 'screen')
        offered = {}

        def deliver(code):
            # The shared sealed `session.offer` (session_offer.py), as the camera uses.
            result = controller.session_offer(device_id, 'screen', code)
            offered['id'] = result.get('offer')
            return result['sent']
        started = self.session.start(resolution=resolution, fps=fps, quality=quality, launch=launch,
                                     device_id=device_id, deliver=deliver if controller is not None else None)
        if offered.get('id') and hasattr(controller, 'session_close'):
            # The phone drops its notification and pop-up once this session is answered or ends.
            session, epoch = self.session, started['session']
            session_offer.watch_offer(lambda: session.session == epoch and session.state == 'waiting',
                                      lambda: controller.session_close(device_id, offered['id']))
        return started

    def open_app(self, device_id, package, name=''):
        """Mirror one app: launch it in a live session, else start a session that launches it."""
        if not session_offer.valid_package(package):
            raise ValueError('Choose an app from the list.')
        if type(device_id) is str and device_id:
            self.library.preferences.opened(device_id, package)  # "Most used", counted on this computer.
        if self.session.status()['state'] == 'live':
            return {'live': True, **self.session.open_app(package)}
        if self.session.status()['state'] != 'idle':
            self.session.stop()
        return {'live': False, **self.start(device_id, launch=package)}

    def apps(self, device_id):
        """{'apps': [...]} once known; {'pending': True} while the phone is answering.

        Every answer carries this computer's pins and open counts for that phone and
        whether icons can be fetched (`icons`: Cloud phones only)."""
        extra = {**self.library.preferences.view(device_id), 'icons': self._hosted(device_id, 'apps') is not None}
        return {**self._apps(device_id), **extra}

    def _apps(self, device_id):
        live = self.session.session_apps()
        if live is not None:
            return {'apps': live, 'source': 'screen'}
        controller = self._hosted(device_id, 'apps')
        if controller is not None:
            known = controller.phone_apps(device_id)
            fresh = known is not None and controller.clock() - known['at'] <= 300
            if not fresh:
                controller.request_apps(device_id)
            if known is not None:
                return {'apps': known['apps'], 'source': 'cloud', 'refreshing': not fresh}
            return {'pending': True, 'source': 'cloud'}
        if self.session.status()['state'] == 'live':
            self.session.request_apps()
            return {'pending': True, 'source': 'screen'}
        return {'unavailable': True, 'message': 'Start the phone screen to list its apps, or update Saiph on your phone.'}

    def icons(self, device_id, packages):
        """Cached icons for these packages; missing or unchecked ones are requested from the phone."""
        controller = self._hosted(device_id, 'apps')
        if controller is not None and hasattr(controller, 'take_app_icons'):
            self.library.receive(device_id, *controller.take_app_icons(device_id))
        request = (lambda rows: controller.request_app_icons(device_id, rows)) if controller is not None else None
        return self.library.lookup(device_id, packages, request)

    def pin(self, device_id, package, pinned):
        return self.library.preferences.pin(device_id, package, pinned)

    def raise_window(self):
        if self.show_window is None:
            raise ValueError('The phone screen window is unavailable here.')
        return self.show_window()

    def status(self):
        return {**self.session.status(), 'reveal': self.reveal, 'window': self.window}

    def stop(self):
        return self.session.stop()
