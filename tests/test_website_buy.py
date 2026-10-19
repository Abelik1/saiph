# SPDX-License-Identifier: AGPL-3.0-or-later
"""The simplified landing page, cookie choice, GA4 loading and price test
(docs/LANDING_CONVERSION.md). Scripts run in Node with a synthetic DOM; nothing
contacts Google, Stripe or the account site."""
import copy
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('build_website', ROOT / 'scripts/public-release/build-website.py')
site = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(site)
LANDING = json.loads((ROOT / 'website/landing-settings.json').read_text(encoding='utf-8'))
INDEX = (ROOT / 'website/index.html').read_text(encoding='utf-8')


def test_landing_sells_one_product_with_one_main_button_and_no_downloads():
    assert 'data-download' not in INDEX and 'android-beta' not in INDEX and 'Download for' not in INDEX
    assert len(re.findall(r'data-link="buy"', INDEX)) == 1
    # Start your free trial is the main button while trials run; Buy now is the
    # main button otherwise (site.js steps it back only when a trial is offered).
    assert re.search(r'<a class="btn primary trial-now" data-link="trial-start"[^>]*>Start your free trial</a>', INDEX)
    assert re.search(r'<div class="trial-cta" data-trial-shown hidden>', INDEX)
    assert re.search(r'<a class="btn primary buy-now" data-link="buy"[^>]*>Buy now</a>', INDEX)
    assert 'nothing is charged automatically' in INDEX
    # The Cloud page's two-price box, as a plan choice with monthly preselected.
    assert re.search(r'id="plan-monthly" value="monthly" checked', INDEX)
    assert 'id="plan-yearly" value="yearly"' in INDEX and 'Save about' in INDEX
    assert '€9.99' in INDEX and '€89.99' in INDEX and 'No VAT is added' in INDEX
    assert '14 days to withdraw' in INDEX and 'Sign in with Google' in INDEX
    assert 'href="self-host.html"' in INDEX and 'href="hosted.html"' in INDEX


def test_footer_legal_links_and_accessibility_are_kept_on_every_page():
    for page in sorted((ROOT / 'website').glob('*.html')):
        text = page.read_text(encoding='utf-8')
        assert '&copy; <span data-year>2026</span> Crios' in text or '© <span data-year>2026</span> Crios' in text, page.name
        for link in ('privacy.html', 'account-privacy.html', 'terms.html', 'refunds.html', 'contact.html'):
            assert f'href="{link}"' in text, (page.name, link)
        assert 'data-consent-open' in text, page.name
        assert 'index.html#download' not in text and 'index.html#features' not in text, page.name
        scripts = re.findall(r'<script src="assets/([a-z]+)\.js"></script>', text)
        assert scripts[:3] == ['config', 'consent', 'site'], page.name
    assert 'class="btn skip-link" href="#main"' in INDEX and '<main id="main">' in INDEX
    assert 'name="viewport" content="width=device-width, initial-scale=1"' in INDEX


def test_demo_and_comparison_moved_to_the_cloud_page():
    hosted = (ROOT / 'website/hosted.html').read_text(encoding='utf-8')
    assert 'id="features"' in hosted and 'id="compare"' in hosted and 'assets/stage.js' in hosted
    assert 'data-link="buy" data-plan="monthly"' in hosted and 'data-link="buy" data-plan="yearly"' in hosted


def test_website_csp_allows_only_googles_analytics_hosts_and_spares_the_callback():
    config = json.loads((ROOT / 'vercel.json').read_text(encoding='utf-8'))
    rule = config['headers'][0]
    assert rule['source'] == '/((?!android/|\\.well-known/).*)'
    csp = {h['key']: h['value'] for h in rule['headers']}['Content-Security-Policy']
    assert "script-src 'self' https://www.googletagmanager.com;" in csp
    assert "unsafe-inline" not in csp.split('script-src')[1].split(';')[0]
    assert "connect-src 'self' https://*.google-analytics.com" in csp and "frame-ancestors 'none'" in csp
    assert not re.fullmatch(r'/((?!android/|\.well-known/).*)', '/android/oauth2redirect')
    assert re.fullmatch(r'/((?!android/|\.well-known/).*)', '/index.html')


