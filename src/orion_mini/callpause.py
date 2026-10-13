# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pause this computer's playing media while a paired phone rings or is in a call.

Only players that were actually playing are paused, and only those are resumed
when the call ends: a toggle key could otherwise start playback. Linux uses
playerctl (MPRIS). Windows uses the system media session API when its optional
WinRT binding is installed; otherwise the feature reports itself unavailable."""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys

NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


class Playerctl:
    def __init__(self, runner=subprocess.run):
        self.runner = runner

    def available(self):
        return bool(shutil.which("playerctl"))

    def _run(self, *arguments):
        try:
            result = self.runner(["playerctl", *arguments], capture_output=True, timeout=5, check=False, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            return None
        output = result.stdout.decode("utf-8", "replace") if isinstance(result.stdout, bytes) else (result.stdout or "")
        return output if result.returncode == 0 else None

    def pause_playing(self):
        paused = []
        for player in (self._run("-l") or "").split():
            if (self._run("-p", player, "status") or "").strip() == "Playing" and self._run("-p", player, "pause") is not None:
                paused.append(player)
        return paused

    def resume(self, players):
        for player in players:
            self._run("-p", player, "play")


class WindowsSessions:
    """System Media Transport Controls through the optional winrt binding."""

    def available(self):
        try:
            from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager  # noqa: F401
            return True
        except ImportError:
            return False

    def _sessions(self):
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
        async def load():
            return list((await Manager.request_async()).get_sessions())
        return asyncio.run(load())

    def pause_playing(self):
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status
        paused = []
        for session in self._sessions():
            if session.get_playback_info().playback_status == Status.PLAYING:
                if asyncio.run(session.try_pause_async()):
                    paused.append(session.source_app_user_model_id)
        return paused

    def resume(self, players):
        for session in self._sessions():
            if session.source_app_user_model_id in players:
                asyncio.run(session.try_play_async())


class CallPause:
    def __init__(self, settings, backend=None):
        self.settings = settings
        self.backend = backend or (WindowsSessions() if sys.platform == "win32" else Playerctl())
        self.paused = None  # Players paused for the current call; None when not in a call.

    def enabled(self):
        return (self.settings.get("link") or {}).get("pause_media_on_calls", True) is not False

    def available(self):
        try:
            return self.backend.available()
        except Exception:
            return False

    def call(self, state):
        """Called with the phone's call state: ringing, active, missed or ended."""
        if state in {"ringing", "active"}:
            if self.paused is None and self.enabled() and self.available():
                try:
                    self.paused = self.backend.pause_playing()
                except Exception:
                    self.paused = []
        elif state in {"missed", "ended"} and self.paused is not None:
            players, self.paused = self.paused, None
            if players:
                try:
                    self.backend.resume(players)
                except Exception:
                    pass
