# SPDX-License-Identifier: AGPL-3.0-or-later
"""Create a small audited source package without runtime data or owner configuration."""
from __future__ import annotations
import argparse
import hashlib
import json
import tarfile
from pathlib import Path
import io
import os
import re
import stat
import subprocess


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def snapshot_files(root):
    """Verify the scanned public tree, including all bytes, before selecting Hub files."""
    root = Path(root).resolve(strict=True)
    receipt_path = root / 'PUBLIC_EXPORT.json'
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    if receipt.get('scans') != {'owner_private_boundary': 'passed', 'gitleaks': 'passed'} or receipt.get('git_history') is not False:
        raise ValueError('A clean scanned public export is required')
    expected = receipt.get('files')
    if not isinstance(expected, dict) or not expected:
        raise ValueError('Public export receipt has no file inventory')
    actual = set()
    pending = [root]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                relative = Path(entry.path).relative_to(root).as_posix()
                if relative == '.git':
                    continue  # A future fresh public Git checkout may have its own history.
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    raise ValueError('Public source may not contain linked files or directories')
                if stat.S_ISDIR(info.st_mode):
                    pending.append(Path(entry.path))
                elif stat.S_ISREG(info.st_mode):
                    actual.add(relative)
                else:
                    raise ValueError('Public source contains an unsupported file type')
    if actual != set(expected) | {'PUBLIC_EXPORT.json'}:
        raise ValueError('Public source file set differs from its scan receipt')
    contents = {}
    for name, expected_hash in expected.items():
        if not isinstance(name, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_hash):
            raise ValueError('Invalid public source inventory')
        relative = Path(name)
        if relative.is_absolute() or '\\' in name or ':' in name or any(part in {'', '.', '..'} for part in name.split('/')):
            raise ValueError('Unsafe public source inventory path')
        data = (root / relative).read_bytes()
        if sha256(data) != expected_hash:
            raise ValueError('Public source bytes differ from the scan receipt: ' + name)
        contents[name] = data
    return contents, receipt_path.read_bytes()