def settings(**changes):
    value = copy.deepcopy(LANDING)
    value.update(changes)
    return value


def test_ga4_and_price_test_are_off_by_default_and_validated():
    # The owner's GA4 web stream (public Measurement ID, never an API secret); the price test stays off.
    assert LANDING['ga4'] == {'measurementId': 'G-8S9PGZ7P6Z'}
    assert site.validate_settings(settings(ga4={'measurementId': ''}), 'preview')['ga4']['measurementId'] == ''
    assert LANDING['priceTest'] == {'enabled': False, 'id': '', 'variants': {}}
    assert site.validate_settings(settings(ga4={'measurementId': 'G-ABC123XYZ'}), 'preview')['ga4']['measurementId'] == 'G-ABC123XYZ'
    for bad in ({'measurementId': 'UA-1234-1'}, {'measurementId': 'G-ABC', 'apiSecret': 'x'}, {'id': 'G-ABC123'}, 'G-ABC123'):
        with pytest.raises(ValueError, match='GA4'):
            site.validate_settings(settings(ga4=bad), 'preview')
    draft = settings(ga4={'measurementId': 'G-ABC123XYZ'})
    draft['privacy'] = {**draft['privacy'], 'status': 'draft'}
    with pytest.raises(ValueError, match='approved'):
        site.validate_settings(draft, 'preview')
    test = {'enabled': True, 'id': '2026-11-price', 'variants': {'b': {'monthly': '€7.99', 'yearly': '€69.99'}}}
    assert site.validate_settings(settings(priceTest=test), 'preview')['priceTest'] == test
    for bad in ({**test, 'variants': {}}, {**test, 'id': ''}, {**test, 'id': 'Bad id'}, {**test, 'variants': {'a': test['variants']['b']}},
                {**test, 'variants': {'b': {'monthly': '7.99', 'yearly': '€69.99'}}}, {**test, 'variants': {'b': {'monthly': '€7.99'}}},
                {**test, 'variants': {'b': {'monthly': '€7.99', 'yearly': '€69.99', 'price': 'price_x'}}}, {**test, 'enabled': 'yes'}):
        with pytest.raises(ValueError):
            site.validate_settings(settings(priceTest=bad), 'preview')
    with pytest.raises(ValueError, match='open subscriptions'):
        site.validate_settings(settings(priceTest=test, subscribeUrl='', hostedPrice='', hostedPriceNote='', hostedYearlyPrice='', hostedTrial=''), 'preview')
    with pytest.raises(ValueError, match='Yearly price'):
        site.validate_settings(settings(hostedYearlyPrice='89.99'), 'preview')


