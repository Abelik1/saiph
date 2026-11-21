# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public release helpers gather exact files and refuse an APK from other source."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts/public-release' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collect = load('collect_release', 'collect-release.py')
finish = load('finish_release', 'finish-release.py')
COMMIT = 'c' * 40


def distribution(tmp_path, platform, suffixes):
    root = tmp_path / 'distribution'
    package = root / f'package-0.1.0-beta.13-{platform}'
    (package / 'licenses').mkdir(parents=True)
    (package / 'package-manifest.json').write_text('{"synthetic": "manifest"}')
    (package / 'licenses/inventory.json').write_text('{"synthetic": "inventory"}')
    for suffix in suffixes:
        (root / f'Saiph-Link-0.1.0-beta.13-{platform}{suffix}').write_bytes(b'synthetic package')
    return root


def test_collect_gives_each_platform_unique_asset_names(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = tmp_path / 'release'
    collect.collect(distribution(tmp_path, 'linux-x86_64', ('.tar.gz', '.run')), 'linux-x86_64', '0.1.0-beta.13', output)
    assert sorted(path.name for path in output.iterdir()) == [
        'Saiph-Link-0.1.0-beta.13-linux-x86_64.run', 'Saiph-Link-0.1.0-beta.13-linux-x86_64.tar.gz',
        'dependency-inventory-linux-x86_64.json', 'package-manifest-linux-x86_64.json']


def test_collect_requires_the_installer(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match='Missing packaged file'):
        collect.collect(distribution(tmp_path, 'windows-x86_64', ()), 'windows-x86_64', '0.1.0-beta.13', tmp_path / 'release')


def fake_github(monkeypatch, tmp_path, calls):
    assets = {name: b'synthetic ' + name.encode() for name in finish.platform_files('0.1.0-beta.13').values() if 'android' not in name}

    def gh(*args, capture=True):
        calls.append(args)
        if args[0] == 'api':
            return json.dumps([[{'tag_name': 'v0.1.0-beta.13', 'draft': True, 'target_commitish': COMMIT}]])
        if args[:2] == ('release', 'download'):
            directory = Path(args[args.index('--dir') + 1])
            for name, data in assets.items():
                (directory / name).write_bytes(data)
            return ''
        raise AssertionError('A dry run must not change the release: ' + ' '.join(args))
    monkeypatch.setattr(finish, 'gh', gh)


def apk(tmp_path, commit):
    folder = tmp_path / 'android'
    folder.mkdir()
    (folder / 'Saiph-0.9.8.apk').write_bytes(b'synthetic signed apk')
    (folder / 'release.json').write_text(json.dumps({'sourceCommit': commit, 'uncommitted': False}))
    return folder / 'Saiph-0.9.8.apk'


def run(monkeypatch, *args):
    monkeypatch.setattr(sys, 'argv', ['finish-release.py', *args])
    finish.main()


def test_dry_run_adds_the_apk_and_checksums_everything_without_uploading(tmp_path, monkeypatch):
    calls = []
    fake_github(monkeypatch, tmp_path, calls)
    work = tmp_path / 'work'
    run(monkeypatch, '--tag', 'v0.1.0-beta.13', '--android-apk', str(apk(tmp_path, COMMIT)), '--work', str(work))
    source = json.loads((work / 'release-source.json').read_text())
    assert source['source_commit'] == COMMIT
    assert {item['file'] for item in source['artifacts']} == set(finish.platform_files('0.1.0-beta.13').values())
    assert [call[:2] for call in calls] == [('api', '--paginate'), ('release', 'download')]


def test_refuses_an_apk_built_from_another_commit(tmp_path, monkeypatch):
    fake_github(monkeypatch, tmp_path, [])
    with pytest.raises(SystemExit, match='Build the APK from'):
        run(monkeypatch, '--tag', 'v0.1.0-beta.13', '--android-apk', str(apk(tmp_path, 'd' * 40)), '--work', str(tmp_path / 'work'))
    assert not (tmp_path / 'work').exists()
