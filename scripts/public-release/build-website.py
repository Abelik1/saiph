#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Prepare a static Saiph site without publishing it or inventing release URLs."""
import argparse
import hashlib
from html.parser import HTMLParser
import ipaddress
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

FILES = ('index.html', 'self-host.html', 'hosted.html', 'downloads.html', 'waitlist.html', 'privacy.html',
         'account-privacy.html', 'terms.html', 'refunds.html', 'contact.html', 'assets/logo.svg',
         'assets/site.css', 'assets/site.js', 'assets/stage.js', 'assets/analytics.js')
PLATFORMS = ('windows', 'linux', 'android', 'server')
FIELDS = {'sourceVisibility', 'githubUrl', 'releasesUrl', 'downloads', 'subscribeUrl', 'waitlistUrl',
          'androidBetaUrl', 'betaAccountUrl', 'waitlistPrivacyUrl', 'waitlistNotice', 'hostedPrice', 'hostedPeriod', 'license', 'privacy', 'waitlist', 'release', 'analytics'}


def public_url(value):
    if not isinstance(value, str) or any(char.isspace() for char in value):
        raise ValueError('Public links must be HTTPS URLs without whitespace')
    parts = urlsplit(value)
    host = (parts.hostname or '').lower()
    if (parts.scheme != 'https' or not host or parts.username or parts.password
            or parts.port not in (None, 443) or parts.query
            or host in {'localhost', 'example.com', 'example.org', 'example.net'}
            or host.endswith(('.invalid', '.localhost', '.example', '.test', '.local'))):
        raise ValueError('Use a public HTTPS URL without credentials, query tokens or placeholder hosts')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError('Public links must not point to private or documentation addresses')
    return value


PRIVACY_FIELDS = ('status', 'controllerName', 'controllerCountry', 'contactEmail', 'updatedAt',
                  'hostingRetention', 'hostingTransfers', 'contactProcessing')
TALLY_FORM = 'https://tally.so/r/gDy42K'
TALLY_CONSENT = ('I agree to receive the Saiph launch announcement and occasional launch updates by email. '
                 'I can unsubscribe or ask for my email to be deleted at any time.')
WAITLIST_CONTROLS = ('emailRequired', 'consentRequired', 'partialSubmissionsDisabled', 'confirmationEmailDisabled', 'trackingDisabled')
WAITLIST_FIELDS = ('processorName', 'processorPrivacyUrl', 'processingLocations',
                   'transferSafeguards', 'retention', 'withdrawal', 'consentText',
                   'noticeVersion', 'optInMode', *WAITLIST_CONTROLS)
RELEASE_FIELDS = ('tag', 'sourceCommit', 'checksumsUrl', 'sourceMetadataUrl')
FIREBASE_INVITE = re.compile(r'https://appdistribution\.firebase\.dev/i/[A-Za-z0-9]{8,64}')
BETA_ACCOUNT = re.compile(r'https://[a-z0-9.-]+/account')


def validate_waitlist_url(value, notice_version):
    """Only the reviewed Tally form may carry the public consent-version query."""
    if not isinstance(notice_version, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', notice_version):
        raise ValueError('Provide a fixed public consent notice version')
    if not isinstance(value, str) or any(char.isspace() for char in value):
        raise ValueError('Use the reviewed Tally form and matching consent_version')
    parts = urlsplit(value)
    public_url(value.split('?', 1)[0])
    try:
        parameters = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True, max_num_fields=1)
    except ValueError:
        raise ValueError('Use only one consent_version query parameter') from None
    if (value != TALLY_FORM + '?consent_version=' + notice_version
            or parts.fragment or parameters != [('consent_version', notice_version)]):
        raise ValueError('Use the reviewed Tally form and matching consent_version')
    return value


