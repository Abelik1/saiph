# SPDX-License-Identifier: AGPL-3.0-or-later
"""Calls through this computer's audio (B2). Synthetic fixtures only: a fake Linux
computer, adapter, phone and PipeWire telephony bus. Nothing real is read or changed,
and these tests say nothing about real Bluetooth audio (see docs/CALL_AUDIO.md)."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from orion_mini import call_audio
from orion_mini.call_audio import (AWAY_MESSAGE, CallAudio, Telephony, adapter_state, device_state, paired_devices,
                                   readiness, setup_text, validate_options)

PHONE = "AA:BB:CC:DD:EE:01"
OTHER = "AA:BB:CC:DD:EE:02"
AG = "/org/pipewire/Telephony/ag1"
CALL = AG + "/call1"
GATEWAY_LINE = "\tUUID: Handsfree Audio Gateway   (0000111f-0000-1000-8000-00805f9b34fb)\n"


class FakeComputer:
    """Answers the commands CallAudio runs, and keeps PipeWire's telephony state."""

    def __init__(self, *, pipewire="1.6.2", wireplumber="0.5.13", handsfree=True, telephony=True, powered=True,
                 adapter=True, paired=True, connected=True, gateway=True, reject_sco=False, nodes=False,
                 sco_follows_answer=False, registers_after_restart=False):
        self.pipewire, self.wireplumber = pipewire, wireplumber
        self.handsfree, self.telephony, self.powered, self.adapter = handsfree, telephony, powered, adapter
        self.paired, self.connected, self.gateway = paired, connected, gateway
        self.reject_sco, self.nodes = reject_sco, nodes
        self.transport, self.codec, self.calls = "idle", 2, {}
        self.sco_follows_answer, self.registers_after_restart = sco_follows_answer, registers_after_restart
        self.commands = []

    def ring(self, state="incoming"):
        self.calls[CALL] = state

    def answered_on_phone(self):
        self.calls[CALL] = "active"
        if self.sco_follows_answer and not self.reject_sco:
            self.transport = "active"

    def objects(self):
        ag = {"org.pipewire.Telephony.AudioGateway1": {"Address": {"type": "s", "data": PHONE.lower()}},
              "org.pipewire.Telephony.AudioGatewayTransport1": {"State": {"type": "s", "data": self.transport},
                                                                 "Codec": {"type": "y", "data": self.codec},
                                                                 "RejectSCO": {"type": "b", "data": self.reject_sco}}}
        objects = {AG: ag}
        for path, state in self.calls.items():
            objects[path] = {"org.pipewire.Telephony.Call1": {"State": {"type": "s", "data": state},
                                                               "LineIdentification": {"type": "s", "data": "+15550100"},
                                                               "Name": {"type": "s", "data": ""}}}
        return objects

    def answer(self, command):
        joined = " ".join(command)
        if command[:2] == ["pipewire", "--version"]:
            return f"pipewire\nLinked with libpipewire {self.pipewire}\n"
        if command[:2] == ["wireplumber", "--version"]:
            return f"wireplumber\nLinked with libwireplumber {self.wireplumber}\n"
        if command == ["bluetoothctl", "--version"]:
            return "bluetoothctl: 5.85\n"
        if command == ["pactl", "info"]:
            return f"Server Name: PulseAudio (on PipeWire {self.pipewire})\n"
        if command == ["bluetoothctl", "show"]:
            if not self.adapter:
                return None
            return (f"Controller 00:11:22:33:44:55 (public)\n\tPowered: {'yes' if self.powered else 'no'}\n"
                    + ("\tUUID: Handsfree                 (0000111e-0000-1000-8000-00805f9b34fb)\n" if self.handsfree else ""))
        if command == ["bluetoothctl", "devices", "Paired"]:
            return f"Device {PHONE} Test Phone\nDevice {OTHER} Test Earbuds\n" if self.paired else ""
        if command[:2] == ["bluetoothctl", "info"]:
            if command[2] == PHONE and self.paired:
                return (f"Device {PHONE} (public)\n\tPaired: yes\n\tConnected: {'yes' if self.connected else 'no'}\n"
                        + (GATEWAY_LINE if self.gateway else ""))
            if command[2] == OTHER and self.paired:
                return f"Device {OTHER} (public)\n\tPaired: yes\n\tConnected: no\n"
            return None
        if command[:2] == ["busctl", "--user"] and "list" in command:
            return "org.pipewire.Telephony 1200 pipewire user - - -\n" if self.telephony else ""
        if command[:2] == ["busctl", "--system"]:
            return "org.bluez 800 bluetoothd root - - -\n"
        if "GetManagedObjects" in command:
            if not self.telephony:
                return None
            if command[5] == call_audio.ROOT_PATH:
                return json.dumps({"type": "a{oa{sa{sv}}}", "data": [self.objects()]})
            return json.dumps({"type": "a{oa{sa{sv}}}", "data": [{}]})
        if "set-property" in command and "RejectSCO" in command:
            self.reject_sco = command[-1] == "true"
            return ""
        if command[-1] == "Activate":
            if any(state == "active" for state in self.calls.values()):
                self.transport = "active"
            return ""
        if command[-1] == "Answer":
            self.answered_on_phone()
            return ""
        if command[-1] == "Hangup":
            self.calls.pop(command[4], None)
            return ""
        if command == ["systemctl", "--user", "restart", "wireplumber"]:
            if self.registers_after_restart:
                self.handsfree = True
            return ""
        if command[:3] == ["pactl", "list", "short"]:
            name = "bluez_input.aa_bb_cc_dd_ee_01.0" if command[3] == "sources" else "bluez_output.aa_bb_cc_dd_ee_01.1"
            return f"57\t{name}\tPipeWire\tfloat32le 1ch 16000Hz\tRUNNING\n" if self.nodes else ""
        raise AssertionError("Unexpected command: " + joined)

    def run(self, command, **options):
        assert options["timeout"] and options["stdin"] is subprocess.DEVNULL
        self.commands.append(command)
        out = self.answer(command)
        return SimpleNamespace(returncode=0 if out is not None else 1, stdout=out or "")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def make(tmp_path, monkeypatch, computer=None, *, enabled=True, device=PHONE, platform="linux"):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    computer = computer or FakeComputer()
    clock = Clock()
    settings = {"link": {"call_audio": {"enabled": enabled, "device": device}}}
    audio = CallAudio(settings, runner=computer.run, which=lambda name: "/usr/bin/" + name, platform=platform,
                      home=tmp_path / "home", root=tmp_path / "root", clock=clock, sleep=clock.sleep, threaded=False)
    changes = []
    audio.changed = lambda: changes.append(audio.session["state"])
    return audio, computer, clock, changes


