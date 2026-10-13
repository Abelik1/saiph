# SPDX-License-Identifier: AGPL-3.0-or-later
"""Launch only Orion's installed bundled worker on an authorized, paired device."""
import os
import re
import subprocess
from pathlib import Path
from .companion_tools import tool_path

PACKAGE = 'com.orionmini.mobile'
def worker_command(status):
    apk = status.get('apk',''); starter = status.get('starter','')
    if not re.fullmatch(r'/data/app/(?:~~[A-Za-z0-9_=+\-]+/)?com\.orionmini\.mobile-[A-Za-z0-9_=+\-]+/base\.apk', apk):
        raise ValueError('Invalid installed Orion APK path')
    base=apk.rsplit('/',1)[0]
    if starter not in {base+'/lib/arm64/libsefirah_worker.so',base+'/lib/x86_64/libsefirah_worker.so',base+'/lib/arm/libsefirah_worker.so',base+'/lib/x86/libsefirah_worker.so'}:
        raise ValueError('Invalid installed Orion worker path')
    # The existing native starter daemonizes itself. Its two arguments are
    # validated installed paths; no bus-provided shell command is executed.
    return f'{starter} --apk={apk}'

class AdbWorker:
    def __init__(self):
        sdk=Path(__file__).resolve().parents[2]/'.orion-mini/android-sdk/platform-tools'
        self.adb=tool_path('adb') or next((str(p) for p in (sdk/'adb.exe',sdk/'adb') if p.is_file()),None)
        self.status='Authorized debugging is unavailable.'
    def run(self,*args):
        if not self.adb:return ''
        result=subprocess.run([self.adb,*args],capture_output=True,text=True,timeout=10,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        return result.stdout if result.returncode==0 else ''
    def poll(self, paired):
        if not self.adb:return
        try:
            attached=self.run('devices')
            for line in attached.splitlines()[1:]:
                fields=line.split()
                if len(fields)!=2 or fields[1]!='device':continue
                serial=fields[0]
                raw=self.run('-s',serial,'shell','content','call','--uri',f'content://{PACKAGE}.worker.bridge','--method','status')
                status=dict(re.findall(r'(apk|starter|device_id|worker_alive|watching)=([^,}\s]+)',raw))
                # ADB authorization alone does not establish Orion trust.
                if status.get('device_id') not in paired or status.get('watching')!='true':continue
                if status.get('worker_alive')!='true':
                    self.run('-s',serial,'shell',worker_command(status))
                self.status='Bundled clipboard worker is managed automatically.'
        except (OSError,subprocess.SubprocessError,ValueError):
            self.status='The bundled worker will retry when authorized debugging is available.'

    def paired_serial(self, device_id):
        """Resolve a deliberate local mirror request using the installed provider."""
        for line in self.run('devices').splitlines()[1:]:
            fields=line.split()
            if len(fields)!=2 or fields[1]!='device':continue
            raw=self.run('-s',fields[0],'shell','content','call','--uri',f'content://{PACKAGE}.worker.bridge','--method','status')
            status=dict(re.findall(r'(device_id)=([^,}\s]+)',raw))
            if status.get('device_id')==device_id:return fields[0]
        raise ValueError('Authorized debugging is unavailable for this phone. Connect it over USB or wireless debugging and allow this computer. Optional tools in the setup guide shows whether adb is installed.')
