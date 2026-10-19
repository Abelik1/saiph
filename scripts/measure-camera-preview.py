# SPDX-License-Identifier: AGPL-3.0-or-later
"""Measure the in-app camera preview end to end with a synthetic loopback phone.

Runs the real Qt shell, bridge and dashboard in a fresh disposable profile
(offscreen unless --show), starts a preview-only camera session, and streams
synthetic 1080p JPEG frames at --fps from a loopback client over the real TLS
camera server. Inside the page it counts distinct pictures actually displayed
(a changed <img> source or a canvas draw) and reports that rate beside what the
desktop received, plus the process tree's CPU. No virtual webcam is registered,
no phone or network peer is involved and nothing is recorded.

    python scripts/measure-camera-preview.py
    python scripts/measure-camera-preview.py --repo build/before-src --dashboard build/dist-before/index.html

`--repo` runs another checkout's sources, for a before/after comparison.
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]

# Counts what the viewer sees: each new <img> picture or canvas draw of the preview.
SAMPLER = """
(() => {
  const state = window.__previewSampler = { shown: [] };
  const note = () => state.shown.push(performance.now());
  const draw = CanvasRenderingContext2D.prototype.drawImage;
  CanvasRenderingContext2D.prototype.drawImage = function (...args) {
    if (this.canvas.getAttribute('aria-label') === 'Live phone camera preview') note();
    return draw.apply(this, args);
  };
  new MutationObserver((changes) => {
    for (const change of changes) {
      const node = change.target;
      if (node.tagName === 'IMG' && node.alt === 'Live phone camera preview') note();
    }
  }).observe(document.body, { subtree: true, attributes: true, attributeFilter: ['src'] });
  new MutationObserver((changes) => {
    for (const change of changes) for (const node of change.addedNodes)
      if (node.querySelector && node.querySelector('img[alt="Live phone camera preview"]')) note();
  }).observe(document.body, { subtree: true, childList: true });
  return true;
})()
"""


def synthetic_frames(count=24):
    """Distinct 1080p JPEGs, so every frame differs like real video."""
    from PySide6.QtCore import QBuffer, QIODevice, Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    frames = []
    for n in range(count):
        image = QImage(1920, 1080, QImage.Format.Format_RGB888)
        image.fill(QColor.fromHsv((n * 15) % 360, 120, 140))
        painter = QPainter(image)
        painter.fillRect(80 + n * 60, 300, 240, 480, Qt.GlobalColor.white)
        painter.end()
        output = QBuffer()
        output.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(output, 'JPEG', 85)
        frames.append(bytes(output.data()))
    return frames


def phone(session, frames, fps, stop):
    """A loopback stand-in for the phone app: authorised upgrade, then paced SCF1 frames."""
    from websockets.sync.client import connect
    from orion_mini.camera_session import FRAME
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.maximum_version = ssl.TLSVersion.TLSv1_2  # See tests/lan_tls.py.
    port = session.server.socket.getsockname()[1]
    with connect(f'wss://127.0.0.1:{port}/camera/{session.session}', ssl=context, proxy=None,
                 additional_headers={'Authorization': 'Bearer ' + session.secret}) as socket:
        sequence, due = 0, time.perf_counter()
        while not stop.is_set():
            sequence += 1
            socket.send(FRAME.pack(b'SCF1', 1920, 1080, 0, sequence) + frames[sequence % len(frames)])
            due += 1 / fps
            time.sleep(max(0, due - time.perf_counter()))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--dashboard", type=Path, default=REPO / "frontend" / "dist" / "index.html")
    parser.add_argument("--fps", type=int, default=20, choices=(15, 20, 30))
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--show", action="store_true")
    options = parser.parse_args(argv)
    directory = REPO / "build" / "camera-perf" / uuid4().hex
    profile = directory / "profile"
    profile.mkdir(parents=True)
    # A synthetic paired Hub puts the Phone page in its normal layout, where the
    # live camera card appears. It is never contacted: ORION_MINI_TEST keeps
    # every background worker off.
    (profile / "settings.json").write_text(json.dumps({"machine": {"name": "Test desktop"}, "start_with_windows": False,
                                                       "close_to_tray": False, "hub": {"base_url": "https://hub.invalid",
                                                       "device_id": "synthetic-desktop", "paired": True}}), encoding="utf-8")
    (directory / "tmp").mkdir()
    os.environ.update({"ORION_MINI_DATA_DIR": str(profile), "ORION_MINI_TEST": "1",
                       "TEMP": str(directory / "tmp"), "TMP": str(directory / "tmp")})
    if not options.show:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
    sys.path.insert(0, str(options.repo.resolve() / "src"))
    import psutil
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtWidgets import QApplication
    try:
        from orion_mini.dashboard_view import prepare_web_engine
        prepare_web_engine()
        from PySide6.QtWebEngineQuick import QQuickWebEngineProfile as QWebEngineProfile
    except ImportError:  # A checkout from before the native dashboard view.
        from PySide6.QtWebEngineCore import QWebEngineProfile
        try:
            from orion_mini.frame_feed import register_scheme
            register_scheme()
        except ImportError:
            pass  # A checkout from before the frame feed.
    from orion_mini.app import MainWindow

    app = QApplication(["Saiph camera preview measurement"])
    browser = QWebEngineProfile.defaultProfile()
    browser.setCachePath(str(directory / "browser-cache"))
    browser.setPersistentStoragePath(str(directory / "browser-storage"))

    class TestWindow(MainWindow):
        def dashboard_path(self):
            return options.dashboard.resolve()

    window = TestWindow(str(profile), bootstrap=False)
    window.resize(1280, 900)
    window.show()

    def wait(seconds):
        loop = QEventLoop()
        QTimer.singleShot(int(seconds * 1000), loop.quit)
        loop.exec()

    def evaluate(code):
        result, loop = {}, QEventLoop()
        done = lambda value: (result.setdefault("value", value), loop.quit())
        if hasattr(window.view, "page"):
            window.view.page().runJavaScript(code, 0, done)
        else:
            window.view.runJavaScript(code, done)
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
        return result.get("value")

    stop = threading.Event()
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not evaluate("document.querySelector('main') !== null"):
            wait(0.5)
        evaluate(SAMPLER)
        # The UI turns the camera setting on before its first session; so does this.
        window.workspace.settings["link"]["camera"]["enabled"] = True
        session = window.workspace.camera.local
        session.addresses = lambda: ["192.168.1.7"]  # Loopback only; the server listens locally.
        session.start(True, resolution="1080p", fps=options.fps, quality="high")
        frames = synthetic_frames()
        sender = threading.Thread(target=phone, args=(session, frames, options.fps, stop), daemon=True)
        sender.start()
        wait(6)  # Live, the dashboard refreshed, the preview card mounted.
        evaluate("window.__previewSampler.shown.length = 0")
        process = psutil.Process()
        def cpu():
            total = 0.0
            for item in [process, *process.children(recursive=True)]:
                try:
                    times = item.cpu_times(); total += times.user + times.system
                except psutil.Error:
                    pass
            return total
        start_cpu, began = cpu(), time.perf_counter()
        wait(options.seconds)
        used, elapsed = cpu() - start_cpu, time.perf_counter() - began
        shown = evaluate("window.__previewSampler.shown.length") or 0
        if os.environ.get("SAIPH_MEASURE_DEBUG"):
            print(evaluate('JSON.stringify({sampler: !!window.__previewSampler, card: !!document.querySelector("[aria-label=\'Live phone camera\']"), '
                           'preview: (document.querySelector("canvas[aria-label=\'Live phone camera preview\'], img[alt=\'Live phone camera preview\']") || {}).tagName || null, '
                           'text: document.body.innerText.slice(0, 300)})'))
        received = session.latest().get("fps", 0) if hasattr(session, "latest") else 0
        print(json.dumps({"synthetic": True, "rendering": "visible" if options.show else "offscreen",
                          "repo": str(options.repo.resolve()), "sent_fps": options.fps, "received_fps": received,
                          "shown_fps": round(shown / elapsed, 1), "cpu_percent_of_one_core": round(100 * used / elapsed, 1),
                          "state": session.status()["state"]}))
        return 0
    finally:
        stop.set()
        window.quit_app()


if __name__ == "__main__":
    sys.exit(main())
