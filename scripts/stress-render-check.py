# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stress the real desktop shell and look for rendering glitches in what Windows shows.

Each configuration runs in its own process: the real shell (MainWindow, bridge,
dashboard) in a fresh synthetic profile with seeded rows and a synthetic phone,
in a window shown without focus and kept behind other windows. Windows Graphics
Capture records only that window's composed pixels (never the rest of the
screen) while the harness drives what tends to expose GPU presentation faults:
a refresh every 300 ms, page and tab switching, scrolling, resizing and moving
the window, and hiding/showing the web view.

A glitch is a frame whose header or footer differs from how they always look.
Those strips (the logo and computer name at the top, the status line at the
bottom) are identical on every page and never move, so missing tiles, stripes,
blocks or pixelation there can only be a rendering fault, whatever the stress is
doing to the page in between. The glitching frame and its neighbours are saved
for review; they contain only the test window.

    python scripts/stress-render-check.py --config native --config native-noflip --config native-opengl
    python scripts/stress-render-check.py --config widget --repo build/before2 --dashboard build/before2/dist/index.html

`--offscreen` renders without any window on screen and checks only Chromium's
own frames (DevTools screencast); use it to compare Chromium settings without
disturbing the desktop:

    python scripts/stress-render-check.py --offscreen --config native --chromium-flags=--run-all-compositor-stages-before-draw

The window capture needs Windows and `pip install windows-capture numpy`.
Synthetic: no installed app, owner profile, account or device is involved.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONFIGS = {
    "native": {},
    "native-noflip": {"QT_D3D_NO_FLIP": "1"},
    "native-opengl": {"QSG_RHI_BACKEND": "opengl"},
    "native-no-gpu-raster": {"QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu-rasterization"},
    "native-basic-loop": {"QSG_RENDER_LOOP": "basic"},
    "native-no-gpu-raster-basic-loop": {"QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu-rasterization", "QSG_RENDER_LOOP": "basic"},
    "native-software": {"QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu"},
    "native-noflip-no-gpu-raster": {"QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu-rasterization", "QT_D3D_NO_FLIP": "1"},
    "native-opengl-no-gpu-raster": {"QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu-rasterization", "QSG_RHI_BACKEND": "opengl"},
    # The same choices as the installed app's rendering.json (src/orion_mini/rendering.py).
    "switch-noflip": {"SAIPH_RENDERING": '{"present": "noflip"}'},
    "switch-opengl": {"SAIPH_RENDERING": '{"backend": "opengl"}'},
    "switch-basic-loop": {"SAIPH_RENDERING": '{"loop": "basic"}'},
    "switch-widget": {"SAIPH_RENDERING": '{"host": "widget"}'},
    "widget": {},
    "widget-no-gpu-raster": {"QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu-rasterization"},
}


