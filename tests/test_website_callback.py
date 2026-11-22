# SPDX-License-Identifier: AGPL-3.0-or-later
"""Protect the static authentication fallback from leaking callback parameters."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location('callback_site', ROOT / 'scripts/public-release/build-website.py')
site = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(site)


def test_published_bundle_contains_association_and_minimal_callback(tmp_path):
    output = tmp_path / 'site'
    site.prepare(ROOT / 'website', output, {})
    association = json.loads((output / '.well-known/assetlinks.json').read_text())
    # Saiph (Google Play) and Saiph Unlocked (website) each have a verified callback.
    assert [entry['target']['package_name'] for entry in association] == ['com.orionmini.mobile', 'com.orionmini.mobile.unlocked']
    for entry in association:
        assert entry['relation'] == ['delegate_permission/common.handle_all_urls']
        target = entry['target']
        assert target['namespace'] == 'android_app'
        assert 1 <= len(target['sha256_cert_fingerprints']) <= 2
        assert all(re.fullmatch(r'(?:[0-9A-F]{2}:){31}[0-9A-F]{2}', fp) for fp in target['sha256_cert_fingerprints'])
    # Google Play re-signs the Play app with its app signing key; that key must come first.
    assert association[0]['target']['sha256_cert_fingerprints'][0] == 'E5:F3:29:25:59:DF:64:CC:09:62:F7:99:7D:9D:A2:3E:57:D6:98:1D:03:05:51:FB:F7:BA:12:60:77:ED:F4:BA'
    for name in ('android/oauth2redirect.html', 'android/unlocked/oauth2redirect.html'):
        page = (output / name).read_text(encoding='utf-8')
        parsed = site.Page(page)
        assert parsed.links == []  # No analytics, remote assets, redirects or outgoing links.
        assert 'http-equiv="refresh"' not in page.lower()
        assert '<form' not in page.lower()
        assert 'content="no-referrer"' in page
        assert 'noindex, nofollow, noarchive' in page


def test_callback_scrubs_address_without_reading_or_forwarding_credentials():
    page = (ROOT / 'website/android/oauth2redirect.html').read_text(encoding='utf-8')
    scripts = re.findall(r'<script>(.*?)</script>', page, re.S)
    assert len(scripts) == 1
    # Execute the shipped script with synthetic codes. No network or DOM is available.
    runner = """
    const vm = require('node:vm'), assert = require('node:assert/strict');
    let url = '/android/oauth2redirect?code=synthetic&state=synthetic#synthetic';
    vm.runInNewContext(process.argv[1], {history: {replaceState(state, title, path) {url = path;}}});
    assert.equal(url, '/android/oauth2redirect');
    """
    subprocess.run(['node', '-e', runner, scripts[0]], check=True, capture_output=True, text=True)


def test_extensionless_callback_is_rewritten_with_no_store_and_restrictive_csp():
    config = json.loads((ROOT / 'vercel.json').read_text())
    assert config['rewrites'] == [{'source': '/android/oauth2redirect', 'destination': '/android/oauth2redirect.html'},
                                  {'source': '/android/unlocked/oauth2redirect', 'destination': '/android/unlocked/oauth2redirect.html'}]
    routes = {entry['source']: {h['key'].lower(): h['value'] for h in entry['headers']} for entry in config['headers']}
    for base in ['/android/oauth2redirect', '/android/unlocked/oauth2redirect']:
        script = re.search(r'<script>(.*?)</script>', (ROOT / ('website' + base + '.html')).read_text(), re.S)[1]
        script_hash = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        for path in [base, base + '.html']:
            headers = routes[path]
            assert headers['cache-control'] == 'no-store'
            assert headers['referrer-policy'] == 'no-referrer'
            assert headers['x-content-type-options'] == 'nosniff'
            assert headers['x-frame-options'] == 'DENY'
            assert "default-src 'none'" in headers['content-security-policy']
            assert "script-src 'sha256-" + script_hash + "'" in headers['content-security-policy']
            assert "form-action 'none'" in headers['content-security-policy']
    assert routes['/.well-known/assetlinks.json']['content-type'] == 'application/json'
