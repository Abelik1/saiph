# SPDX-License-Identifier: AGPL-3.0-or-later
"""Operating-system user verification before device-adding actions; no real prompt opens."""
import pytest

from orion_mini import hub_client
from orion_mini.user_presence import (
    UNAVAILABLE, VERIFIED, UserPresence, UserVerificationError, async_operation_iid, confirm, parameterized_iid,
)


class Backend:
    def __init__(self, result=0, available=True):
        self.result, self._available, self.calls = result, available, []

    def available(self):
        return self._available

    def verify(self, message, window):
        self.calls.append((message, window))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_parameterized_interface_ids_match_published_windows_values():
    # IAsyncOperation<bool> is published in the Windows SDK headers.
    assert parameterized_iid("pinterface({9fc2b0bb-e446-44e2-aa61-9cab8f636af2};b1)") == "cdb5efb3-5788-509d-9be1-71ccb8a3362a"
    assert async_operation_iid("Windows.Security.Credentials.UI.UserConsentVerificationResult") == "fd596ffd-2318-558f-9dbe-d21df43764a5"


def test_verified_person_continues_with_the_window_as_parent():
    backend = Backend(0)
    presence = UserPresence(lambda: 1234, backend=backend, platform="win32")
    assert presence.confirm("approve a synthetic device") == VERIFIED
    assert backend.calls == [("Saiph: approve a synthetic device", 1234)]
    assert presence.cached_status() == "windows_hello"


@pytest.mark.parametrize("result", [4, 5, 6, 99])
def test_refused_cancelled_or_busy_verification_stops_the_action(result):
    presence = UserPresence(backend=Backend(result), platform="win32")
    with pytest.raises(UserVerificationError):
        presence.confirm("approve a synthetic device")


@pytest.mark.parametrize("result", [1, 2, 3, OSError("synthetic")])
def test_missing_or_unconfigured_verifier_reports_unavailable(result):
    presence = UserPresence(backend=Backend(result), platform="win32")
    assert presence.confirm("approve a synthetic device") == UNAVAILABLE
    assert presence.cached_status() == UNAVAILABLE


def test_platforms_without_a_verifier_and_headless_workspaces_never_prompt():
    assert UserPresence(platform="linux").confirm("approve a synthetic device") == UNAVAILABLE
    assert UserPresence(platform="linux").status() == UNAVAILABLE
    assert confirm(object(), "approve a synthetic device") == UNAVAILABLE
    with pytest.raises(ValueError):
        UserPresence(backend=Backend(), platform="win32").confirm("")


def test_hub_pairing_code_requires_the_person_before_requesting_an_invitation(tmp_path, monkeypatch):
    from orion_mini.link_service import LinkWorkspace
    from orion_mini.storage import write_json
    write_json(tmp_path / 'connections.json', {'hub': {'base_url': 'http://100.64.1.2:9876', 'device_id': 'dev_' + '0' * 32, 'paired': True}})
    workspace = LinkWorkspace(tmp_path)
    calls = []
    monkeypatch.setattr(hub_client, 'signed', lambda *args, **kwargs: calls.append(args) or {})
    workspace.user_presence = UserPresence(backend=Backend(6), platform="win32")
    with pytest.raises(UserVerificationError):
        workspace.dispatch('enrollment.qr', {})
    assert not calls
    # A cancelled prompt says nothing about availability; the startup check decides.
    assert workspace.state()['user_verification'] == 'checking'