def busctl(computer, word):
    return [c for c in computer.commands if c[0] == "busctl" and word in c]


# Detection -----------------------------------------------------------------------------------
def test_parsers_read_adapter_phone_and_paired_list():
    assert adapter_state("") == {"present": False, "powered": None}
    assert adapter_state("Controller 00:11:22:33:44:55\n\tPowered: no\n") == {"present": True, "powered": False}
    assert device_state(f"Device {PHONE}\n\tPaired: yes\n\tConnected: yes\n{GATEWAY_LINE}") == {"paired": True, "connected": True, "gateway": True}
    assert device_state(None) == {"paired": False, "connected": False, "gateway": False}
    assert paired_devices(f"Device {PHONE} Test Phone\nnoise\nDevice nope Name\n") == [{"address": PHONE, "name": "Test Phone"}]


READY_FACTS = {"probe": {"audio": "ready"}, "adapter": {"present": True, "powered": True},
               "phones": {PHONE: {"paired": True, "connected": True, "gateway": True}}}


@pytest.mark.parametrize("change, options, expected", [
    (None, {"device": PHONE}, "checking"),
    ({"probe": {"audio": "unsupported", "issues": ["The sound server is not PipeWire."]}}, {"device": PHONE}, "unsupported"),
    ({"adapter": {"present": False, "powered": None}}, {"device": PHONE}, "no-adapter"),
    ({"adapter": {"present": True, "powered": False}}, {"device": PHONE}, "bluetooth-off"),
    ({"probe": {"audio": "needs-setup"}}, {"device": PHONE}, "needs-setup"),
    ({}, {}, "choose-phone"),
    ({}, {"device": OTHER}, "not-paired"),
    ({"phones": {PHONE: {"paired": True, "connected": True, "gateway": False}}}, {"device": PHONE}, "no-calls-profile"),
    ({"phones": {PHONE: {"paired": True, "connected": False, "gateway": True}}}, {"device": PHONE}, "phone-away"),
    ({}, {"device": PHONE}, "ready"),
])
def test_readiness_covers_every_setup_step(change, options, expected):
    facts = None if change is None else {**READY_FACTS, **change}
    state, message = readiness(facts, options)
    assert state == expected and message
    if expected == "unsupported":
        assert message == "The sound server is not PipeWire."