class ChromiumFrames:
    """Chromium's own output (DevTools screencast), checked with the same strips.

    A broken frame here was drawn broken by Chromium; one seen only in the
    Windows capture went wrong between Chromium and the screen."""

    def __init__(self, out, config, resizing):
        import numpy as np
        self.np, self.out, self.config, self.resizing = np, out, config, resizing
        self.frames, self.glitches, self.reference, self.running, self.socket, self.error = 0, [], None, True, None, ""
        self.references = {}
        self.begun = time.perf_counter()
        # Off the GUI thread: Qt answers DevTools requests on it.
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def strips(self, grey):
        h, w = grey.shape
        return {"header-left": grey[4:58, 8:72], "header-right": grey[4:58, w - 240:w - 8],
                "footer-left": grey[h - 24:h - 4, 8:200], "footer-right": grey[h - 24:h - 4, w - 200:w - 8]}

    def read(self):
        import base64
        from urllib.request import urlopen
        from websockets.sync.client import connect
        from PySide6.QtGui import QImage
        np = self.np
        try:
            port = os.environ["SAIPH_STRESS_DEBUG_PORT"]
            targets = json.loads(urlopen(f"http://127.0.0.1:{port}/json", timeout=10).read())
            page = next(t for t in targets if t.get("type") == "page")
            self.socket = connect(page["webSocketDebuggerUrl"], max_size=None, open_timeout=10)
            self.socket.send(json.dumps({"id": 1, "method": "Page.startScreencast",
                                         "params": {"format": "png", "everyNthFrame": 1}}))
        except Exception as error:
            self.error = repr(error)[:200]
            return
        while self.running:
            try:
                message = json.loads(self.socket.recv(timeout=1))
            except TimeoutError:
                continue
            except Exception:
                return
            if message.get("method") != "Page.screencastFrame":
                continue
            params = message["params"]
            try:
                self.socket.send(json.dumps({"id": 2, "method": "Page.screencastFrameAck", "params": {"sessionId": params["sessionId"]}}))
            except Exception:
                return
            image = QImage.fromData(base64.b64decode(params["data"])).convertToFormat(QImage.Format.Format_RGB32)
            raw = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(), image.bytesPerLine() // 4, 4)[:, :image.width(), :3]
            grey = raw.astype(np.int16).mean(axis=2)
            self.frames += 1
            # One reference per frame size: the screencast follows window resizes.
            if grey.shape not in self.references:
                self.references[grey.shape] = self.strips(grey)
                if self.reference is not None:
                    continue
                self.reference = self.references[grey.shape]
                broken = grey.copy()
                broken[:, 64:320] = 12  # A missing 256 px tile column must be caught.
                self.self_test = any(int((np.abs(strip - self.reference[name]) > 40).sum()) > 25
                                     for name, strip in self.strips(broken).items())
                continue
            if self.resizing.is_set():
                continue
            bad = {}
            for name, strip in self.strips(grey).items():
                ref = self.references[grey.shape][name]
                if ref.shape == strip.shape:
                    count = int((np.abs(strip - ref) > 40).sum())
                    if count > 25:
                        bad[name] = count
            if bad:
                self.glitches.append({"t": round(time.perf_counter() - self.begun, 3), "strips": bad})
                if len(self.glitches) <= 6:
                    image.save(str(self.out / f"{self.config}-chromium-{len(self.glitches):02d}.png"))

    def stop(self):
        self.running = False
        try:
            if self.socket is not None:
                self.socket.close()
        except Exception:
            pass
        self.thread.join(3)

    def summary(self):
        return {"frames": self.frames, "glitches": len(self.glitches), "first": self.glitches[:8], "error": self.error,
                "self_test": getattr(self, "self_test", None)}


