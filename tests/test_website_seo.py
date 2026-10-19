# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search and link-preview metadata for the public landing pages."""
import importlib.util
import json
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET

ROOT = Path(__file__).parents[1]
WEBSITE = ROOT / 'website'
SPEC = importlib.util.spec_from_file_location('seo_website_release', ROOT / 'scripts/public-release/build-website.py')
site = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(site)
BASE = 'https://usesaiph.com/'
PAGES = [name for name in site.FILES if name.endswith('.html') and '/' not in name]


def head(name):
    return (WEBSITE / name).read_text(encoding='utf-8').split('</head>', 1)[0]


def indexed(name):
    return '<meta name="robots" content="noindex">' not in head(name)


def test_every_page_has_canonical_and_link_preview_tags():
    for name in PAGES:
        page = head(name)
        url = BASE if name == 'index.html' else BASE + name
        assert f'<link rel="canonical" href="{url}">' in page, name
        assert f'<meta property="og:url" content="{url}">' in page, name
        title = re.search(r'<title>([^<]+)</title>', page)[1]
        description = re.search(r'<meta name="description" content="([^"]+)">', page)[1]
        assert f'<meta property="og:title" content="{title}">' in page, name
        assert f'<meta property="og:description" content="{description}">' in page, name
        assert '<meta property="og:image" content="https://usesaiph.com/assets/og-image.png">' in page, name
        assert '<meta name="twitter:card" content="summary_large_image">' in page, name
        assert 50 <= len(description) <= 200, name
        assert 'launch preparation status' not in description, name


def test_titles_and_descriptions_are_unique():
    titles = [re.search(r'<title>([^<]+)</title>', head(name))[1] for name in PAGES]
    descriptions = [re.search(r'<meta name="description" content="([^"]+)">', head(name))[1] for name in PAGES]
    assert len(set(titles)) == len(titles)
    assert len(set(descriptions)) == len(descriptions)


def test_sitemap_lists_exactly_the_indexed_pages():
    tree = ET.parse(WEBSITE / 'sitemap.xml')
    ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    listed = [loc.text for loc in tree.getroot().findall('s:url/s:loc', ns)]
    expected = {BASE if name == 'index.html' else BASE + name for name in PAGES if indexed(name)}
    assert len(listed) == len(set(listed)) and set(listed) == expected
    assert not indexed('contact.html') and not indexed('waitlist.html')


def test_robots_points_to_the_sitemap_and_keeps_the_sign_in_callback_out():
    robots = (WEBSITE / 'robots.txt').read_text(encoding='utf-8').splitlines()
    assert 'User-agent: *' in robots
    assert 'Disallow: /android/' in robots
    assert 'Sitemap: https://usesaiph.com/sitemap.xml' in robots
    assert not any(line.strip() in ('Disallow: /', 'Disallow: /*') for line in robots)


def test_structured_data_matches_the_published_prices():
    page = head('index.html')
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)[1]
    data = json.loads(block)
    assert data['@type'] == 'SoftwareApplication' and data['url'] == BASE
    prices = {offer['price'] for offer in data['offers']}
    settings = json.loads((WEBSITE / 'landing-settings.json').read_text(encoding='utf-8'))
    assert settings['hostedPrice'].lstrip('€') in prices
    assert '0' in prices


def test_share_image_is_a_1200_by_630_png():
    data = (WEBSITE / 'assets/og-image.png').read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    assert struct.unpack('>II', data[16:24]) == (1200, 630)
    assert len(data) < 400_000


def test_builder_ships_the_search_files(tmp_path):
    manifest = site.prepare(WEBSITE, tmp_path / 'site', {})
    for name in ('robots.txt', 'sitemap.xml', 'assets/og-image.png'):
        assert name in manifest['files']
