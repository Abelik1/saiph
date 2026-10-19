# SPDX-License-Identifier: AGPL-3.0-or-later
"""The bundled Windows camera component; never discover other apps' DLLs."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys


def component_root():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'camera'
    return Path(__file__).resolve().parents[2] / 'build/camera-native'


def available():
    root = component_root()
    return sys.platform == 'win32' and all((root / name).is_file() for name in ('SaiphCamera64.dll', 'SaiphCamera32.dll'))


class NativeCameraSink:
    def __init__(self):
        if not available():
            raise ValueError('This build does not include the Saiph webcam component. Camera preview is still available.')
        root = component_root()
        self.dll = ctypes.WinDLL(str(root / 'SaiphCamera64.dll'))
        register = self.dll.DllRegisterServer
        register.restype = ctypes.c_long
        if register() != 0:
            raise ValueError('Saiph Camera could not be enabled. Close other Saiph installations and reinstall this build.')
        # This component's registration is explicitly per-user. System regsvr32
        # selects the x86 COM view; no administrator or third-party installer.
        system = Path(os.environ.get('SystemRoot', 'C:/Windows'))
        result = subprocess.run([str(system / 'SysWOW64/regsvr32.exe'), '/s', str(root / 'SaiphCamera32.dll')],
                                timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise ValueError('Saiph Camera setup could not finish. Reinstall this Saiph build and try again.')
        self.write_fn = ctypes.CDLL(str(root / 'SaiphCamera64.dll')).SaiphCameraWriteSized
        self.write_fn.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
        self.write_fn.restype = ctypes.c_int
        self.stop_fn = ctypes.CDLL(str(root / 'SaiphCamera64.dll')).SaiphCameraStop
        self.stop_fn.argtypes = []
        self.stop_fn.restype = None

    def write(self, rgba, width=1280, height=720):
        if type(rgba) is not bytes or (width, height) not in ((1280, 720), (1920, 1080)) or len(rgba) != width * height * 4:
            raise ValueError('Camera frame has an unexpected size.')
        if self.write_fn(ctypes.c_char_p(rgba), len(rgba), width, height) < 0:
            raise ValueError('Saiph Camera could not accept a frame.')

    def close(self):
        self.stop_fn()