def child(config, repo, dashboard, seconds, out, hide=True):
    import importlib.util as iu
    import numpy as np
    spec = iu.spec_from_file_location("mp", REPO / "scripts" / "measure-presentation.py")
    mp = iu.module_from_spec(spec)
    spec.loader.exec_module(mp)
    app, window = mp.shell_window(repo, dashboard)
    spec = iu.spec_from_file_location("ms", REPO / "scripts" / "measure-desktop-state.py")
    ms = iu.module_from_spec(spec)
    spec.loader.exec_module(ms)
    from PySide6.QtCore import QEventLoop, Qt, QTimer
    workspace = window.workspace
    ms.seed(workspace.root, 300, 2000, 150)
    workspace.phone.connected = True
    workspace.phone.restore({"devices": [{"id": "synthetic-phone", "name": "Synthetic phone", "online": True,
        "capabilities": ["battery", "photos", "files", "notifications", "sms", "calls"],
        "battery": {"battery_level": 80, "is_charging": False, "updated_at": 1}}], "notifications": []})

    title = f"Saiph render stress {os.getpid()}"
    window.setWindowTitle(title)
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    window.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
    parked = os.environ.get("SAIPH_STRESS_PARKED") == "1"
    if parked:
        # Off every monitor, no taskbar button, never focused: Windows still
        # composes it, so the window capture works without showing anything.
        window.setWindowFlag(Qt.WindowType.Tool, True)
    origin = (-6000, -4000) if parked else (80, 60)
    window.resize(1320, 900)
    window.move(*origin)
    window.show()
    offscreen = os.environ.get("QT_QPA_PLATFORM") == "offscreen"
    if not offscreen:
        window.lower()

    def wait(value):
        loop = QEventLoop()
        QTimer.singleShot(int(value * 1000), loop.quit)
        loop.exec()

    def js(code):
        if hasattr(window.view, "page"):
            window.view.page().runJavaScript(code)
        else:
            window.view.runJavaScript(code)

    wait(8)
    if not offscreen:
        window.lower()

    # --- capture: only this window's composed pixels -------------------------------
    if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
        from windows_capture import WindowsCapture
    stats = {"frames": 0, "glitches": [], "sizes": set(), "worst": (0, {})}
    history = []  # (time, small grey frame, full BGRA copy)
    lock = threading.Lock()
    stopping = threading.Event()
    begun = time.perf_counter()
    out.mkdir(parents=True, exist_ok=True)

    def small(frame):
        return frame[::2, ::2, :3].astype(np.int16).mean(axis=2)

    client_w, client_h = window.width(), window.height()
    reference = {}

    def strips(frame):
        """The always-identical strips: header left/right ends, footer left/right ends."""
        h, w = frame.shape[:2]
        side = max(0, (w - window.width()) // 2)
        top = max(0, h - window.height() - side)
        bottom = h - side
        grey = frame[:, :, :3].astype(np.int16).mean(axis=2)
        return {"header-left": grey[top + 4:top + 58, side + 8:side + 72],
                "header-right": grey[top + 4:top + 58, w - side - 240:w - side - 8],
                "footer-left": grey[bottom - 24:bottom - 4, side + 8:side + 200],
                "footer-right": grey[bottom - 24:bottom - 4, w - side - 200:w - side - 8]}

    def deviation(frame):
        found = {}
        for name, strip in strips(frame).items():
            ref = reference.get(name)
            if ref is not None and ref.shape == strip.shape:
                found[name] = int((np.abs(strip - ref) > 40).sum())
        return found

    def check():
        a, b, c = history[-3:]
        if not reference:
            return
        bad = deviation(b[2])
        worst = sum(bad.values())
        if worst > stats["worst"][0]:
            stats["worst"] = (worst, bad)
        bad = {name: count for name, count in bad.items() if count > 25}
        if not bad:
            return
        event = {"t": round(b[0], 3), "strips": bad, "frame": stats["frames"]}
        stats["glitches"].append(event)
        if len(stats["glitches"]) <= 12:
            from PySide6.QtGui import QImage
            for tag, item in (("before", a), ("glitch", b), ("after", c)):
                full = item[2]
                image = QImage(full.data, full.shape[1], full.shape[0], full.strides[0], QImage.Format.Format_ARGB32)
                image.save(str(out / f"{config}-{len(stats['glitches']):02d}-{tag}.png"))

    capture = None if offscreen else WindowsCapture(cursor_capture=False, draw_border=False, window_hwnd=int(window.winId()))

    def on_frame_arrived(frame, control):
        if stopping.is_set():
            control.stop()
            return
        buffer = np.array(frame.frame_buffer, copy=True)
        with lock:
            stats["frames"] += 1
            stats["sizes"].add(buffer.shape[:2])
            history.append((time.perf_counter() - begun, small(buffer), buffer))
            del history[:-3]
            if len(history) == 3 and not resizing.is_set():
                check()

    def on_closed():
        pass

    resizing = threading.Event()
    control = None
    if capture is not None:
        capture.event(on_frame_arrived)
        capture.event(on_closed)
        control = capture.start_free_threaded()
    chromium = ChromiumFrames(out, config, resizing) if os.environ.get("SAIPH_STRESS_DEBUG_PORT") else None
    # Reference strips from a quiet second before any stress begins.
    wait(1.5)
    with lock:
        if history:
            reference.update(strips(history[-1][2]))
            # Self-test: a frame with one missing 256 px tile column must be caught.
            broken = history[-1][2].copy()
            broken[:, 64:320, :3] = 12
            stats["self_test"] = sum(1 for count in deviation(broken).values() if count > 25) > 0

    # --- stress -------------------------------------------------------------------------
    counter = {"n": 0, "tick": 0}
    pages = ["Phone", "Cloud", "Settings", "Phone", "Phone"]
    tabs = ["Messages", "Photos", "Calls", "Messages", "Photos"]

    def churn():
        counter["n"] += 1
        workspace.store.save("phone_notification", {"id": f"live{counter['n']}", "device_id": "synthetic-phone", "key": "live",
            "app": "Synthetic chat", "package": "org.example.chat", "title": "Test contact",
            "text": f"Synthetic live message {counter['n']}", "timestamp": 1_770_000_000_000 + counter["n"], "actions": []})
        window.bridge.changed.emit()

    def scroll():
        js("document.querySelectorAll('*').forEach(e=>{if(e.scrollHeight>e.clientHeight+40&&getComputedStyle(e).overflowY!=='visible'){"
           "e.scrollTop=(e.scrollTop+180)%(e.scrollHeight-e.clientHeight+1)}})")

    def navigate():
        counter["tick"] += 1
        page = pages[counter["tick"] % len(pages)]
        tab = tabs[counter["tick"] % len(tabs)]
        js(f"document.querySelector('nav [aria-label=\"{page}\"]')?.click();"
           f"setTimeout(()=>[...document.querySelectorAll('[role=tab]')].find(t=>t.textContent.trim()==='{tab}')?.click(),300)")

    def reshape():
        resizing.set()
        size = (1320, 900) if counter["tick"] % 2 else (1240, 860)
        window.resize(*size)
        window.move(origin[0] + (counter["tick"] % 3) * 40, origin[1])
        window.lower()
        QTimer.singleShot(1200, resizing.clear)

    def hide_show():
        shown = getattr(window, "dashboard_shown", None)
        if shown is None:
            return
        resizing.set()
        shown(False)
        QTimer.singleShot(400, lambda: (shown(True), QTimer.singleShot(1200, resizing.clear)))

    timers = []
    scale = float(os.environ.get("SAIPH_STRESS_SCALE", "1"))  # Above 1: everything more often.
    stressors = [(300, churn), (120, scroll), (2000, navigate), (7000, reshape)] + ([(11000, hide_show)] if hide else [])
    stressors = [(max(30, int(interval / scale)), action) for interval, action in stressors]
    for interval, action in stressors:
        timer = QTimer()
        timer.timeout.connect(action)
        timer.start(interval)
        timers.append(timer)
    wait(seconds)
    for timer in timers:
        timer.stop()
    stopping.set()
    wait(0.5)
    if control is not None:
        control.stop()
    if chromium is not None:
        chromium.stop()
    result = {"config": config, "env": CONFIGS[config], "flags": os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""),
              "offscreen": offscreen, "hide_show": hide, "repo": str(Path(repo).resolve()), "seconds": seconds,
              "frames": stats["frames"], "glitches": len(stats["glitches"]), "first": stats["glitches"][:12],
              "detector_self_test": stats.get("self_test"), "largest_strip_deviation": stats["worst"],
              **({"chromium": chromium.summary()} if chromium is not None else {})}
    print("RESULT " + json.dumps(result), flush=True)
    window.quit_app()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", action="append", choices=sorted(CONFIGS))
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--dashboard", type=Path, default=REPO / "frontend" / "dist" / "index.html")
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--out", type=Path, default=REPO / "build" / "render-stress")
    parser.add_argument("--chromium", action="store_true", help="Also check Chromium's own frames (DevTools screencast).")
    parser.add_argument("--offscreen", action="store_true", help="No window on screen: check Chromium's frames only.")
    parser.add_argument("--parked", action="store_true", help="A real window placed outside every monitor, without a taskbar button.")
    parser.add_argument("--chromium-flags", default="", help="Extra Chromium flags for every configuration.")
    parser.add_argument("--no-hide", action="store_true", help="Skip hiding/showing the web view (builds without it).")
    parser.add_argument("--child", help=argparse.SUPPRESS)
    options = parser.parse_args(argv)
    if options.child:
        child(options.child, options.repo, options.dashboard, options.seconds, options.out, hide=not options.no_hide)
        return 0
    for config in options.config or ["native", "native-noflip", "native-opengl"]:
        env = dict(os.environ, **CONFIGS[config])
        if options.chromium_flags:
            env["QTWEBENGINE_CHROMIUM_FLAGS"] = (env.get("QTWEBENGINE_CHROMIUM_FLAGS", "") + " " + options.chromium_flags).strip()
        if options.offscreen:
            env["QT_QPA_PLATFORM"] = "offscreen"
        if options.parked:
            env["SAIPH_STRESS_PARKED"] = "1"
        if options.chromium or options.offscreen:
            # Chromium's own frames over DevTools, on a loopback port for this run only.
            import socket
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            env["SAIPH_STRESS_DEBUG_PORT"] = str(port)
            env["QTWEBENGINE_REMOTE_DEBUGGING"] = f"127.0.0.1:{port}"
        process = subprocess.Popen([sys.executable, __file__, "--child", config, "--repo", str(options.repo),
                                    "--dashboard", str(options.dashboard), "--seconds", str(options.seconds),
                                    "--out", str(options.out)] + (["--no-hide"] if options.no_hide else []), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            stdout, stderr = process.communicate(timeout=options.seconds + 120)
        except subprocess.TimeoutExpired:
            import psutil
            for item in [*psutil.Process(process.pid).children(recursive=True), psutil.Process(process.pid)]:
                try:
                    item.kill()
                except psutil.Error:
                    pass
            stdout, stderr = process.communicate()
        line = next((l for l in stdout.splitlines() if l.startswith("RESULT ")), None)
        print(line[7:] if line else json.dumps({"config": config, "error": stderr[-600:]}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
