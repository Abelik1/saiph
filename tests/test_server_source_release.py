# SPDX-License-Identifier: AGPL-3.0-or-later
"""Server source artifacts must preserve licences, reviewed bytes and honest identity."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('server_source_builder', ROOT / 'scripts/build-orion-server.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
spec = importlib.util.spec_from_file_location('server_source_installer', ROOT / 'hub/orion_hub/server_install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def snapshot(tmp_path):
    root = tmp_path / 'public'
    items = {'hub/requirements.txt': b'requests>=2\n',
             'hub/orion_hub/server_install.py': (ROOT / 'hub/orion_hub/server_install.py').read_bytes(),
             'hub/orion_hub/__init__.py': b'', 'hub/orion_hub/server.py': b'# Synthetic server source\n',
             'LICENSE': b'GNU AFFERO GENERAL PUBLIC LICENSE\nSynthetic fixture',
             'THIRD_PARTY_NOTICES.md': b'Synthetic component notice',
             'docs/SERVER_RELEASE.md': b'Synthetic source-only release scope'}
    for name, data in items.items():
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
    receipt = {'schema': 1, 'files': {name: builder.sha256(data) for name, data in items.items()},
               'scans': {'owner_private_boundary': 'passed', 'gitleaks': 'passed'}, 'git_history': False}
    (root / 'PUBLIC_EXPORT.json').write_text(json.dumps(receipt))
    return root


def test_local_snapshot_has_licence_notices_exact_hashes_and_no_fabricated_commit(tmp_path):
    root = snapshot(tmp_path); output = tmp_path / 'server.tar.gz'
    digest = builder.build_public(root, output, '0.1.0-beta.1', local_snapshot=True)
    assert digest == builder.sha256(output.read_bytes())
    manifest = builder.verify_archive(output)
    assert manifest['source']['source_commit'] is None
    assert manifest['source']['official_release'] is False
    assert {'LICENSE', 'THIRD_PARTY_NOTICES.md', 'SOURCE.json', 'docs/SERVER_RELEASE.md'} <= set(manifest['files'])
    with tarfile.open(output) as archive:
        archive.extractall(tmp_path / 'extracted', **({'filter': 'data'} if hasattr(tarfile, 'data_filter') else {}))
    assert installer.verify_package(tmp_path / 'extracted/orion-server') == manifest
    (tmp_path / 'extracted/orion-server/SHA256SUMS').write_text('wrong')
    with pytest.raises(installer.SetupError, match='checksum'):
        installer.verify_package(tmp_path / 'extracted/orion-server')


@pytest.mark.parametrize('mutation', ['changed', 'extra', 'failed_scan', 'missing_licence'])
def test_public_package_rejects_changed_or_incomplete_source(tmp_path, mutation):
    root = snapshot(tmp_path)
    if mutation == 'changed': (root / 'hub/requirements.txt').write_text('changed')
    if mutation == 'extra': (root / 'owner.env').write_text('PRIVATE_FIXTURE')
    if mutation == 'missing_licence': (root / 'LICENSE').unlink()
    if mutation == 'failed_scan':
        receipt = json.loads((root / 'PUBLIC_EXPORT.json').read_text()); receipt['scans']['gitleaks'] = 'failed'
        (root / 'PUBLIC_EXPORT.json').write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        builder.build_public(root, tmp_path / 'server.tar.gz', '0.1.0-beta.1', local_snapshot=True)
    assert not (tmp_path / 'server.tar.gz').exists()


def test_source_identity_requires_real_clean_commit_and_snapshot_cannot_claim_one(tmp_path):
    root = snapshot(tmp_path); receipt = (root / 'PUBLIC_EXPORT.json').read_bytes()
    with pytest.raises(ValueError, match='exact full public'):
        builder.source_identity(root, receipt)
    with pytest.raises(ValueError, match='must not claim'):
        builder.source_identity(root, receipt, 'a' * 40, local_snapshot=True)
    def git(*args):
        return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()
    git('init'); git('add', '.')
    git('-c', 'user.name=Synthetic release fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'Synthetic public snapshot')
    commit = git('rev-parse', 'HEAD')
    assert builder.source_identity(root, receipt, commit)['source_commit'] == commit
    with pytest.raises(ValueError, match='match HEAD'):
        builder.source_identity(root, receipt, 'a' * 40)
    (root / 'untracked.txt').write_text('fixture')
    with pytest.raises(ValueError, match='clean checkout'):
        builder.source_identity(root, receipt, commit)


def test_output_cannot_pollute_snapshot_or_overwrite_existing_artifact(tmp_path):
    root = snapshot(tmp_path)
    with pytest.raises(ValueError, match='outside'):
        builder.build_public(root, root / 'out.tar.gz', '0.1.0-beta.1', local_snapshot=True)
    output = tmp_path / 'existing.tar.gz'; output.write_bytes(b'keep')
    with pytest.raises(FileExistsError):
        builder.build_public(root, output, '0.1.0-beta.1', local_snapshot=True)
    assert output.read_bytes() == b'keep'


def test_archive_rejects_unmanifested_file_and_duplicate_members(tmp_path):
    root = snapshot(tmp_path); output = tmp_path / 'server.tar.gz'
    builder.build_public(root, output, '0.1.0-beta.1', local_snapshot=True)
    with tarfile.open(output) as archive:
        members = [(member.name, archive.extractfile(member).read()) for member in archive.getmembers()]
    for name in ('orion-server/owner.env', 'orion-server/LICENSE'):
        bad = tmp_path / ('bad-' + str(len(name)) + '.tar.gz')
        with tarfile.open(bad, 'w:gz') as archive:
            for member_name, data in members + [(name, b'unreviewed')]:
                item = tarfile.TarInfo(member_name); item.size = len(data); archive.addfile(item, io.BytesIO(data))
        with pytest.raises(ValueError): builder.verify_archive(bad)
