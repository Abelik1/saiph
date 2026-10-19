# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build the disposable offline pad with an installed SDK; no Gradle/network needed."""
import argparse
import os
import re
import subprocess
import zipfile
from pathlib import Path


def version_key(path):
    """Numeric parts of a build-tools or platform folder name: android-37.0, 36.0.0, 37.0.0-rc1."""
    return tuple(int(part) for part in re.findall(r'\d+', path.name))


def default_sdk():
    for name in ('ANDROID_HOME', 'ANDROID_SDK_ROOT'):
        if os.environ.get(name):
            return Path(os.environ[name])
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'Android' / 'Sdk'
    return Path.home() / 'Android/Sdk'


def sdk_tool(folder, name):
    """Windows ships d8 and apksigner as .bat and the others as .exe; subprocess needs the suffix."""
    if os.name == 'nt':
        for suffix in ('.exe', '.bat'):
            if (folder / (name + suffix)).is_file():
                return folder / (name + suffix)
    return folder / name


def java_tool(name):
    home = os.environ.get('JAVA_HOME')
    if home:
        candidate = sdk_tool(Path(home) / 'bin', name)
        if candidate.is_file():
            return candidate
    return name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path, default=default_sdk())
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--application-id', default='ie.orion.acceptance.pad',
                        help='Separate ie.orion.acceptance.* package for a campaign; preserves any existing helper.')
    args = parser.parse_args()
    if not re.fullmatch(r'ie\.orion\.acceptance\.[a-z][a-z0-9_]*', args.application_id):
        parser.error('Choose a package under ie.orion.acceptance with a simple lowercase suffix')
    source = Path(__file__).resolve().parent
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.application_id != 'ie.orion.acceptance.pad':
        generated = out / 'generated-source'
        generated.mkdir(exist_ok=True)
        for original in [source / 'AndroidManifest.xml', *sorted(source.glob('*.java'))]:
            (generated / original.name).write_text(original.read_text(encoding='utf-8').replace(
                'ie.orion.acceptance.pad', args.application_id), encoding='utf-8')
        source = generated
    tools = max((args.sdk / 'build-tools').iterdir(), key=version_key)
    platform = max((p for p in (args.sdk / 'platforms').glob('android-*') if (p / 'android.jar').is_file()), key=version_key) / 'android.jar'
    classes = out / 'classes'
    dex = out / 'dex'
    classes.mkdir(exist_ok=True)
    dex.mkdir(exist_ok=True)

    def run(*cmd):
        subprocess.run(list(map(str, cmd)), check=True)

    run(java_tool('javac'), '--release', '8', '-classpath', platform, '-d', classes, *sorted(source.glob('*.java')))
    run(sdk_tool(tools, 'd8'), '--min-api', '29', '--lib', platform, '--output', dex, *sorted(classes.rglob('*.class')))
    unsigned = out / 'unsigned.apk'
    run(sdk_tool(tools, 'aapt'), 'package', '-f', '-M', source / 'AndroidManifest.xml', '-I', platform, '-F', unsigned)
    with zipfile.ZipFile(unsigned, 'a') as archive:
        archive.write(dex / 'classes.dex', 'classes.dex')
    key = out / 'disposable-fixture.keystore'
    if not key.exists():
        run(java_tool('keytool'), '-genkeypair', '-keystore', key, '-storepass', 'fixture-only', '-keypass', 'fixture-only', '-alias', 'fixture', '-dname', 'CN=Disposable Offline Acceptance Fixture', '-keyalg', 'RSA', '-validity', '30')
    aligned = out / 'aligned.apk'
    run(sdk_tool(tools, 'zipalign'), '-f', '4', unsigned, aligned)
    apk = out / 'acceptance-pad.apk'
    run(sdk_tool(tools, 'apksigner'), 'sign', '--ks', key, '--ks-pass', 'pass:fixture-only', '--key-pass', 'pass:fixture-only', '--out', apk, aligned)
    run(sdk_tool(tools, 'apksigner'), 'verify', apk)
    print(apk)


if __name__ == '__main__':
    main()
