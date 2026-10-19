# SPDX-License-Identifier: AGPL-3.0-or-later
"""Measure what Qt costs to present one web frame, per way of hosting Chromium.

Each configuration runs in its own process with a visible 1320x900 window and
the platform's normal GPU rendering. The page is shaped like the dashboard (a
static full-window canvas, a header) with one small element moved 1 px at
--rate updates per second by a JavaScript timer, so Chromium presents exactly
that many frames. It samples the process tree's CPU with the element still and
moving, then moves the window programmatically for a few seconds and records
how late a 16 ms GUI-thread timer fires (the "lag behind the pointer" proxy).

    python scripts/measure-presentation.py
    python scripts/measure-presentation.py --mode widget --mode quick --backend d3d11

Modes:
  widget     QMainWindow with a QWebEngineView central widget (the shell before this change)
  widget-top a top-level QWebEngineView
  widget-native  the widget in its own native child window (WA_NativeWindow)
  quick      a QQuickView holding a QML WebEngineView (no QWidget at all)
  container  QMainWindow whose central widget is createWindowContainer(QQuickView)
  shell      the real desktop MainWindow and dashboard from --repo/--dashboard, in a
             fresh disposable profile with background workers off (idle on Phone;
             the page's own selected-tab wave is the only motion)

Synthetic: no profile, account, device or installed app is involved. It opens
visible test windows briefly; numbers are for comparing configurations on one
machine.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PAGE = """<!doctype html><html><head><style>
html,body{margin:0;height:100%;background:#040916;color:#e9fbff;font:13px sans-serif;overflow:hidden}
canvas{position:fixed;inset:0;width:100%;height:100%}
header{position:relative;height:64px;display:flex;align-items:center;padding:0 32px;background:rgba(5,11,26,.86)}
#wave{position:absolute;left:120px;bottom:10px;width:40px;height:6px;overflow:hidden}
#wave i{position:absolute;inset:0 -12px 0 0;background:repeating-linear-gradient(90deg,#67e8f9 0 6px,transparent 6px 12px)}
</style></head><body><canvas></canvas><header>Saiph presentation test<span id="wave"><i></i></span></header>
<script>
const c=document.querySelector('canvas');c.width=innerWidth;c.height=innerHeight;const x=c.getContext('2d');
x.strokeStyle='rgba(103,232,249,.25)';for(let i=1;i<=30;i++){x.beginPath();for(let p=0;p<=c.width;p+=6){const y=i*c.height/31+Math.sin(p/c.width*2.6+i*.13)*18;p?x.lineTo(p,y):x.moveTo(p,y)}x.stroke()}
const wave=document.querySelector('#wave i');let k=0;
window.setRate=(rate)=>{clearInterval(window.timer);if(rate>0)window.timer=setInterval(()=>{k=(k+1)%12;wave.style.transform='translateX(-'+k+'px)'},1000/rate)};
</script></body></html>"""

QML = """import QtQuick
import QtWebEngine
WebEngineView { id: view; anchors.fill: parent; url: pageUrl }
"""


def shell_window(repo, dashboard):
    """The real shell in a disposable profile; returns (app, window)."""
    folder = Path(tempfile.mkdtemp(prefix="saiph-present-shell-"))
    profile = folder / "profile"
    profile.mkdir()
    (profile / "settings.json").write_text(json.dumps({"machine": {"name": "Test desktop"}, "start_with_windows": False,
        "close_to_tray": False, "hub": {"base_url": "https://hub.invalid", "device_id": "synthetic-desktop", "paired": True}}), encoding="utf-8")
    os.environ.update({"ORION_MINI_DATA_DIR": str(profile), "ORION_MINI_TEST": "1"})
    if os.environ.get("SAIPH_RENDERING"):  # A presentation choice to try (src/orion_mini/rendering.py).
        (profile / "rendering.json").write_text(os.environ["SAIPH_RENDERING"], encoding="utf-8")
    sys.path.insert(0, str(Path(repo).resolve() / "src"))
    try:
        from orion_mini.dashboard_view import prepare_web_engine
        try:
            prepare_web_engine(profile)
        except TypeError:  # A checkout from before rendering.json.
            prepare_web_engine()
    except ImportError:  # A checkout from before the native dashboard view.
        from orion_mini.frame_feed import register_scheme
        register_scheme()
    from PySide6.QtWidgets import QApplication
    from orion_mini.app import MainWindow
    app = QApplication(["Saiph presentation test"])

    class TestWindow(MainWindow):
        def dashboard_path(self):
            return Path(dashboard).resolve()
    return app, TestWindow(str(profile), bootstrap=False)


def child(mode, backend, rate, seconds, move_seconds, repo=None, dashboard=None):
    if backend:
        os.environ["QSG_RHI_BACKEND"] = backend
    import psutil
    from PySide6.QtCore import QEventLoop, QTimer, QUrl, Qt, QCoreApplication
    from PySide6.QtWidgets import QApplication, QMainWindow, QWidget
    quick = mode in ("quick", "container")
    if mode == "shell":
        app, window = shell_window(repo, dashboard)
        run = lambda code: None
        frames = {"count": 0}
    elif quick:
        from PySide6.QtWebEngineQuick import QtWebEngineQuick
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
        QtWebEngineQuick.initialize()
    if mode != "shell":
        app = QApplication(["Saiph presentation test"])
    folder = Path(tempfile.mkdtemp(prefix="saiph-present-"))
    (folder / "page.html").write_text(PAGE, encoding="utf-8")
    url = QUrl.fromLocalFile(str(folder / "page.html"))
    frames = {"count": 0}
    if mode == "shell":
        pass
    elif quick:
        from PySide6.QtQuick import QQuickView
        (folder / "view.qml").write_text(QML, encoding="utf-8")
        view = QQuickView()
        view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        view.rootContext().setContextProperty("pageUrl", url)
        view.setSource(QUrl.fromLocalFile(str(folder / "view.qml")))
        view.frameSwapped.connect(lambda: frames.__setitem__("count", frames["count"] + 1))
        from PySide6.QtQml import QJSValue
        run = lambda code: view.rootObject().runJavaScript(code, QJSValue())
        if mode == "quick":
            window = view
        else:
            window = QMainWindow()
            window.setCentralWidget(QWidget.createWindowContainer(view, window))
    else:
        from PySide6.QtWebEngineWidgets import QWebEngineView
        web = QWebEngineView()
        web.load(url)
        run = lambda code: web.page().runJavaScript(code)
        if mode == "widget-top":
            window = web
        elif mode == "widget-native":
            # The same widget, but in its own native child window.
            window = QMainWindow()
            web.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
            web.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
            window.setCentralWidget(web)
        else:
            window = QMainWindow()
            window.setCentralWidget(web)
    window.resize(1320, 900)
    window.setPosition(120, 80) if hasattr(window, "setPosition") else window.move(120, 80)
    window.show()
    me = psutil.Process()

    def wait(value):
        loop = QEventLoop()
        QTimer.singleShot(int(value * 1000), loop.quit)
        loop.exec()

    def cpu():
        total = 0.0
        for process in [me, *me.children(recursive=True)]:
            try:
                times = process.cpu_times()
                total += times.user + times.system
            except psutil.Error:
                pass
        return total

    def sample(seconds):
        frames["count"] = 0
        start, began = cpu(), time.perf_counter()
        wait(seconds)
        elapsed = time.perf_counter() - began
        return round(100 * (cpu() - start) / elapsed, 1), round(frames["count"] / elapsed, 1)

    wait(8 if mode == "shell" else 4)
    run("setRate(0)")
    wait(1)
    still, still_frames = sample(seconds)
    if mode == "shell":
        moving, moving_frames = still, still_frames
    else:
        run(f"setRate({rate})")
        wait(1)
        moving, moving_frames = sample(seconds)
    # Move the window as a drag would, and time a 16 ms GUI-thread timer meanwhile.
    gaps, last, step = [], [time.perf_counter()], [0]
    def tick():
        now = time.perf_counter()
        gaps.append((now - last[0]) * 1000)
        last[0] = now
        step[0] += 1
        x = 120 + (step[0] % 60) * 6 if (step[0] // 60) % 2 == 0 else 480 - (step[0] % 60) * 6
        window.setPosition(x, 80) if hasattr(window, "setPosition") else window.move(x, 80)
    timer = QTimer()
    timer.setTimerType(Qt.TimerType.PreciseTimer)
    timer.timeout.connect(tick)
    start_cpu, began = cpu(), time.perf_counter()
    timer.start(16)
    wait(move_seconds)
    timer.stop()
    move_cpu = round(100 * (cpu() - start_cpu) / (time.perf_counter() - began), 1)
    gaps = sorted(gaps[5:])
    result = {"mode": mode, "backend": backend or "default", "rate": None if mode == "shell" else rate,
              **({"repo": str(Path(repo).resolve())} if mode == "shell" else {}),
              "cpu_still": still, "cpu_moving_element": moving,
              "cpu_per_update": round((moving - still) / rate, 2) if rate and mode != "shell" else None,
              "quick_frames_still": still_frames if quick else None, "quick_frames_moving": moving_frames if quick else None,
              "window_move_cpu": move_cpu,
              "move_timer_ms_p50": round(statistics.median(gaps), 1) if gaps else None,
              "move_timer_ms_p95": round(gaps[int(len(gaps) * 0.95)], 1) if gaps else None,
              "move_timer_ms_max": round(gaps[-1], 1) if gaps else None}
    print("RESULT " + json.dumps(result), flush=True)
    if mode == "shell":
        window.quit_app()
    else:
        window.close()
        app.quit()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", action="append", choices=["widget", "widget-top", "widget-native", "quick", "container", "shell"])
    parser.add_argument("--backend", action="append", help="QSG_RHI_BACKEND value(s), e.g. d3d11, opengl; default leaves it unset.")
    parser.add_argument("--rate", type=int, default=10)
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--move-seconds", type=float, default=5)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1], help="Checkout for --mode shell.")
    parser.add_argument("--dashboard", type=Path, default=Path(__file__).resolve().parents[1] / "frontend" / "dist" / "index.html")
    parser.add_argument("--child", nargs=2, metavar=("MODE", "BACKEND"), help=argparse.SUPPRESS)
    options = parser.parse_args(argv)
    if options.child:
        child(options.child[0], "" if options.child[1] == "default" else options.child[1], options.rate, options.seconds, options.move_seconds,
              options.repo, options.dashboard)
        return 0
    results = []
    for mode in options.mode or ["widget", "widget-top", "quick", "container"]:
        for backend in options.backend or ["default"]:
            output = subprocess.run([sys.executable, __file__, "--child", mode, backend, "--rate", str(options.rate),
                                     "--seconds", str(options.seconds), "--move-seconds", str(options.move_seconds),
                                     "--repo", str(options.repo), "--dashboard", str(options.dashboard)],
                                    capture_output=True, text=True, timeout=180)
            line = next((l for l in output.stdout.splitlines() if l.startswith("RESULT ")), None)
            result = json.loads(line[7:]) if line else {"mode": mode, "backend": backend, "error": output.stderr[-400:]}
            results.append(result)
            print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
