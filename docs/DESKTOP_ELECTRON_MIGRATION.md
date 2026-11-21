# Electron desktop migration

Status: Link implementation converted to Electron on 2026-10-20. Source launch,
all shared Link operations, native shell adapters, binary media, detached viewer,
Qt-free service packaging and compatibility installer paths are implemented.
The external private Workspace code remains on its explicit Qt build path.
[Desktop instructions](../desktop/README.md) and [release evidence](RELEASE_STATUS.md)
distinguish local checks from release acceptance. No owner installation or live
account/device operation is implied.

Replace Saiph's Qt desktop shell with Electron while retaining the React design
and Python device/service implementation. The purpose is to resolve persistent
visible rendering corruption and simplify the presentation path. Electron is the
chosen destination; successful visible testing is required before release.

This document is the implementation brief for an architectural change. Implementation in this repository does
not authorize operating an installed application,
real account, physical device, signing service or production infrastructure.

## Scope and architecture

Implement and verify the complete Link shell on Windows x86_64. Preserve Linux
x86_64 support and require its parity before replacing the current desktop release.
macOS and a Python-to-TypeScript backend rewrite are separate projects.

```text
Existing React dashboard and design
               |
     narrow, typed preload API
               |
Electron main process: windows, tray, dialogs, OS integration
               |
     private child-process IPC
               |
Python service process: LinkWorkspace, storage, phone/Hub/Cloud services
```

Electron owns all desktop windows in the completed Link migration, including the
separate phone-screen window. Python owns application state, network protocols,
pairing, cryptography and the existing local reporting API. Expensive work stays
off Electron's main thread. Do not embed Qt WebEngine inside Electron.

Retain React components, CSS, assets and navigation in `frontend/`. Replace the
transport behind `frontend/src/workspace/client.ts` while preserving the `Client`
interface in `types.ts` and its event/unsubscribe behaviour. Render the production
frontend with synthetic data first; never silently substitute fixtures if a real
service connection fails.

## Current responsibilities that must move

| Current code | Migration responsibility |
| --- | --- |
| `src/orion_mini/app.py` | Separate service startup, timers, job processing and shutdown from window/tray/dialog ownership. Preserve command-line launch and second-instance forwarding. |
| `desktop_bridge.py` | Extract finite validated service operations; move dialogs, clipboard, drag-and-drop and other shell actions into Electron adapters. Preserve state revisions and read-only event behaviour. |
| `link_service.py`, `link_operations.py` | Reuse Link services and existing operation validation. Audit callbacks that currently assume a Qt window or event loop. |
| `dashboard_view.py`, `widget_view.py`, `rendering.py` | Retire from the completed Electron Link shell after acceptance; retain during comparison. |
| `frame_feed.py`, `camera_session.py` | Preserve memory-only camera/screen frame delivery and native camera output; replace Qt-dependent image handling where required. |
| `phone_screen_window.py` | Recreate the detached viewer in an Electron window; retain tested rotation, coordinate mapping, input, geometry and session behaviour. |
| `clipboard.py`, `hosted_clipboard.py`, `platform.py` | Separate platform integration from transport. Preserve clipboard consent, formats, feedback-loop suppression and Linux platform limitations. |
| `startup.py`, `taskbar_badge.py`, `user_presence.py` | Preserve startup opt-out, shortcut/taskbar identity, unread badge and OS owner verification with the new window handle. |
| `update_schedule.py`, `package_updates.py` | Reuse the existing update source, verification, state machine and installer handoff. Replace only shell scheduling and lifecycle coupling. |
| `scripts/build-native.py`, `scripts/packaging/`, native installer sources | Bundle Electron plus a Python service executable and audit the complete package. |
| `scripts/desktop-ui.py`, `scripts/desktop-ui.cjs`, `tests/packaging/` | Extend the established isolated-session workflow to drive the actual Electron shell and native bridge. |

These responsibilities are implemented by the Electron main/preload, shared
DesktopActions, ElectronRuntime, native ProfileLock and Pillow image adapters.
The Link package excludes Qt; the legacy comparison code is retained explicitly.

## Compatibility requirements

- Keep internal Orion identifiers and the existing data-directory resolver in
  `paths.py`, including `ORION_MINI_DATA_DIR`. Electron's default `userData`
  directory must not become a replacement application database or identity store.
  Put browser caches/session data in an explicitly chosen separate subdirectory.
