# SPDX-License-Identifier: AGPL-3.0-or-later
from types import SimpleNamespace

from orion_mini.callpause import CallPause, Playerctl


class Backend:
    def __init__(self, playing=("spotify",)):
        self.playing, self.calls = list(playing), []

    def available(self):
        return True

    def pause_playing(self):
        self.calls.append("pause")
        return list(self.playing)

    def resume(self, players):
        self.calls.append(("resume", players))


def test_pauses_once_per_call_and_resumes_only_what_it_paused():
    backend = Backend()
    pause = CallPause({"link": {}}, backend)
    pause.call("ringing"); pause.call("active")
    pause.call("ended")
    assert backend.calls == ["pause", ("resume", ["spotify"])]
    pause.call("ended")
    assert len(backend.calls) == 2


def test_nothing_playing_resumes_nothing_and_setting_switches_it_off():
    backend = Backend(playing=())
    pause = CallPause({"link": {}}, backend)
    pause.call("ringing"); pause.call("missed")
    assert backend.calls == ["pause"]
    off = Backend()
    CallPause({"link": {"pause_media_on_calls": False}}, off).call("ringing")
    assert off.calls == []


def test_playerctl_pauses_only_players_that_are_playing():
    commands = []
    statuses = {"spotify": "Playing", "vlc": "Paused"}
    def run(command, **_kwargs):
        commands.append(command[1:])
        if command[1:] == ["-l"]:
            return SimpleNamespace(returncode=0, stdout=b"spotify\nvlc\n")
        if command[-1] == "status":
            return SimpleNamespace(returncode=0, stdout=statuses[command[2]].encode())
        return SimpleNamespace(returncode=0, stdout=b"")
    player = Playerctl(run)
    assert player.pause_playing() == ["spotify"]
    player.resume(["spotify"])
    assert ["-p", "spotify", "pause"] in commands and ["-p", "vlc", "pause"] not in commands
    assert commands[-1] == ["-p", "spotify", "play"]
