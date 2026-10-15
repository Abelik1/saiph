# SPDX-License-Identifier: AGPL-3.0-or-later
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location('website_release', ROOT / 'scripts/public-release/build-website.py')
site = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(site)


def test_preview_has_no_private_configuration_or_unreviewed_files(tmp_path):
    source = tmp_path / 'website'
    shutil.copytree(ROOT / 'website', source)
    (source / '.env').write_text('PRIVATE_CONFIGURATION_MUST_NOT_SHIP')
    (source / 'assets/config.js').write_text('PRIVATE_CONFIGURATION_MUST_NOT_SHIP')
    output = tmp_path / 'public'
    manifest = site.prepare(source, output, {})
    assert not (output / '.env').exists()
    assert 'PRIVATE_CONFIGURATION' not in (output / 'assets/config.js').read_text()
    assert len(manifest['files']) == len(site.FILES) + 1
    assert manifest['published'] is False


@pytest.mark.parametrize('value', ['javascript:alert(1)', 'http://github.com/a/b',
    'https://user:password@github.com/a/b', 'https://example.com/releases',
    'https://github.com/a/b?token=private', 'https://localhost/a',
    'https://127.0.0.1/a', 'https://192.0.2.1/a', 'https://192.168.1.2/a'])
def test_unsafe_or_placeholder_public_urls_fail(value):
    with pytest.raises(ValueError):
        site.validate_settings({'githubUrl': value}, 'preview')


def test_launch_needs_every_artifact_and_waitlist_privacy():
    with pytest.raises(ValueError, match='Launch requires'):
        site.validate_settings({}, 'launch')
    with pytest.raises(ValueError, match='notice'):
        site.validate_settings({'waitlistUrl': 'https://forms.github.com/saiph'}, 'preview')
    config = launch_settings()
    assert site.validate_settings(config, 'launch')['downloads'] == config['downloads']
    config['downloads']['linux'] = 'https://github.com/saiph-app/saiph/releases/latest'
    with pytest.raises(ValueError, match='versioned'):
        site.validate_settings(config, 'launch')


SUBSCRIBE = {'subscribeUrl': 'https://account.dev.usesaiph.com/account', 'hostedPrice': '€3.99'}


@pytest.mark.parametrize('settings', [{'subscribeUrl': 'https://payments.github.com/pay', 'hostedPrice': '€3.99'},
    {'subscribeUrl': 'https://account.dev.usesaiph.com/account?plan=x', 'hostedPrice': '€3.99'},
    {**SUBSCRIBE, 'hostedPrice': '5'}, {**SUBSCRIBE, 'hostedPrice': '€0'}, {'hostedPrice': '€3.99'},
    {'subscribeUrl': SUBSCRIBE['subscribeUrl']}, {'hostedPriceNote': 'or €36 a year'},
    {**SUBSCRIBE, 'hostedPriceNote': 'x' * 81}, {'AUTH_TOKEN': 'private'}, {'license': {'core': 'MIT'}}])
def test_bad_hosted_plan_settings_credentials_and_wrong_licences_fail(settings):
    with pytest.raises(ValueError):
        site.validate_settings(settings, 'preview')


@pytest.mark.parametrize('link', ['../../private.txt', 'missing.css', 'index.html#missing-anchor'])
def test_broken_links_fail_before_writing_output(tmp_path, link):
    source = tmp_path / 'website'
    shutil.copytree(ROOT / 'website', source)
    with (source / 'index.html').open('a') as stream:
        stream.write(f'<a href="{link}">Synthetic broken reference</a>')
    output = tmp_path / 'public'
    with pytest.raises(ValueError):
        site.prepare(source, output, {})
    assert not output.exists()


def test_existing_output_is_never_overwritten(tmp_path):
    (tmp_path / 'existing').mkdir()
    with pytest.raises(ValueError, match='fresh'):
        site.prepare(ROOT / 'website', tmp_path / 'existing', {})


def test_public_source_landing_has_truthful_link_and_account_checkout(tmp_path):
    settings = json.loads((ROOT / 'website/landing-settings.json').read_text(encoding='utf-8'))
    output = tmp_path / 'landing'
    site.prepare(ROOT / 'website', output, settings)
    config = (output / 'assets/config.js').read_text(encoding='utf-8')
    assert 'https://github.com/Abelik1/saiph' in config
    assert '"sourceVisibility": "public"' in config
    # Checkout happens on the account site after sign-in, never on these pages.
    assert '"subscribeUrl": "https://account.dev.usesaiph.com/account"' in config
    assert '"waitlistUrl": ""' in config
    # Public source alone does not open launch mode: release downloads and the
    # reviewed waitlist remain separate gates.
    with pytest.raises(ValueError, match='Launch requires'):
        site.validate_settings(settings, 'launch')
    assert 'beta service' in (output / 'hosted.html').read_text(encoding='utf-8')