- Preserve `OrionMini.Desktop`, supported executable names and legacy
  `OrionMini(.exe)` compatibility entrypoints, install roots, archive/manifest
  contracts, startup entries, file associations and Linux desktop-file identity.
  Existing packaging uses byte-identical executable compatibility copies; test
  that Electron resolves its resources correctly through both entrypoint names.
- Keep pairing keys, trust decisions, revocation, data formats, Downloads paths,
  account sign-in and native owner verification. A renderer-provided boolean
  must never stand in for Windows Hello or another existing consent check.
- Preserve the database integrity check before opening the profile and preserve
  failed databases as the current app does. No migration-driven schema change is
  needed; avoid one so rollback remains practical.
- Enforce one service owner per profile across Qt and Electron. Electron's own
  single-instance lock is insufficient for mixed versions. Prove compatibility
  with the existing `app.lock` before any database or listener is opened.
- Preserve invitation opening, Send to/file arguments, pinned-phone-app launches,
  restart waits and forwarding to an already running instance. Never allow the
  backend and shell to bootstrap duplicate network services.
- Keep the stable `SaiphNetwork.exe` relay path, camera registration contracts
  and existing helper executables. Check executable-path assumptions in native
  audio, webcam, firewall and installer integration.
- Keep the SDK MIT, Android GPL and app/Hub AGPL boundaries and upstream credits.
  Include Electron/Chromium/Node/Python and remaining native dependency notices.
- Keep private Workspace implementation outside this repository and Link bundles.
  The current add-on supplies a Qt `MainWindow` subclass, so it cannot be claimed
  compatible with Electron automatically. Specify a versioned public extension
  interface; keep the existing Workspace build path until its separate owner
  migrates it. Test this boundary using synthetic delegates only.

## Process and bridge contract

Create `desktop/` for the Electron TypeScript main/preload code and its own npm
lockfile. Add a separate Python service entrypoint; do not launch `app.py` in a
hidden window as the final service architecture. Use Python 3.12 and Node 24 for
repository build tooling, as required by `CONTRIBUTING.md`; Electron's embedded
Node version follows the selected Electron release.

Use a supported stable Electron release, pinned exactly with a lockfile when
implementation starts. Confirm its Windows/Linux baseline and schedule runtime
security updates. Do not choose a historical major from an example project.

The control connection is a child process's inherited stdin/stdout pipes, with
versioned JSON-line requests, responses and events. No new localhost control
server is necessary. Existing reporting/sign-in/network listeners retain their
existing authorization boundaries.

- Handshake includes protocol version, service readiness and capability version.
  Incompatible versions fail visibly before operations can run.
- Validate allowed method, argument schema, trusted sending window/frame and
  message size. Preserve request IDs, cancellation where supported, timeouts,
  structured errors and subscription cleanup. Bound queues and concurrent work;
  serialize stateful operations as required by existing services.
- Keep stdout exclusively for protocol messages; route redacted diagnostics to
  stderr. Handle partial reads, Unicode, malformed messages, backpressure and EOF.
  Establish a measured control-message limit in the extraction phase that accepts
  existing large state snapshots without allowing unbounded input.
- Fail pending operations on service exit. Do not automatically replay messages,
  file sends, approvals or other mutations after a crash. Offer controlled recovery
  after service cleanup and profile ownership are established.
- Electron owns the child's lifecycle. Parent loss stops the service and its owned
  helpers; bounded graceful shutdown releases devices, listeners and locks. Test
  forced termination on Windows and Linux as well as normal quit/update/restart.
- Keep keys, enrollment secrets and account tokens in the existing backend stores.
  Do not log IPC payloads containing personal content or move secrets into browser
  storage as part of the migration.

Serve bundled frontend assets from a restricted custom application protocol.
Enable renderer sandboxing, context isolation and web security; disable Node
integration. Expose the finite Saiph API through preload, without raw Electron
IPC, arbitrary filesystem access or arbitrary process execution. Use restrictive
CSP, reject unexpected navigation/popups and handle validated external URLs through
the OS browser. Native file pickers authorize paths; renderer path strings alone
must not bypass existing picker/operation checks.

Keep JPEG/media bytes out of JSON/base64 control messages. Prototype a separate
bounded binary pipe or user-scoped local IPC stream between Python and Electron
for latest-frame delivery; prove framing, authorization and throughput before
settling its platform adapters. Serve frames through a restricted `saiph-frame:`
handler with session/source/sequence checks, no-store responses and memory-only
buffers. Retain only the latest pending preview frame under load. File transfers
continue through existing services, not through this preview channel. Authorize
the detached phone viewer separately and restrict it to its session's operations.

## Delivery stages and exit checks