HARNESS = r"""
const fs = require('node:fs'), vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const appended = [], cookies = [], stored = {}, storageReads = [];
let cookieJar = input.cookie || '';
function element(tag) {
  return { tag, hidden: false, children: [], dataset: {}, attributes: {}, className: '', textContent: '', listeners: {},
    setAttribute(k, v) { this.attributes[k] = v; }, removeAttribute(k) { delete this.attributes[k]; },
    appendChild(c) { this.children.push(c); return c; }, append(...c) { this.children.push(...c); },
    addEventListener(t, f) { this.listeners[t] = f; }, contains(x) { return x === this || this.children.some(c => c.contains && c.contains(x)); } };
}
const opener = element('button'); opener.hidden = true;
const status = element('span');
const body = element('body'), head = element('head');
head.appendChild = (c) => { appended.push(c.src); return c; };
const document = {
  readyState: 'complete', body, head, activeElement: null,
  get cookie() { return cookieJar; },
  set cookie(value) { cookies.push(value); const [pair] = value.split(';'); if (!/Max-Age=0/.test(value)) cookieJar = pair; },
  createElement: element, createTextNode: (text) => ({ textContent: text }),
  querySelector: (s) => s === '[data-consent-open]' ? opener : null,
  querySelectorAll: (s) => s === '[data-consent-open]' ? [opener] : s === '[data-consent-status]' ? [status] : [],
  addEventListener() {},
};
const localStorage = { getItem(k) { storageReads.push(k); return stored[k] ?? null; }, setItem(k, v) { stored[k] = v; }, removeItem(k) { delete stored[k]; } };
const window = { ORION_SITE: input.cfg, location: { origin: input.origin, href: input.href, protocol: 'https:', hostname: new URL(input.href).hostname },
  navigator: { globalPrivacyControl: input.gpc === true }, localStorage, crypto: { getRandomValues: (a) => { a[0] = input.random || 0; return a; } } };
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), { window, document, URL, URLSearchParams, Date, JSON, Math, Uint32Array });
const banner = body.children[0];
const buttons = banner ? banner.children[1].children : [];
const before = { banner: Boolean(banner && !banner.hidden), appended: [...appended], cookies: [...cookies], storageReads: [...storageReads],
  opener: !opener.hidden, offer: { ...window.saiphConsent.offer }, layer: (window.dataLayer || []).length };
if (input.press && buttons.length) buttons[input.press === 'accept' ? 0 : 1].listeners.click();
console.log(JSON.stringify({ before, after: { appended, cookies, stored, layer: (window.dataLayer || []).map(a => Array.from(a)),
  bannerHidden: banner ? banner.hidden : null, labels: buttons.map(b => b.textContent), classes: buttons.map(b => b.className), status: status.textContent } }));
"""


def run_consent(cfg, *, origin='https://usesaiph.com', href=None, cookie='', press=None, gpc=False, random=0):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for website script checks')
    payload = {'cfg': cfg, 'origin': origin, 'href': href or origin + '/', 'cookie': cookie, 'press': press, 'gpc': gpc, 'random': random}
    result = subprocess.run([node, '-e', HARNESS, str(ROOT / 'website/assets/consent.js')], input=json.dumps(payload),
                            text=True, encoding="utf-8", capture_output=True, check=True)
    return json.loads(result.stdout)


GA = {'ga4': {'measurementId': 'G-SYNTHETIC1'}}
TEST = {'priceTest': {'enabled': True, 'id': '2026-11-price', 'variants': {'b': {'monthly': '€7.99', 'yearly': '€69.99'}}}}


def test_without_a_measurement_id_there_is_no_banner_cookie_or_google():
    result = run_consent({})
    assert result['before'] == {'banner': False, 'appended': [], 'cookies': [], 'storageReads': [], 'opener': False,
                                'offer': {'test': None, 'variant': 'a', 'inTest': False}, 'layer': 0}


def test_nothing_loads_or_is_stored_until_accept_and_decline_is_as_easy():
    first = run_consent(GA)
    assert first['before']['banner'] is True and first['before']['opener'] is True
    assert first['before']['appended'] == [] and first['before']['cookies'] == [] and first['before']['layer'] == 0
    assert first['after']['labels'] == ['Accept', 'Decline']
    assert first['after']['classes'][0] == first['after']['classes'][1] == 'btn', 'equal prominence'

    accepted = run_consent(GA, press='accept')
    assert accepted['after']['appended'] == ['https://www.googletagmanager.com/gtag/js?id=G-SYNTHETIC1']
    layer = accepted['after']['layer']
    assert layer[0] == ['consent', 'default', {'ad_storage': 'denied', 'ad_user_data': 'denied', 'ad_personalization': 'denied', 'analytics_storage': 'denied'}]
    assert layer[1] == ['consent', 'update', {'analytics_storage': 'granted'}]
    config = next(entry for entry in layer if entry[0] == 'config')
    assert config[2]['cookie_domain'] == 'usesaiph.com' and config[2]['page_location'] == 'https://usesaiph.com/'
    assert re.match(r'saiph_consent=v1\.granted\.\d{10}; Max-Age=15724800; Path=/; Domain=usesaiph.com; SameSite=Lax; Secure', accepted['after']['cookies'][0])
    assert accepted['after']['bannerHidden'] is True

    declined = run_consent(GA, press='decline')
    assert declined['after']['appended'] == [] and declined['after']['layer'] == []
    assert declined['after']['cookies'][0].startswith('saiph_consent=v1.denied.')


