# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unread phone notifications as a badge on Saiph's Windows taskbar button.

Qt 6 dropped QWinTaskbarButton, so the overlay goes through the shell's
ITaskbarList3 with ctypes. Linux has no common badge API (only Unity's
LauncherEntry, which most desktops ignore), so there the badge is not shown.
"""
from __future__ import annotations

import sys

from .phone_settings import preferences

MAX_SHOWN = 99


def unread_count(store, settings) -> int:
    """Phone notifications waiting on this computer, Hub and Saiph Cloud; 0 when the badge or notifications are off."""
    options = preferences(settings)
    if not options["badges"] or not options["features"]["notifications"]:
        return 0
    with store.connect() as db:
        row = db.execute("SELECT COUNT(*) FROM records WHERE kind IN ('phone_notification','hosted_notification')").fetchone()
    return int(row[0] or 0)


def label(count: int) -> str:
    return "" if count <= 0 else str(count) if count <= MAX_SHOWN else f"{MAX_SHOWN}+"


class TaskbarBadge:
    """Sets or clears the overlay; every failure leaves the taskbar as it was."""

    def __init__(self, hwnd: int):
        self.hwnd = hwnd
        self.shown = None
        self._list = None
        self._icon = None

    def _taskbar(self):
        if self._list is not None:
            return self._list
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        def guid(text):
            value = GUID()
            ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(value))
            return value

        ole32 = ctypes.oledll.ole32
        ole32.CoInitializeEx(None, 2)  # Apartment-threaded, like Qt's GUI thread; S_FALSE when already set up.
        pointer = ctypes.c_void_p()
        ole32.CoCreateInstance(ctypes.byref(guid("{56FDF344-FD6D-11d0-958A-006097C9A090}")), None, 1,
                               ctypes.byref(guid("{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}")), ctypes.byref(pointer))
        table = ctypes.cast(ctypes.cast(pointer, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)(table[3])(pointer)  # ITaskbarList::HrInit
        # ITaskbarList3::SetOverlayIcon is the 19th method (index 18) of the vtable.
        overlay = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.HWND, wintypes.HICON, wintypes.LPCWSTR)(table[18])
        self._list = (pointer, overlay)
        return self._list

    def show(self, count: int) -> None:
        text = label(count)
        if sys.platform != "win32" or text == self.shown:
            return
        try:
            pointer, overlay = self._taskbar()
            icon = _icon(text) if text else None
            overlay(pointer, self.hwnd, icon, f"{count} phone notifications" if text else None)
            if self._icon:
                import ctypes
                ctypes.windll.user32.DestroyIcon(self._icon)
            self._icon = icon
            self.shown = text
        except (OSError, ValueError, AttributeError):
            self._list = None  # The taskbar button may not exist yet; try again on the next change.


def _icon(text: str) -> int:
    """A 32-pixel accent circle with the count, as a Windows icon handle."""
    import ctypes
    from ctypes import wintypes
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter

    size = 32
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#c42b1c"))
    painter.drawEllipse(0, 0, size, size)
    font = QFont("Segoe UI", 15 if len(text) == 1 else 12 if len(text) == 2 else 9)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    pixels = bytes(image.constBits())[:size * size * 4]

    class ICONINFO(ctypes.Structure):
        _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD), ("yHotspot", wintypes.DWORD),
                    ("hbmMask", wintypes.HBITMAP), ("hbmColor", wintypes.HBITMAP)]

    gdi32, user32 = ctypes.windll.gdi32, ctypes.windll.user32
    gdi32.CreateBitmap.restype = wintypes.HBITMAP
    user32.CreateIconIndirect.restype = wintypes.HICON
    color = gdi32.CreateBitmap(size, size, 1, 32, pixels)
    mask = gdi32.CreateBitmap(size, size, 1, 1, bytes(size * size // 8))
    try:
        icon = user32.CreateIconIndirect(ctypes.byref(ICONINFO(True, 0, 0, mask, color)))
    finally:
        gdi32.DeleteObject(color)
        gdi32.DeleteObject(mask)
    if not icon:
        raise OSError("The badge icon could not be created.")
    return icon
