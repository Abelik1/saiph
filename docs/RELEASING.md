# Preparing a Saiph release

CI builds are unsigned development artifacts. A public release needs a reviewed
source commit, successful Windows and Linux native builds, synthetic pairing and
upgrade checks and complete third-party notices/source obligations. Until Windows
signing is accepted, the Windows installer ships unsigned and says so; do not label
a build signed until verification succeeds.

## Publishing a release

Every download is free on the project's GitHub releases; the website's Download
buttons point at the latest one. Saiph Cloud is chosen and paid for inside the
apps and on the account site, never by gating the installers.

1. On GitHub, run **Actions → Public release** on `main` with the new version and
   build number. Leave **sign** off until SignPath is configured. The repository
   variable `SAIPH_HOSTED_CONFIG` must hold the five public Saiph Cloud settings so
   the apps offer Saiph Cloud. It builds and tests Windows, Linux and the
   self-hosted Hub from that commit and opens a draft release with the exact source,
   build evidence and `SHA256SUMS`.
2. Build the Android APK from the same commit with
   `scripts/android/build-release.ps1`.
3. Check, then publish:

   ```text
   python scripts/public-release/finish-release.py --tag vVERSION --android-apk PATH\TO\Saiph-VERSION.apk
   python scripts/public-release/finish-release.py --tag vVERSION --android-apk PATH\TO\Saiph-VERSION.apk --publish --work build/finish-vVERSION-publish
   ```

   The first command is a dry run. The second uploads the APK and the complete
   checksums, publishes the release and updates `website/landing-settings.json`.
4. Commit that settings change and deploy the website.

Run the [native evidence check](RELEASE_REVIEW.md) on each final package, with
retained matching source and package-bound review results. Missing notices,
changed bytes and incomplete source/replacement review must block distribution.

## Electron Link packages

Install both locked npm projects (`frontend/`, `desktop/`) before building.
Link defaults to Electron plus `resources/service/SaiphService.exe`; explicit
`--shell qt` remains for legacy comparisons and the external Workspace build.
Use a clean build environment with `[hosted]` and PyInstaller. The service must
contain no PySide/Qt modules; package audits enforce this. See
[desktop build commands](../desktop/README.md).

The existing SignPath application configuration must cover both `Saiph.exe` and
`resources/service/SaiphService.exe`, with the same approved publisher identity,
before an Electron release can be signed. The bundle checker requires signatures
on both project executables and rejects changes to other files. The final Windows
signature verifier accepts `--service` and the workflow supplies it. No signing
configuration, certificate, service or deployed release was changed by this migration.

## Windows

Signing is not configured. The maintainer must obtain an approved signing service
or certificate, retain control over release approval, and keep signing credentials
out of source, build archives and untrusted pull-request jobs. SignPath Foundation
is the chosen provider; acceptance is not assured. The `Public release` workflow
with **sign** on implements the order below and refuses to run until SignPath is
configured; see the [code signing policy](CODE_SIGNING.md#release-workflow).

Use an isolated release workflow with protected-environment manual approval on
the exact reviewed public source revision. Build using the committed scripts,
sign the project-authored executable and installer, and retain upstream signatures
on dependencies. For SignPath, bind signing requests to the CI artifact's verified
origin and approved artifact policy. Never sign arbitrary contributor uploads.
The native builder and installer generator set product metadata to Saiph with the
same semantic product version; numeric Windows file versions include the build
number (all four components must fit 0–65535). The project executable is
`Saiph.exe`. The packager adds `OrionMini.exe`, a byte copy of the signed
`Saiph.exe`, because updaters installed before the rename (0.1.0-beta.4 and
older) relaunch that name. Keep the copy until no supported install predates
the rename; removing it breaks in-app updates from those installs.

Sign the project executable **before** packaging: `package-manifest.json` hashes
the bundled executable. Then package the signed executable, and sign the completed
installer **after** its payload is appended. Signing either file later changes its
bytes and invalidates previously recorded hashes. Retain upstream dependency
signatures. A provider integration must support this order and verify build origin
for both requests; today's unsigned CI is not a signing workflow. The installer
reads its payload from just before the Authenticode certificate table, and the
builder 8-byte aligns it so signing inserts no padding; append nothing after signing.

After signing, verify the installer and installed project executable with
PowerShell `Get-AuthenticodeSignature` (status `Valid`, expected publisher and
timestamp), and verify with Windows SDK SignTool `signtool verify /pa /all /v`.
The verification helper performs both checks, requires an embedded signature and
timestamp, pins the approved publisher/certificate and checks Saiph product/version
metadata. Run it against the final installer and its matching packaged executable:

```text
python scripts/public-release/verify-windows-signatures.py --installer release-artifacts/Saiph-Link-VERSION-windows-x86_64.exe --executable build/ci-distribution/package-VERSION-windows-x86_64/app/Saiph.exe --publisher "APPROVED_CERTIFICATE_SUBJECT" --certificate-sha256 APPROVED_LOWERCASE_CERTIFICATE_SHA256 --version VERSION --output release-artifacts/windows-signatures.json
```

Obtain the expected certificate values through the signing provider's approved
policy, independently of the binary being verified. The helper rejects unsigned,
wrong-publisher, stale-version and untimestamped files and SignTool warnings.
It never signs files. See the [code signing policy](CODE_SIGNING.md).
Install on a clean Windows machine; signing alone does not guarantee SmartScreen
reputation or remove all warnings. Record actual results, not expected results.

## Android

The current Android release is built from the Sefirah fork in `android/` in this repository.
Use the existing approved release key, with encrypted offline backups. Never
commit it or generate a replacement key for an update. Verify APK signer identity
with Android SDK `apksigner verify --verbose --print-certs`, compare to the previous
official release, and test update installation preserves pairing and data.
Independent beta tester builds distributed through Firebase App Distribution follow
[Android beta testing](ANDROID_BETA_TESTING.md) and `scripts/android/build-tester-apk.ps1`.

## Checksums and corresponding source

Assemble final signed artifacts in one directory, then run:

```text
python scripts/public-release/release-checksums.py release-artifacts --source-commit FULL_PUBLIC_COMMIT_ID
python scripts/public-release/release-checksums.py release-artifacts --source-commit FULL_PUBLIC_COMMIT_ID --verify
```

Ship `SHA256SUMS` and `release-source.json` with the binaries and corresponding
source from that exact public commit, including SDK and upstream notices. The
private monorepo commit must not be substituted for the public source commit.
Include the Windows signature receipt in the artifact directory before generating
checksums. Run the read-only verification again immediately before uploading;
it rejects extra files, changed bytes, changed source IDs and modified checksums.
Checksums detect changed bytes; they do not authenticate a publisher by themselves.

## Public repository setup

Enable private vulnerability reporting and ensure maintainers receive security
notifications. Require the DCO sign-off check before accepting outside
contributions. Require tests, native
builds, secret scanning and dependency audits in branch protection. Restrict
release/tag writes, require 2FA, review changes to workflows and signing scripts,
and configure only public download URLs after signed release artifacts exist.
