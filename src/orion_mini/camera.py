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

from .adb_worker import AdbWorker
from .companion_tools import tool_path

WINDOW_TITLE = 'Orion Phone Camera'
OBS_NAME = 'Orion Phone'
SETUP_MESSAGE = 'Complete the one-time phone camera setup in Settings → Advanced.'


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


class Camera:
    def __init__(self, workspace, *, system=None, popen=subprocess.Popen, run=subprocess.run, worker_factory=AdbWorker, verify_sink=loopback_sink):
        self.workspace = workspace
        self.system = system or sys.platform
        self.popen, self.run, self.worker_factory, self.verify_sink = popen, run, worker_factory, verify_sink
        self.lock = threading.RLock()
        self.processes = []
        self.device_id = None
        self.error = ''
        self.capture_options = {}
        self.monitor_stop = None

    def _check_session(self):
        if not self.processes:return
        device=next((row for row in self.workspace.phone.snapshot()['devices'] if row.get('id')==self.device_id),None)
        if self._config().get('enabled',True) is False or not device or not device.get('online',False):
            self.stop();self.error='Phone camera stopped. Your phone must stay online and paired.'
        elif not all(process.poll() is None for process in self.processes):
            self.stop();self.error='Phone camera stopped. Start it again when you are ready.'

    def _monitor(self,finished):
        while not finished.wait(1):
            with self.lock:
                if finished.is_set():return
                self._check_session()

    def _config(self):return (self.workspace.settings.get('link') or {}).get('camera') or {}

    def _prepared(self):
        config = self._config()
        if config.get('enabled',True) is False:return None, 'Phone camera is switched off in Settings.'
        executable = tool_path('scrcpy', config.get('scrcpy_executable'))
        if not executable:return None, 'Install scrcpy in Settings → Advanced to use the phone camera.'
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
            prepared, message = self._prepared()
            running = bool(self.processes) and all(process.poll() is None for process in self.processes)
            if self.processes and not running:
                self.stop(); self.error = 'Phone camera stopped. Start it again when you are ready.'
            return {'available':prepared is not None,'running':running,'verified':False,
                    'mode':prepared['mode'] if prepared else 'unavailable',
                    'device_id':self.device_id if running else None,
                    **self.capture_options,
                    'message':self.error or message or ('Camera processes are running; select the camera in your meeting app.' if running else 'Ready to start the phone camera.')}

    def start(self, device_id):
        """Call only from the explicit local UI action; revalidate phone/ADB trust here."""
        with self.lock:
            if self._config().get('enabled',True) is False:
                self.stop();raise ValueError('Phone camera is switched off in Settings.')
            if self.processes:
                if all(process.poll() is None for process in self.processes):
                    if device_id!=self.device_id:raise ValueError('Stop the current phone camera first.')
                    return self.status()
                self.stop()
            device=next((device for device in self.workspace.phone.snapshot()['devices'] if device.get('id')==device_id),None)
            if not device:raise ValueError('Choose a paired phone.')
            if not device.get('online',False):raise ValueError('Your paired phone must be online before starting its camera.')
            config=validate_options(self._config())
            prepared, message = self._prepared()
            if prepared is None:raise ValueError(message)
            worker = self.worker_factory()
            serial = worker.paired_serial(device_id)
            if not isinstance(serial,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:\[\]-]{0,199}',serial) or not worker.adb:
                raise ValueError('Authorized debugging is unavailable for this phone. See Settings → Advanced.')
            flags = subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
            if prepared['mode']=='windows-obs':
                try:
                    existing = self.run(['tasklist','/FI','IMAGENAME eq obs64.exe','/FO','CSV','/NH'],capture_output=True,text=True,timeout=5,creationflags=flags)
                except (OSError,subprocess.SubprocessError):raise ValueError('Cannot confirm whether OBS is already in use.') from None
                if existing.returncode or 'obs64.exe' in existing.stdout.lower():
                    raise ValueError('OBS is already in use. Saiph cannot take over its camera session.')
            facing=config.get('facing','front');quality=config.get('quality','720p');rotation=config.get('rotation','0')
            args = [prepared['scrcpy'],'--serial',serial,'--video-source=camera','--camera-facing='+facing,
                    '--max-size='+('1280' if quality=='720p' else '1920'),'--camera-ar=16:9','--camera-fps=30',
                    '--orientation='+rotation,'--no-audio','--no-control','--window-title',WINDOW_TITLE]
            if prepared['mode']=='linux-v4l2':args += ['--v4l2-sink='+prepared['sink'],'--no-playback']
            environment = os.environ.copy(); environment['ADB'] = str(worker.adb)
            options = {'stdin':subprocess.DEVNULL,'stdout':subprocess.DEVNULL,'stderr':subprocess.DEVNULL,'creationflags':flags}
            try:
                self.processes.append(self.popen(args,env=environment,**options))
                if prepared['mode']=='windows-obs':
                    obs_args = [prepared['obs'],'--profile',prepared['profile'],'--collection',prepared['collection'],
                                '--scene',prepared['scene'],'--startvirtualcam','--minimize-to-tray']
                    self.processes.append(self.popen(obs_args,cwd=str(Path(prepared['obs']).parent),**options))
                self.device_id = device_id; self.error = ''
                self.capture_options={'facing':facing,'quality':quality,'rotation':rotation}
                self.monitor_stop=threading.Event()
                threading.Thread(target=self._monitor,args=(self.monitor_stop,),name='orion-camera',daemon=True).start()
                return self.status()
            except OSError:
                self.stop();raise ValueError('Phone camera could not start. Check Settings → Advanced.') from None

    def stop(self):
        with self.lock:
            if self.monitor_stop is not None:self.monitor_stop.set()
            for process in reversed(self.processes):
                if process.poll() is None:
                    try:
                        process.terminate();process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill();process.wait(timeout=3)
                    except OSError:pass
            self.processes.clear();self.device_id = None;self.capture_options={}
            return {'stopped':True}
