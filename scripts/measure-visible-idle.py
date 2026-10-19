# SPDX-License-Identifier: AGPL-3.0-or-later
"""How busy the desktop's main process is while the dashboard sits visible and idle.

Runs the real shell (MainWindow, bridge, dashboard) offscreen in a fresh synthetic
profile with seeded rows and a synthetic online phone. The page's own Cloud polling
reaches the real bridge (`hosted.requests` every 4 s, `hosted.approvals` every 15 s,
as the setup and approval prompts do); with `--quiet-poll-notices`, a change notice
every 4 s stands in for a Cloud fast poll that announced one whether or not anything
arrived (the behaviour before this change; the controller itself is not started
here). Reports how many state snapshots were built, their average cost, and the main
process's CPU (Chromium's renderer is a separate process and is not included).

    python scripts/measure-visible-idle.py
    python scripts/measure-visible-idle.py --repo build/before3 --dashboard build/before3/dist/index.html --quiet-poll-notices

Synthetic: no installed app, owner profile, account, network or device is used.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--dashboard", type=Path, default=REPO / "frontend" / "dist" / "index.html")
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--quiet-poll-notices", action="store_true")
    options = parser.parse_args(argv)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
    presentation = load("measure_presentation", REPO / "scripts" / "measure-presentation.py")
    app, window = presentation.shell_window(options.repo, options.dashboard)
    seed = load("measure_desktop_state", REPO / "scripts" / "measure-desktop-state.py")
    workspace = window.workspace
    seed.seed(workspace.root, 300, 2000, 150)
    workspace.phone.connected = True
    workspace.phone.restore({"devices": [{"id": "synthetic-phone", "name": "Synthetic phone", "online": True,
        "capabilities": ["battery", "photos", "files", "notifications", "sms", "calls"],
        "battery": {"battery_level": 80, "is_charging": False, "updated_at": 1}}], "notifications": []})
    import psutil
    from PySide6.QtCore import QEventLoop, QTimer

    counts = {"snapshots": 0, "snapshot_ms": 0.0, "notices": 0}
    window.bridge.changed.connect(lambda: counts.__setitem__("notices", counts["notices"] + 1))
    dispatch = workspace.dispatch

    def timed(method, args):
        if method != "state":
            return dispatch(method, args)
        began = time.perf_counter()
        try:
            return dispatch(method, args)
        finally:
            counts["snapshots"] += 1
            counts["snapshot_ms"] += (time.perf_counter() - began) * 1000
    workspace.dispatch = timed

    timers = []
    def every(ms, action):
        timer = QTimer()
        timer.timeout.connect(action)
        timer.start(ms)
        timers.append(timer)
    serial = {"n": 0}
    def page_asks(method):
        serial["n"] += 1
        window.bridge.request(f"measure-{serial['n']}", method, "{}")
    every(4000, lambda: page_asks("hosted.requests"))
    every(15000, lambda: page_asks("hosted.approvals"))
    if options.quiet_poll_notices:
        every(4000, window.bridge.changed.emit)

    window.resize(1320, 900)
    window.show()

    def wait(seconds):
        loop = QEventLoop()
        QTimer.singleShot(int(seconds * 1000), loop.quit)
        loop.exec()

    wait(10)
    for key in counts:
        counts[key] = 0
    me = psutil.Process()
    start, began = me.cpu_times(), time.perf_counter()
    wait(options.seconds)
    end, elapsed = me.cpu_times(), time.perf_counter() - began
    cpu = (end.user + end.system - start.user - start.system) / elapsed * 100
    print(json.dumps({"synthetic": True, "repo": str(options.repo.resolve()), "quiet_poll_notices": options.quiet_poll_notices,
                      "seconds": round(elapsed, 1), "snapshots": counts["snapshots"],
                      "snapshot_ms_avg": round(counts["snapshot_ms"] / max(1, counts["snapshots"]), 1),
                      "change_notices": counts["notices"], "main_process_cpu_percent": round(cpu, 1)}), flush=True)
    window.quit_app()
    return 0


if __name__ == "__main__":
    sys.exit(main())