def test_preferences_are_validated():
    assert validate_options({"enabled": True, "device": PHONE}) == {"enabled": True, "device": PHONE}
    assert validate_options({"device": ""}) == {"device": ""}
    for bad in ({"enabled": "yes"}, {"device": "phone"}, {"relay": True}, []):
        with pytest.raises(ValueError):
            validate_options(bad)


def test_windows_and_macos_are_reported_without_running_anything(tmp_path, monkeypatch):
    for platform in ("win32", "darwin"):
        audio, computer, _, _ = make(tmp_path, monkeypatch, platform=platform)
        status = audio.status()
        assert status["supported"] is False and status["windows"] is (platform == "win32")
        assert computer.commands == []
        audio.call_state("ringing")
        assert audio.answered_here() is None and audio.fallback("answer") is None
        with pytest.raises(ValueError, match="Linux"):
            audio.move_here()
        with pytest.raises(ValueError, match="Linux"):
            audio.apply_setup()


def test_ubuntu_26_04_with_a_connected_phone_is_ready(tmp_path, monkeypatch):
    audio, computer, _, _ = make(tmp_path, monkeypatch)
    status = audio.status()
    assert status["readiness"] == "ready" and status["call_control"] == "hfp" and status["phone_connected"] is True
    assert status["versions"]["pipewire"] == "1.6.2"
    assert status["setup"] == {"action": "", "file": str(tmp_path / "home/.config/wireplumber/wireplumber.conf.d/51-saiph-hfp-hf.conf"), "applied": False}
    assert [row["address"] for row in status["devices"]] == [PHONE, OTHER]
    assert status["devices"][0]["gateway"] is True and status["devices"][1]["gateway"] is False
    assert status["session"]["state"] == "idle"
    # Detection only reads: no property is set, no call is made, nothing is restarted.
    assert not busctl(computer, "set-property") and not busctl(computer, "Activate")
    assert not any(c[0] == "systemctl" for c in computer.commands)


def test_detection_is_cached_between_snapshots(tmp_path, monkeypatch):
    audio, computer, clock, _ = make(tmp_path, monkeypatch)
    audio.status()
    count = len(computer.commands)
    audio.status()
    assert len(computer.commands) == count
    clock.now += call_audio.REFRESH_SECONDS
    audio.status()
    assert len(computer.commands) > count


def test_phone_states_reach_the_card(tmp_path, monkeypatch):
    for computer, expected in ((FakeComputer(connected=False), "phone-away"), (FakeComputer(gateway=False), "no-calls-profile"),
                               (FakeComputer(powered=False), "bluetooth-off"), (FakeComputer(adapter=False), "no-adapter")):
        audio, _, _, _ = make(tmp_path, monkeypatch, computer)
        assert audio.status()["readiness"] == expected


# Setup ---------------------------------------------------------------------------------------
def test_wireplumber_04_setup_writes_only_saiphs_file_and_restarts_as_the_user(tmp_path, monkeypatch):
    computer = FakeComputer(pipewire="1.0.5", wireplumber="0.4.17", handsfree=False, telephony=False, registers_after_restart=True)
    audio, _, _, _ = make(tmp_path, monkeypatch, computer)
    status = audio.status()
    assert status["readiness"] == "needs-setup" and status["setup"]["action"] == "write" and status["call_control"] == "app"
    assert audio.apply_setup() == {"queued": True}
    path = tmp_path / "home/.config/wireplumber/bluetooth.lua.d/51-saiph-hfp-hf.lua"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("-- Saiph: calls through this computer")
    assert 'bluez_monitor.properties["bluez5.headset-roles"] = "[ hsp_hs hfp_ag hfp_hf ]"' in text
    assert ["systemctl", "--user", "restart", "wireplumber"] in computer.commands
    status = audio.status()
    assert status["readiness"] == "ready" and status["setup"]["applied"] is True
    assert not (tmp_path / "root/etc").exists()  # Nothing system-wide.
    assert audio.remove_setup() == {"removed": True} and not path.exists()


