# SPDX-License-Identifier: AGPL-3.0-or-later
"""Launch the standard Seafile applet with its private profile set before Qt starts."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


def launch_configuration(client_root: Path, binary_root: Path, inherited: dict[str, str]) -> tuple[list[str], dict[str, str]]:
    config = client_root.absolute() / "ccnet"
    data = client_root.absolute() / "data"
    executable = binary_root.absolute() / "seafile-applet.exe"
    if not executable.is_file() or not config.is_dir() or not data.is_dir():
        raise ValueError("Prepare the standard private Seafile client first")
    if not (config / "seafile.ini").is_file() or not (data / "repo.db").is_file():
        raise ValueError("Existing Seafile profile is not initialized")
    for value in (str(config), str(data), str(executable)):
        if any(character in value for character in ('"', '\r', '\n', '\0')):
            raise ValueError("Invalid Seafile launch path")
    environment = dict(inherited)
    # Upstream constructs Configurator before parsing -c. Both variables must
    # exist in the child at process creation, not merely as applet arguments.
    environment["CCNET_CONF_DIR"] = config.as_posix()
    environment["SEAFILE_DATA_DIR"] = data.as_posix()
    return [str(executable), "-c", str(config), "-d", str(data)], environment


def run(client_root: Path, binary_root: Path) -> int:
    command, environment = launch_configuration(client_root, binary_root, os.environ)
    options: dict = {}
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        options["startupinfo"] = startup
    with subprocess.Popen(command, env=environment, cwd=binary_root.absolute(),
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          **options) as process:
        # Keep the scheduled task alive with the applet, so its existing restart
        # policy supervises the applet instead of an immediately exited launcher.
        return process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-root", type=Path, default=Path("E:/Documents/OrionLinkClient"))
    parser.add_argument("--binary-root", type=Path, default=Path(os.environ.get("LOCALAPPDATA", "")) / "OrionMini/tools/seafile/9.0.21/portable/bin")
    args = parser.parse_args()
    try:
        return run(args.client_root, args.binary_root)
    except Exception:
        print("The standard Orion Cloud client could not start; verify its private profile and installation.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
