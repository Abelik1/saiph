# SPDX-License-Identifier: AGPL-3.0-or-later
"""Use upstream dependency discovery without its unused virtual keyboard plugin.

Orion uses the system's native desktop input method. Collecting every QtGui
platforminputcontexts plugin otherwise pulls the optional GPL-only virtual
keyboard library into a Widgets application, even with QML hooks excluded.
"""
from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
binaries = [(source, target) for source, target in binaries
            if 'qtvirtualkeyboardplugin' not in source.lower()]