def test_setup_keeps_a_users_own_roles_and_never_overwrites_their_file(tmp_path, monkeypatch):
    computer = FakeComputer(wireplumber="0.5.13", handsfree=False)
    audio, _, _, _ = make(tmp_path, monkeypatch, computer)
    own = tmp_path / "home/.config/wireplumber/wireplumber.conf.d/10-mine.conf"
    own.parent.mkdir(parents=True)
    own.write_text("monitor.bluez.properties = { bluez5.roles = [ a2dp_sink hfp_ag ] }\n", encoding="utf-8")
    audio.apply_setup()
    ours = own.parent / "51-saiph-hfp-hf.conf"
    assert "bluez5.roles = [ a2dp_sink hfp_ag hfp_hf ]" in ours.read_text(encoding="utf-8")
    assert own.read_text(encoding="utf-8").startswith("monitor.bluez.properties")
    ours.write_text("# someone else's file\n", encoding="utf-8")
    assert audio.remove_setup() == {"removed": False} and ours.exists()
    computer.handsfree = False
    with pytest.raises(ValueError, match="not written by Saiph"):
        CallAudio({}, runner=computer.run, which=lambda n: "/usr/bin/" + n, platform="linux", home=tmp_path / "home",
                  root=tmp_path / "root", threaded=False).apply_setup()


def test_configured_but_unregistered_role_offers_a_restart(tmp_path, monkeypatch):
    audio, _, _, _ = make(tmp_path, monkeypatch, FakeComputer(handsfree=False))
    assert audio.status()["setup"]["action"] == "restart"


def test_setup_text_matches_both_wireplumber_formats():
    assert setup_text((0, 4, 17), ["hsp_hs", "hfp_ag", "hfp_hf", "hfp_hf"]).splitlines()[1] == \
        'bluez_monitor.properties["bluez5.headset-roles"] = "[ hsp_hs hfp_ag hfp_hf ]"'
    assert "  bluez5.roles = [ hfp_hf ]" in setup_text((0, 5, 13), ["hfp_hf"])


# The call ------------------------------------------------------------------------------------
def test_answer_here_holds_then_routes_then_restores(tmp_path, monkeypatch):
    audio, computer, _, changes = make(tmp_path, monkeypatch)
    computer.ring()
    audio.call_state("ringing")
    assert computer.reject_sco is True and audio.session["state"] == "ringing"   # No second ringtone here.
    computer.answered_on_phone()  # The phone app answered after Saiph's call.command.
    assert audio.answered_here() == {"audio": "connecting"}
    assert computer.reject_sco is False and computer.transport == "active"
    assert audio.session == {"state": "here", "message": "Talking through this computer.", "codec": "mSBC"}
    assert busctl(computer, "Activate")
    audio.call_state("active")
    assert audio.session["state"] == "here"   # Answered here stays here.
    computer.calls.clear()
    audio.call_state("ended")
    assert audio.session["state"] == "idle" and computer.reject_sco is False
    assert [state for state in changes if state != "idle"][:3] == ["ringing", "connecting", "here"]


def test_answer_on_the_phone_keeps_the_audio_there_until_the_call_ends(tmp_path, monkeypatch):
    audio, computer, _, _ = make(tmp_path, monkeypatch)
    computer.ring()
    audio.call_state("ringing")
    computer.answered_on_phone()
    audio.call_state("active")
    assert audio.session["state"] == "on-phone" and computer.reject_sco is True
    assert not busctl(computer, "Activate")
    audio.call_state("ended")
    assert computer.reject_sco is False and audio.session["state"] == "idle"