def launch_settings():
    # Offline synthetic configuration; no provider or release is accessed.
    repo = 'https://github.com/synthetic/saiph'
    prefix = repo + '/releases/download/v1.0/'
    consent = site.TALLY_CONSENT
    return {'sourceVisibility': 'public', 'githubUrl': repo,
            'releasesUrl': repo + '/releases/tag/v1.0',
            'downloads': {name: prefix + name + '.zip' for name in site.PLATFORMS},
            'release': {'tag': 'v1.0', 'sourceCommit': 'a' * 40,
                        'checksumsUrl': prefix + 'SHA256SUMS', 'sourceMetadataUrl': prefix + 'release-source.json'},
            'waitlistUrl': 'https://tally.so/r/gDy42K?consent_version=synthetic-v1',
            'waitlistPrivacyUrl': 'privacy.html#waitlist', 'waitlistNotice': consent,
            'privacy': {'status': 'approved', 'controllerName': 'Synthetic Controller',
                        'controllerCountry': 'Ireland', 'contactEmail': 'synthetic@github.com',
                        'updatedAt': '2026-10-11', 'hostingRetention': 'Synthetic retention',
                        'hostingTransfers': 'Synthetic hosting transfers', 'contactProcessing': 'Synthetic mail processing and retention'},
            'waitlist': {'processorName': 'Tally',
                         'processorPrivacyUrl': 'https://tally.so/help/privacy-policy',
                         'processingLocations': 'Synthetic location', 'transferSafeguards': 'Synthetic safeguards',
                         'retention': 'Synthetic retention', 'withdrawal': 'Synthetic unsubscribe',
                         'consentText': consent, 'noticeVersion': 'synthetic-v1', 'optInMode': 'single',
                         'emailRequired': True, 'consentRequired': True, 'partialSubmissionsDisabled': True,
                         'confirmationEmailDisabled': True, 'trackingDisabled': True}}


@pytest.mark.parametrize('field,value', [('emailRequired', False), ('consentRequired', False), ('partialSubmissionsDisabled', False),
    ('confirmationEmailDisabled', False), ('optInMode', 'double'), ('confirmedOptIn', True),
    ('consentRequired', 'true'), ('trackingDisabled', False), ('trackingDisabled', 1),
    ('consentText', 'Different notice'), ('noticeVersion', ''), ('noticeVersion', 'different'),
    ('processorPrivacyUrl', 'http://github.com/privacy'), ('retention', '')])
def test_waitlist_requires_real_consistent_notice_and_controls(field, value):
    settings = launch_settings()
    settings['waitlist'][field] = value
    with pytest.raises(ValueError):
        site.validate_settings(settings, 'preview')


@pytest.mark.parametrize('field,value', [('status', 'draft'), ('contactEmail', ''),
    ('contactEmail', 'a@b.com?subject=secret'), ('hostingRetention', ''), ('hostingTransfers', ''), ('contactProcessing', ''),
    ('updatedAt', 'not-a-date'), ('secret', 'must-not-ship')])
def test_waitlist_requires_complete_approved_privacy(field, value):
    settings = launch_settings()
    settings['privacy'][field] = value
    with pytest.raises(ValueError):
        site.validate_settings(settings, 'preview')


@pytest.mark.parametrize('suffix', ['../file.zip', '%2e%2e', 'folder%2ffile.zip',
    '%5cfile.zip', '%0afile.zip', 'file.zip#fragment', 'file.zip?token=secret', '%20file.zip'])
def test_download_filename_cannot_escape_version(suffix):
    settings = launch_settings()
    settings['downloads']['windows'] = 'https://github.com/synthetic/saiph/releases/download/v1.0/' + suffix
    with pytest.raises(ValueError):
        site.validate_settings(settings, 'preview')


def test_downloads_require_public_source_and_exact_release():
    settings = launch_settings()
    settings['sourceVisibility'] = 'private'
    with pytest.raises(ValueError, match='public source'):
        site.validate_settings(settings, 'preview')
    settings['sourceVisibility'] = 'public'
    settings['release']['tag'] = 'v2.0'
    with pytest.raises(ValueError, match='exact'):
        site.validate_settings(settings, 'preview')
    settings = launch_settings()
    settings['downloads']['linux'] = settings['downloads']['windows']
    with pytest.raises(ValueError, match='own release artifact'):
        site.validate_settings(settings, 'preview')


