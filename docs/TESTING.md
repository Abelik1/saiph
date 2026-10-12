# Testing the public edition

Use synthetic text, files and accounts. Never copy a production data directory
or enrollment invitation into a fixture. Report unit, native, container and
physical-device checks separately.

Desktop development uses Python 3.12 and Node 24. After installing dependencies
as described in [CONTRIBUTING.md](../CONTRIBUTING.md), run:

```text
python scripts/public-release/verify-public.py
npm --prefix frontend run test:unit
python scripts/build-native.py --profile link --version 0.1.0-beta.1
```

Push and pull-request CI run unit suites on Windows and Linux. Explicit
workflow dispatch additionally builds and wraps the native bundle with its
package auditor; a green push check alone does not establish packaging success. Linux needs Qt/WebEngine runtime libraries and an
appropriate display environment; consult `.github/workflows/public-ci.yml`.
Do not label a Windows-built executable as a Linux build.

Hosted Hub tests use a separate Python 3.12 environment:

```sh
python -m pip install -r hub/requirements-hosted.txt pytest httpx
PYTHONPATH=hub python -m pytest hub/tests -q
```

On PowerShell, set `$env:PYTHONPATH='hub'` before running pytest. Account tokens
and live servers are not required for the normal synthetic suite. Real-provider
sign-in checks require separately authorized development configuration.

Before a release, verify clean installation, upgrade from the previous official
release, retained pairing and startup opt-out, uninstall preserving user data,
and representative phone operations on actual supported devices. A frozen build,
isolated fixture or successful unit suite does not establish those results.

## Attended automation

The desktop's local API can run a small allowlist of the app's own actions
(`state`, photo save/prefetch, file send and notification commands) through
`POST /v1/app/call`. It is off unless `automation.json` in the data folder
contains `{"enabled": true}`, is re-read on every call, never reaches SMS,
calls, settings or pairing, and cannot be triggered by offline inbox replay.
`POST /v1/app/restart` relaunches the same build. Both need the live API token.

```text
python scripts/desktop-call.py state --temporary-enable --summary
python scripts/restart-desktop.py
python scripts/acceptance-phone-pad/build.py --help
python scripts/acceptance-laptop-phone.py --help
```

`--temporary-enable` creates the opt-in only for that call and removes it
afterwards; an existing disabled setting is preserved. The laptop/phone harness
drives a disposable native Qt editor and a separately built acceptance pad APK
with synthetic fixtures over authorized USB debugging. Coordinate with the
device owner first. Its results are attended physical evidence, kept privately,
not unit-test results.

Public CI also scans source/history with gitleaks and audits Python/frontend
dependencies. Review findings and fix affected dependencies; never suppress an
entire file because it contains one synthetic fixture. Signing and final source
metadata are covered in [RELEASING.md](RELEASING.md).
