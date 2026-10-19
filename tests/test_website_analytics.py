# SPDX-License-Identifier: AGPL-3.0-or-later
"""Offline privacy-boundary checks for the shipped static analytics loader."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location('analytics_website_release', ROOT / 'scripts/public-release/build-website.py')
site = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(site)
ORIGIN = 'https://usesaiph.com'


def settings():
    return {'analytics': {'enabled': True, 'scriptPath': '/_vercel/insights/script.js'},
            'privacy': {'status': 'approved', 'controllerName': 'Synthetic controller',
                        'controllerCountry': 'Ireland', 'contactEmail': 'synthetic@github.com',
                        'updatedAt': '2026-10-11', 'hostingRetention': 'Synthetic hosting retention',
                        'hostingTransfers': 'Synthetic transfers', 'contactProcessing': 'Synthetic contact processing'}}


def run_loader(config=None, url=ORIGIN + '/', referrer='', events=None, navigator=None, clicks=None):
    node = shutil.which('node')
    if not node:
        pytest.fail('Node 24 is required for analytics privacy-boundary checks')
    harness = r"""
const fs = require('node:fs'), vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const inserted = [], status = {textContent: ''}, listeners = [];
const window = { ORION_SITE: input.config, location: new URL(input.url), navigator: input.navigator };
const document = {referrer: input.referrer, querySelectorAll: () => [status],
  addEventListener: (type, listener) => listeners.push([type, listener]),
  createElement: () => ({dataset: {}}), head: {appendChild: script => inserted.push(script)} };
