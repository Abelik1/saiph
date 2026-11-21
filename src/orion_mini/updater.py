# SPDX-License-Identifier: AGPL-3.0-or-later
"""Update button: close the app, pull and rebuild it from its source checkout, then reopen it."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .paths import app_data_dir, find_repo, desktop_pid
from . import child_process

SCRIPT = r'''param([int]$AppPid, [string]$Root, [string]$Python)
$Host.UI.RawUI.WindowTitle = 'Updating Saiph'
$exe = Join-Path $Root 'dist\Saiph\Saiph.exe'
function Reopen { if (Test-Path -LiteralPath $exe) { Start-Process -FilePath $exe } }
Write-Host 'Waiting for Saiph to close...'
Wait-Process -Id $AppPid -Timeout 60 -ErrorAction SilentlyContinue
if (Get-Process -Id $AppPid -ErrorAction SilentlyContinue) { Write-Warning 'Saiph is still closing. No build files were changed.'; exit 1 }
Set-Location -LiteralPath $Root
if (Test-Path -LiteralPath (Join-Path $Root '.git')) {
  Write-Host 'Pulling the latest changes...'
  git pull --ff-only
  if ($LASTEXITCODE) { Write-Warning 'git pull did not finish; rebuilding the files already on disk.' }
}
Write-Host 'Rebuilding...'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'scripts\build.ps1') -Python $Python
if ($LASTEXITCODE) {
  Write-Host ''
  Write-Host 'The rebuild failed. Scroll up for the reason.' -ForegroundColor Red
  Reopen
  Read-Host 'Press Enter to close this window'
  exit 1
}
Reopen
'''


def source_checkout() -> Path | None:
    """The folder holding scripts/build.ps1: this source tree, or the orion_mini repo on this computer."""
    own = Path(__file__).resolve().parents[2]
    for folder in (own, find_repo("orion_mini")):
        if folder and (folder / "scripts" / "build.ps1").is_file():
            return folder
    return None


def start_update(checkout: Path | None = None, pid: int | None = None) -> Path:
    """Start the detached update script in its own console. The caller must then quit the app."""
    if sys.platform != "win32":
        raise ValueError("This build updates from its Linux source checkout. Run python scripts/build-native.py --profile link there, then reopen Saiph.")
    checkout = checkout or source_checkout()
    if checkout is None:
        raise ValueError("Saiph's source folder (with scripts\build.ps1) was not found on this computer.")
    script = app_data_dir() / "update.ps1"
    script.write_text(SCRIPT, encoding="utf-8-sig")
    env = child_process.system_environment()
    child_process.popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-AppPid", str(pid or desktop_pid()), "-Root", str(checkout), "-Python", sys.executable],
        creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP,
        cwd=str(checkout), env=env, close_fds=True)
    return script
