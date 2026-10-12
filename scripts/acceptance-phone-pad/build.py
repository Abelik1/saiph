# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build the disposable offline pad with an installed SDK; no Gradle/network needed."""
import argparse
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--sdk', type=Path, default=Path(os.environ.get('ANDROID_HOME', str(Path.home() / 'Android/Sdk'))))
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
source = Path(__file__).resolve().parent
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=True)
tools = sorted((args.sdk / 'build-tools').iterdir(), key=lambda p: tuple(map(int, p.name.split('.'))))[-1]
platform = sorted((args.sdk / 'platforms').glob('android-*'), key=lambda p: int(p.name.split('-')[-1]))[-1] / 'android.jar'
classes = out / 'classes'
dex = out / 'dex'
classes.mkdir(exist_ok=True)
dex.mkdir(exist_ok=True)

def run(*cmd):
    subprocess.run(list(map(str, cmd)), check=True)

run('javac', '--release', '8', '-classpath', platform, '-d', classes, *sorted(source.glob('*.java')))
run(tools / 'd8', '--min-api', '29', '--lib', platform, '--output', dex, *sorted(classes.rglob('*.class')))
unsigned = out / 'unsigned.apk'
run(tools / 'aapt', 'package', '-f', '-M', source / 'AndroidManifest.xml', '-I', platform, '-F', unsigned)
with zipfile.ZipFile(unsigned, 'a') as archive:
    archive.write(dex / 'classes.dex', 'classes.dex')
key = out / 'disposable-fixture.keystore'
if not key.exists():
    run('keytool', '-genkeypair', '-keystore', key, '-storepass', 'fixture-only', '-keypass', 'fixture-only', '-alias', 'fixture', '-dname', 'CN=Disposable Offline Acceptance Fixture', '-keyalg', 'RSA', '-validity', '30')
aligned = out / 'aligned.apk'
run(tools / 'zipalign', '-f', '4', unsigned, aligned)
apk = out / 'acceptance-pad.apk'
run(tools / 'apksigner', 'sign', '--ks', key, '--ks-pass', 'pass:fixture-only', '--key-pass', 'pass:fixture-only', '--out', apk, aligned)
run(tools / 'apksigner', 'verify', apk)
print(apk)