Each stage is a reviewable change. Keep the Qt release path working until the
replacement satisfies the final gates; prototype runs always use fresh profiles.

| Stage | Deliverable | Required exit evidence |
| --- | --- | --- |
| 0. Baseline and inventory | Synthetic screen/state catalogue, bridge method inventory with ownership and consent rules, launch/identity inventory, repeatable rendering/performance scenarios. | Record actual current failures and baseline metrics. Include onboarding, Phone, Messages, Photos, Apps, Cloud, Settings, overlays, errors and detached viewer. Identify what can only be checked with separately authorized live scope. |
| 1. Electron rendering proof | Packaged local React frontend in an actual sandboxed Electron window, synthetic bridge, test-session driver and screenshots. | Existing design/navigation preserved. Repeated visible Windows stress passes; measure idle/drag CPU and process-tree memory. Make no backend/device-completeness claim. |
| 2. Python service extraction | Qt-independent service entrypoint and control protocol; first real synthetic state/settings flow through Electron. | Handshake/error/crash/lock tests, revision-aware state, persistence after restart, integrity-check failure handling and cross-shell single-profile exclusion. Existing service suites remain meaningful and passing, with existing failures recorded separately. |
| 3. Desktop feature parity | Native Electron adapters, background lifecycles, phone features, binary previews and detached viewer. | Complete method inventory has an implementation, contract check and end-to-end scenario. No silent no-op or fixture fallback. Test native dialogs/clipboard/drop/tray/startup/badges and allowed/denied owner verification paths. |
| 4. Distribution and Linux parity | Frozen Python service plus Electron folder, current installer wrappers/manifests/update flow, native builds and CI. | Synthetic old-to-new upgrade, preserved identity/data/keys, legacy entrypoint launch, mixed-version exclusion, complete shutdown, rollback and uninstall behaviour. Linux build and actual Electron-shell checks on the target OS. Complete dependency/notices inventory. |
| 5. Acceptance and release switch | Evidence report and release candidate. | Visible rendering gates, platform feature acceptance, authorized physical/account tests and bridge/security review. Then change the default entrypoint and remove Qt from the Link shipping bundle; document remaining private-add-on differences. |

Do not spend the first stage recreating UI components from screenshots. Capture
screenshots automatically with synthetic content as visual references and compare
the existing components in the two hosts. Distinguish normal font rasterization
differences from missing content, layout regressions and corruption.

## Verification and rendering acceptance

Extend `scripts/desktop-ui.py` and `scripts/desktop-ui.cjs` with an explicit shell
choice rather than introducing an unrelated test workflow. Keep their fresh
session/profile contract and existing Qt mode for comparisons. Electron tests
must exercise Electron's actual main/preload/Python connection; a Vite browser
preview is not native-shell evidence. Adapt existing smoke scenarios rather than
discarding them. No production debug port; test automation is explicitly scoped
to its disposable session.

Automate tab/button/form/screenshot interactions. Continue using the current
desktop scripts for the Qt baseline. Do not require the user to click through
routine UI checks. OS verification and external sign-in may still need the user
inside a separately authorized live test.

Proposed visible release gates, recorded per build, OS, display scale and GPU:

1. Zero detected broken frames and zero observed blank/pixelated regions in three
   10-minute normal-use runs and three 90-second runs of the existing 3x stress
   scenario adapted for Electron. Validate the detector with injected missing
   content and capture both browser output and OS-presented frames. A successful
   run is evidence for that configuration, not proof for all hardware.
2. Drag, resize, maximize/restore, minimize/tray/show and repeated tab changes;
   mixed-DPI monitor movement, display reconnection and sleep/wake where hardware
   permits. Include dropdown placement, context menus, keyboard/IME, focus,
   accessibility and reduced motion. Record unavailable configurations explicitly.
3. A 30-minute synthetic camera/screen run with realistic JPEG dimensions/rate,
   rotation/input checks and concurrent state updates. Record received/shown/dropped
   frames, responsiveness, process-tree CPU and memory; verify buffers stay bounded.
4. Record idle, hidden and active resource costs for both shells on the same
   fixtures, machine and capture settings. Establish numeric CPU/responsiveness
   budgets from stage 0 before stage 1 sign-off; document the measured browser
   memory tradeoff. Hidden windows stop preview work and avoid unnecessary state
   snapshots while required network/background services continue.
5. Functional checks cover pending requests during crash/restart, repeated window
   creation, service disconnect/reconnect, update interruption and denied consent.
   Renderer reload must not start another backend or duplicate subscriptions.

