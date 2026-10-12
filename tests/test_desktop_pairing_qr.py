# SPDX-License-Identifier: AGPL-3.0-or-later
"""The desktop pairing QR reuses the Hub invitation and the Android ``orion://pair`` link."""
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlsplit

import pytest
import qrcode

from orion_mini import hub_client
from orion_mini.enrollment import pairing_link, pairing_qr, parse_invitation
from orion_mini.link_service import LinkWorkspace
from orion_mini.storage import write_json

CODE = '12345678'
# Literal links accepted by android/core/network/src/test/.../EnrollmentTest.kt
# (existingQrAndOptionalControllerQrRemainCompatible).
ANDROID_LINK = 'orion://pair?v=1&hub=http%3A%2F%2F100.100.10.2%3A8765&code=12345678'
ANDROID_CONTROLLER = '&mesh_login_server=https%3A%2F%2Fmesh.example.test'


def artifact(hub='http://100.100.10.2:8765', login=None, minutes=10, code=CODE):
    expires = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat().replace('+00:00', 'Z')
    return {'format': 'orion-enrollment', 'version': 1, 'hub': hub, 'code': code, 'expires_at': expires, 'mesh_login_server': login}


def parsed(**kwargs):
    return parse_invitation(json.dumps(artifact(**kwargs)).encode())


def android_link(value):
    """Python mirror of Enrollment.link's acceptance rules for the fields we emit."""
    uri = urlsplit(value)
    assert (uri.scheme, uri.netloc, uri.path, uri.fragment) == ('orion', 'pair', '', '')
    pairs = parse_qsl(uri.query, keep_blank_values=True, strict_parsing=True)
    assert len({key for key, _ in pairs}) == len(pairs)
    args = dict(pairs)
    assert {'v', 'hub', 'code'} <= set(args) <= {'v', 'hub', 'code', 'mesh_login_server'} and args['v'] == '1'
    return args


def test_link_is_byte_identical_to_the_android_compatibility_fixtures():
    assert pairing_link(parsed()) == ANDROID_LINK
    assert pairing_link(parsed(login='https://mesh.example.test/')) == ANDROID_LINK + ANDROID_CONTROLLER
    ipv6 = android_link(pairing_link(parsed(hub='http://[FD7A:115C:A1E0::1]:9876')))
    assert ipv6 == {'v': '1', 'hub': 'http://[fd7a:115c:a1e0::1]:9876', 'code': CODE}


@pytest.mark.parametrize('login', [None, 'https://mesh.example.test'])
def test_link_matches_the_server_cli_qr_for_the_same_invitation(tmp_path, monkeypatch, login):
    pytest.importorskip('fastapi')
    from orion_hub import enrollment as hub_enrollment
    captured = []
    real_make = hub_enrollment.qrcode.make
    monkeypatch.setattr(hub_enrollment, 'create_pairing_code', lambda db, minutes: CODE)
    monkeypatch.setattr(hub_enrollment.qrcode, 'make', lambda uri, **kw: captured.append(uri) or real_make(uri, **kw))
    target = tmp_path / 'phone.orion-enrollment'
    hub_enrollment.write_enrollment(None, target, 10, 'http://100.100.10.2:8765', login)
    assert pairing_link(parse_invitation(target.read_bytes())) == captured[0]


def test_qr_grid_encodes_the_link_and_omits_code_text():
    item = parsed(login='https://mesh.example.test')
    result = pairing_qr(item)
    assert set(result) == {'modules', 'expires_at', 'expires_in'}
    reference = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    reference.add_data(ANDROID_LINK + ANDROID_CONTROLLER); reference.make(fit=True)
    assert result['modules'] == [''.join('1' if cell else '0' for cell in row) for row in reference.get_matrix()]
    size = len(result['modules'])
    assert size >= 29 and all(len(row) == size and set(row) <= {'0', '1'} for row in result['modules'])
    assert CODE not in json.dumps(result) and 'orion://' not in json.dumps(result)
    assert 590 <= result['expires_in'] <= 600 and result['expires_at'] == item['expires_at']


def test_qr_refuses_an_expired_invitation():
    item = parsed()
    with pytest.raises(ValueError):
        pairing_qr(item, now=datetime.fromisoformat(item['expires_at']))


def paired(root):
    write_json(root / 'connections.json', {'hub': {'base_url': 'http://100.64.1.2:9876', 'device_id': 'dev_' + '0' * 32, 'paired': True}})
    return LinkWorkspace(root)


def test_dispatch_requests_one_signed_invitation_and_writes_nothing(tmp_path, monkeypatch, caplog):
    workspace = paired(tmp_path)
    secret = '73519046'
    calls = []
    monkeypatch.setattr(hub_client, 'signed', lambda root, config, path, method='GET', body=None: calls.append((path, method, body)) or artifact(hub='http://100.64.1.2:9876', code=secret))
    result = workspace.dispatch('enrollment.qr', {})
    assert calls == [('/v1/link/enrollment', 'POST', {})]
    assert set(result) == {'modules', 'expires_at', 'expires_in'} and secret not in json.dumps(result)
    # Shown on screen only: no profile file, database or log receives the code.
    assert not [p for p in tmp_path.rglob('*') if p.is_file() and secret.encode() in p.read_bytes()]
    assert secret not in json.dumps(workspace.state()) and secret not in caplog.text


def test_dispatch_hides_server_errors_and_refuses_unpaired_or_extra_arguments(tmp_path, monkeypatch):
    workspace = paired(tmp_path)

    def failing(*args, **kwargs):
        raise RuntimeError('synthetic private response ' + CODE)
    monkeypatch.setattr(hub_client, 'signed', failing)
    with pytest.raises(ValueError) as error:
        workspace.dispatch('enrollment.qr', {})
    assert CODE not in str(error.value) and error.value.__cause__ is None and error.value.__suppress_context__
    monkeypatch.setattr(hub_client, 'signed', lambda *a, **k: {**artifact(), 'code': '1234'})
    with pytest.raises(ValueError):
        workspace.dispatch('enrollment.qr', {})
    with pytest.raises(ValueError):
        workspace.dispatch('enrollment.qr', {'hub': 'http://100.64.9.9:8765'})
    calls = []
    monkeypatch.setattr(hub_client, 'signed', lambda *a, **k: calls.append(a))
    with pytest.raises(ValueError):
        LinkWorkspace(tmp_path / 'unpaired').dispatch('enrollment.qr', {})
    assert not calls
