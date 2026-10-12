# SPDX-License-Identifier: AGPL-3.0-or-later
"""Create Start Menu and Desktop shortcuts that carry Orion Mini's application identity.

Windows resolves a taskbar pin through that identity. Pinning the running window
without a matching shortcut produces a pin to the bare host executable, with no
icon and no command line.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from orion_mini.app import APP_MODEL_ID, resource_root
from orion_mini.startup import read_shortcut_model_id, startup_command, write_shortcut

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--name", default="Saiph")
parser.add_argument("--desktop", action="store_true", help="also write a Desktop shortcut")
parser.add_argument("--packaged", action="store_true",
                    help="point at dist/OrionMini/OrionMini.exe instead of this checkout")
args = parser.parse_args()

root = resource_root()
if args.packaged:
    target, arguments = root / "dist" / "OrionMini" / "OrionMini.exe", ""
    if not target.is_file():
        raise SystemExit("Run scripts/build.ps1 first, or drop --packaged.")
else:
    executable = Path(sys.executable)
    windowless = executable.with_name("pythonw.exe")
    target = windowless if windowless.exists() else executable
    arguments = "-m orion_mini"
icon = root / "assets" / "orion-mini-icon.ico"

places = [Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs" / f"{args.name}.lnk"]
if args.desktop:
    places.append(Path(os.environ["USERPROFILE"]) / "Desktop" / f"{args.name}.lnk")

for place in places:
    write_shortcut(place, target, arguments, icon, root, APP_MODEL_ID)
    identity = read_shortcut_model_id(place)
    print(f"{place}\n  target   {target} {arguments}".rstrip())
    print(f"  icon     {icon}")
    print(f"  identity {identity or 'MISSING'}")
    if identity != APP_MODEL_ID:
        raise SystemExit("The shortcut did not keep its application identity.")
print("\nUnpin Saiph if it is already pinned, then pin it again from this shortcut.")
print("Startup entry currently runs:", startup_command())