def test_answer_from_here_but_talk_on_the_phone(tmp_path, monkeypatch):
    audio, computer, _, _ = make(tmp_path, monkeypatch)
    computer.ring()
    audio.call_state("ringing")
    audio.answered_on_phone()
    assert audio.session["state"] == "on-phone" and computer.reject_sco is True


def test_phone_opening_the_audio_itself_needs_no_activate(tmp_path, monkeypatch):
    audio, computer, _, _ = make(tmp_path, monkeypatch, FakeComputer(sco_follows_answer=True))
    computer.ring()
    computer.answered_on_phone()   # Nothing held the audio, so the phone opened the link itself.
    audio.answered_here()
    assert audio.session["state"] == "here" and not busctl(computer, "Activate") and not busctl(computer, "set-property")


def test_audio_that_never_arrives_is_reported_honestly(tmp_path, monkeypatch):
    audio, computer, clock, _ = make(tmp_path, monkeypatch)
    computer.ring()
    audio.call_state("ringing")
    start = clock.now
    audio.answered_here()   # The phone never answers, so the audio link never opens.
    assert audio.session == {"state": "on-phone", "message": AWAY_MESSAGE, "codec": ""}
    assert clock.now - start >= call_audio.ROUTE_SECONDS


def test_move_audio_here_during_a_call(tmp_path, monkeypatch):
    audio, computer, _, _ = make(tmp_path, monkeypatch, FakeComputer(reject_sco=True))
    computer.answered_on_phone()
    assert audio.move_here() == {"audio": "connecting"}
    assert audio.session["state"] == "here" and computer.reject_sco is False


def test_without_pipewire_telephony_the_audio_is_confirmed_by_its_nodes(tmp_path, monkeypatch):
    computer = FakeComputer(pipewire="1.0.5", wireplumber="0.4.17", telephony=False, nodes=True)
    audio, _, _, _ = make(tmp_path, monkeypatch, computer)
    audio.call_state("ringing")
    assert audio.session["state"] == "ringing" and not busctl(computer, "set-property")
    audio.answered_here()
    assert audio.session["state"] == "here"
    computer.nodes = False
    audio.answered_here()
    assert audio.session == {"state": "on-phone", "message": AWAY_MESSAGE, "codec": ""}


def test_bluetooth_answers_and_declines_when_the_phone_app_is_unreachable(tmp_path, monkeypatch):
    audio, computer, _, _ = make(tmp_path, monkeypatch)
    assert audio.fallback("answer") is None          # Nothing is ringing.
    computer.ring()
    assert audio.fallback("reject") == {"queued": True, "via": "bluetooth"} and not computer.calls
    computer.ring()
    assert audio.fallback("answer") == {"queued": True, "via": "bluetooth", "audio": "connecting"}
    assert computer.calls[CALL] == "active" and audio.session["state"] == "here"
    assert audio.fallback("hold") is None


def test_nothing_happens_when_call_audio_is_off(tmp_path, monkeypatch):
    audio, computer, _, _ = make(tmp_path, monkeypatch, enabled=False)
    computer.ring()
    audio.call_state("ringing")
    assert audio.answered_here() is None and audio.fallback("answer") is None
    assert audio.session["state"] == "idle" and not busctl(computer, "set-property")
    with pytest.raises(ValueError, match="Set up"):
        audio.move_here()


def test_a_missed_end_of_call_does_not_leave_the_session_stuck(tmp_path, monkeypatch):
    audio, computer, _, _ = make(tmp_path, monkeypatch)
    computer.ring()
    audio.call_state("ringing")
    assert audio.status([{"state": "ringing"}])["session"]["state"] == "ringing"
    status = audio.status([{"state": "ended"}])
    assert audio.session["state"] == "idle" and computer.reject_sco is False
    assert status["session"]["state"] in {"idle", "ringing"}


def test_telephony_reads_calls_from_each_gateway_when_the_root_lists_only_gateways():
    root = {AG: {"org.pipewire.Telephony.AudioGateway1": {"Address": {"type": "s", "data": PHONE}},
                 "org.pipewire.Telephony.AudioGatewayTransport1": {"Codec": {"type": "y", "data": 1}}}}
    calls = {CALL: {"org.pipewire.Telephony.Call1": {"State": {"type": "s", "data": "incoming"}}}}
    def run(*arguments):
        path = arguments[5]
        return json.dumps({"data": [root if path == call_audio.ROOT_PATH else calls]})
    gateway = Telephony(run).gateway(PHONE.lower())
    assert gateway["transport"]["codec"] == "CVSD" and gateway["calls"] == [{"path": CALL, "state": "incoming", "line": "", "name": ""}]
    assert Telephony(lambda *a: None).gateways() is None
    assert Telephony(lambda *a: "not json").gateways() is None


