# SPDX-License-Identifier: AGPL-3.0-or-later
"""One legal destination without losing deep links or leaking the trader address."""
import importlib.util
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('legal_website', ROOT / 'scripts/public-release/build-website.py')
site = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(site)


def test_policies_share_one_page_and_previous_urls_remain_compatible(tmp_path):
    output = tmp_path / 'site'
    site.prepare(ROOT / 'website', output, {})
    privacy = (output / 'privacy.html').read_text(encoding='utf-8')
    for key, (name, label) in site.LEGAL_PAGES.items():
        assert f'<a id="policy-tab-{key}" href="#{key}">{label}</a>' in privacy
        assert f'<section id="{key}" data-policy-panel tabindex="0">' in privacy
        source = (ROOT / 'website' / name).read_text(encoding='utf-8')
        # Each source policy paragraph survives exactly, without rewriting terms.
        body = source.split('<main id="main">', 1)[1].split('</main>', 1)[0]
        for paragraph in re.findall(r'<p\b[^>]*>.*?</p>', body, re.S):
            assert paragraph in privacy, (name, paragraph)
        if key != 'website':
            alias = (output / name).read_text(encoding='utf-8')
            assert f'data-policy-redirect="{key}"' in alias
            assert f'href="privacy.html#{key}"' in alias
            assert f'rel="canonical" href="https://usesaiph.com/privacy.html#{key}"' in alias
            assert '<meta name="robots" content="noindex">' in alias
            assert 'src="assets/legal.js"' in alias
    assert len(re.findall(r'<h1\b', privacy)) == 1
    ids = re.findall(r'\bid="([^"]+)"', privacy)
    assert len(ids) == len(set(ids)), 'Consolidated policies must not duplicate anchor IDs'
    for anchor in ('cookies', 'waitlist', 'analytics', 'trial', 'withdrawal', 'buy'):
        assert anchor in ids


def test_contact_address_remains_only_on_the_noindexed_contact_page(tmp_path):
    output = tmp_path / 'site'
    site.prepare(ROOT / 'website', output, {}, address='1 Synthetic Street, Testtown')
    assert '1 Synthetic Street' in (output / 'contact.html').read_text(encoding='utf-8')
    assert '1 Synthetic Street' not in (output / 'privacy.html').read_text(encoding='utf-8')