def test_approved_controller_ships_without_enabling_collection(tmp_path):
    settings = json.loads((ROOT / 'website/landing-settings.json').read_text(encoding='utf-8'))
    result = site.validate_settings(settings, 'preview')
    assert result['privacy']['status'] == 'approved'
    assert result['privacy']['contactEmail'] == 'support@usesaiph.com'
    assert result['waitlistUrl'] == ''
    assert result['release'] == {}
    assert not any(result['downloads'].values())
    settings['privacy']['secret'] = 'must-not-ship'
    with pytest.raises(ValueError):
        site.prepare(ROOT / 'website', tmp_path / 'bad', settings)
    assert not (tmp_path / 'bad').exists()


@pytest.mark.parametrize('url', [
    'https://tally.so/r/gDy42K',
    'https://tally.so/r/gDy42K?consent_version=other',
    'https://tally.so/r/gDy42K?consent_version=synthetic-v1&consent_version=synthetic-v1',
    'https://tally.so/r/gDy42K?consent_version=synthetic-v1&token=secret',
    'https://tally.so/r/gDy42K?consent_version=synthetic-v1&',
    'https://tally.so/r/gDy42K?consent_version=',
    'https://tally.so/r/gDy42K?consent%5fversion=synthetic-v1',
    'https://tally.so/r/gDy42K?consent_version=synthetic%2dv1',
    'https://tally.so/r/gDy42K?consent_version=synthetic-v1#fragment',
    'https://tally.so/r/another?consent_version=synthetic-v1',
    'https://tally.so.evil.com/r/gDy42K?consent_version=synthetic-v1',
    'https://tally.so@github.com/r/gDy42K?consent_version=synthetic-v1',
    'https://user:secret@tally.so/r/gDy42K?consent_version=synthetic-v1',
    'http://tally.so/r/gDy42K?consent_version=synthetic-v1',
    'https://tally.so:444/r/gDy42K?consent_version=synthetic-v1',
    'https://localhost/r/gDy42K?consent_version=synthetic-v1',
])
def test_only_reviewed_tally_form_and_matching_notice_query_are_accepted(url):
    settings = launch_settings()
    settings['waitlistUrl'] = url
    with pytest.raises(ValueError):
        site.validate_settings(settings, 'preview')


def test_single_opt_in_form_preserves_query_but_does_not_relax_other_urls(tmp_path):
    settings = launch_settings()
    output = tmp_path / 'single-opt-in'
    site.prepare(ROOT / 'website', output, settings, 'launch', SYNTHETIC_ADDRESS)
    config = (output / 'assets/config.js').read_text(encoding='utf-8')
    assert settings['waitlistUrl'] in config
    assert '"optInMode": "single"' in config
    assert 'confirmedOptIn' not in config
    settings['githubUrl'] = 'https://github.com/synthetic/saiph?consent_version=synthetic-v1'
    with pytest.raises(ValueError, match='query'):
        site.validate_settings(settings, 'preview')


def test_published_form_stays_disabled_without_controller_contact():
    settings = json.loads((ROOT / 'website/landing-settings.json').read_text(encoding='utf-8'))
    settings['privacy'].update(status='draft', contactEmail='')
    assert settings['waitlist']['optInMode'] == 'single'
    settings['waitlistUrl'] = 'https://tally.so/r/gDy42K?consent_version=' + settings['waitlist']['noticeVersion']
    with pytest.raises(ValueError, match='approved'):
        site.validate_settings(settings, 'preview')
    settings['privacy']['status'] = 'approved'
    with pytest.raises(ValueError):
        site.validate_settings(settings, 'preview')


def render_site_script(settings):
    """Exercise the shipped script with DOM elements, without visiting a provider."""
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for website script checks')
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const cfg = JSON.parse(fs.readFileSync(0, 'utf8'));
function element() {
  return { hidden: true, textContent: '', dataset: {}, attributes: {},
    setAttribute(k, v) { this.attributes[k] = v; },
    removeAttribute(k) { delete this.attributes[k]; if (k === 'href') delete this.href; },
    appendChild() {}, insertAdjacentElement() {} };
}
const form = element(), details = element(), inactive = element(), contact = element(), subscribe = element();
const beta = element(), betaBox = element(), status = element();
const elements = {
  '[data-link="android-beta"]': [beta], '[data-android-beta]': [betaBox],
  '[data-link="waitlist"]': [form], '[data-waitlist-details]': [details],
  '[data-waitlist-inactive]': [inactive], '[data-privacy-contact]': [contact],
  '[data-link="subscribe"]': [subscribe], '[data-hosted-status]': [status]
};
const document = { querySelectorAll: selector => elements[selector] || [],
  querySelector: () => null, createElement: element, createTextNode: text => ({textContent: text}) };
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {window: {ORION_SITE: cfg}, document, Date});
console.log(JSON.stringify({form: form.href || '', disabled: form.attributes['aria-disabled'],
  hidden: details.hidden, inactiveHidden: inactive.hidden, contact: contact.href || '',
  subscribe: subscribe.href || '', subscribeText: subscribe.textContent, subscribeDisabled: subscribe.attributes['aria-disabled'] || '',
  hostedStatus: status.textContent, beta: beta.href || '', betaHidden: betaBox.hidden}));
