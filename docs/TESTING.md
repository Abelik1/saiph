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

## Desktop UI control

Agents can drive the real Qt desktop directly: switch tabs, click buttons, type
into forms, use keyboard shortcuts and capture screenshots. Use these tools for
routine desktop testing instead of asking the user to click or enter details.
This uses the production dashboard, native QWebChannel and actual LinkWorkspace;
it is separate from the browser-only synthetic previews.

Build the frontend and install the desktop dependencies in an isolated Python
3.12 environment first. No Playwright browser download is needed: Qt supplies
the Chromium instance. Launch a disposable test instance (the session directory
must be new):

```text
python scripts/desktop-ui.py --session build/desktop-ui/my-test --dashboard frontend/dist/index.html
```

The launcher stays running and prints the path to `session.json` when the
dashboard loads. Run it in a managed background process or exec session while
issuing controller commands in another process. On Windows, background helpers
should use a hidden process window. Keep the printed session path for subsequent
commands; do not attach to arbitrary debug ports or discover an owner's window.

```text
node scripts/desktop-ui.cjs --session build/desktop-ui/my-test/session.json snapshot
node scripts/desktop-ui.cjs --session build/desktop-ui/my-test/session.json click --role button --name Settings
node scripts/desktop-ui.cjs --session build/desktop-ui/my-test/session.json click --role tab --name Connections
node scripts/desktop-ui.cjs --session build/desktop-ui/my-test/session.json click --role tab --name General
node scripts/desktop-ui.cjs --session build/desktop-ui/my-test/session.json fill --label "Computer name" --value "Test desktop"
node scripts/desktop-ui.cjs --session build/desktop-ui/my-test/session.json click --role button --name "Save this computer"
node scripts/desktop-ui.cjs --session build/desktop-ui/my-test/session.json screenshot --output test-artifacts/desktop-ui/settings.png
node scripts/desktop-ui.cjs --session build/desktop-ui/my-test/session.json stop
```

`snapshot` returns accessible names for selecting controls. Commands also cover
`check`, `uncheck`, `select --value` and `press --key`. For multi-step assertions,
`run --script path/to/flow.cjs` loads a trusted local module exporting
`async ({page, expect, session}) => { ... }`. The reusable native smoke flow:

```text
node scripts/desktop-ui.cjs --session build/desktop-ui/my-test/session.json run --script tests/packaging/desktop_control_smoke.cjs
```

For Cloud settings and the visible weekly summary, also run
`node scripts/desktop-ui.cjs --session <session.json> run --script tests/packaging/desktop_layout_smoke.cjs`. This saves an isolated Cloud path, checks native persistence, and toggles the local summary. It does not open Explorer, install file sync or contact an account service.

The smoke flow navigates Settings, saves a synthetic name through the real native
bridge, checks the written profile, returns to Phone, exercises available setup
choices and captures screenshots/results under the session's `evidence/` folder.
It also verifies that a mismatched session cannot control the window. Source
builds without Hosted extras or packaged service defaults retain their normal
unavailable/unconfigured account states; the harness does not fake those services.

By default the window renders offscreen and `ORION_MINI_TEST=1` disables normal
background device/account workers. A fresh data profile, Qt storage/cache and
temporary folder live inside the session directory. The launcher does not copy
owner data, install an app, restart an installed instance, or apply startup
settings. Explicit UI actions still reach real native handlers, so choose
synthetic inputs and stay within the authorized test scope. The control endpoint
binds only to `127.0.0.1`, checks a per-session window marker, and is present only
in this deliberately launched instance. The normal app has no added debug port;
the existing local API allowlist is unchanged. `stop` requests clean shutdown
of that session; it does not kill other processes. The default timeout is one hour.

For authorized real account/device tests, `--live` enables normal workers in the
fresh test profile; `--show` displays its window when a visible native test is
needed. External provider sign-in, Windows Hello and physical phone prompts can
still require the owner. Do not bypass them or treat isolated UI results as live
connection, cryptography, installation or physical-device acceptance.

For isolated frontend dependencies, set `SAIPH_UI_PLAYWRIGHT_PATH` to that copy's
`node_modules/@playwright/test` directory. Qt WebEngine needs permission to start
its renderer subprocesses; if an execution sandbox blocks this, request scoped
permission for the isolated launch rather than turning off Chromium's sandbox.
Implementation references: [Qt remote debugging](https://doc.qt.io/qt-6/qtwebengine-debugging.html)
and [Playwright CDP connections](https://playwright.dev/docs/api/class-browsertype#browser-type-connect-over-cdp).

## Attended physical automation

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

## Android protected connection regression

On a fresh disposable emulator, run HostedKeyStorageInstrumentedTest through
AndroidJUnitRunner. It uses actual Android Keystore and SQLite to create/reload a
protected recipient, build an enrollment request, verify a synthetic signed root
roster, exchange encrypted content, retain inbox/checkpoint state, restart failed
setup without losing old files or memory-only synthetic sign-in, and check that
only nested screens show Back. It does not contact an account or operate a phone.
Do not run this class in an owner profile. JVM crypto tests do not replace it.

## Android callback and Cloud photo gallery regression

In a fresh disposable emulator, run HostedCallbackInstrumentedTest and HostedPhotosInstrumentedTest. The first never exchanges a token: it validates pending state, PKCE, client/endpoints, replay/cancellation/expiry, legacy in-flight compatibility, restored pre-upgrade activity-result routing and compiled-manifest URI routing. The second writes/deletes one synthetic MediaStore image, grants only the test app photo permission, checks the separate opt-in and a bounded JPEG preview with preserved aspect ratio. It must not run on an owner phone/profile. Separately verify the distributed APK's exact signer against the live assetlinks.json and Android's actual domain verification result; never force a link approved to manufacture acceptance.

The desktop synthetic gallery tests use real sealed envelopes and streaming encryption through an in-memory relay, check unrequested/stale original rejection and one saved copy per original. No live account, personal gallery or SMS is accessed.


For the sharing follow-up, also run HostedAccountInstrumentedTest and
HostedPermissionsInstrumentedTest in that disposable emulator. The first accepts
only synthetic grants and tests actual Keystore refresh wrapping, rotation and
account recreation. The second uses real Android permission dialogs to deny photo
access and verifies the Settings fallback; it never enables gallery sharing.
The permission-dialog matcher assumes the test emulator uses English. Keep the
existing activity-result launcher registration order when adding launchers:
Android retains the old generated keys during an APK update with browser sign-in
open. The callback regression restores that old launch key using a cancelled
result, so it never contacts an identity provider.