# Wiring --------------------------------------------------------------------------------------
class FakeAudio:
    def __init__(self, fallback=None):
        self.events, self.fallback_result = [], fallback

    def answered_here(self):
        self.events.append("here")
        return {"audio": "connecting"}

    def answered_on_phone(self):
        self.events.append("phone")

    def fallback(self, operation):
        self.events.append("fallback:" + operation)
        return self.fallback_result


def features(audio, sent, fail=False):
    from orion_mini.phone_features import PhoneFeatures
    def hosted(device, kind, payload):
        if fail:
            raise ValueError("Saiph is offline. This action has not been sent.")
        sent.append((device, kind, payload))
        return {"queued": True}
    workspace = SimpleNamespace(hosted_phone_command=hosted, call_audio=audio)
    feature = PhoneFeatures.__new__(PhoneFeatures)
    feature.workspace = workspace
    return feature


def test_answer_and_decline_keep_the_same_phone_command():
    audio, sent = FakeAudio(), []
    feature = features(audio, sent)
    assert feature.dispatch("phone.call", {"device_id": "dev_phone", "operation": "answer"}) == {"queued": True, "audio": "connecting"}
    assert feature.dispatch("phone.call", {"device_id": "dev_phone", "operation": "answer", "audio": "phone"}) == {"queued": True}
    assert feature.dispatch("phone.call", {"device_id": "dev_phone", "operation": "reject"}) == {"queued": True}
    # Saiph Cloud and Hub phones receive exactly what they did before: no audio field, no new type.
    assert sent == [("dev_phone", "call.command", {"operation": "answer"})] * 2 + [("dev_phone", "call.command", {"operation": "reject"})]
    assert audio.events == ["here", "phone"]
    with pytest.raises(ValueError, match="where to talk"):
        feature.dispatch("phone.call", {"device_id": "dev_phone", "operation": "answer", "audio": "cloud"})


def test_unreachable_phone_app_falls_back_to_bluetooth_or_reports_the_error():
    sent = []
    assert features(FakeAudio({"queued": True, "via": "bluetooth"}), sent, fail=True).dispatch(
        "phone.call", {"device_id": "dev_phone", "operation": "answer"}) == {"queued": True, "via": "bluetooth"}
    with pytest.raises(ValueError, match="offline"):
        features(FakeAudio(None), sent, fail=True).dispatch("phone.call", {"device_id": "dev_phone", "operation": "reject"})
    with pytest.raises(ValueError, match="offline"):
        features(None, sent, fail=True).dispatch("phone.call", {"device_id": "dev_phone", "operation": "answer"})
    assert sent == []


def test_link_workspace_saves_the_preference_and_reports_status(tmp_path, monkeypatch):
    from orion_mini.link_service import LinkWorkspace
    workspace = LinkWorkspace(tmp_path)
    workspace.call_audio.platform = "win32"   # No real Bluetooth is inspected in this test.
    workspace.dispatch("settings.save", {"link": {"call_audio": {"enabled": True, "device": PHONE}}})
    assert workspace.settings["link"]["call_audio"] == {"enabled": True, "device": PHONE}
    with pytest.raises(ValueError):
        workspace.dispatch("settings.save", {"link": {"call_audio": {"enabled": True, "device": "not-a-mac"}}})
    state = workspace.dispatch("state", {})
    assert state["call_audio"]["supported"] is False and state["call_audio"]["enabled"] is True
    with pytest.raises(ValueError, match="Unknown call audio action"):
        workspace.dispatch("call_audio.refresh", {"device": PHONE})
    with pytest.raises(ValueError, match="Linux"):
        workspace.dispatch("call_audio.move_here", {})
    assert workspace.dispatch("call_audio.refresh", {}) == {"supported": False}