def test_a_stored_choice_is_honoured_for_six_months_and_gpc_counts_as_decline():
    import time
    now = int(time.time())
    granted = run_consent(GA, cookie=f'saiph_consent=v1.granted.{now - 86400}')
    assert granted['before']['banner'] is False and len(granted['before']['appended']) == 1
    stale = run_consent(GA, cookie=f'saiph_consent=v1.granted.{now - 200 * 86400}')
    assert stale['before']['banner'] is True and stale['before']['appended'] == []
    gpc = run_consent(GA, gpc=True)
    assert gpc['before']['banner'] is False and gpc['before']['appended'] == [] and gpc['before']['opener'] is False


def test_google_is_never_loaded_from_previews_and_campaign_tags_are_the_only_query_kept():
    preview = run_consent(GA, origin='https://saiph-landing-git-x.vercel.app', press='accept')
    assert preview['after']['appended'] == []
    tagged = run_consent(GA, href='https://usesaiph.com/?utm_source=reddit&email=a@b.c&offer=b', press='accept')
    config = next(entry for entry in tagged['after']['layer'] if entry[0] == 'config')
    assert config[2]['page_location'] == 'https://usesaiph.com/?utm_source=reddit'


def test_price_test_assigns_only_where_the_price_can_stay_the_same():
    import time
    now = int(time.time())
    # No choice yet: the standard price, and local storage is not even read.
    fresh = run_consent({**GA, **TEST})
    assert fresh['before']['offer'] == {'test': '2026-11-price', 'variant': 'a', 'inTest': False}
    assert fresh['before']['storageReads'] == []
    # Accepting on that page keeps the standard price and leaves the test.
    kept = run_consent({**GA, **TEST}, press='accept')
    assert json.loads(kept['after']['stored']['saiph_price_test'])['variant'] == 'a'
    assert json.loads(kept['after']['stored']['saiph_price_test'])['inTest'] is False
    # Accepted earlier: a random variant, remembered.
    drawn = run_consent({**GA, **TEST}, cookie=f'saiph_consent=v1.granted.{now}', random=1)
    assert drawn['before']['offer'] == {'test': '2026-11-price', 'variant': 'b', 'inTest': True}
    assert json.loads(drawn['after']['stored']['saiph_price_test'])['variant'] == 'b'
    # A campaign link carries a variant with nothing stored.
    linked = run_consent({**GA, **TEST}, href='https://usesaiph.com/?offer=b')
    assert linked['before']['offer'] == {'test': '2026-11-price', 'variant': 'b', 'inTest': True}
    assert linked['before']['storageReads'] == [] and linked['after']['stored'] == {}
    # Switched off: everyone sees the standard price.
    off = run_consent({**GA, 'priceTest': {**TEST['priceTest'], 'enabled': False}}, href='https://usesaiph.com/?offer=b')
    assert off['before']['offer'] == {'test': None, 'variant': 'a', 'inTest': False}


