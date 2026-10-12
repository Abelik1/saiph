# Preparing a Saiph release

CI builds are unsigned development artifacts. A public release needs a reviewed
source commit, successful Windows and Linux native builds, synthetic pairing and
upgrade checks, complete third-party notices/source obligations, and the platform
signatures below. Do not label a build signed until verification succeeds.

Run the [native evidence check](RELEASE_REVIEW.md) on each final package, with
retained matching source and package-bound review results. Missing notices,
changed bytes and incomplete source/replacement review must block distribution.

## Windows

Signing is not configured. The maintainer must obtain an approved signing service
or certificate, retain control over release approval, and keep signing credentials
out of source, build archives and untrusted pull-request jobs. SignPath Foundation
is the chosen provider; acceptance is not assured. The `Signed Windows release`
workflow implements the order below and refuses to run until SignPath is
configured; see the [code signing policy](CODE_SIGNING.md#release-workflow).

Use an isolated release workflow with protected-environment manual approval on
the exact reviewed public source revision. Build using the committed scripts,
sign the project-authored executable and installer, and retain upstream signatures
on dependencies. For SignPath, bind signing requests to the CI artifact's verified
origin and approved artifact policy. Never sign arbitrary contributor uploads.
The native builder and installer generator set product metadata to Saiph with the
same semantic product version; numeric Windows file versions include the build
number (all four components must fit 0â€“65535). Do not change the compatibility
filename `OrionMini.exe`.

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
python scripts/public-release/verify-windows-signatures.py --installer release-artifacts/Saiph-Link-VERSION-windows-x86_64.exe --executable build/ci-distribution/package-VERSION-windows-x86_64/app/OrionMini.exe --publisher "APPROVED_CERTIFICATE_SUBJECT" --certificate-sha256 APPROVED_LOWERCASE_CERTIFICATE_SHA256 --version VERSION --output release-artifacts/windows-signatures.json
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
