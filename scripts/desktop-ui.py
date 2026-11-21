# SPDX-License-Identifier: AGPL-3.0-or-later
"""Launch the real Qt or Electron desktop with a disposable UI-control profile.

Use desktop-ui.cjs to inspect, click, fill, screenshot or run a Playwright flow.
No installed app is restarted or attached. Background device/account workers are
disabled unless --live is explicitly selected. No browser installation is needed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]


def run_electron(directory: Path, session: dict, dashboard: Path, show: bool, timeout: int, fixture: str, executable: Path | None = None) -> int:
    """Launch the native Electron shell; live services require explicit --live."""
    runtime = REPO / "desktop/node_modules/electron"
    packaged = executable is not None
    executable = executable.resolve(strict=True) if executable else runtime / "dist" / (runtime / "path.txt").read_text(encoding="utf-8").strip()
    if not executable.is_file() or not packaged and not (REPO / "desktop/dist/main.cjs").is_file():
        raise ValueError("Install and build desktop/ first; see desktop/README.md.")
    session.update(shell="electron", source_dashboard=dashboard.resolve().as_uri(),
                   dashboard="saiph-app://desktop/index.html", python=sys.executable,
                   show=show, timeout=timeout, fixture=fixture, packaged=packaged)
    write_session(directory, session)
    environment(directory, session, show)
    child_env = dict(os.environ)
    for name in ("ELECTRON_RUN_AS_NODE", "NODE_OPTIONS"):
        child_env.pop(name, None)
    # The shell restarts itself to add this on Wayland; here that would lose the session's process.
    wayland = sys.platform == "linux" and os.environ.get("DISPLAY") and (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland")
    platform = [f"--ozone-platform={os.environ.get('ORION_MINI_ELECTRON_PLATFORM') or 'x11'}"] if wayland else []
    child = subprocess.Popen([str(executable), *platform, *([] if packaged else [str(REPO / "desktop")]), "--ui-session", str(directory / "session.json")],
                             cwd=REPO, env=child_env,
                             creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    try:
        return child.wait(timeout=timeout + 30)
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
        current = json.loads((directory / "session.json").read_text(encoding="utf-8"))
        if current["status"] not in ("stopped", "failed"):
            current["status"] = "failed"
            write_session(directory, current)


def create_session(directory: Path, dashboard: Path, live: bool, existing_profile: Path | None = None) -> dict:
    dashboard = dashboard.resolve(strict=True)
    if not dashboard.is_file() or dashboard.name != "index.html":
        raise ValueError("Choose the built desktop dashboard's index.html.")
    directory = directory.resolve()
    if existing_profile is not None:
        if not live:
            raise ValueError("An existing profile requires explicit --live mode.")
        profile = existing_profile.resolve(strict=True)
        if not profile.is_dir() or not (profile / "settings.json").is_file():
            raise ValueError("Choose an existing Saiph profile with settings.json.")
    else:
        profile = directory / "profile"
    # Never reuse an owner's profile or overwrite another test session.
    directory.mkdir(parents=True, exist_ok=False)
    if existing_profile is None:
        profile.mkdir()
        (profile / "settings.json").write_text(json.dumps({
            "machine": {"name": "Test desktop"},
            "start_with_windows": False, "close_to_tray": False,
        }), encoding="utf-8")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    return {"schema": 1, "pid": os.getpid(), "nonce": secrets.token_hex(24),
            "endpoint": f"http://127.0.0.1:{port}", "dashboard": dashboard.as_uri(),
            "profile": str(profile), "mode": "live" if live else "isolated", "status": "starting",
            "existing_profile": existing_profile is not None}


def write_session(directory: Path, session: dict) -> None:
    temporary = directory / "session.tmp"
    temporary.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
    temporary.replace(directory / "session.json")


def environment(directory: Path, session: dict, show: bool) -> None:
    os.environ["ORION_MINI_DATA_DIR"] = session["profile"]
    os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = session["endpoint"].removeprefix("http://")
    # Qt otherwise allows every web origin when remote debugging is enabled.
    # Visible acceptance must use the app's normal rendering. Software-only
    # rendering is useful for offscreen CI but distorts interactive performance.
    flags = f"--remote-allow-origins={session['endpoint']}"
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = flags if show else flags + " --disable-gpu"
    if session["mode"] == "isolated":
        os.environ["ORION_MINI_TEST"] = "1"
    else:
        os.environ.pop("ORION_MINI_TEST", None)
    if show:
        os.environ.pop("QT_QPA_PLATFORM", None)
    else:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    temporary = directory / "tmp"
    temporary.mkdir()
    os.environ["TEMP"] = os.environ["TMP"] = str(temporary)
    os.environ["TMPDIR"] = str(temporary)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shell", choices=("qt", "electron"), default="electron")
    parser.add_argument("--executable", type=Path, help="Electron bundle executable to test with this session's fresh profile.")
    parser.add_argument("--fixture", choices=("empty", "phone"), default="empty",
                        help="Synthetic phone data for the isolated Electron migration session.")
    parser.add_argument("--session", type=Path, default=REPO / "build" / "desktop-ui" / uuid4().hex,
                        help="New session directory; must not already exist.")
    parser.add_argument("--dashboard", type=Path, default=REPO / "frontend" / "dist" / "index.html")
    parser.add_argument("--live", action="store_true", help="Enable real services in this fresh test profile; uses real account/device actions if requested.")
    parser.add_argument("--existing-profile", type=Path,
                        help="Use an explicitly authorized existing profile in --live mode, without copying it. Refuses a running instance.")
    parser.add_argument("--show", action="store_true", help="Show the native test window instead of rendering offscreen.")
    parser.add_argument("--timeout", type=int, default=3600, help="Stop this test instance after this many seconds.")
    options = parser.parse_args(argv)
    if options.timeout < 1:
        parser.error("--timeout must be positive")
    if options.fixture != "empty" and options.live:
        parser.error("Synthetic fixtures cannot be used with live services.")
    if options.executable and options.shell != "electron":
        parser.error("--executable requires --shell electron")
    if options.fixture != "empty" and options.shell != "electron":
        parser.error("--fixture currently requires --shell electron")
    directory = options.session.resolve()
    try:
        session = create_session(directory, options.dashboard, options.live, options.existing_profile)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    write_session(directory, session)
    if options.shell == "electron":
        try:
            return run_electron(directory, session, options.dashboard, options.show, options.timeout, options.fixture, options.executable)
        except (OSError, ValueError) as error:
            session["status"] = "failed"
            write_session(directory, session)
            parser.error(str(error))
    environment(directory, session, options.show)
    sys.path.insert(0, str(REPO / "src"))

    window = None
    try:
        # WebEngine reads its environment during import; keep these imports here.
        from PySide6.QtCore import QLockFile, QTimer, QUrl
        from PySide6.QtWidgets import QApplication
        from orion_mini.app import MainWindow
        from orion_mini.dashboard_view import prepare_web_engine

        prepare_web_engine(Path(session["profile"]))
        app = QApplication(["Saiph UI test"])
        app.setApplicationName("Saiph UI test")
        # Hold the production lock before opening any databases or keys. This
        # also prevents an installed app from starting during the attended run.
        profile_lock = QLockFile(str(Path(session["profile"]) / "app.lock"))
        if not profile_lock.tryLock(100):
            raise RuntimeError("This Saiph profile is already in use; its running app was left untouched.")
        if session["existing_profile"]:
            from orion_mini.db_health import check as check_databases
            health = check_databases(Path(session["profile"]))
            if any(result == "failed" for result in health["results"].values()):
                raise RuntimeError("The existing profile failed its database check; no workspace was opened.")
        from PySide6.QtWebEngineCore import QWebEngineProfile
        from PySide6.QtWebEngineQuick import QQuickWebEngineProfile
        for browser_profile in (QQuickWebEngineProfile.defaultProfile(), QWebEngineProfile.defaultProfile()):
            browser_profile.setCachePath(str(directory / "browser-cache"))
            browser_profile.setPersistentStoragePath(str(directory / "browser-storage"))

        class TestWindow(MainWindow):
            def dashboard_path(self):
                return options.dashboard.resolve()

        # Real Qt shell, QWebChannel, bridge and LinkWorkspace; no mocked client.
        window = TestWindow(session["profile"], bootstrap=False)
        window.view.add_script("saiph-ui-test-session", f"window.__saiphUISession = {json.dumps(session['nonce'])};")

        def loaded(ok):
            if not ok:
                session["status"] = "failed"
                write_session(directory, session)
                window.quit_app()
                return
            session["status"] = "ready"
            write_session(directory, session)
            print(json.dumps({"session": str(directory / "session.json"),
                              "endpoint": session["endpoint"], "mode": session["mode"]}), flush=True)

        window.view.loadFinished.connect(loaded)
        window.view.load(QUrl(session["dashboard"]))
        window.resize(1280, 900)
        window.show()

        def check_stop():
            request = directory / "stop-request.json"
            try:
                value = json.loads(request.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return
            if value == {"nonce": session["nonce"]}:
                window.quit_app()

        timer = QTimer()
        timer.timeout.connect(check_stop)
        timer.start(200)
        QTimer.singleShot(options.timeout * 1000, window.quit_app)
        signal.signal(signal.SIGINT, lambda *_: window.quit_app())
        signal.signal(signal.SIGTERM, lambda *_: window.quit_app())
        result = app.exec()
        return result if session["status"] == "ready" else 1
    finally:
        if window is not None and not window.closing:
            window.quit_app()
        session["status"] = "stopped" if session["status"] == "ready" else "failed"
        write_session(directory, session)


if __name__ == "__main__":
    raise SystemExit(main())
