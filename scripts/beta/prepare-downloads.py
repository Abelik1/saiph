#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage checked beta files and a small download portal; never upload or publish."""
import argparse
import hashlib
import html
import importlib.util
import json
from pathlib import Path
import re
import shutil
from urllib.parse import quote, urlsplit

SPEC = importlib.util.spec_from_file_location('beta_checksums', Path(__file__).parents[1] / 'public-release/release-checksums.py')
checksums = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checksums)
REQUIRED = {'windows', 'linux', 'android', 'desktop_source', 'android_source'}
LABELS = {'windows': 'Windows installer', 'linux': 'Linux installer', 'android': 'Android APK',
          'desktop_source': 'Desktop corresponding source', 'android_source': 'Android corresponding source'}


def regular(path):
    if any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)() for p in (path, *path.parents)):
        raise ValueError('Links and junctions are not accepted')
    if not path.is_file():
        raise ValueError('A regular file is required')


def prepare(directory, mapping, commit, base_url, output, android_invite='', supporting_files=()):
    directory, output = Path(directory).absolute(), Path(output).absolute()
    parsed = urlsplit(base_url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.port not in (None, 443)
            or not base_url.endswith('/') or re.search(r'[\s<>"\\]', base_url)):
        raise ValueError('Use a fixed HTTPS artifact directory URL, ending in /, without tokens')
    if android_invite and not re.fullmatch(r'https://appdistribution\.firebase\.dev/i/[A-Za-z0-9]{8,64}', android_invite):
        raise ValueError('Use the actual Firebase group invite URL')
    if (not isinstance(mapping, dict) or set(mapping) != REQUIRED
            or any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', v) for v in mapping.values())
            or len(set(mapping.values())) != len(REQUIRED)):
        raise ValueError('Map the three installers and two corresponding-source archives to distinct filenames')
    if not mapping['windows'].endswith('.exe') or not mapping['linux'].endswith('.run') or not mapping['android'].endswith('.apk'):
        raise ValueError('Use the native Windows .exe, Linux .run and Android .apk installers')
    if any(not mapping[k].endswith(('.zip', '.tar.gz')) for k in ('desktop_source', 'android_source')):
        raise ValueError('Corresponding source must be an archive')
    if (not isinstance(supporting_files, (list, tuple))
            or any(not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name)
                   or not (name.endswith(('.zip', '.tar.gz')) or name.startswith(('LICENSE', 'NOTICE', 'THIRD_PARTY')))
                   for name in supporting_files)
            or len(set(supporting_files)) != len(supporting_files)
            or set(supporting_files) & set(mapping.values())):
        raise ValueError('Explicitly select distinct dependency-source archives and licence/notices files')
    selected = list(mapping.values()) + list(supporting_files)
    if output.exists() or output.is_relative_to(directory) or directory.is_relative_to(output):
        raise ValueError('Use a fresh output directory separate from the input artifacts')
    for p in (directory, *directory.parents, output, *output.parents):
        if p.is_symlink() or getattr(p, 'is_junction', lambda: False)():
            raise ValueError('Directories must not use links or junctions')
    for path in directory.iterdir():
        regular(path)
    metadata = checksums.verify(directory, commit)
    records = {item['file']: item for item in metadata['artifacts']}
    if any(v not in records or records[v]['bytes'] == 0 for v in selected):
        raise ValueError('Every selected file must be nonempty and checksum-recorded')
    # Stage only named downloads. Other input files (including logs) never reach the site.
    files, portal = output / 'files', output / 'portal'
    files.mkdir(parents=True)
    portal.mkdir()
    for name in selected:
        shutil.copyfile(directory / name, files / name)
        with (files / name).open('rb') as staged:
            digest = hashlib.file_digest(staged, 'sha256').hexdigest()
        if digest != records[name]['sha256']:
            raise ValueError('An artifact changed while being staged')
    checksums.record(files, commit)
    checksums.verify(files, commit)
    downloads = {key: {**records[name], 'url': base_url + quote(name)} for key, name in mapping.items()}
    supporting = [{**records[name], 'url': base_url + quote(name)} for name in supporting_files]
    manifest = {'schema': 1, 'audience': 'private-beta', 'source_commit': commit,
                'downloads': downloads, 'supporting_files': supporting, 'android_invite': android_invite,
                'checksums_url': base_url + 'SHA256SUMS',
                'source_metadata_url': base_url + 'release-source.json',
                'verification': 'local-bytes-only; signatures, hosted readiness and remote access remain unverified'}
    (portal / 'downloads.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    cards = ''.join(f'<li><a href="{html.escape(item["url"], quote=True)}">{LABELS[key]}</a>'
                    f'<p>{item["bytes"]:,} bytes · SHA-256 <code>{item["sha256"]}</code></p></li>'
                    for key, item in downloads.items())
    cards += ''.join(f'<li><a href="{html.escape(item["url"], quote=True)}">{html.escape(item["file"])}</a>'
                     f'<p>{item["bytes"]:,} bytes · SHA-256 <code>{item["sha256"]}</code></p></li>' for item in supporting)
    invite = (f'<p><a href="{html.escape(android_invite, quote=True)}">Join the Android beta through Google</a></p>'
              if android_invite else '')
    page = f'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">
<title>Saiph friends beta downloads</title><link rel="stylesheet" href="style.css">
<main><h1>Saiph friends beta</h1><p>Download the installer for your device. No compilation is needed.</p>
<p>Use the hosted setup details supplied with your invitation. No Tailscale or personal server is required for Hosted.</p>
<p>Development preview: installation and hosted acceptance checks are still in progress.</p>
{invite}<ul>{cards}</ul><p><a href="{html.escape(base_url + 'SHA256SUMS', quote=True)}">Checksums</a> ·
<a href="{html.escape(base_url + 'release-source.json', quote=True)}">Source and file metadata</a></p>
<p>Uninstalling removes device keys. Use a test profile and keep your existing installation until recovery is checked.</p>
<p>Build source: <code>{html.escape(commit)}</code></p></main></html>'''
    (portal / 'index.html').write_text(page, encoding='utf-8')
    (portal / 'style.css').write_text('body{font:17px/1.6 system-ui;background:#111820;color:#e6edf3;margin:0}main{max-width:850px;margin:4rem auto;padding:0 1.5rem}a{color:#6ee7e8}li{margin:1.5rem 0}code{overflow-wrap:anywhere;font-size:.8em}p{color:#bac8d3}', encoding='utf-8')
    (portal / 'vercel.json').write_text(json.dumps({'headers': [{'source': '/(.*)', 'headers': [
        {'key': 'X-Robots-Tag', 'value': 'noindex, nofollow'}, {'key': 'Cache-Control', 'value': 'no-store'},
        {'key': 'X-Content-Type-Options', 'value': 'nosniff'},
        {'key': 'Content-Security-Policy', 'value': "default-src 'none'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'"}]}]}, indent=2), encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--platform-map', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--artifact-base-url', required=True)
    parser.add_argument('--android-invite', default='')
    parser.add_argument('--supporting-file', action='append', default=[], help='Repeat for required dependency sources and licence/notices files')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        prepare(args.artifacts, json.loads(args.platform_map.read_text(encoding='utf-8')),
                args.source_commit, args.artifact_base_url, args.output, args.android_invite, args.supporting_file)
    except (ValueError, OSError, TypeError, KeyError):
        parser.exit(1, 'Beta bundle rejected; no upload or deployment attempted.\n')
    print('Staged checked files and a separate portal. Protect both hosting locations before sharing.')


if __name__ == '__main__':
    main()
