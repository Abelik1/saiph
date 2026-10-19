# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deliberate phone-camera sessions through upstream scrcpy and OS webcam tools."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time

from .adb_worker import AdbWorker
from .companion_tools import tool_path
from .phone_debugging import SERIAL, PhoneDebugging, adb_path

WINDOW_TITLE = 'Orion Phone Camera'
OBS_NAME = 'Orion Phone'
SETUP_MESSAGE = 'Complete the one-time phone camera setup in Settings → Devices.'
MIN_SCRCPY = (2, 2)  # First release with --video-source=camera.
MIN_ANDROID_SDK = 31  # Android 12: scrcpy camera capture needs it on the phone.


def validate_options(options):
    allowed = {'enabled','v4l2_sink','obs_profile','obs_collection','obs_scene','obs_scene_file','obs_executable','scrcpy_executable','facing','quality','rotation'}
    if not isinstance(options,dict) or set(options)-allowed:raise ValueError('Unknown phone camera preference.')
    if 'enabled' in options and not isinstance(options['enabled'],bool):raise ValueError('Phone camera is on or off.')
    for key,value in options.items():
        if key=='enabled':continue
        choices={'facing':{'front','back'},'quality':{'720p','1080p'},'rotation':{'0','90','180','270'}}
        if key in choices:
            if not isinstance(value,str) or value not in choices[key]:raise ValueError('Choose a supported camera option.')
            continue
        if not isinstance(value,str) or len(value)>4096 or any(ord(character)<32 for character in value):
            raise ValueError('Choose a local camera configuration file.')
        if key=='v4l2_sink' and value and not re.fullmatch(r'/dev/video[0-9]{1,4}',value):
            raise ValueError('Choose an existing Linux video loopback device.')
        if key in {'obs_profile','obs_collection','obs_scene'} and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}',value):
            raise ValueError('Choose a named OBS profile, collection and scene.')
    return dict(options)


def loopback_sink(path):
    """Query the configured existing kernel node; never create one or load modules."""
    if not isinstance(path, str) or not re.fullmatch(r'/dev/video[0-9]{1,4}', path):return False
    try:
        import fcntl
        import stat
        if not stat.S_ISCHR(os.stat(path).st_mode):return False
        descriptor = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        try:
            capability = bytearray(104)
            fcntl.ioctl(descriptor, 0x80685600, capability, True)  # VIDIOC_QUERYCAP
            return capability[:16].split(b'\0', 1)[0] == b'v4l2 loopback'
        finally:os.close(descriptor)
    except (ImportError, OSError):return False


def obs_path(config):
    configured = config.get('obs_executable')
    if configured:return str(Path(configured)) if Path(configured).is_file() else None
    standard = shutil.which('obs64')
    installed = Path(os.environ.get('ProgramFiles', 'C:/Program Files'))/'obs-studio/bin/64bit/obs64.exe'
    return standard or (str(installed) if installed.is_file() else None)


