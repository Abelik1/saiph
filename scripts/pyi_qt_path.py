# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ensure a frozen Windows build resolves Qt DLLs from its bundled PySide6 folder."""
import os
import sys
import ctypes


if getattr(sys, "frozen", False) and sys.platform == 'win32':
    # Ensure Qt binds the Windows unversioned ICU API, not a namespaced
    # ICU from a toolchain in PATH or a transitive bundle dependency.
    _orion_windows_icu = ctypes.WinDLL(os.path.join(os.environ["SystemRoot"], "System32", "icuuc.dll"))
    bundled_qt = os.path.join(sys._MEIPASS, "PySide6")
    if os.path.isdir(bundled_qt):
        _orion_qt_dll_directory = os.add_dll_directory(bundled_qt)