Run affected Python unit/service tests, frontend unit/type/build checks, Electron
IPC/lifecycle tests and real-shell smoke flows with isolated profiles/caches.
Update `.github/workflows/public-ci.yml` for the Electron and service artifacts on
Windows/Linux. Headless/offscreen success must remain separate from visible GPU
acceptance. The known native-notices inventory precondition and any new failures
must be recorded accurately; do not relabel prior Qt checks as Electron results.

## Packaging, upgrade and rollback

Use Electron Packager to produce the platform application folder and PyInstaller
to freeze the Qt-independent Python service. Keep the service outside ASAR so it
can execute; resolve only packaged absolute paths and never an ambient `python`
from PATH in production. Audit Linux executable modes, Electron helper/sandbox
permissions, symlinks and native libraries instead of applying PyInstaller-only
assumptions to the new runtime. Preserve sandboxing during tests and distribution.

Keep the existing installer/update format unless a demonstrated incompatibility
requires a separately reviewed transition. Do not enable a second automatic
updater. Electron's built-in updater has no Linux support and is not a drop-in
replacement for Saiph's current release verification and per-source update flow.

An early packaging test must prove that an old Qt version can validate and stage
the Electron distribution and find its compatibility entrypoint. Test the current
release and the oldest explicitly supported updater contract. On Windows, shut
down Python and owned helpers before replacing files; on both platforms preserve
the established installer handoff and relaunch semantics.

Rollback means an explicit compatible installer transition to the retained prior
build with the same profile, not bypassing version/security checks. Test against a
synthetic paired profile and fake credentials. Keep application schemas unchanged
for this migration; any unavoidable transformation requires a separate recovery
design and tests. Require signed-release identity continuity and clean install,
upgrade, rollback and uninstall acceptance before production rollout.

## Implementation and acceptance record (2026-10-20)

The repository implementation now covers the full public Link desktop: native
shell, shared operation dispatch, real service startup/shutdown, source and
packaged launch, owner-verification HWND, dialogs, clipboard, notifications,
tray/badges, startup/update identity, drag and drop, media and detached viewer.
QtCore was removed from the service; a native cross-shell lock is tested in both
directions. Pillow replaces Qt image decoding and applies EXIF for clipboard and
original-photo copy/drag. A clean Windows package is audited without Qt or private
Workspace modules and without unmatched native bytes. The existing installer and
old executable alias were exercised in a disposable legacy-upgrade fixture.

Control protocol is version 1, capability 2. Requests are limited to 64 KiB,
responses to 32 MiB, with 16 main-process pending requests and 32 service slots.
Binary payloads are limited to 64 MiB (preview frames 8 MiB, clipboard input 16 MiB),
headers to 4096 bytes, with eight queued transfer keys and latest-only preview
replacement. Authenticated publish/receive connections share a random private
named-pipe/Unix-socket address. Windows needs separate synchronous handles so an
idle read cannot block frame publication.

Exact Electron 44.9.0 and packager 20.3.0 are npm-locked. Linux remains an actual
Linux build/CI target; this Windows workstation does not establish its execution
or sandbox acceptance. Native installer/signing compatibility is retained; the
SignPath application policy must include the new service executable before any
signed Electron release. No signing or operations configuration was changed.

Implementation completion is separate from the proposed release gates above.
Outstanding acceptance includes long-duration media/GPU and resource baselines,
mixed-DPI/sleep/display scenarios, actual Linux execution, authorized real-device
and account flows, clean-machine installation, signing, licence/source review and
independent security review. The external private Workspace add-on still uses its
separate Qt contract; its implementation is absent from this public repository.
A future Electron add-on API requires coordination with that separate owner.

See [release status](RELEASE_STATUS.md) for exact checks, failures corrected or
rerun, saved Windows frame candidates and limits. Do not infer that the original
rendering complaint is conclusively fixed on all hardware from these checks.

Official references consulted 2026-10-19:

- [Electron process model](https://www.electronjs.org/docs/latest/tutorial/process-model)
- [Electron security guidance](https://www.electronjs.org/docs/latest/tutorial/security)
- [Custom protocols](https://www.electronjs.org/docs/latest/api/protocol)
- [Updater platform limitations](https://www.electronjs.org/docs/latest/api/auto-updater)

Repository references: `docs/DESKTOP_PERFORMANCE.md`, `docs/ARCHITECTURE.md`,
`docs/TESTING.md`, `docs/RELEASE_STATUS.md`, `docs/ORION_DESKTOP_DISTRIBUTION.md`
and `CONTRIBUTING.md`.