SITE_HARNESS = r"""
const fs = require('node:fs'), vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
function element(data = {}) {
  return { hidden: true, textContent: '', dataset: data, attributes: {}, classes: ['primary'],
    classList: { toggle() {}, remove(c) { this.owner.classes = this.owner.classes.filter(x => x !== c); } },
    setAttribute(k, v) { this.attributes[k] = v; }, removeAttribute(k) { delete this.attributes[k]; if (k === 'href') delete this.href; },
    appendChild() {}, insertAdjacentElement() {}, addEventListener() {}, querySelector() { return null; } };
}
function owned(e) { e.classList.owner = e; return e; }
const trialStart = owned(element()), trialShown = element();
const buy = owned(element()), monthly = element({planPrice: 'monthly'}), yearly = element({planPrice: 'yearly'}), note = element(), summary = element();
const planButton = element({plan: 'yearly'});
const elements = { '[data-link="trial-start"]': [trialStart], '[data-trial-shown]': [trialShown], '.buy-now': [buy], '[data-link="buy"]': [buy, planButton], '[data-plan-price]': [monthly, yearly], '[data-price-test-note]': [note], '[data-buy-summary]': [summary] };
const document = { querySelectorAll: (s) => elements[s] || [], querySelector: () => null, createElement: element, createTextNode: (t) => ({textContent: t}) };
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), { window: { ORION_SITE: input.cfg, saiphConsent: { offer: input.offer, track() {} } }, document, Date });
console.log(JSON.stringify({ trial: trialStart.href || '', trialShown: !trialShown.hidden, buyPrimary: buy.classes.includes('primary'), buy: buy.href || '', plan: planButton.href || '', text: buy.textContent, monthly: monthly.textContent,
  yearly: yearly.textContent, note: note.hidden, summary: summary.textContent }));
"""


def run_site(cfg, offer):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for website script checks')
    result = subprocess.run([node, '-e', SITE_HARNESS, str(ROOT / 'website/assets/site.js')],
                            input=json.dumps({'cfg': cfg, 'offer': offer}), text=True, encoding="utf-8", capture_output=True, check=True)
    return json.loads(result.stdout)


def test_start_your_free_trial_is_the_main_button_while_trials_run():
    on = run_site(LANDING, {'test': None, 'variant': 'a', 'inTest': False})
    assert on['trial'] == 'https://account.dev.usesaiph.com/trial' and on['trialShown'] is True
    assert on['buyPrimary'] is False and on['buy'] == 'https://account.dev.usesaiph.com/buy/monthly'
    off = run_site({**LANDING, 'hostedTrial': ''}, {'test': None, 'variant': 'a', 'inTest': False})
    assert off['trial'] == '' and off['trialShown'] is False and off['buyPrimary'] is True


def test_buy_now_carries_the_plan_and_the_shown_variant_to_the_account_site():
    standard = run_site(LANDING, {'test': None, 'variant': 'a', 'inTest': False})
    assert standard['buy'] == 'https://account.dev.usesaiph.com/buy/monthly'
    assert standard['plan'] == 'https://account.dev.usesaiph.com/buy/yearly'
    assert standard['summary'] == '€9.99 today, then every month. No VAT is added.' and standard['note'] is True
    tested = run_site({**LANDING, **TEST}, {'test': '2026-11-price', 'variant': 'b', 'inTest': True})
    assert tested['buy'] == 'https://account.dev.usesaiph.com/buy/monthly?offer=b'
    assert (tested['monthly'], tested['yearly'], tested['note']) == ('€7.99', '€69.99', False)
    assert tested['summary'].startswith('€7.99 today')
    control = run_site({**LANDING, **TEST}, {'test': '2026-11-price', 'variant': 'a', 'inTest': True})
    assert control['buy'] == 'https://account.dev.usesaiph.com/buy/monthly?offer=a'
    # A variant the page cannot show is never sent: the visitor pays what they saw.
    unknown = run_site(LANDING, {'test': '2026-11-price', 'variant': 'c', 'inTest': True})
    assert unknown['buy'] == 'https://account.dev.usesaiph.com/buy/monthly' and unknown['monthly'] == ''
    # Before subscriptions open, Buy now falls back to what Subscribe offers.
    closed = run_site({}, {'test': None, 'variant': 'a', 'inTest': False})
    assert closed['buy'] == '' and closed['text'] == 'Early access coming soon'


def test_built_site_includes_the_consent_script(tmp_path):
    output = tmp_path / 'site'
    site.prepare(ROOT / 'website', output, LANDING, 'preview')
    assert (output / 'assets/consent.js').exists()
    config = (output / 'assets/config.js').read_text(encoding='utf-8')
    assert '"measurementId": "G-8S9PGZ7P6Z"' in config and '"enabled": false' in config