"""
    result = subprocess.run([node, '-e', script, str(ROOT / 'website/assets/site.js')],
                            input=json.dumps(settings), text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_site_script_allows_reviewed_single_opt_in():
    settings = launch_settings()
    result = render_site_script(settings)
    assert result['form'] == settings['waitlistUrl']
    assert 'disabled' not in result
    assert result['hidden'] is False and result['inactiveHidden'] is True
    assert result['subscribe'] == 'waitlist.html'


@pytest.mark.parametrize('field,value', [('optInMode', 'double'), ('noticeVersion', 'different'),
    ('emailRequired', False), ('consentRequired', False), ('partialSubmissionsDisabled', False),
    ('confirmationEmailDisabled', False), ('trackingDisabled', False), ('retention', '')])
def test_site_script_fails_closed_for_unreviewed_controls(field, value):
    settings = launch_settings()
    settings['waitlist'][field] = value
    result = render_site_script(settings)
    assert result['form'] == '' and result['disabled'] == 'true'
    assert result['hidden'] is True and result['inactiveHidden'] is False
    assert result['subscribe'] != 'waitlist.html'


@pytest.mark.parametrize('field,value', [('status', 'draft'), ('contactEmail', ''), ('contactEmail', 'not-an-email')])
def test_site_script_draft_or_missing_contact_cannot_enable_signup(field, value):
    settings = launch_settings()
    settings['privacy'][field] = value
    result = render_site_script(settings)
    assert result['form'] == '' and result['contact'] == ''
    assert result['hidden'] is True and result['subscribe'] != 'waitlist.html'


BETA_INVITE = 'https://appdistribution.firebase.dev/i/0123abcd4567ef89'


def test_android_beta_invite_is_optional_and_shown_when_configured(tmp_path):
    assert site.validate_settings({}, 'preview')['androidBetaUrl'] == ''
    assert site.validate_settings({'androidBetaUrl': BETA_INVITE}, 'preview')['androidBetaUrl'] == BETA_INVITE
    settings = json.loads((ROOT / 'website/landing-settings.json').read_text(encoding='utf-8'))
    settings['androidBetaUrl'] = BETA_INVITE
    result = render_site_script(settings)
    assert result['beta'] == BETA_INVITE and result['betaHidden'] is False
    del settings['androidBetaUrl']
    result = render_site_script(settings)
    assert result['beta'] == '' and result['betaHidden'] is True


@pytest.mark.parametrize('value', ['https://example.com/i/0123abcd4567ef89',
    'http://appdistribution.firebase.dev/i/0123abcd4567ef89',
    'https://appdistribution.firebase.dev/i/0123abcd4567ef89?email=a@b.c',
    'https://appdistribution.firebase.dev.evil.example/i/0123abcd4567ef89',
    'https://appdistribution.firebase.dev/i/short', 'javascript:alert(1)', 42])
def test_android_beta_invite_rejects_other_links(value):
    with pytest.raises(ValueError, match='Firebase App Distribution'):
        site.validate_settings({'androidBetaUrl': value}, 'preview')


BETA_ACCOUNT = 'https://account.dev.usesaiph.com/account'


def test_beta_access_account_link_is_optional_and_exact():
    assert site.validate_settings({}, 'preview')['betaAccountUrl'] == ''
    assert site.validate_settings({'betaAccountUrl': BETA_ACCOUNT}, 'preview')['betaAccountUrl'] == BETA_ACCOUNT


@pytest.mark.parametrize('value', ['http://account.dev.usesaiph.com/account', 'https://account.dev.usesaiph.com/',
    'https://account.dev.usesaiph.com/account?code=x', 'https://account.dev.usesaiph.com/account/../x',
    'https://localhost/account', 'privacy.html#waitlist', 'javascript:alert(1)', 42])
def test_beta_access_account_link_rejects_other_links(value):
    with pytest.raises(ValueError):
        site.validate_settings({'betaAccountUrl': value}, 'preview')


def test_early_access_opens_beta_access_until_signup_or_payment_opens():
    settings = json.loads((ROOT / 'website/landing-settings.json').read_text(encoding='utf-8'))
    for name in ('subscribeUrl', 'hostedPrice', 'hostedPriceNote'):
        settings.pop(name, None)
    settings['betaAccountUrl'] = BETA_ACCOUNT
    result = render_site_script(settings)
    # The beta's front page explains the invitation before asking anyone to sign in.
    assert result['subscribe'] == BETA_ACCOUNT.removesuffix('account')
    assert result['subscribeText'] == 'Get beta access' and result['subscribeDisabled'] == ''
    assert result['hostedStatus'] == 'Invite-only beta'
    del settings['betaAccountUrl']
    # Without the beta link, public source points people to the repository.
    result = render_site_script(settings)
    assert result['subscribe'] == settings['githubUrl'] and result['subscribeDisabled'] == ''
    assert result['subscribeText'] == 'Follow progress on GitHub'
    settings['sourceVisibility'] = 'private'
    result = render_site_script(settings)
    assert result['subscribe'] == '' and result['subscribeDisabled'] == 'true'
    assert result['subscribeText'] == 'Early access coming soon'


def test_hosted_plan_settings_accept_the_account_page_and_euro_price():
    config = site.validate_settings({**SUBSCRIBE, 'hostedPriceNote': 'or €36 a year'}, 'preview')
    assert config['subscribeUrl'] == SUBSCRIBE['subscribeUrl'] and config['hostedPrice'] == '€3.99'


def test_open_subscriptions_link_to_the_account_and_show_hosted_as_available():
    settings = json.loads((ROOT / 'website/landing-settings.json').read_text(encoding='utf-8'))
    assert settings['subscribeUrl'] == BETA_ACCOUNT and settings['hostedPrice'] == '€3.99'
    site.validate_settings(settings, 'preview')
    result = render_site_script(settings)
    assert result['subscribe'] == BETA_ACCOUNT and result['subscribeDisabled'] == ''
    assert result['subscribeText'] == 'Subscribe' and result['hostedStatus'] == 'Available now'
    # Subscriptions take precedence over the email list and invitation-only access.
    settings = {**launch_settings(), **SUBSCRIBE, 'betaAccountUrl': BETA_ACCOUNT}
    assert render_site_script(settings)['subscribe'] == SUBSCRIBE['subscribeUrl']


def test_reviewed_waitlist_still_comes_before_beta_access():
    settings = launch_settings()
    settings['betaAccountUrl'] = BETA_ACCOUNT
    assert render_site_script(settings)['subscribe'] == 'waitlist.html'


SYNTHETIC_ADDRESS = '1 Synthetic Street, Testtown, A00 B000'


def test_trader_address_reaches_only_the_noindexed_contact_page(tmp_path):
    settings = json.loads((ROOT / 'website/landing-settings.json').read_text(encoding='utf-8'))
    site.prepare(ROOT / 'website', tmp_path / 'with', settings, 'preview', '  1 Synthetic Street,\n Testtown, A00 B000 ')
    contact = (tmp_path / 'with/contact.html').read_text(encoding='utf-8')
    assert '<span data-trader-address>' + SYNTHETIC_ADDRESS + '</span>' in contact
    assert '<meta name="robots" content="noindex">' in contact
    others = [p for p in (tmp_path / 'with').rglob('*') if p.is_file() and p.name != 'contact.html']
    assert others and not any('Synthetic Street' in p.read_text(encoding='utf-8') for p in others)
    site.prepare(ROOT / 'website', tmp_path / 'without', settings)
    assert 'available on request' in (tmp_path / 'without/contact.html').read_text(encoding='utf-8')
    assert 'Synthetic Street' not in (ROOT / 'website/contact.html').read_text(encoding='utf-8')


@pytest.mark.parametrize('value', ['<script>1 Main St</script>', 'No number street', '1 Main St & Co', 'x' * 250 + ' 1'])
def test_trader_address_must_be_one_plain_line(tmp_path, value):
    settings = json.loads((ROOT / 'website/landing-settings.json').read_text(encoding='utf-8'))
    with pytest.raises(ValueError, match='Trader address'):
        site.prepare(ROOT / 'website', tmp_path / 'bad', settings, 'preview', value)
    assert not (tmp_path / 'bad').exists()


def test_launch_requires_trader_address(tmp_path):
    with pytest.raises(ValueError, match='SAIPH_TRADER_ADDRESS'):
        site.prepare(ROOT / 'website', tmp_path / 'launch', launch_settings(), 'launch')
