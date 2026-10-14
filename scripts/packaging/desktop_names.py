# SPDX-License-Identifier: AGPL-3.0-or-later
"""Executable names that people see, and the compatibility copy older updaters need.

Installed 0.1.0-beta.4 and earlier updaters, and Hub releases from before the
rename, look for ``app/OrionMini(.exe)`` in every newer package. Packages
therefore carry a byte-identical copy under that name. Application identity,
install and data folders, registry names and the ``orion/`` archive prefix are
compatibility identifiers and do not change here.
"""
from __future__ import annotations

PLATFORMS = ('windows-x86_64', 'linux-x86_64')


def _platform(platform: str) -> bool:
    if platform not in PLATFORMS:
        raise ValueError('Unknown desktop platform')
    return platform.startswith('windows')


def bundle_name(platform: str) -> str:
    """PyInstaller ``--name``: the dist/build folder and the executable stem."""
    return 'Saiph' if _platform(platform) else 'saiph'


def executable(platform: str) -> str:
    return 'Saiph.exe' if _platform(platform) else 'saiph'


def legacy_executable(platform: str) -> str:
    return 'OrionMini.exe' if _platform(platform) else 'OrionMini'


def host_platform() -> str:
    import os
    return 'windows-x86_64' if os.name == 'nt' else 'linux-x86_64'