def source_identity(root, receipt_bytes, source_commit=None, *, local_snapshot=False):
    if local_snapshot:
        if source_commit is not None:
            raise ValueError('Local snapshot must not claim a public Git commit')
        return {'kind': 'local-scanned-export', 'source_commit': None,
                'public_export_sha256': sha256(receipt_bytes), 'official_release': False}
    if not source_commit or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', source_commit):
        raise ValueError('An exact full public source commit is required; use --local-snapshot for preparation')
    def git(*args):
        return subprocess.run(['git', '-C', str(root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    if git('rev-parse', 'HEAD') != source_commit or git('status', '--porcelain', '--untracked-files=all'):
        raise ValueError('Public source commit must match HEAD in a clean checkout')
    tracked = set(git('ls-files').splitlines())
    expected = set(json.loads(receipt_bytes)['files']) | {'PUBLIC_EXPORT.json'}
    if tracked != expected:
        raise ValueError('The public commit must track exactly the reviewed source snapshot')
    return {'kind': 'reviewed-public-git-checkout', 'source_commit': source_commit,
            'public_export_sha256': sha256(receipt_bytes), 'official_release': False,
            'scope': 'Source identity only; signing and release approval remain separate.'}


def write_archive(output, release, files, *, source=None):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}', release):
        raise ValueError('Invalid release')
    manifest = {'format': 'orion-server-package', 'version': 1, 'release': release,
                'files': {name: sha256(data) for name, data in sorted(files.items())}}
    if source is not None:
        manifest['source'] = source
    contents = dict(files)
    contents['package.json'] = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    if source is not None:
        contents['SHA256SUMS'] = ''.join(sha256(data) + '  ' + name + '\n'
                                       for name, data in sorted(contents.items())).encode()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream, tarfile.open(fileobj=stream, mode='w:gz') as archive:
        for name, data in sorted(contents.items()):
            item = tarfile.TarInfo('orion-server/' + name)
            item.size = len(data); item.mode = 0o644
            archive.addfile(item, io.BytesIO(data))
    verify_archive(output)
    return sha256(output.read_bytes())


def verify_archive(path):
    """Check archive member types, exact files, package hashes and final checksums."""
    files = {}
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive.getmembers():
            prefix = 'orion-server/'
            name = member.name.removeprefix(prefix)
            if (not member.name.startswith(prefix) or not member.isfile() or member.size > 4 * 1024 ** 2
                    or name in files or not name or '\\' in name or ':' in name
                    or any(part in {'', '.', '..'} for part in name.split('/'))):
                raise ValueError('Unsafe or duplicate server archive member')
            files[name] = archive.extractfile(member).read()
    manifest = json.loads(files['package.json'])
    if manifest.get('format') != 'orion-server-package' or manifest.get('version') != 1:
        raise ValueError('Unsupported server archive')
    expected = manifest['files']
    extras = {'package.json', 'SHA256SUMS'} if 'source' in manifest else {'package.json'}
    if set(files) != set(expected) | extras:
        raise ValueError('Server archive has unrecorded or missing files')
    if any(sha256(files[name]) != expected_hash for name, expected_hash in expected.items()):
        raise ValueError('Server archive integrity check failed')
    if 'source' in manifest:
        checksums = ''.join(sha256(data) + '  ' + name + '\n' for name, data in sorted(files.items()) if name != 'SHA256SUMS').encode()
        if files['SHA256SUMS'] != checksums or json.loads(files['SOURCE.json']) != manifest['source']:
            raise ValueError('Server source/checksum metadata does not match final bytes')
    return manifest


def build_public(root, output, release, source_commit=None, *, local_snapshot=False):
    root = Path(root).resolve(strict=True)
    if Path(output).resolve().is_relative_to(root):
        raise ValueError('Build output must stay outside the clean public source tree')
    public, receipt = snapshot_files(root)
    source = source_identity(root, receipt, source_commit, local_snapshot=local_snapshot)
    required = {'hub/requirements.txt', 'hub/orion_hub/server_install.py', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'docs/SERVER_RELEASE.md'}
    if not required <= set(public) or b'GNU AFFERO GENERAL PUBLIC LICENSE' not in public['LICENSE']:
        raise ValueError('Public source is missing its Hub, project licence or release notices')
    files = {name: data for name, data in public.items() if re.fullmatch(r'hub/orion_hub/[a-z_]+\.py', name)}
    files.update({name: public[name] for name in ('hub/requirements.txt', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'docs/SERVER_RELEASE.md')})
    files['install.py'] = public['hub/orion_hub/server_install.py']
    files['SOURCE.json'] = (json.dumps(source, sort_keys=True, indent=2) + '\n').encode()
    return write_archive(output, release, files, source=source)


def build(root, output, release):
    """Legacy private preview API; public releases must use build_public instead."""
    import re
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}", release): raise ValueError("Invalid release")
    files = {"hub/requirements.txt": root / "hub/requirements.txt",
             "install.py": root / "hub/orion_hub/server_install.py"}
    files.update({"hub/orion_hub/" + path.name: path for path in sorted((root / "hub/orion_hub").glob("*.py"))})
    return write_archive(output, release, {name: path.read_bytes() for name, path in files.items()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True)
    parser.add_argument("--output", type=Path, default=Path("dist/orion-server.tar.gz"))
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--source-commit', help='Exact HEAD of the clean reviewed public Git checkout')
    parser.add_argument('--local-snapshot', action='store_true', help='Record export receipt identity without claiming a public commit')
    parser.add_argument('--private-preview', action='store_true', help='Legacy private source preview; never an official public artifact')
    parser.add_argument('--verify', action='store_true', help='Verify --output archive without building')
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify_archive(args.output), indent=2))
    else:
        if args.private_preview and (args.source_commit or args.local_snapshot):
            parser.error('Private preview cannot claim public source metadata')
        digest = (build(args.source_root, args.output, args.release) if args.private_preview else
                  build_public(args.source_root, args.output, args.release, args.source_commit, local_snapshot=args.local_snapshot))
        print(f"Server source package created; SHA256 {digest}")