def obs_configuration(config):
    """Read only the explicitly selected collection; refuse broad/window fallback capture."""
    names = {name:config.get('obs_'+name, OBS_NAME) for name in ('profile','collection','scene')}
    if any(not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}',value) for value in names.values()):return None
    basic = Path(os.environ.get('APPDATA', Path.home()/'AppData/Roaming'))/'obs-studio/basic'
    profile_dirs = [basic/'profiles'/names['profile'], basic/'profiles'/names['profile'].replace(' ','_')]
    if not any((folder/'basic.ini').is_file() for folder in profile_dirs):return None
    files = ([Path(config['obs_scene_file'])] if config.get('obs_scene_file') else
             [basic/'scenes'/(names['collection']+suffix) for suffix in ('.json',)] +
             [basic/'scenes'/(names['collection'].replace(' ','_')+'.json')])
    try:
        path = next((candidate for candidate in files if candidate.is_file()), None)
        if path is None or path.stat().st_size>2*1024*1024:return None
        with path.open('rb') as handle:content = handle.read(2*1024*1024+1)
        if len(content)>2*1024*1024:return None
        collection = json.loads(content.decode('utf-8-sig'))
        if collection.get('name') != names['collection']:return None
        if any(value for key,value in collection.items() if key.startswith(('DesktopAudioDevice','AuxAudioDevice'))):return None
        sources = collection.get('sources',[])
        if not isinstance(sources,list) or len(sources)>20:return None
        windows = [source for source in sources if source.get('id')=='window_capture']
        if len(windows)!=1 or any(source.get('id') not in {'window_capture','scene'} for source in sources):return None
        window = windows[0]; settings = window.get('settings',{})
        parts = settings.get('window','').split(':')
        if len(parts)!=3 or parts[0]!=WINDOW_TITLE or parts[2].lower()!='scrcpy.exe':return None
        if settings.get('priority')!=1 or settings.get('capture_audio'):return None
        scene = next((source for source in sources if source.get('id')=='scene' and source.get('name')==names['scene']), None)
        items = (scene or {}).get('settings',{}).get('items',[])
        if len(items)!=1 or items[0].get('name')!=window.get('name') or items[0].get('visible',True) is not True:return None
        # A stale custom Virtual Camera output must not expose another source.
        virtual = collection.get('virtual-camera',{})
        if virtual.get('type2',0)!=0:return None
        return names
    except (OSError, ValueError, TypeError, AttributeError, KeyError, RecursionError):return None


def scrcpy_version(executable, run=subprocess.run):
    """(major, minor) from `scrcpy --version`, or None when it cannot be read."""
    try:
        result = run([executable, '--version'], capture_output=True, text=True, timeout=5,
                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'^scrcpy v?([0-9]{1,3})\.([0-9]{1,3})', result.stdout or '', re.M)
    return (int(match.group(1)), int(match.group(2))) if result.returncode == 0 and match else None


