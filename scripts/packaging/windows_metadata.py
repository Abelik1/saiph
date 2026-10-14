# SPDX-License-Identifier: AGPL-3.0-or-later
"""Generate consistent Windows file resources without changing installed identities."""
from __future__ import annotations

from pathlib import Path
import re


def version_tuple(version: str, build: int) -> tuple[int, int, int, int]:
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)(?:-[A-Za-z0-9.-]+)?", version)
    if not match or type(build) is not int:
        raise ValueError("Explicit semantic version and integer build required")
    values = (*map(int, match.groups()), build)
    if any(value < 0 or value > 65535 for value in values):
        raise ValueError("Windows version components must be between 0 and 65535")
    return values


def write_version_resource(path: Path, version: str, build: int, profile: str):
    numbers = version_tuple(version, build)
    if profile not in {"link", "workspace"}:
        raise ValueError("Unknown desktop profile")
    strings = {"CompanyName": "Saiph contributors", "FileDescription": "Saiph " + profile.title(),
               "FileVersion": version, "InternalName": "Saiph", "OriginalFilename": "Saiph.exe",
               "ProductName": "Saiph", "ProductVersion": version}
    entries = ",\n".join(f"            StringStruct({key!r}, {value!r})" for key, value in strings.items())
    path.write_text(f"""# UTF-8
VSVersionInfo(
    ffi=FixedFileInfo(filevers={numbers!r}, prodvers={numbers!r},
                      mask=0x3f, flags={2 if '-' in version else 0}, OS=0x40004,
                      fileType=0x1, subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable('040904B0', [
{entries}
    ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""", encoding="utf-8")


def write_assembly_metadata(path: Path, version: str, build: int, profile: str):
    numbers = version_tuple(version, build)
    if profile not in {"link", "workspace"}:
        raise ValueError("Unknown desktop profile")
    numeric = ".".join(map(str, numbers))
    path.write_text(f"""// Generated from package-manifest.json. No signing credentials.
using System.Reflection;
[assembly: AssemblyTitle("Saiph {profile.title()} Setup")]
[assembly: AssemblyDescription("Saiph {profile.title()} per-user installer")]
[assembly: AssemblyCompany("Saiph contributors")]
[assembly: AssemblyProduct("Saiph")]
[assembly: AssemblyVersion("{numeric}")]
[assembly: AssemblyFileVersion("{numeric}")]
[assembly: AssemblyInformationalVersion("{version}")]
""", encoding="utf-8")
