# SPDX-License-Identifier: AGPL-3.0-or-later
"""Retain official, hash-verified corresponding Qt source and notice evidence.

Run deliberately on a release build machine, never during an installation.
No credentials, live user profiles or application configuration are accessed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile
import urllib.request


def retain(version, output, notices):
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('An exact stable Qt version is required')
    output.mkdir(parents=True, exist_ok=True)
    notices.mkdir(parents=True, exist_ok=True)
    archives = []
    major_minor = '.'.join(version.split('.')[:2])
    modules = ('qtbase','qtdeclarative','qtwebengine','qtwebchannel','qtpositioning','qtshadertools','qtsvg')
    urls = [f'https://download.qt.io/archive/qt/{major_minor}/{version}/submodules/{module}-everywhere-src-{version}.tar.xz' for module in modules]
    urls.append(f'https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{version}-src/pyside-setup-everywhere-src-{version}.tar.xz')
    for url in urls:
        with urllib.request.urlopen(url + '.mirrorlist', timeout=60) as response:
            listing = response.read().decode('utf-8')
        match = re.search(r'SHA-256 Hash.*?<tt>([0-9a-f]{64})</tt>', listing)
        if not match: raise ValueError('Official upstream SHA-256 is missing')
        expected = match.group(1)
        archive = output / url.rsplit('/',1)[1]
        if not archive.exists():
            temporary = archive.with_suffix(archive.suffix + '.partial')
            try:
                digest = hashlib.sha256()
                with urllib.request.urlopen(url, timeout=120) as source, temporary.open('xb') as destination:
                    while block := source.read(1024 * 1024):
                        digest.update(block); destination.write(block)
                if digest.hexdigest() != expected: raise ValueError('Official source archive integrity check failed')
                temporary.replace(archive)
            finally:
                temporary.unlink(missing_ok=True)
        with archive.open('rb') as source:
            digest = hashlib.sha256()
            while block := source.read(1024 * 1024): digest.update(block)
        if digest.hexdigest() != expected: raise ValueError('Retained archive integrity check failed')
        # Read archive members without extracting paths or executing build code.
        notice_file = notices / (archive.name.removesuffix('.tar.xz') + '-ATTRIBUTIONS.txt')
        count = 0
        with tarfile.open(archive, 'r:xz') as source, notice_file.open('w',encoding='utf-8') as destination:
            for member in source:
                name = Path(member.name).name.lower()
                if not member.isfile() or member.size > 8 * 1024**2: continue
                if not (name.startswith(('license','licence','copying','notice','copyright')) or name.endswith(('.license','.licence')) or name == 'readme.chromium'): continue
                stream = source.extractfile(member)
                if stream is None: continue
                raw = stream.read()
                if b'\x00' in raw: continue
                destination.write('\n===== ' + member.name + ' =====\n')
                destination.write(raw.decode('utf-8',errors='replace')); destination.write('\n')
                count += 1
        archives.append({'archive':archive.name,'url':url,'sha256':expected,'bytes':archive.stat().st_size,'attribution_file':notice_file.name,'attribution_entries':count})
        print(json.dumps({'archive':archive.name,'verified':True,'attribution_entries':count}), flush=True)
        # Publish evidence after each archive; partial progress is explicit.
        (notices / 'RETAINED_SOURCE.txt').write_text(json.dumps({'version':version,'archives':archives,'complete':len(archives)==len(urls),'build_provenance':'Official source archive hashes do not establish wheel build options or interface-compatible replacement verification.'},indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',required=True)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--notices',required=True,type=Path)
    args = parser.parse_args()
    retain(args.version,args.output,args.notices)