class Camera:
    def __init__(self, workspace, *, system=None, popen=subprocess.Popen, run=subprocess.run, worker_factory=AdbWorker,
                 verify_sink=loopback_sink, debugging_factory=PhoneDebugging):
        self.workspace = workspace
        self.system = system or sys.platform
        self.popen, self.run, self.worker_factory, self.verify_sink = popen, run, worker_factory, verify_sink
        self.debugging_factory = debugging_factory
        self.lock = threading.RLock()
        self.processes = []
        self.device_id = None
        self.serial = None
        self.mode = None
        self.error = ''
        self.capture_options = {}
        self.monitor_stop = None
        self._version_cache = None
        from .camera_session import CameraSession
        from .camera_native import NativeCameraSink
        self.local = CameraSession(NativeCameraSink)

    def start_local(self, preview=False, **options):
        if type(preview) is not bool:
            raise ValueError('Choose whether to preview your camera.')
        if self._config().get('enabled', True) is False:
            raise ValueError('Turn on Phone camera in Settings → Devices first.')
        with self.lock:
            if self.processes:
                raise ValueError('Stop the current camera first.')
            return self.local.start(preview, **options)

    def offer_to_phone(self, session, device_id):
        """Send this waiting camera code to an approved Saiph Cloud phone instead of a scan."""
        if type(session) is not str or type(device_id) is not str:
            raise ValueError('Choose a phone for the camera.')
        controller = getattr(self.workspace, '_active_hosted', lambda: None)()
        if controller is None:
            raise ValueError('Sign in to Saiph Cloud on both devices to send the camera to your phone.')
        result = controller.session_offer(device_id, 'camera', self.local.invitation(session))
        offer_id = result.get('offer') if isinstance(result, dict) else None
        if offer_id:
            # Clear the phone's prompt as soon as this code is answered, cancelled or expires.
            from .session_offer import watch_offer
            local = self.local
            watch_offer(lambda: getattr(local, 'session', None) == session and local.state == 'waiting',
                        lambda: controller.session_close(device_id, offer_id))
        return result

    def _check_session(self):
        if not self.processes:return
        if self._config().get('enabled',True) is False:
            self.stop();self.error='Phone camera stopped because it was switched off in Settings.'
            return
        if self.device_id is not None:
            # Self-hosted pairing: the paired phone must stay online through the Hub.
            device=next((row for row in self.workspace.phone.snapshot()['devices'] if row.get('id')==self.device_id),None)
            if not device or not device.get('online',False):
                self.stop();self.error='Phone camera stopped. Your phone must stay online and paired.'
                return
        if not all(process.poll() is None for process in self.processes):
            self.stop();self.error=('Phone camera stopped. Keep the phone connected and unlocked, then start it again.'
                                    if self.device_id is None else 'Phone camera stopped. Start it again when you are ready.')

    def _monitor(self,finished):
        while not finished.wait(1):
            with self.lock:
                if finished.is_set():return
                self._check_session()

    def _config(self):return (self.workspace.settings.get('link') or {}).get('camera') or {}

    def _version(self, executable):
        try:key=(executable, os.stat(executable).st_mtime_ns)
        except OSError:return None
        if self._version_cache is None or self._version_cache[0]!=key:
            self._version_cache=(key, scrcpy_version(executable, self.run))
        return self._version_cache[1]

    def _scrcpy(self, config):
        executable = tool_path('scrcpy', config.get('scrcpy_executable'))
        if not executable:
            return None, 'Install scrcpy 2.2 or later to use the phone camera. Settings → Devices explains how.'
        version = self._version(executable)
        if version is not None and version < MIN_SCRCPY:
            return None, (f'This computer has scrcpy {version[0]}.{version[1]}. The phone camera needs scrcpy 2.2 or later; '
                          'Settings → Devices explains how to get it.')
        return executable, ''

    def _prepared(self, preview=False):
        config = self._config()
        if config.get('enabled',True) is False:return None, 'Phone camera is switched off in Settings.'
        executable, message = self._scrcpy(config)
        if not executable:return None, message
        if preview:
            return {'mode':'preview','scrcpy':executable}, ''
        if self.system.startswith('linux'):
            sink = config.get('v4l2_sink')
            if not self.verify_sink(sink):return None, SETUP_MESSAGE
            return {'mode':'linux-v4l2','scrcpy':executable,'sink':sink}, ''
        if self.system=='win32':
            obs = obs_path(config); names = obs_configuration(config)
            if not obs or not names:return None, SETUP_MESSAGE
            return {'mode':'windows-obs','scrcpy':executable,'obs':obs,**names}, ''
        return None, 'Phone camera integration is available on Windows and Linux.'

    def status(self):
        with self.lock:
            self._check_session()
            if self._config().get('enabled',True) is False:self.stop()
            # Discovery can scan thousands of PATH candidates on Windows.
            # Status is read once a second beside the live preview; reuse only
            # this display probe. Starting a legacy capture still calls
            # _prepared() afresh and validates its tools/configuration.
            config = dict(self._config())
            cached = getattr(self, '_status_probe', None)
            now = time.monotonic()
            if cached is None or cached[0] != config:
                prepared, message = self._prepared()
                can_preview = config.get('enabled', True) is not False and self._scrcpy(config)[0] is not None
                self._status_probe = cached = (config, now, prepared, message, can_preview)
            elif now - cached[1] >= 15 and not getattr(self, '_status_refreshing', False):
                # Periodic display discovery must not freeze the dashboard.
                # Config changes and actual starts still validate synchronously.
                self._status_refreshing = True
                def refresh():
                    try:
                        prepared, message = self._prepared()
                        preview = config.get('enabled', True) is not False and self._scrcpy(config)[0] is not None
                        with self.lock:
                            if self._status_probe is cached and config == dict(self._config()):
                                self._status_probe = (config, time.monotonic(), prepared, message, preview)
                    except (OSError, ValueError):
                        with self.lock:
                            if self._status_probe is cached:
                                self._status_probe = (config, time.monotonic(), *cached[2:])
                    finally:
                        self._status_refreshing = False
                self._status_refresh_thread = threading.Thread(target=refresh, name='orion-camera-inspection', daemon=True)
                self._status_refresh_thread.start()
            _, _, prepared, message, can_preview = cached
            running = bool(self.processes) and all(process.poll() is None for process in self.processes)
            if self.processes and not running:
                self.stop(); self.error = 'Phone camera stopped. Start it again when you are ready.'
            if running and self.mode=='preview':
                ready = 'Your phone camera is open in its own window.'
            elif running:
                ready = 'Camera processes are running; select the camera in your meeting app.'
            else:
                ready = 'Ready to start the phone camera.'
            from .camera_native import available as native_available
            local = self.local.status()
            local_active = local['running'] or local['waiting']
            return {'available':prepared is not None,'running':running or local['running'],'verified':False,
                    'integrated_available': native_available(), 'local_state': local['state'],
                    'local_message': local['message'], 'local_preview': local['preview'],
                    'local_resolution': local['resolution'], 'local_fps': local['fps'], 'local_quality': local['quality'],
                    'local_preview_available': self._config().get('enabled',True) is not False,
                    'mode':('windows-saiph' if local_active else self.mode if running else prepared['mode'] if prepared else 'unavailable'),
                    'device_id':self.device_id if running else None,
                    'serial':self.serial if running else None,
                    'can_preview':can_preview,
                    **self.capture_options,
                    'message':self.error or ('' if running else message) or ready}

    def _adb_for(self, config):
        return adb_path(tool_path('scrcpy', config.get('scrcpy_executable')))

    def debug_devices(self):
        """Phones attached over USB or wireless debugging. Lists only; starts nothing."""
        adb = self._adb_for(self._config())
        return {'adb': bool(adb), 'devices': self.debugging_factory(adb, run=self.run).devices() if adb else []}

    def pair(self, address, code):
        return self.debugging_factory(self._adb_for(self._config()), run=self.run).pair(address, code)

    def connect(self, address):
        return self.debugging_factory(self._adb_for(self._config()), run=self.run).connect(address)

    def _require_camera_android(self, adb, serial, flags):
        """scrcpy can open the phone camera only on Android 12 (API 31) or later."""
        try:
            result = self.run([adb,'-s',serial,'shell','getprop','ro.build.version.sdk'],capture_output=True,text=True,timeout=10,creationflags=flags)
            text = (result.stdout or '').strip()
            sdk = int(text) if result.returncode==0 and text.isdigit() else None
        except (OSError, subprocess.SubprocessError):
            sdk = None
        if sdk is not None and sdk < MIN_ANDROID_SDK:
            raise ValueError('Using the phone as a webcam needs Android 12 or later on the phone.')

    def start(self, device_id=None, serial=None, preview=False):
        """Call only from the explicit local UI action; revalidate phone/ADB trust here.

        `device_id` is a phone paired through a self-hosted Hub. `serial` is a phone
        that has allowed this computer over USB or wireless debugging; that is how
        Saiph Cloud and Hub-less computers reach the phone camera."""
        if (device_id is None) == (serial is None):raise ValueError('Choose one phone for the camera.')
        if type(preview) is not bool:raise ValueError('Choose whether to open a camera preview.')
        with self.lock:
            if self._config().get('enabled',True) is False:
                self.stop();raise ValueError('Phone camera is switched off in Settings.')
            if self.local.status()['state'] != 'idle':
                raise ValueError('Stop the current phone camera first.')
            if self.processes:
                if all(process.poll() is None for process in self.processes):
                    if (device_id,serial)!=(self.device_id,None if self.device_id else self.serial) or (self.mode=='preview')!=preview:
                        raise ValueError('Stop the current phone camera first.')
                    return self.status()
                self.stop()
            if device_id is not None:
                device=next((device for device in self.workspace.phone.snapshot()['devices'] if device.get('id')==device_id),None)
                if not device:raise ValueError('Choose a paired phone.')
                if not device.get('online',False):raise ValueError('Your paired phone must be online before starting its camera.')
            config=validate_options(self._config())
            prepared, message = self._prepared(preview)
            if prepared is None:raise ValueError(message)
            unavailable = ('Authorized debugging is unavailable for this phone. Connect it over USB or wireless debugging '
                           'and allow this computer. Settings → Devices explains the one-time phone setup.')
            if device_id is not None:
                worker = self.worker_factory()
                if not worker.adb:worker.adb = adb_path(prepared['scrcpy'])
                if not worker.adb:raise ValueError(unavailable)
                found = worker.paired_serial(device_id)
                adb = worker.adb
            else:
                adb = adb_path(prepared['scrcpy'])
                if not adb:raise ValueError('adb was not found. Install scrcpy (it includes adb), then try again.')
                found = self.debugging_factory(adb, run=self.run).ready(serial)['serial']
            if not isinstance(found,str) or not SERIAL.fullmatch(found):raise ValueError(unavailable)
            flags = subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
            self._require_camera_android(adb, found, flags)
            if prepared['mode']=='windows-obs':
                try:
                    existing = self.run(['tasklist','/FI','IMAGENAME eq obs64.exe','/FO','CSV','/NH'],capture_output=True,text=True,timeout=5,creationflags=flags)
                except (OSError,subprocess.SubprocessError):raise ValueError('Cannot confirm whether OBS is already in use.') from None
                if existing.returncode or 'obs64.exe' in existing.stdout.lower():
                    raise ValueError('OBS is already in use. Close OBS completely (File → Exit), then start the phone camera again.')
            facing=config.get('facing','front');quality=config.get('quality','720p');rotation=config.get('rotation','0')
            args = [prepared['scrcpy'],'--serial',found,'--video-source=camera','--camera-facing='+facing,
                    '--max-size='+('1280' if quality=='720p' else '1920'),'--camera-ar=16:9','--camera-fps=30',
                    '--orientation='+rotation,'--no-audio','--no-control','--window-title',WINDOW_TITLE]
            if prepared['mode']=='linux-v4l2':args += ['--v4l2-sink='+prepared['sink'],'--no-playback']
            environment = os.environ.copy(); environment['ADB'] = str(adb)
            options = {'stdin':subprocess.DEVNULL,'stdout':subprocess.DEVNULL,'stderr':subprocess.DEVNULL,'creationflags':flags}
            try:
                self.processes.append(self.popen(args,env=environment,**options))
                if prepared['mode']=='windows-obs':
                    obs_args = [prepared['obs'],'--profile',prepared['profile'],'--collection',prepared['collection'],
                                '--scene',prepared['scene'],'--startvirtualcam','--minimize-to-tray']
                    self.processes.append(self.popen(obs_args,cwd=str(Path(prepared['obs']).parent),**options))
                self.device_id = device_id; self.serial = found; self.mode = prepared['mode']; self.error = ''
                self.capture_options={'facing':facing,'quality':quality,'rotation':rotation}
                self.monitor_stop=threading.Event()
                threading.Thread(target=self._monitor,args=(self.monitor_stop,),name='orion-camera',daemon=True).start()
                return self.status()
            except OSError:
                self.stop();raise ValueError('Phone camera could not start. Check Settings → Devices.') from None

    def stop(self):
        self.local.stop()
        with self.lock:
            if self.monitor_stop is not None:self.monitor_stop.set()
            for process in reversed(self.processes):
                if process.poll() is None:
                    try:
                        process.terminate();process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill();process.wait(timeout=3)
                    except OSError:pass
            self.processes.clear();self.device_id = None;self.serial = None;self.mode = None;self.capture_options={}
            return {'stopped':True}