// A synthetic link element built from its attributes, used as a click target.
const link = attrs => { const dataset = {};
  Object.entries(attrs).forEach(([k, v]) => { if (k.startsWith('data-')) dataset[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v; });
  const el = {dataset, hasAttribute: name => name in attrs, closest: selector =>
    (selector.includes('data-download') && 'data-download' in attrs) || (selector.includes('data-link') && 'data-link' in attrs) ? el : null};
  return el; };
const source = fs.readFileSync(process.argv[1], 'utf8');
const context = {window, document, URL, Set};
vm.runInNewContext(source, context);
const firstCount = inserted.length;
const hook = window.vaq && window.vaq.find(([name]) => name === 'beforeSend');
const events = input.events.map(event => hook ? hook[1](event) : null);
const queueLength = (window.vaq || []).length;
input.clicks.forEach(attrs => listeners.filter(([type]) => type === 'click').forEach(([, listener]) => listener({target: link(attrs)})));
const tracked = (window.vaq || []).slice(queueLength).map(args => Array.from(args));
vm.runInNewContext(source, context);
console.log(JSON.stringify({inserted, firstCount, queueLength, listeners: listeners.length,
  events, tracked, status: status.textContent}));
"""
    result = subprocess.run([node, '-e', harness, str(ROOT / 'website/assets/analytics.js')],
                            input=json.dumps({'config': config or {}, 'url': url, 'referrer': referrer,
                                              'events': events or [], 'navigator': navigator or {},
                                              'clicks': clicks or []}),
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_analytics_is_off_in_defaults_and_unconfigured_preview_build(tmp_path):
    assert site.validate_settings({}, 'preview')['analytics']['enabled'] is False
    for name in ('preview-settings.json', 'launch-settings.template.json'):
        config = json.loads((ROOT / 'website' / name).read_text(encoding='utf-8'))
        assert site.validate_settings(config, 'preview')['analytics']['enabled'] is False
    output = tmp_path / 'site'
    manifest = site.prepare(ROOT / 'website', output, {})
    assert 'assets/analytics.js' in manifest['files']
    for name in site.FILES:
        if name.endswith('.html'):
            page = (output / name).read_text(encoding='utf-8')
            assert '<meta name="referrer" content="no-referrer">' in page
            if name == 'android/oauth2redirect.html':
                assert 'assets/analytics.js' not in page
                assert 'assets/config.js' not in page
                continue
            assert page.index('assets/config.js') < page.index('assets/analytics.js')
    assert run_loader()['inserted'] == []


def test_landing_settings_enable_public_pageviews_but_keep_local_previews_untracked():
    config = json.loads((ROOT / 'website/landing-settings.json').read_text(encoding='utf-8'))
    assert site.validate_settings(config, 'preview')['analytics']['enabled'] is True
    assert run_loader(config, url=ORIGIN + '/')['firstCount'] == 1
    assert run_loader(config, url='http://localhost:8099/')['inserted'] == []


@pytest.mark.parametrize('value', [True, None, {}, {'enabled': True},
    {'enabled': 'true', 'scriptPath': '/_vercel/insights/script.js'},
    {'enabled': 1, 'scriptPath': '/_vercel/insights/script.js'},
    {'enabled': False, 'scriptPath': 'https://attacker.invalid/script.js'},
    {'enabled': False, 'scriptPath': '//attacker.invalid/script.js'},
    {'enabled': False, 'scriptPath': '/_vercel/insights/script.js?token=secret'},
    {'enabled': False, 'scriptPath': '/account/script.js'},
    {'enabled': False, 'scriptPath': '/_vercel/insights/../private/script.js'},
    {'enabled': False, 'scriptPath': '/_vercel/insights/script.js', 'token': 'private'}])
def test_analytics_settings_cannot_carry_credentials_or_arbitrary_scripts(value):
    with pytest.raises(ValueError, match='Analytics'):
        site.validate_settings({'analytics': value}, 'preview')
    assert run_loader({'analytics': value})['inserted'] == []


def test_activation_requires_approved_privacy_and_public_contact():
    config = settings()
    assert site.validate_settings(config, 'preview')['analytics']['enabled'] is True
    config['privacy']['status'] = 'draft'
    with pytest.raises(ValueError, match='Analytics requires an approved'):
        site.validate_settings(config, 'preview')
    assert run_loader(config)['inserted'] == []
    config['privacy']['status'] = 'approved'
    config['privacy']['contactEmail'] = ''
    with pytest.raises(ValueError):
        site.validate_settings(config, 'preview')
    assert run_loader(config)['inserted'] == []


@pytest.mark.parametrize('url', ['http://localhost:8099/',
    'https://saiph-account-dev.vercel.app/', 'https://unrelated.invalid/',
    'https://account.dev.usesaiph.com/', 'https://account.usesaiph.com/',
    'https://private-owner.invalid/', 'https://saiph-landing.vercel.app/',
    'https://saiph-landing-preview-alias.vercel.app/', ORIGIN + '/account',
    ORIGIN + '/auth/callback?code=secret', ORIGIN + '/checkout/success',
    ORIGIN + '/users/synthetic@example.invalid', ORIGIN + '/terms', ORIGIN + '/%70rivacy.html'])
def test_nonpublic_routes_hosts_and_local_previews_never_load_provider(url):
    result = run_loader(settings(), url=url)
    assert result['inserted'] == []
    assert result['status'] == 'Visit analytics is off for this visit.'


@pytest.mark.parametrize('referrer', [ORIGIN + '/auth/callback', ORIGIN + '/?code=secret',
    ORIGIN + '/#secret', 'https://external.invalid/invoice/synthetic',
    'https://external.invalid/?email=synthetic@example.invalid',
    'https://user:password@external.invalid/', 'http://external.invalid/', 'invalid'])
def test_unsafe_referrers_never_load_provider(referrer):
    assert run_loader(settings(), referrer=referrer)['inserted'] == []


@pytest.mark.parametrize('navigator', [{'globalPrivacyControl': True}, {'doNotTrack': '1'}])
def test_browser_privacy_choices_disable_collection(navigator):
    assert run_loader(settings(), navigator=navigator)['inserted'] == []


@pytest.mark.parametrize('path', ['/','/index.html','/privacy.html','/terms.html','/refunds.html','/contact.html'])
@pytest.mark.parametrize('referrer', ['', 'https://external.invalid/', ORIGIN + '/index.html'])
def test_known_public_pages_queue_filter_before_loading_once(path, referrer):
    result = run_loader(settings(), url=ORIGIN + path, referrer=referrer)
    assert result['firstCount'] == 1 and len(result['inserted']) == 1
    assert result['queueLength'] == 1
    script = result['inserted'][0]
    assert script['src'] == '/_vercel/insights/script.js'
    assert script['defer'] is True
    assert script['dataset']['viewEndpoint'] == '/_vercel/insights/view'
    assert result['status'] == 'Cookie-free visit analytics is enabled.'


def test_before_send_removes_sensitive_url_parts_payloads_and_identity():
    events = [{'type': 'pageview', 'url': ORIGIN + '/downloads.html?email=synthetic@example.invalid#secret',
               'payload': {'userId': 'synthetic'}, '__cdp': {'userId': 'synthetic'}},
              {'type': 'event', 'url': ORIGIN + '/', 'payload': {'name': 'checkout'}},
              {'type': 'event', 'url': ORIGIN + '/', 'payload': None},
              {'type': 'identify', 'url': ORIGIN + '/', 'userId': 'synthetic'},
              {'type': 'pageview', 'url': ORIGIN + '/auth/callback?code=secret'},
              {'type': 'pageview', 'url': 'https://saiph-account-dev.vercel.app/'},
              {'type': 'pageview', 'url': 'https://user:password@private-owner.invalid/'},
              {'type': 'pageview', 'url': 'invalid'}, None]
    result = run_loader(settings(), events=events)
    assert result['events'] == [{'type': 'pageview', 'url': ORIGIN + '/downloads.html'}, *[None] * 8]
    assert 'secret' not in json.dumps(result)
    assert 'synthetic@example.invalid' not in json.dumps(result)


def test_vercel_v2_dashboard_path_stays_same_origin():
    config = settings()
    config['analytics']['scriptPath'] = '/abcdefgh12345678/script.js'
    assert site.validate_settings(config, 'preview')['analytics']['scriptPath'] == config['analytics']['scriptPath']
    result = run_loader(config)
    assert result['inserted'][0]['dataset']['viewEndpoint'] == '/abcdefgh12345678/view'


def test_www_landing_origin_keeps_the_same_public_page_boundary():
    origin = 'https://www.usesaiph.com'
    result = run_loader(settings(), url=origin + '/privacy.html', events=[
        {'type': 'pageview', 'url': origin + '/privacy.html?email=synthetic@example.invalid#secret'},
        {'type': 'pageview', 'url': ORIGIN + '/privacy.html'},
        {'type': 'pageview', 'url': origin + '/account'}])
    assert result['firstCount'] == 1
    assert result['events'] == [{'type': 'pageview', 'url': origin + '/privacy.html'}, None, None]


def test_only_allow_listed_campaign_tags_survive_on_pageviews():
    url = (ORIGIN + '/?utm_source=reddit&utm_medium=paid_social&utm_campaign=2026-10-launch'
           '&utm_content=01-ecosystem-convenience&utm_term=synthetic+search&email=synthetic@example.invalid#secret')
    result = run_loader(settings(), url=url, events=[
        {'type': 'pageview', 'url': url},
        {'type': 'pageview', 'url': ORIGIN + '/?utm_source=synthetic-person&utm_medium=email&utm_campaign=private'},
        {'type': 'pageview', 'url': ORIGIN + '/?utm_content=Synthetic%20Name&utm_campaign=2026-10-launch'},
        {'type': 'pageview', 'url': ORIGIN + '/?utm_source=reddit&utm_source=synthetic'},
        {'type': 'event', 'url': url, 'payload': {'name': 'github_click'}}])
    assert result['events'] == [
        {'type': 'pageview', 'url': ORIGIN + '/?utm_source=reddit&utm_medium=paid_social&utm_campaign=2026-10-launch'
                                             '&utm_content=01-ecosystem-convenience'},
        {'type': 'pageview', 'url': ORIGIN + '/?utm_medium=email'},
        {'type': 'pageview', 'url': ORIGIN + '/?utm_campaign=2026-10-launch'},
        {'type': 'pageview', 'url': ORIGIN + '/?utm_source=reddit'},
        {'type': 'event', 'url': ORIGIN + '/', 'payload': {'name': 'github_click'}}]
    text = json.dumps(result['events'])
    assert 'synthetic' not in text and 'secret' not in text and 'utm_term' not in text


def test_custom_events_are_rebuilt_from_the_fixed_list():
    result = run_loader(settings(), events=[
        {'type': 'event', 'url': ORIGIN + '/downloads.html',
         'payload': {'name': 'download_click', 'data': {'platform': 'linux'}}},
        {'type': 'event', 'url': ORIGIN + '/', 'payload': {'name': 'cloud_click', 'data': None}, '__cdp': {'userId': 'x'}},
        {'type': 'event', 'url': ORIGIN + '/',
         'payload': {'name': 'download_click', 'data': {'platform': 'synthetic@example.invalid'}}},
        {'type': 'event', 'url': ORIGIN + '/', 'payload': {'name': 'download_click', 'data': {'platform': 'linux', 'email': 'x'}}},
        {'type': 'event', 'url': ORIGIN + '/', 'payload': {'name': 'github_click', 'data': ['x']}},
        {'type': 'event', 'url': ORIGIN + '/', 'payload': {'name': 'toString'}},
        {'type': 'event', 'url': ORIGIN + '/account', 'payload': {'name': 'github_click'}},
        {'type': 'identify', 'url': ORIGIN + '/', 'payload': {'name': 'identify', 'data': {'userId': 'x'}}}])
    assert result['events'] == [
        {'type': 'event', 'url': ORIGIN + '/downloads.html',
         'payload': {'name': 'download_click', 'data': {'platform': 'linux'}}},
        {'type': 'event', 'url': ORIGIN + '/', 'payload': {'name': 'cloud_click'}}, *[None] * 6]


def test_button_clicks_queue_only_known_events_without_link_targets():
    result = run_loader(settings(), clicks=[
        {'href': 'https://github.com/synthetic/x/releases/download/v1/a.exe', 'data-download': 'windows'},
        {'href': 'https://github.com/synthetic/x/releases/download/v1/a.apk', 'data-download': 'android'},
        {'href': 'https://appdistribution.firebase.dev/i/abcdefgh', 'data-link': 'android-beta'},
        {'href': 'https://account.dev.usesaiph.com/account', 'data-link': 'subscribe'},
        {'href': 'https://account.dev.usesaiph.com/account', 'data-link': 'account'},
        {'href': 'https://github.com/synthetic/x', 'data-link': 'github'},
        {'data-download': 'linux'},
        {'href': 'https://example.invalid/', 'data-link': 'releases'},
        {'href': '#', 'data-download': 'synthetic'}])
    assert result['listeners'] == 1
    assert result['tracked'] == [
        ['event', {'name': 'download_click', 'data': {'platform': 'windows'}}],
        ['event', {'name': 'download_click', 'data': {'platform': 'android_apk'}}],
        ['event', {'name': 'download_click', 'data': {'platform': 'android'}}],
        ['event', {'name': 'cloud_click'}], ['event', {'name': 'account_click'}], ['event', {'name': 'github_click'}]]
    assert 'github.com' not in json.dumps(result['tracked'])


def test_disabled_analytics_adds_no_click_listener():
    assert run_loader({}, clicks=[{'href': 'x', 'data-link': 'github'}])['listeners'] == 0
    assert run_loader(settings(), navigator={'doNotTrack': '1'})['listeners'] == 0
