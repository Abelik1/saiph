# SPDX-License-Identifier: AGPL-3.0-or-later
from types import SimpleNamespace

import pytest

from orion_mini import remote
from orion_mini.remote import ADAPTERS, Remote, validate_options


class Controls:
    wayland = False

    def __init__(self, foreground="powerpnt", available=True):
        self.calls, self.current, self.ready = [], foreground, available

    def available(self, adapter):
        return self.ready

    def foreground(self):
        return self.current

    def key(self, name):
        self.calls.append(("key", name))

    def media(self, action):
        self.calls.append(("media", action))

    def lock(self):
        self.calls.append(("lock",))

    def type(self, text):
        self.calls.append(("type", text))


def setup(options=None, controls=None):
    settings = {"link": {"remote": {"enabled": True, "devices": ["phone"], **(options or {})}}}
    published, now = [], {"value": 100.0}
    workspace = SimpleNamespace(settings=settings)
    return Remote(workspace, published.append, controls or Controls(), clock=lambda: now["value"]), published, now


def command(app, control, source="phone", **extra):
    return {"type": "remote.command", "source": source, "payload": {"app": app, "control": control, **extra}}


def results(published):
    return [(event["targets"], event["payload"]["ok"], event["payload"]["message"]) for event in published if event["type"] == "remote.result"]


def test_catalog_lists_only_enabled_adapters_without_internal_keys():
    service, published, _ = setup()
    assert service.event({"type": "remote.catalog.request", "source": "phone", "payload": {}})
    catalog = published[-1]
    assert catalog["type"] == "remote.catalog" and catalog["targets"] == ["phone"]
    names = [app["id"] for app in catalog["payload"]["apps"]]
    assert names == ["media", "presentation", "video"]  # System and typing are separate opt-ins.
    assert all(set(control) <= {"id", "label", "kind", "max"} for app in catalog["payload"]["apps"] for control in app["controls"])


def test_controls_map_to_fixed_actions_only():
    controls = Controls()
    service, published, _ = setup({"adapters": {"system": True, "keyboard": True}}, controls)
    service.event(command("presentation", "next"))
    service.event(command("system", "lock"))
    service.event(command("keyboard", "type", text="Hello, world"))
    expected_media = ("key", "media_play_pause") if remote.sys.platform == "win32" else ("media", "play-pause")
    service.event(command("media", "play_pause"))
    assert controls.calls == [("key", "right"), ("lock",), ("type", "Hello, world"), expected_media]
    assert all(ok for _, ok, _ in results(published))


def test_unapproved_phones_and_disabled_remote_get_only_a_refusal():
    controls = Controls()
    service, published, _ = setup(controls=controls)
    service.event(command("media", "next", source="other-phone"))
    service.event({"type": "remote.catalog.request", "source": "other-phone", "payload": {}})
    service.workspace.settings["link"]["remote"]["enabled"] = False
    service.event(command("media", "next"))
    assert controls.calls == [] and not any(event["type"] == "remote.catalog" for event in published)
    assert all(not ok and "Allow this phone" in message for _, ok, message in results(published))


@pytest.mark.parametrize("payload", [
    {"app": "keyboard", "control": "type", "text": "x"},           # Typing not enabled.
    {"app": "media", "control": "shutdown"},                        # Unknown control.
    {"app": "shell", "control": "run"},                             # Unknown adapter.
    {"app": "media", "control": "next", "text": "extra"},           # Buttons take no text.
    {"app": "media", "control": "next", "key": "F4"},               # No raw keys.
])
def test_unknown_or_disabled_controls_do_nothing(payload):
    controls = Controls()
    service, published, _ = setup(controls=controls)
    service.event({"type": "remote.command", "source": "phone", "payload": payload})
    assert controls.calls == [] and results(published)[-1][1] is False


def test_typed_text_is_bounded_and_single_line():
    controls = Controls()
    service, published, now = setup({"adapters": {"keyboard": True}}, controls)
    for text in ("", "line\nbreak", "\x1b[escape", "x" * (remote.MAX_TEXT + 1)):
        service.event(command("keyboard", "type", text=text))
        now["value"] += 1
    assert controls.calls == []
    service.event(command("keyboard", "type", text="ok ✓"))
    assert controls.calls == [("type", "ok ✓")]


def test_scoped_adapters_need_their_app_in_front():
    controls = Controls(foreground="explorer")
    service, published, _ = setup(controls=controls)
    service.event(command("presentation", "next"))
    service.event(command("video", "play_pause"))
    assert controls.calls == []
    assert "Bring the presentation window" in results(published)[0][2]
    controls.current = "msedge"
    service.event(command("video", "play_pause"))
    assert controls.calls == [("key", "k")]


def test_bursts_are_rate_limited_per_phone():
    controls = Controls()
    service, published, now = setup(controls=controls)
    for _ in range(12):
        service.event(command("media", "volume_up"))
    assert len(controls.calls) == 10
    now["value"] += 1
    service.event(command("media", "volume_up"))
    assert len(controls.calls) == 11


def test_unavailable_platform_explains_wayland():
    controls = Controls(available=False)
    controls.wayland = True
    service, published, _ = setup(controls=controls)
    service.event(command("presentation", "next"))
    assert "Wayland" in results(published)[-1][2]


def test_preferences_validate_and_merge():
    merged = validate_options({"adapters": {"keyboard": True}}, {"enabled": True, "devices": ["phone"], "adapters": {"system": True}})
    assert merged == {"enabled": True, "devices": ["phone"], "adapters": {"system": True, "keyboard": True}}
    for options in ({"enabled": "yes"}, {"adapters": {"shell": True}}, {"adapters": {"media": 1}}, {"devices": "phone"}, {"commands": []}):
        with pytest.raises(ValueError):
            validate_options(options)
    assert set(ADAPTERS) == {"media", "presentation", "video", "system", "keyboard"}


def test_malformed_payloads_from_older_hubs_are_refused_without_raising():
    controls = Controls()
    service, published, _ = setup(controls=controls)
    assert service.event({"type": "remote.command", "source": "phone", "payload": ["media", "next"]})
    assert controls.calls == [] and results(published)[-1][1] is False
