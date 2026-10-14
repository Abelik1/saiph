# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import ctypes
import sys
from pathlib import Path


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def set_start_with_windows(enabled: bool) -> None:
    if sys.platform != "win32":
        from .platform import set_startup
        return set_startup(enabled)
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, "OrionMini", 0, winreg.REG_SZ, startup_command())
        else:
            try: winreg.DeleteValue(key, "OrionMini")
            except FileNotFoundError: pass


def startup_command() -> str:
    executable = Path(sys.executable)
    if getattr(sys, "frozen", False):
        # Older updaters relaunch through the OrionMini.exe compatibility copy; the
        # installer's shortcuts and startup entry name Saiph.exe beside it.
        preferred = executable.with_name("Saiph.exe")
        if executable.name.lower() == "orionmini.exe" and preferred.is_file():
            executable = preferred
        return f'"{executable}"'
    windowless = executable.with_name("pythonw.exe")
    return f'"{windowless if windowless.exists() else executable}" -m orion_mini'


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text: str):
        super().__init__()
        ctypes.oledll.ole32.CLSIDFromString(text, ctypes.byref(self))


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_ulong)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                ("r3", ctypes.c_ushort), ("value", ctypes.c_void_p), ("extra", ctypes.c_void_p)]


def _call(interface, slot, *argtypes):
    """Invoke a COM method by vtable slot; PySide6 brings no COM binding of its own."""
    table = ctypes.cast(interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    return ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(table[slot])


# IShellLinkW and IPropertyStore vtable slots, after the three IUnknown entries.
_SET_WORKING_DIRECTORY, _SET_ARGUMENTS, _SET_ICON_LOCATION, _SET_PATH = 9, 11, 17, 20
_SET_VALUE, _COMMIT, _SAVE = 6, 7, 6
_PKEY_APP_USER_MODEL_ID = _PROPERTYKEY(_GUID("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"), 5) if sys.platform == "win32" else None
VT_LPWSTR = 31


def write_shortcut(path: Path, target: Path, arguments: str = "", icon: Path | None = None,
                   working_directory: Path | None = None, model_id: str = "") -> Path:
    """Write a .lnk that also declares its application identity.

    Windows resolves a taskbar pin through that identity. Without a shortcut
    carrying it, pinning a running window falls back to the host executable and
    loses both the icon and the command line.
    """
    ole32 = ctypes.oledll.ole32
    ole32.CoInitialize(None)
    link = ctypes.c_void_p()
    ole32.CoCreateInstance(ctypes.byref(_GUID("{00021401-0000-0000-C000-000000000046}")), None, 1,
                           ctypes.byref(_GUID("{000214F9-0000-0000-C000-000000000046}")), ctypes.byref(link))
    try:
        _call(link, _SET_PATH, ctypes.c_wchar_p)(link, str(target))
        if arguments:
            _call(link, _SET_ARGUMENTS, ctypes.c_wchar_p)(link, arguments)
        if working_directory:
            _call(link, _SET_WORKING_DIRECTORY, ctypes.c_wchar_p)(link, str(working_directory))
        if icon:
            _call(link, _SET_ICON_LOCATION, ctypes.c_wchar_p, ctypes.c_int)(link, str(icon), 0)
        if model_id:
            store = ctypes.c_void_p()
            _call(link, 0, ctypes.c_void_p, ctypes.c_void_p)(
                link, ctypes.byref(_GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")), ctypes.byref(store))
            try:
                # propsys does not export InitPropVariantFromString here, so build the
                # string variant directly; PropVariantClear frees the task-allocated copy.
                ctypes.windll.ole32.CoTaskMemAlloc.restype = ctypes.c_void_p
                text = ctypes.create_unicode_buffer(model_id)
                value = _PROPVARIANT()
                value.vt = VT_LPWSTR
                value.value = ctypes.windll.ole32.CoTaskMemAlloc(ctypes.sizeof(text))
                ctypes.memmove(value.value, text, ctypes.sizeof(text))
                try:
                    _call(store, _SET_VALUE, ctypes.c_void_p, ctypes.c_void_p)(
                        store, ctypes.byref(_PKEY_APP_USER_MODEL_ID), ctypes.byref(value))
                    _call(store, _COMMIT)(store)
                finally:
                    ole32.PropVariantClear(ctypes.byref(value))
            finally:
                _call(store, 2)(store)
        persist = ctypes.c_void_p()
        _call(link, 0, ctypes.c_void_p, ctypes.c_void_p)(
            link, ctypes.byref(_GUID("{0000010B-0000-0000-C000-000000000046}")), ctypes.byref(persist))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _call(persist, _SAVE, ctypes.c_wchar_p, ctypes.c_int)(persist, str(path), 1)
        finally:
            _call(persist, 2)(persist)
    finally:
        _call(link, 2)(link)
    return path


def read_shortcut_model_id(path: Path) -> str:
    """Read the identity back, so a written shortcut can be checked rather than assumed."""
    ole32 = ctypes.oledll.ole32
    ole32.CoInitialize(None)
    store = ctypes.c_void_p()
    ctypes.oledll.shell32.SHGetPropertyStoreFromParsingName(
        ctypes.c_wchar_p(str(path)), None, 0,
        ctypes.byref(_GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")), ctypes.byref(store))
    try:
        value = _PROPVARIANT()
        _call(store, 5, ctypes.c_void_p, ctypes.c_void_p)(
            store, ctypes.byref(_PKEY_APP_USER_MODEL_ID), ctypes.byref(value))
        try:
            return ctypes.c_wchar_p(value.value).value or "" if value.vt == VT_LPWSTR else ""
        finally:
            ole32.PropVariantClear(ctypes.byref(value))
    finally:
        _call(store, 2)(store)
