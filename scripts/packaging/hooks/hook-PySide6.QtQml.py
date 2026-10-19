# SPDX-License-Identifier: AGPL-3.0-or-later
"""Collect only the QML imports the dashboard's web view uses.

The dashboard is one QML WebEngineView in a native child window
(src/orion_mini/dashboard_view.py). PyInstaller's own QtQml hook would collect
every QML module in the wheel, including GPL-only Charts, Graphs and the virtual
keyboard. This hook keeps the upstream Qt library dependencies and adds just:
QtQml (with its Models and WorkerScript imports), QtQuick, QtWebEngine and
QtWebChannel, each without sub-modules. Menus, tooltips and dialogs are native
Qt widgets, so QtWebEngine.ControlsDelegates and Qt Quick Controls stay out.
"""
from pathlib import Path, PurePath

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info

# Each import directory's own files only, never its sub-modules.
QML_IMPORTS = ('QtQml', 'QtQml/Models', 'QtQml/WorkerScript', 'QtQuick', 'QtWebEngine', 'QtWebChannel')

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
source = Path(pyside6_library_info.location['QmlImportsPath']).resolve()
target = PurePath(pyside6_library_info.qt_rel_dir) / 'qml'
for name in QML_IMPORTS:
    folder = source / name
    if not (folder / 'qmldir').is_file():
        raise SystemExit(f'Missing QML import {name} in {source}')
    for item in sorted(folder.iterdir()):
        if not item.is_file():
            continue
        entry = (str(item), str(target / name))
        (binaries if item.suffix.lower() in ('.dll', '.so', '.dylib') else datas).append(entry)
