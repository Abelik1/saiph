# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sample the idle CPU of the real Qt desktop in a fresh, disposable test session.

Launches scripts/desktop-ui.py (real shell, QWebChannel bridge and dashboard,
isolated profile, background device/account workers off), optionally fills the
profile with synthetic phone rows, waits, then samples the CPU time of the shell
and its QtWebEngineProcess children while the window sits on the Phone page.

    python scripts/measure-desktop-idle.py
    python scripts/measure-desktop-idle.py --seed --seconds 30
    python scripts/measure-desktop-idle.py --repo build/before-src --dashboard build/dist-before/index.html

`--repo` runs another checkout's desktop-ui.py and sources (for a before/after
comparison). Offscreen rendering is software-only, so numbers are synthetic and
only comparable within one machine and mode. No installed app, owner profile,
account or device is touched; the session directory is new and disposable.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]


def tree_cpu(process) -> float:
    import psutil
    total = 0.0
    for item in [process, *process.children(recursive=True)]:
        try:
            times = item.cpu_times()
            total += times.user + times.system
        except psutil.Error:
            pass
    return total


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=REPO, help="Checkout whose desktop-ui.py and src/ to run.")
    parser.add_argument("--dashboard", type=Path, default=REPO / "frontend" / "dist" / "index.html")
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--warmup", type=float, default=8)
    parser.add_argument("--seed", action="store_true", help="Add synthetic phone rows (measure-desktop-state.py) to the test profile.")
    parser.add_argument("--show", action="store_true", help="Visible window with normal rendering instead of offscreen.")
    options = parser.parse_args(argv)
    import psutil

    session = REPO / "build" / "desktop-perf" / uuid4().hex
    command = [sys.executable, str(options.repo.resolve() / "scripts" / "desktop-ui.py"), "--session", str(session),
               "--dashboard", str(options.dashboard.resolve()), "--timeout", str(int(options.warmup + options.seconds + 120))]
    if options.show:
        command.append("--show")
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    child = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    try:
        deadline = time.monotonic() + 90
        info = {}
        while time.monotonic() < deadline:
            try:
                info = json.loads((session / "session.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                info = {}
            if info.get("status") in ("ready", "failed", "stopped") or child.poll() is not None:
                break
            time.sleep(0.25)
        if info.get("status") != "ready":
            print(json.dumps({"error": "The test session did not become ready.", "status": info.get("status")}))
            return 1
        if options.seed:
            subprocess.run([sys.executable, str(REPO / "scripts" / "measure-desktop-state.py"), "--seed-only", info["profile"]],
                           check=True, stdout=subprocess.DEVNULL, creationflags=flags)
        time.sleep(options.warmup)
        process = psutil.Process(child.pid)
        start, began = tree_cpu(process), time.perf_counter()
        time.sleep(options.seconds)
        used = tree_cpu(process) - start
        elapsed = time.perf_counter() - began
        print(json.dumps({"synthetic": True, "rendering": "visible" if options.show else "offscreen",
                          "repo": str(options.repo.resolve()), "dashboard": str(options.dashboard.resolve()), "seeded": options.seed,
                          "seconds": round(elapsed, 1), "cpu_percent_of_one_core": round(100 * used / elapsed, 1)}))
        return 0
    finally:
        try:
            nonce = json.loads((session / "session.json").read_text(encoding="utf-8"))["nonce"]
            (session / "stop-request.json").write_text(json.dumps({"nonce": nonce}), encoding="utf-8")
            child.wait(20)
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
            child.kill()


if __name__ == "__main__":
    sys.exit(main())
