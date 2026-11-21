# Electron desktop

Saiph Link now launches Electron 44.9.0 around the existing React dashboard. A
Qt-free Python 3.12 child owns LinkWorkspace, storage, device protocols, pairing,
cryptography, native owner verification and the authenticated reporting API.
Electron owns windows, tray, dialogs, notifications, clipboard, drag and drop,
startup-facing process identity and the detached phone-screen viewer.

Normal source entrypoints (`python -m orion_mini`, `orion-mini` and
`run_orion_mini.py`), the UI launcher and Link packaging default to Electron.
The external private Workspace add-on and explicit `--shell qt` comparison build
retain their old Qt contract. Link's Electron package excludes Qt and private code.
The existing design, Orion identifiers, pairing stores and installation paths stay
compatible; browser caches live under the profile's `.electron` directory.

## Development

Use Python 3.12, Node 24, an isolated Python environment and task-local caches.
Install `python -m pip install -e ".[hosted]"`; tests additionally need `[dev]`.
From the repository root in PowerShell:

```powershell
$taskDirectory = Join-Path (Get-Location) 'build/electron-local'
New-Item -ItemType Directory -Force -Path "$taskDirectory/tmp" | Out-Null
$env:TEMP = "$taskDirectory/tmp"
$env:TMP = "$taskDirectory/tmp"
$env:electron_config_cache = "$taskDirectory/electron-cache"
$env:npm_config_cache = "$taskDirectory/npm-cache"
npm --prefix desktop ci
node desktop/node_modules/electron/install.js  # Fetches Electron when npm skipped it (no desktop/node_modules/electron/path.txt)
npm --prefix frontend ci
npm --prefix desktop run build
npm --prefix frontend run build
python scripts/desktop-ui.py --fixture phone --show --session build/electron-local/session
```

The isolated session has actual Link state and synthetic phone/photo records.
It starts no device/account listeners or workers, changes no installed app,
uses memory for clipboard tests and cancels native pickers unless its scoped
fixture file supplies a test path. Synthetic media injection exists only in this
explicit mode. Each session directory must be fresh. Omit `--show` for hidden,
software-rendered checks. Keep Chromium sandboxing enabled even when a restricted
host needs permission to launch the test process outside its filesystem sandbox.

Drive the real app through the standard controller:

```text
node scripts/desktop-ui.cjs --session build/electron-local/session/session.json snapshot
node scripts/desktop-ui.cjs --session build/electron-local/session/session.json run --script tests/packaging/desktop_electron_visible.cjs
node scripts/desktop-ui.cjs --session build/electron-local/session/session.json stop
```

`python -m orion_mini` is the normal live source launch. UI-control sessions need
explicit `--live` for real services and `--existing-profile PATH` for an authorized
existing profile. Never use those modes against an owner's profile or devices
without coordination. Native OS verification and external sign-in are preserved.
Test mode alone disables background renderer throttling so automation can click
an occluded test window; normal launches retain Electron's default throttling.

## Process and security boundaries

The sandboxed renderer has no Node or raw Electron API. The self-contained preload
exposes finite requests/events. Main validates the sending window, top frame,
method syntax and message size; Python retains the shared operation validators in
`desktop_actions.py`. The phone viewer has only screen status/input/stop access.
Assets use a contained, CSP-protected custom origin. Navigation, popups, downloads
and unrequested browser permissions are refused. Only explicit UI-test launches
open a nonce-verified loopback DevTools endpoint.

Control travels over inherited JSON-line pipes (64 KiB requests, 32 MiB replies,
bounded pending requests). Media uses two authenticated binary connections to a
random Windows named pipe or private Unix socket. Separate directions avoid
Windows synchronous read/write serialization. JPEG previews retain only the newest
pending frame per source and stay in memory. Photo URLs are short-lived random
capabilities. Clipboard delivery rechecks consent/revocation immediately before
the native write and preserves the existing echo cache and image validation.

The independent native `app.lock` is compatible with QLockFile, including aged
live locks. The database integrity check precedes opening the store. EOF shuts down
services and releases ownership; failed mutations are never automatically replayed.
Electron's process identity and PID are passed to existing startup/relay/update
adapters so installers wait for the desktop, rather than only its service child.

## Native packages and checks

Create a clean build environment containing `[hosted]` and PyInstaller, without
unrelated development native libraries. Install both locked npm projects first.
Build on the actual target Windows/Linux x86_64 system:

```text
python scripts/build-native.py --profile link --version 0.1.0-electron.1 --build-number 1 --workpath build/my-electron-build --distpath build/my-electron-dist
python scripts/packaging/build-desktop-distribution.py --platform windows-x86_64 --version 0.1.0-electron.1 --bundle build/my-electron-dist/Saiph --analysis build/my-electron-build/electron/python-build/SaiphService/Analysis-00.toc --output build/my-electron-package
```

Linux uses bundle `saiph`, platform `linux-x86_64` and optional `--linux-setup`.
The existing installer format, release metadata, compatibility executable copy,
network relay, camera registration paths and user data retention remain in use.
Electron/Chromium notices and native byte provenance join the Python/frontend
inventory. Building does not install or register the camera. Use fresh output
folders; failed builds preserve their diagnostics and previous outputs.

To test the actual portable package, pass `--executable ABSOLUTE_EXE_PATH` to
`desktop-ui.py` along with a fresh isolated session. `--shell qt` explicitly
selects the retained Qt harness or build. CI includes source-shell tests on both
operating systems and native packaging on workflow dispatch.

Run `npm --prefix desktop test`, frontend unit/build/lint, and
`python scripts/public-release/verify-public.py`. Evidence and unresolved release
acceptance are recorded in `docs/RELEASE_STATUS.md`. Automated synthetic results
do not establish Linux execution on this Windows workstation, signing, physical
phone acceptance, multi-day GPU stability or independent security review.