def text_fields(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(f'Provide exactly the {label} fields; no credentials')
    if any(not isinstance(value[k], str) or not value[k].strip() or len(value[k]) > 4000
           for k in fields if k not in WAITLIST_CONTROLS):
        raise ValueError(f'Complete the public {label} text before enabling it')


def validate_settings(settings, mode):
    if mode not in ('preview', 'launch'):
        raise ValueError('Unknown website mode')
    if not isinstance(settings, dict) or set(settings) - FIELDS:
        raise ValueError('Unknown website settings; do not copy deployment credentials into site config')
    config = {'sourceVisibility': 'private', 'githubUrl': '', 'releasesUrl': '',
              'downloads': {name: '' for name in PLATFORMS}, 'release': {},
              'subscribeUrl': '', 'waitlistUrl': '', 'androidBetaUrl': '', 'betaAccountUrl': '', 'waitlistPrivacyUrl': '', 'waitlistNotice': '',
              'privacy': {}, 'waitlist': {}, 'analytics': {'enabled': False, 'scriptPath': '/_vercel/insights/script.js'}, 'hostedPrice': '', 'hostedPeriod': '/ month',
              'license': {'core': 'AGPL-3.0-or-later', 'android': 'GPL-3.0-only'}}
    config.update(settings)
    if not isinstance(config['downloads'], dict) or set(config['downloads']) != set(PLATFORMS):
        raise ValueError('Provide exactly the Windows, Linux, Android and server download fields')
    if config['license'] != {'core': 'AGPL-3.0-or-later', 'android': 'GPL-3.0-only'}:
        raise ValueError('Website licence labels must match the reviewed source licences')
    if config['subscribeUrl'] or config['hostedPrice']:
        raise ValueError('Paid Hosted is not ready; keep subscription links and prices empty')
    for name in ('githubUrl', 'releasesUrl', 'waitlistPrivacyUrl', 'betaAccountUrl'):
        if not isinstance(config[name], str):
            raise ValueError('Public link fields must be text')
        if config[name] and config[name] != 'privacy.html#waitlist':
            public_url(config[name])
        elif config[name] and name != 'waitlistPrivacyUrl':
            raise ValueError('Use public HTTPS links')
    for url in config['downloads'].values():
        if not isinstance(url, str):
            raise ValueError('Download link fields must be text')
        if url:
            public_url(url)
    if not isinstance(config['androidBetaUrl'], str) or (
            config['androidBetaUrl'] and not FIREBASE_INVITE.fullmatch(config['androidBetaUrl'])):
        raise ValueError('Android beta link must be a Firebase App Distribution invite link')
    if config['betaAccountUrl'] and not BETA_ACCOUNT.fullmatch(config['betaAccountUrl']):
        raise ValueError('Friends beta link must be the HTTPS account /account page')
    if not isinstance(config['waitlistNotice'], str) or not isinstance(config['hostedPeriod'], str):
        raise ValueError('Notice and period must be text')
    if config['sourceVisibility'] not in ('private', 'public'):
        raise ValueError('Source visibility must be private or public')
    if mode == 'launch' and config['sourceVisibility'] != 'public':
        raise ValueError('Launch requires public source visibility')
    privacy = config['privacy']
    if not isinstance(privacy, dict) or set(privacy) - set(PRIVACY_FIELDS):
        raise ValueError('Unknown public privacy fields')
    if any(not isinstance(v, str) or len(v) > 4000 for v in privacy.values()):
        raise ValueError('Public privacy fields must be text')
    if privacy and privacy.get('status') not in ('draft', 'approved'):
        raise ValueError('Privacy status must be draft or approved')
    if privacy.get('status') == 'approved':
        text_fields(privacy, PRIVACY_FIELDS, 'privacy')
        if not re.fullmatch(r'[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', privacy['contactEmail']):
            raise ValueError('A working public contact email is required')
        date.fromisoformat(privacy['updatedAt'])
    analytics = config['analytics']
    if (not isinstance(analytics, dict) or set(analytics) != {'enabled', 'scriptPath'}
            or type(analytics['enabled']) is not bool
            or not isinstance(analytics['scriptPath'], str)
            or not re.fullmatch(r'/(?:_vercel/insights|[A-Za-z0-9_-]{8,128})/script\.js', analytics['scriptPath'])):
        raise ValueError('Analytics requires a boolean enabled and a same-origin Vercel scriptPath; no credentials')
    if analytics['enabled'] and privacy.get('status') != 'approved':
        raise ValueError('Analytics requires an approved public privacy notice before activation')
    waitlist = config['waitlist']
    if not isinstance(waitlist, dict) or set(waitlist) - set(WAITLIST_FIELDS):
        raise ValueError('Unknown waitlist fields; no provider secrets')
    if any(not isinstance(v, str) or len(v) > 4000 for k, v in waitlist.items()
           if k not in WAITLIST_CONTROLS):
        raise ValueError('Public waitlist fields must be text')
    if any(type(waitlist[k]) is not bool for k in WAITLIST_CONTROLS if k in waitlist):
        raise ValueError('Waitlist controls must be booleans')
    if not isinstance(config['waitlistUrl'], str):
        raise ValueError('Public link fields must be text')
    if config['waitlistUrl']:
        if config['waitlistPrivacyUrl'] != 'privacy.html#waitlist' or not config['waitlistNotice'].strip():
            raise ValueError('A waitlist requires a visible email-use notice and privacy information link')
        if privacy.get('status') != 'approved':
            raise ValueError('Waitlist requires an approved controller/contact privacy notice')
        text_fields(waitlist, WAITLIST_FIELDS, 'waitlist')
        if config['waitlistNotice'] != waitlist['consentText']:
            raise ValueError('Waitlist notice and signup consent must match')
        public_url(waitlist['processorPrivacyUrl'])
        validate_waitlist_url(config['waitlistUrl'], waitlist['noticeVersion'])
        if (waitlist['processorName'] != 'Tally' or waitlist['processorPrivacyUrl'] != 'https://tally.so/help/privacy-policy'
                or waitlist['consentText'] != TALLY_CONSENT or waitlist['optInMode'] != 'single'
                or any(waitlist[field] is not True for field in WAITLIST_CONTROLS)):
            raise ValueError('Waitlist requires the reviewed Tally single opt-in form, required consent, '
                             'disabled partial submissions/confirmation email and disabled email tracking')
    release = config['release']
    if not isinstance(release, dict) or set(release) - set(RELEASE_FIELDS):
        raise ValueError('Unknown release metadata fields')
    if any(not isinstance(v, str) or len(v) > 4000 for v in release.values()):
        raise ValueError('Public release fields must be text')
    if any(config['downloads'].values()) or config['releasesUrl']:
        if config['sourceVisibility'] != 'public':
            raise ValueError('Public downloads require public source visibility')
        text_fields(release, RELEASE_FIELDS, 'release')
        if not re.fullmatch(r'[a-f0-9]{40}', release['sourceCommit']):
            raise ValueError('Release source must be an exact full Git commit')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', release['tag']) or release['tag'] in ('latest', 'HEAD'):
            raise ValueError('Release tag must be a fixed version')
        repo = config['githubUrl']
        if not re.fullmatch(r'https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            raise ValueError('Use the actual GitHub source repository URL')
        prefix = repo + '/releases/download/' + release['tag'] + '/'
        if config['releasesUrl'] != repo + '/releases/tag/' + release['tag']:
            raise ValueError('Release page must match the exact source repository and tag')
        if release['checksumsUrl'] != prefix + 'SHA256SUMS' or release['sourceMetadataUrl'] != prefix + 'release-source.json':
            raise ValueError('Release checksum/source metadata must match the exact tag')
        for name, url in config['downloads'].items():
            if url and (not url.startswith(prefix) or '/' in url[len(prefix):] or urlsplit(url).fragment
                        or unquote(url[len(prefix):]) in ('.', '..', '')
                        or re.search(r'[\x00-\x1f\x7f/\\:]', unquote(url[len(prefix):]))
                        or unquote(url[len(prefix):]) != unquote(url[len(prefix):]).strip()):
                raise ValueError(f'{name} must link to a versioned release artifact in the source repository')
        configured = [url for url in config['downloads'].values() if url]
        if len(configured) != len(set(configured)):
            raise ValueError('Each platform needs its own release artifact')
    if mode == 'launch' and not all((config['githubUrl'], config['releasesUrl'], config['waitlistUrl'], *config['downloads'].values())):
        raise ValueError('Launch requires actual source, release, four downloads and waitlist URLs')
    return config


class Page(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.ids = set()
        self.links = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.add(attrs['id'])
        for key in ('href', 'src'):
            if attrs.get(key):
                self.links.append(attrs[key])


def prepare(source, output, settings, mode='preview'):
    source, output = Path(source).resolve(), Path(output).absolute()
    config = validate_settings(settings, mode)
    if output.exists() or output.resolve().is_relative_to(source):
        raise ValueError('Use a fresh output directory outside the website source')
    contents = {}
    for name in FILES:
        path = source / name
        if any(part.is_symlink() or part.is_junction() for part in [path, *path.parents] if part != source.parent):
            raise ValueError('Website inputs must not use links or junctions')
        contents[name] = path.read_bytes()
    pages = {name: Page(data.decode('utf-8')) for name, data in contents.items() if name.endswith('.html')}
    for name, page in pages.items():
        for link in page.links:
            parts = urlsplit(link)
            if parts.scheme or parts.netloc:
                if parts.scheme != 'https':
                    raise ValueError('Static page references must use HTTPS or local files')
                continue
            target = ((source / name).parent / unquote(parts.path)).resolve() if parts.path else source / name
            if not target.is_relative_to(source):
                raise ValueError('Website reference escapes the static bundle')
            relative = target.relative_to(source).as_posix()
            if relative not in contents and relative != 'assets/config.js':
                raise ValueError(f'Missing static asset: {relative}')
            if parts.fragment and relative in pages and unquote(parts.fragment) not in pages[relative].ids:
                raise ValueError(f'Missing page anchor: {relative}#{parts.fragment}')
    contents['assets/config.js'] = ('window.ORION_SITE = ' + json.dumps(config, ensure_ascii=False, indent=2) + ';\n').encode()
    manifest = {'schema': 1, 'mode': mode, 'published': False,
                'scope': 'Static source/config validation only; does not verify remote URLs, signatures or release review.',
                'files': {name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
                          for name, data in sorted(contents.items())}}
    output.mkdir(parents=True)
    for name, data in contents.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (output / 'website-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--website', type=Path, default=Path(__file__).resolve().parents[2] / 'website')
    parser.add_argument('--settings', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('preview', 'launch'), default='preview')
    args = parser.parse_args()
    result = prepare(args.website, args.output, json.loads(args.settings.read_text(encoding='utf-8')), args.mode)
    print(f"Prepared {len(result['files'])} static files ({args.mode}); nothing published.")


if __name__ == '__main__':
    main()
