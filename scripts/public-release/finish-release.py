#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Finish a draft release from the Public release workflow; run by the maintainer.

Downloads the draft's files, adds the signed Android APK, recomputes SHA256SUMS and
release-source.json for the full set and verifies them. That is all a dry run does.
With --publish it uploads the APK and new checksums, publishes the release and points
website/landing-settings.json at the exact release files, for review and deployment.

The APK must be built (scripts/android/build-release.ps1) from the release's own
commit, so release-source.json stays true for every file. Needs the GitHub CLI
signed in with write access to the repository.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def gh(*args, capture=True):
    result = subprocess.run(['gh', *args], check=True, capture_output=capture, text=True)
    return result.stdout if capture else ''


def find_release(repository, tag):
    # Drafts have no tag yet, so they are found in the list rather than by tag.
    pages = json.loads(gh('api', '--paginate', '--slurp', f'repos/{repository}/releases'))
    for release in (item for page in pages for item in page):
        if release.get('tag_name') == tag:
            return release
    raise SystemExit(f'No release {tag} in {repository}')


def platform_files(version):
    return {'windows': f'Saiph-Link-{version}-windows-x86_64.exe', 'linux': f'Saiph-Link-{version}-linux-x86_64.tar.gz',
            'android': f'Saiph-{version}-android.apk', 'server': f'Saiph-Hub-{version}.tar.gz'}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--tag', required=True, help='Release tag, for example v0.1.0-beta.13')
    parser.add_argument('--android-apk', type=Path, required=True, help='Signed website APK; its release.json must sit beside it')
    parser.add_argument('--repository', default='Abelik1/saiph')
    parser.add_argument('--work', type=Path, help='Fresh working directory (default build/finish-<tag>)')
    parser.add_argument('--publish', action='store_true', help='Upload, publish and update the website settings (default: dry run)')
    args = parser.parse_args()
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?', args.tag):
        parser.error('Use a tag like v0.1.0-beta.13')
    version = args.tag[1:]
    work = args.work or ROOT / 'build' / f'finish-{args.tag}'
    if work.exists():
        parser.error(f'{work} already exists; remove it or choose --work')

    release = find_release(args.repository, args.tag)
    if release.get('draft') is not True:
        raise SystemExit(f'{args.tag} is already published')
    commit = release.get('target_commitish', '')
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise SystemExit('The draft must target an exact commit (the Public release workflow sets it)')

    receipt = json.loads((args.android_apk.parent / 'release.json').read_text(encoding='utf-8-sig'))
    if receipt.get('sourceCommit') != commit or receipt.get('uncommitted') is not False:
        raise SystemExit(f'Build the APK from {commit} with scripts/android/build-release.ps1; '
                         f'this one comes from {receipt.get("sourceCommit")}')

    work.mkdir(parents=True)
    gh('release', 'download', args.tag, '--repo', args.repository, '--dir', str(work), capture=False)
    files = platform_files(version)
    shutil.copyfile(args.android_apk, work / files['android'])
    checksums = load('release_checksums', 'release-checksums.py')
    for command in ([], ['--verify']):
        subprocess.run([sys.executable, str(HERE / 'release-checksums.py'), str(work), '--source-commit', commit, *command], check=True)
    missing = [name for name in files.values() if not (work / name).is_file()]
    if missing:
        raise SystemExit('Missing release files: ' + ', '.join(missing))
    print(f'Checked {len(checksums.verify(work, commit)["artifacts"])} files in {work} against {commit}.')
    if not args.publish:
        print('Dry run: nothing uploaded or published. Add --publish to finish the release.')
        return

    gh('release', 'upload', args.tag, '--repo', args.repository, '--clobber',
       str(work / files['android']), str(work / 'SHA256SUMS'), str(work / 'release-source.json'), capture=False)
    gh('release', 'edit', args.tag, '--repo', args.repository, '--draft=false', capture=False)
    published = json.loads(gh('api', f'repos/{args.repository}/releases/tags/{args.tag}'))
    settings = load('prepare_website_downloads', 'prepare-website-downloads.py').prepare(
        args.repository, published, files, work, commit)
    path = ROOT / 'website/landing-settings.json'
    site = json.loads(path.read_text(encoding='utf-8'))
    site.update(settings)
    path.write_text(json.dumps(site, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Published {published["html_url"]}.')
    print('Updated website/landing-settings.json: review, commit and deploy the website so its Download buttons use this release.')


if __name__ == '__main__':
    main()
