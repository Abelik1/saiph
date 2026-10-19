# SPDX-License-Identifier: AGPL-3.0-or-later
"""Desktop updates from the Saiph account: a synthetic service for the proposed routes, no network."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

from orion_mini import package_updates as updates
from orion_mini.storage import read_json, write_json
from test_package_updates import CONFIG, metadata, native, packaged, real_linux_package  # noqa: F401  (fixture)

ORIGIN = 'https://updates.example.invalid'
TOKEN = 'synthetic-account-token'
TICKET = 'T' * 43


class FakeResponse:
    def __init__(self, status, body=b'', headers=None):
        self.status_code, self.body = status, body
        self.headers = {'Content-Length': str(len(body)), **(headers or {})}
        self.raw = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, size):
        for start in range(0, len(self.body), size):
            yield self.body[start:start + size]


class FakeService:
    """The proposed /v1/app/desktop/<platform>/release and /download routes."""

    def __init__(self, description=None, body=b'', *, release_status=200, ticket=None, download_headers=None):
        self.description, self.body, self.release_status = description, body, release_status
        self.ticket = TICKET if ticket is None else ticket
        self.download_headers = download_headers or {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(('GET', url, kwargs))
        assert kwargs['allow_redirects'] is False
        if url.endswith('/release'):
            raw = self.description if isinstance(self.description, bytes) else json.dumps(self.description).encode()
            return FakeResponse(self.release_status, raw if self.release_status == 200 else b'')
        # The ticket is the only credential the download carries.
        assert url == f'{ORIGIN}/v1/download/{TICKET}' and 'Authorization' not in kwargs['headers']
        return FakeResponse(200, self.body, self.download_headers)

    def post(self, url, **kwargs):
        self.calls.append(('POST', url, kwargs))
        assert kwargs['allow_redirects'] is False and kwargs['headers']['Authorization'] == 'Bearer ' + TOKEN
        return FakeResponse(200, json.dumps({'ticket': self.ticket}).encode())


def describe(release, notes='Faster photo sync.'):
    return {**release, 'notes': notes}


def feed(service):
    return updates.CloudFeed(ORIGIN, TOKEN, http=service)


def test_check_reads_the_pinned_account_feed_with_notes(packaged):
    root, _ = packaged
    release = metadata(); native(release)
    service = FakeService(describe(release))
    result = updates.check(root, CONFIG, cloud=feed(service))
    assert result['available'] and result['supported'] and result['source'] == 'cloud'
    assert result['release'] == release and result['notes'] == 'Faster photo sync.'
    method, url, kwargs = service.calls[0]
    assert (method, url) == ('GET', ORIGIN + '/v1/app/desktop/windows-x86_64/release')
    assert kwargs['headers']['Authorization'] == 'Bearer ' + TOKEN


@pytest.mark.parametrize('status, reason', [(404, 'cloud_unavailable'), (401, 'cloud_signed_out'), (403, 'cloud_signed_out')])
def test_service_without_the_routes_or_sign_in_explains_why(packaged, status, reason):
    result = updates.check(packaged[0], CONFIG, cloud=feed(FakeService(release_status=status)))
    assert result['reason'] == reason and not result['supported'] and not result['available']


def test_server_errors_are_failures_not_offers(packaged):
    with pytest.raises(ValueError):
        updates.check(packaged[0], CONFIG, cloud=feed(FakeService(release_status=500)))


def test_nothing_published_or_an_equal_build_offers_nothing(packaged):
    root, _ = packaged
    assert not updates.check(root, CONFIG, cloud=feed(FakeService(release_status=204)))['available']
    assert not updates.check(root, CONFIG, cloud=feed(FakeService(describe(metadata(build=1)))))['available']


def test_an_older_or_changed_build_after_a_newer_one_is_refused(packaged):
    root, _ = packaged
    assert updates.check(root, CONFIG, cloud=feed(FakeService(describe(metadata(build=3)))))['available']
    with pytest.raises(ValueError, match='older or conflicting'):
        updates.check(root, CONFIG, cloud=feed(FakeService(describe(metadata(build=2)))))
    with pytest.raises(ValueError, match='older or conflicting'):
        updates.check(root, CONFIG, cloud=feed(FakeService(describe({**metadata(build=3), 'sha256': 'c' * 64}))))


@pytest.mark.parametrize('description', [
    {**metadata(), 'notes': 'x', 'url': 'https://elsewhere.invalid/Saiph.exe'},
    metadata(),
    {**metadata(), 'notes': 'Update ‮exe.txt'},
    {**metadata(), 'notes': 'bell\u0007'},
    {**metadata(), 'notes': 'x' * 4001},
    {**metadata(), 'notes': 1},
    {**metadata(), 'build': True, 'notes': ''},
    {**metadata(), 'sha256': 'A' * 64, 'notes': ''},
    b'{"schema":1,"schema":1}',
    json.dumps(describe(metadata()))[:-1].encode() + b',"build":99}',
    b'{"bytes": NaN}',
    b'\xff\xfe',
    b'[' * 20000,
])
def test_descriptions_are_strict(packaged, description):
    with pytest.raises(ValueError):
        updates.check(packaged[0], CONFIG, cloud=feed(FakeService(description)))


@pytest.mark.parametrize('offered', [metadata(profile='workspace'), metadata(platform='linux-x86_64'),
                                     {**metadata(), 'version': metadata(build=1)['version']}])
def test_account_cannot_switch_edition_platform_or_reuse_a_version(packaged, offered):
    with pytest.raises(ValueError):
        updates.check(packaged[0], CONFIG, cloud=feed(FakeService(describe(offered))))


@pytest.mark.parametrize('origin, token', [('http://updates.example.invalid', TOKEN), (ORIGIN + ':8443', TOKEN),
    (ORIGIN + '/api', TOKEN), (ORIGIN + '?next=x', TOKEN), ('https://user@updates.example.invalid', TOKEN),
    (ORIGIN, ''), (ORIGIN, 'two words'), (ORIGIN, None)])
def test_feed_accepts_only_a_fixed_https_origin_and_a_plain_token(origin, token):
    with pytest.raises(ValueError):
        updates.CloudFeed(origin, token, http=FakeService())


def test_feed_ignores_environment_proxies():
    assert updates.CloudFeed(ORIGIN, TOKEN).http.trust_env is False


def test_stage_uses_a_fresh_ticket_verifies_and_never_runs_code(packaged, monkeypatch):
    root, _ = packaged
    release = metadata(); body = native(release)
    service = FakeService(describe(release), body)
    monkeypatch.setattr(updates.subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('Stage launched code'))
    seen = []
    original = updates._report
    monkeypatch.setattr(updates, '_report', lambda *args: seen.append(args[0]) or original(*args))
    result = updates.stage(root, CONFIG, release, cloud=feed(service))
    assert result['staged'] and Path(result['path']).read_bytes() == body
    assert Path(result['path']).name == release['sha256'] + '.exe'
    assert read_json(Path(result['path']).parent / 'staged.json') == release
    assert [call[:2] for call in service.calls] == [('GET', ORIGIN + '/v1/app/desktop/windows-x86_64/release'),
        ('POST', ORIGIN + '/v1/app/desktop/windows-x86_64/download'), ('GET', f'{ORIGIN}/v1/download/{TICKET}')]
    assert seen[0] == 'downloading' and 'verifying' in seen and seen[-1] == 'ready'
    assert updates.progress() == {'state': 'ready', 'done': release['bytes'], 'total': release['bytes']}


@pytest.mark.parametrize('failure', ['corrupt', 'truncated', 'too-long', 'wrong-length', 'bad-ticket', 'wrong-build'])
def test_downloads_that_fail_a_check_leave_nothing_staged(packaged, failure):
    root, _ = packaged
    release = metadata(); body = native(release)
    headers, ticket = {'Content-Length': str(release['bytes'])}, None
    if failure == 'corrupt':
        body = body[:-1] + b'X'
    if failure == 'truncated':
        body = body[:-1]
    if failure == 'too-long':
        body += b'X'
    if failure == 'wrong-length':
        headers['Content-Length'] = '1'
    if failure == 'bad-ticket':
        ticket = '../../v1/account'
    if failure == 'wrong-build':
        body = native(metadata(build=99))
        release.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
        headers['Content-Length'] = str(len(body))
    service = FakeService(describe(release), body, ticket=ticket, download_headers=headers)
    with pytest.raises(ValueError, match='could not be verified'):
        updates.stage(root, CONFIG, release, cloud=feed(service))
    assert not list((root / 'package-updates').glob('staged-*'))
    assert updates.progress()['state'] == 'failed'


def test_a_changed_publication_needs_a_new_check(packaged):
    root, _ = packaged
    first = metadata(); native(first)
    second = metadata(build=3); native(second)
    with pytest.raises(ValueError, match='changed'):
        updates.stage(root, CONFIG, first, cloud=feed(FakeService(describe(second))))


def test_reasons_never_download(packaged):
    with pytest.raises(ValueError, match='Sign in'):
        updates.stage(packaged[0], CONFIG, metadata(), cloud='cloud_signed_out')


def linux_setup(tmp_path, monkeypatch, release):
    """A real .run written by the packaging script around a real synthetic Linux package."""
    archive = real_linux_package(tmp_path, monkeypatch, release)
    spec = importlib.util.spec_from_file_location('linux_setup_for_updates',
                                                  Path(__file__).parents[1] / 'scripts/packaging/build-desktop-distribution.py')
    packaging = importlib.util.module_from_spec(spec); spec.loader.exec_module(packaging)
    setup = tmp_path / archive.name.replace('.tar.gz', '.run')
    packaging.build_linux_setup(archive, setup)
    body = setup.read_bytes()
    return body, dict(release, bytes=len(body), sha256=hashlib.sha256(body).hexdigest()), dict(release)


@pytest.fixture
def linux(packaged, monkeypatch):
    root, bundle = packaged
    monkeypatch.setattr(sys, 'platform', 'linux')
    write_json(bundle / 'distribution-release.json',
               {key: metadata(build=1, platform='linux-x86_64')[key] for key in ('schema', 'build', 'version', 'platform')})
    return root


def test_linux_setup_is_checked_without_running_and_stages_its_release_archive(linux, tmp_path, monkeypatch):
    body, offered, payload = linux_setup(tmp_path, monkeypatch, metadata(platform='linux-x86_64'))
    monkeypatch.setattr(updates.subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('Stage ran the setup file'))
    result = updates.stage(linux, CONFIG, offered, cloud=feed(FakeService(describe(offered), body)))
    staged = Path(result['path'])
    # install() receives the verified .tar.gz with its own size and hash, exactly as from a Hub.
    assert staged.name == payload['sha256'] + '.tar.gz' and result['release'] == payload
    assert read_json(staged.parent / 'staged.json') == payload
    assert not list(staged.parent.glob('*.run'))
    updates._verify(staged, payload)
    assert updates._extract_linux(staged, staged.parent).name == 'install.sh'


@pytest.mark.parametrize('damage', ['payload', 'version', 'header'])
def test_linux_setup_that_does_not_match_is_refused(linux, tmp_path, monkeypatch, damage):
    body, offered, _ = linux_setup(tmp_path, monkeypatch, metadata(platform='linux-x86_64'))
    if damage == 'payload':
        body = body[:-10] + bytes(10)
    if damage == 'version':
        body = body.replace(b"version='" + offered['version'].encode() + b"'", b"version='9.9.9'", 1)
    if damage == 'header':
        body = b'#!/bin/bash\n' + body[len(b'#!/bin/sh\n'):]
    offered.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
    with pytest.raises(ValueError, match='could not be verified'):
        updates.stage(linux, CONFIG, offered, cloud=feed(FakeService(describe(offered), body)))
    assert not list((linux / 'package-updates').glob('staged-*'))


def test_source_for_keeps_self_hosted_and_cloud_apart():
    hub = SimpleNamespace(hosted_blocks_self_hosted=lambda: False, hosted_controller=lambda: pytest.fail('Cloud asked'))
    assert updates.source_for(hub) is False

    def missing():
        raise ValueError('This build does not include Saiph Cloud.')
    assert updates.source_for(SimpleNamespace(hosted_blocks_self_hosted=lambda: True, hosted_controller=missing)) == 'cloud_manual'
    controller = SimpleNamespace(update_feed=lambda: 'cloud_signed_out')
    assert updates.source_for(SimpleNamespace(hosted_blocks_self_hosted=lambda: True, hosted_controller=lambda: controller)) == 'cloud_signed_out'


def test_hosted_update_feed_is_pinned_to_the_packaged_origin(monkeypatch):
    from orion_mini import hosted_runtime
    from orion_mini.hosted_tokens import SignInRequired
    monkeypatch.setattr(hosted_runtime, 'packaged_config', lambda: {'service_url': ORIGIN})

    def controller(url, account=SimpleNamespace(access_token=lambda: TOKEN)):
        return SimpleNamespace(lock=threading.RLock(), _config=lambda: {'service_url': url}, _account=lambda: account)
    source = hosted_runtime.HostedController.update_feed(controller(ORIGIN))
    assert isinstance(source, updates.CloudFeed) and source.origin == ORIGIN and source.token == TOKEN
    assert hosted_runtime.HostedController.update_feed(controller('https://custom.example.invalid')) == 'cloud_unofficial'

    def signed_out():
        raise SignInRequired()
    assert hosted_runtime.HostedController.update_feed(controller(ORIGIN, SimpleNamespace(access_token=signed_out))) == 'cloud_signed_out'
    monkeypatch.setattr(hosted_runtime, 'packaged_config', lambda: None)
    assert hosted_runtime.HostedController.update_feed(controller(ORIGIN)) == 'cloud_unofficial'
