## 2026-10-19: Free trial of Saiph Cloud on sign-up (development, unreleased, off until configured)

Details and owner steps: [PAID_HOSTED.md](PAID_HOSTED.md#free-trial-on-sign-up). Every new
account can start one 14-day trial (no card) from the account page; an optional cap
(`SAIPH_TRIAL_CAP`, e.g. 100) is off by default. The trial is a signed `trial:` grant;
one trial per sign-in subject, per keyed hash of the verified email and per Hosted
account. Expiry pauses Cloud without deleting anything; the account page, desktop and
Android show days left or "trial ended" with Subscribe. Subscribing during the trial
keeps the free days (Stripe `trial_end`). Prices unchanged. Trials stay off until the
owner applies migration 0004, deploys the Hub and sets `SAIPH_TRIAL_SECRET`.

Checks (synthetic only; isolated venv, worktree npm cache, Docker Postgres 16, isolated
Gradle home; no Stripe call, device, account, installed app or live service):
account-web `npm test` **92 passed** (13 new trial tests), `tsc --noEmit`, `npm run
test:billing-db` **45 passed** on isolated PostgreSQL (4 new: trial rules and permanence,
racing cap, subscribers excluded, grant delivery); `hub/tests` **600 passed, 6 skipped**
(6 new); desktop `pytest tests` 1845 passed before the last fake-transport fixes, then the
affected files 391 passed, 1 failed (the known `test_native_notices` inventory
precondition); frontend `tsc -b`, `oxlint`, `vitest run` 306 passed, 2 timed out under load
and passed alone; Android `:app:testDebugUnitTest` **112 passed** (5 new) and
`:core:network:testDebugUnitTest` 134 passed. **Not done:** a real Stripe sandbox run,
deployment, device or UI acceptance of the new notices, independent security review.

## 2026-10-19: Footer Update button, six-hourly check and the desktop update routes (development, unreleased)

Details: [DESKTOP_UPDATES.md](DESKTOP_UPDATES.md#the-footer-update-button-and-the-six-hourly-check).
The desktop checks its own update source (Saiph account or paired Hub) two
minutes after start-up and every six hours, quietly, in packaged builds only.
When a newer build is offered, a glowing **Update to x.y.z** button appears in
the footer beside the version; one click checks again, downloads and verifies
exactly as Settings does, then runs the existing installer handoff and restarts.
States: none, checking, available, downloading, ready, installing, failed.
Settings → Updates and the tray's check share the same state. The glow is a
still shadow with three breaths (none under reduced motion) and no busy state
uses a spinner; idle cost is two Qt timers. The shared Hosted service now has
the `/v1/app/desktop/<platform>/release` and `/download` routes for native
account tokens, with release descriptions checked against their installers when
the service starts. **Nothing is deployed**: no service, catalog, website or
production change, and the publishing scripts that write descriptions (ops
repository) are not done, so account computers still see no update offered.
Android routes and a release signature remain proposals.

Checks (isolated venv and npm cache, synthetic fixtures; no installer run, no
device, account or installed app):

- Python 3.12 `pytest tests`: **1922 passed, 58 skipped, 1 failed** (the known
  `test_native_notices.py::test_packaged_inventory_fills_reviewed_gap_and_preserves_unknown_gap`
  inventory precondition). New: `test_update_schedule.py` (schedule, quiet
  checks, one-click flow and each failure point, Settings parity, bridge and
  snapshot) and `test_desktop_update_feed.py` (the desktop's real updater against
  the real Hosted routes in process, Windows and a real Linux `.run`).
- `pytest hub/tests`: **625 passed, 6 skipped, 1 failed**
  (`test_hosted_blobs.py::test_expiry_removes_chunks_before_download`, a timing
  test that passed 3 of 3 times alone; it does not touch these routes). New
  `test_hosted_desktop_updates.py`.
- Frontend `vitest run --maxWorkers=3`: **318 passed** (42 files;
  `UpdateButton.test.tsx` covers the button states, progress polling, finite
  glow and reduced motion, Settings following the shared state and the footer
  in the window). Default workers timed out 1 and then 5 unrelated tests under
  load (different ones each run). `tsc -b`, `oxlint` on the changed files and
  `npm run build` passed (existing large-chunk warning).
- Real Qt shell, fresh isolated offscreen session (`scripts/desktop-ui.py`):
  footer shows no button on a source build; Settings → Updates → Check for
  updates answers through the new bridge route. The glowing and busy states were
  checked in the synthetic design preview (`preview.html?update=available`, and
  the other states): 20 px button in the 28 px footer, animation ends after three
  breaths.

**Not done:** deployment and catalog publishing, an installed build updating
itself through the footer on Windows or Linux, CPU measurement on the installed
app, independent security review.

## 2026-10-19: Presentation switches for the render-glitch A/B (development, unreleased)

Details: [DESKTOP_PERFORMANCE.md](DESKTOP_PERFORMANCE.md#comparing-presentation-paths-renderingjson).
The passive watcher saw no broken frames in Chromium's own output from the installed
beta.40 (10 minutes, 4727 frames), so the remaining suspects are on the presentation
side. An optional `rendering.json` in the profile selects, at start-up, a non-flip
Direct3D swap chain, OpenGL, Qt Quick's GUI-thread render loop or the earlier widget
host; without the file nothing changes. Not a fix yet: the on-screen comparison needs
the installed app.

Checks (isolated venv; offscreen; no device, account or installed app): each choice
boots the real shell with the dashboard, bridge and hide/show; `pytest tests` 1672
passed, 58 skipped, 1 failed (the known `test_native_notices` inventory precondition)
plus one store-connection test made robust to other tests' threads (passes).

## 2026-10-19: Windows Firewall keeps allowing Saiph after updates (development, unreleased)

Details: [LAN_FILES.md](LAN_FILES.md#windows-firewall-across-updates). Windows Firewall
rules name a program path and every update installed a new versioned saiph.exe, so the
phone camera, phone screen and direct file transfers needed a fresh firewall approval
after each update (the owner's PC had allow rules only for beta.14 to beta.32). The
package now carries `SaiphNetwork.exe`, a small relay the per-user installer keeps at
one fixed path; Saiph listens on 127.0.0.1 and the relay accepts network connections,
so Windows asks once. Saiph also reads (never changes) the firewall rules and, when a
block rule applies or the Wi-Fi is Public, says so in Settings → Saiph Cloud with
**Open firewall settings**. No firewall rule or system setting was changed on any PC.

Checks (isolated venv; mocked PowerShell and process starts; the real relay compiled
with the Framework csc and run with `--bind loopback` only): `tests/test_lan_relay.py`
(26: relay discovery, start/stop, fallback to a direct listener, rule evaluation incl.
Windows' allow-Private/block-Public prompt rules, read-only script, a 3.2 MB file
through the real relay with exact SHA-256 and the relay exiting, the isolated installer
keeping the relay at one path across beta.39→41 and removing only its own copy, and the
distribution manifest entry); frontend HostedSettings notice test.

**Not done:** physical check on the owner's PC (after installing: one "Saiph local
network" prompt on first camera/file use, none after the next update); signing
`SaiphNetwork.exe` through SignPath (owner configuration); nearby-phone discovery
(UDP 47390) still listens in saiph.exe.

## 2026-10-19: Fewer, cheaper dashboard snapshots while visible (development, unreleased)

Details: [DESKTOP_PERFORMANCE.md](DESKTOP_PERFORMANCE.md#fourth-pass-main-process-work-while-visible-and-idle-beta39).
Cloud's fast poll announces a change only when something was sent, received or
expired; read-only Cloud questions the page polls no longer trigger a snapshot;
a snapshot reads the store over one SQLite connection; the Deskflow check runs on
a worker; the optional-tools scan walks PATH only when a searched folder changed
(still within ten seconds). Synthetic offscreen: snapshots 53–54 → 20 a minute,
101–168 → 34–42 ms each, main process 19–21 % → 10–12 % of a core. The render
glitch under stress is documented as open, with its stress test.

Checks (isolated venv/npm cache; no device, account or installed app): Python
`pytest tests` 1667 passed, 58 skipped, 1 failed (the known `test_native_notices`
inventory precondition); frontend `vitest run --maxWorkers=3` 267 passed
(`PhoneSetup.test.tsx` timed out once under `--maxWorkers=4` and passed alone and on
rerun), `tsc -b`, `oxlint`. **Not done:** measurement on the installed app
(checklist item 12).

## 2026-10-18: Large files directly over the local network, Saiph Cloud as fallback (development, unreleased)

Details: [LAN_FILES.md](LAN_FILES.md). A "file" session offer carries a one-use pinned-TLS
invitation through the sealed Cloud mailbox; the computer always listens, phones ask with
`file.lan.request`. Exact size and SHA-256 on both sides, 90 s resume, Save to Downloads/Saiph.
Files up to 19.9 MB fall back to Saiph Cloud on `session.refuse` or 30 s of silence; larger
ones fail saying both devices must share a network.

Checks (isolated venv, worktree npm, shared Gradle cache; no device, installed app, account or
live service): `pytest tests` **1822 passed, 58 skipped** (licence-inventory test deselected as in
earlier entries; `tests/test_lan_files.py` 47 new); `npm run build` and `vitest run` **296 passed**;
Android `:core:network:testDebugUnitTest :app:testDebugUnitTest :app:assembleBeta` passed
(**128 network (2 skipped), 107 app**; `LanFilesTest` 6); `:app:lintDebug -x :worker:lintAnalyzeDebug`
**0 errors** (the `:worker` lint task crashes inside lint, module untouched). Loopback only: a 500 MB
synthetic file with a 20 s link cut resumed and arrived exact in both directions (get and put).

**Not done:** physical acceptance on real Wi-Fi (desktop↔laptop, desktop↔phone, 20 s Wi-Fi drop,
Cloud fallback with LAN blocked), the Qt shell, and an independent security review.

## 2026-10-18: Still background, nothing refreshed while hidden (development, unreleased)

Details: [DESKTOP_PERFORMANCE.md](DESKTOP_PERFORMANCE.md#third-pass-chunks-of-the-screen-twitching-and-cpu-while-hidden-beta37).
After beta.37 the owner saw chunks of the window twitching. The still background
still curled around working buttons and rippled after them (and on setup step
changes); it is now completely still. Hidden or minimised, the web view is told it
is hidden (its timers stop) and the bridge holds change notices until the window
returns, then refreshes once: hidden CPU under 4-second synthetic churn 6.6 % → 1.0 %
(8.9 % → 1.8 % with an accessibility client). Window-wide flicker was not reproduced
in always-on-top frame captures (statistics only).

Checks (isolated venv/npm cache; no device, account or installed app): frontend
`tsc -b`, `oxlint`, `vitest run --maxWorkers=4` 267 passed, build; Python `pytest tests`
1664 passed, 58 skipped, 1 failed (the known `test_native_notices` inventory
precondition); `desktop_control_smoke.cjs` and `desktop_layout_smoke.cjs` passed.
**Not done:** physical check (checklist item 11).

## 2026-10-18: Windows update leaves the previous release's camera registered (development, unreleased)

Found on the owner's PC, twice (beta.30→31→32 and beta.32→33, installer run with
`--silent --no-launch --no-startup --no-enrollment-association`, the old app quit
first): after the update the HKCU Saiph Camera classes still named the previous
release's `SaiphCamera64/32.dll`, so the new release's `DllRegisterServer` refused
and the desktop said "Saiph Camera could not be enabled". `regsvr32 /u` with the
previous release's own DLLs cleared it. The installer exited 0 with no output.

**What is established.** The ownership logic was right: run against the real
install root's 25 manifests (read only) on a sandboxed HKCU, both the source and
the shipped beta.33 setup removed all four classes and both device entries. The
removal call was `RegistryKey.DeleteSubKeyTree(name, false)`, which opens the key
for writing (`KEY_SET_VALUE | KEY_CREATE_SUB_KEY`) and, when that open is refused,
returns without deleting anything or throwing; nothing checked afterwards. With
the camera key refusing either right, the shipped beta.33 setup left it in place
with no error, while `RegDeleteTree` (what `regsvr32 /u` runs) still removed it.
That silent skip is a real defect, but an owner-approved experiment on the real
HKCU shows it is **not** what happened on that PC: beta.32's camera registered
with its own DLLs (System32 and SysWOW64 `regsvr32`) had the usual inherited
ACLs, opened for writing, and the shipped beta.33 `UnregisterOwnedCameras`,
called by reflection outside an install, removed all four classes and both
device entries. In the field the x86 keys were made the same way and still
survived, so the difference lies in the real installer run (its process or
context), not in the keys. **The root cause is not established.** The next real
update's `setup.log` records what the cleanup saw and did (below).

**Changes.**

- `WindowsSetup.cs` deletes camera keys with only `DELETE`, enumerate and query
  rights (as `RegDeleteTree` does) and throws on any error; each class is judged by
  its own server path. It then re-reads both views with fresh handles. Every
  decision goes to `setup.log` beside `orion-install.json`, including a start line
  with the number of verified camera files and "not registered" for absent
  classes, so a cleanup that never ran is visible; a surviving owned
  registration is also printed to stderr as `Saiph installer warning: camera
  registration survived removal: …`. The update still activates.
- The cleanup runs once, after integration and before the current-release marker,
  in installs and uninstalls. `--isolated` runs it only when
  `ORION_SETUP_CAMERA_TEST_ROOT` names a key below
  `HKCU\Software\OrionMini\SetupCameraTests\` (validated before anything changes).
- `registration.cpp`: `DllRegisterServer` also replaces a registration whose module
  is in another release folder of the same installation
  (`<root>\releases\<version>\app\_internal\camera\`, same file name). Another
  root, another file name, a source build or a missing server path are still refused.

**Checks (worktree, no installed app; real camera registrations changed only in
the approved experiment above, which ended with none present, as it began):**

- New `tests/test_windows_camera_registration.py`: **9 passed**. Real installer
  processes, synthetic payloads, disposable HKCU subtree: update removes the
  previous release's registration; a key denying `CreateSubKey` or `SetValue`
  (the silent-skip case) is removed; a key denying `Delete` is reported in
  `setup.log` and on stderr; another installation's registration and a locally
  changed DLL are kept; uninstall removes owned registrations; the test root is
  confined to its subtree. `tests/test_desktop_distribution.py` still passes
  (**12 passed, 1 skipped**).
- `native/camera/build.py`, then `SaiphCameraTest.exe` x64 and x86, 720p and
  1080p: **4/4 PASS**, including the new release-folder case (sibling release
  replaced; other root, other file name, non-release path and System32 refused).

**Not done:** an installed update on a real machine with the camera registered,
and the WOW6432Node redirection (the harness maps both views to one test key).
To verify on the next update, record the four `{D9B25791-5540-48BE-842C-C73BF854034x}`
`InprocServer32` values (CLSID and WOW6432Node\CLSID) before and after, and read
`%LOCALAPPDATA%\Programs\OrionMini\setup.log` and the installer's stderr.

## 2026-10-18: Dashboard in a native child window; tab wave on one 8 Hz timer (development, unreleased)

Details: [DESKTOP_PERFORMANCE.md](DESKTOP_PERFORMANCE.md#second-pass-what-qt-costs-per-frame-and-per-window-move-beta33).
Measured per hosting mode in visible windows: every presented web frame costs about 1 % of a
core whether Chromium is hosted by a widget or a pure Qt Quick window, but moving the window
costs 58–77 % with the `QWebEngineView` widget (Chromium re-renders for every position change)
and 16–25 % with a QML `WebEngineView` in a `QQuickView` embedded by `createWindowContainer`.
The shell now uses the latter (`dashboard_view.py`), keeping local-only navigation, Qt-side
file drops, one web channel object, native menus and tooltips, and re-announcing its screen
position once a move settles so `<select>` lists open under their control. The tab wave is one
JavaScript timer (1 px at 8 Hz, no CSS animation). Packaging collects only the QtQml, QtQuick,
QtWebEngine and QtWebChannel QML imports. Real shell, visible, isolated profile: window move
61–69 % → 22–24 %; idle 13–17 % → 8–14 %.

Checks (isolated venv/npm cache; no device or account; installed app not used deliberately, but
see the note below): frontend `tsc -b`, `oxlint`, build, `vitest run --maxWorkers=4` 267 passed;
Python `pytest tests` 1663 passed, 58 skipped, 1 failed (the known `test_native_notices` inventory precondition); `desktop_control_smoke.cjs` and `desktop_layout_smoke.cjs` passed on
the new view; a local `build-native.py --profile link` build succeeded and its packaged exe,
run offscreen with an isolated profile, loaded the dashboard with the bridge. A
`<select>` list opened under its control after a programmatic drag (screen grab, kept private).
**Not done:** physical acceptance (checklist items 7–10), real-pointer tooltip check, Linux.
Note: while stopping the local packaged build the session ran `taskkill /IM Saiph.exe`,
which would also have closed an installed Saiph if one was running; the coordinator was told.

## 2026-10-18: Wi-Fi and mobile signal bars in the phone header (development, unreleased)

Details: [PHONE_LINK_PARITY.md](PHONE_LINK_PARITY.md#signal-bars-phonesignal-built-acceptance-pending).
After an owner report that the header's Wi-Fi and mobile bars did not match the
phone, phones send a new `phone.signal {wifi_level, cellular_level}` (0-4 or null)
with every `phone.status`, over the Hub and Saiph Cloud. Wi-Fi bars come from the
connection's RSSI, mobile bars from the registered SIM whatever network is active;
the desktop draws each from its own level, and a change in bars alone is sent
after 15 seconds instead of 60. `phone.status` is unchanged, so older desktops
and Hubs keep working; a current Hub validates the new type and keeps the latest
one in its snapshot.

Checks in an isolated worktree (no device, installed app or account used):

- Desktop `pytest tests`: **1635 passed, 58 skipped, 5 failed**. Two fail on the
  untouched base `62722ac` as well (native-notices inventory; the source-release
  test needs a clean commit). Three passed on rerun and on the base
  (distribution upgrade, fresh-interpreter import, one screen-invitation case):
  timing failures while the Android build ran alongside. New cases are in
  `test_phone_status_shared.py` and `test_hosted_phone.py`.
- Hub `pytest hub/tests`: **593 passed, 6 skipped**, including the new `phone.signal` validation and snapshot.
- Frontend: `tsc -b`, `oxlint` (0 findings), `vitest run` **239 passed**, `npm run build`.
- Android `:app:assembleDebug :app:assembleBeta :app:testDebugUnitTest
  :core:network:testDebugUnitTest :restic-android:testDebugUnitTest :app:lintDebug`:
  debug and **unsigned** beta APKs built; **56 app, 119 network (2 skipped) and
  47 restic JVM tests passed**; lint 0 errors, none of its warnings in the changed files.

**Not done:** comparing the header with the phone's own status bar on a real
phone (Wi-Fi near and far, Wi-Fi off, no SIM), and an installed desktop check.

## 2026-10-18: Saiph Cloud phone notifications as desktop notifications (development, unreleased)

Physical testing found that phone notifications reaching a computer through Saiph
Cloud were only listed on the Phone page; unlike the self-hosted Hub path they
never popped up as a Windows toast or a Linux desktop notification. They now go
through the same notifier the Hub path uses (`NativeNotifications` in
`phone.py`, desktop-notifier: WinRT toasts on Windows,
org.freedesktop.Notifications on Linux), on the main computer and on joined
computers alike. The hosted controller runs on its own worker thread, so it only
hands each change to the desktop phone runtime, which schedules it on its own
asyncio notifier loop (the bridge photo notices already use); the controller
never calls the OS notifier or Qt.

- A new notification, or one whose app, title or text changed, pops up. Repeats
  with the same content do not pop up again.
- One already more than ten minutes old when it arrives (a phone resends what is
  showing when it reconnects or a computer joins) is listed without popping up.
  This is the Cloud equivalent of the Hub's `silent` rows: the Cloud
  `notification.upsert` wire format has no `silent` field, so the phone's own
  timestamp decides. A phone clock more than ten minutes behind this computer's
  would therefore silence its popups; Saiph Cloud already warns about this
  computer's clock skew.
- The Notifications switch in Settings → Phone drops them (nothing stored, no
  popup), and quiet hours/Focus silence the popup.
- `notification.remove` from the phone, or dismissing in Saiph, clears the
  toast. Dismissing the toast itself sends `notification.dismiss` to the phone
  (from any approved computer). Clicking it opens Saiph on the Phone page
  (`phone_reveal` in the desktop state). Cloud rows have no action buttons or
  inline reply; a detected one-time code still gets a Copy button.
- With automatic code copying on, a new code is copied once, also during quiet
  hours, but never from a notification that was already on the phone.
- Hub and Cloud toasts are reconciled separately, so one path never clears the
  other's toasts.
- Low battery: Cloud `phone.status` battery and charging now feed the same
  one-time "Phone battery low" notice as Hub phones (20%, re-armed after
  charging or above 30%, off with the Low battery switch, silent in quiet hours).

Checks run in this worktree only (isolated venv `build/toasts-venv` and npm
cache; no device, installed app, Hub or account was used):

- Python: new `tests/test_cloud_toasts.py` **15 passed** (fake notifier on a
  real loop thread: show, unchanged update without a second popup, stale row,
  removal and in-app dismissal reconcile, toast dismissal reaching the phone,
  Notifications switch off, quiet hours, code copying, low battery, Hub/Cloud
  reconcile separation, and a joined computer end to end over the synthetic
  relay). Full `pytest tests`: **1646 passed, 58 skipped, 5 failed**. Four
  (`test_link_service.py` ×2, `test_package_updates.py` missing-release,
  `test_phone_features.py` photo save) passed when rerun alone, as load-timing
  failures; `test_native_notices.py::test_packaged_inventory_fills_reviewed_gap_and_preserves_unknown_gap`
  still fails on its frontend licence-inventory precondition, as in the
  entries below.
- Frontend: `npm run build` (`tsc -b` and Vite) and `oxlint` on the changed
  files passed; `vitest run` **238 passed** (an earlier run alongside the full
  pytest suite had 22 5-second timeouts, all of which passed on the rerun).

**Not done:** physical acceptance. The coordinator should check, with the
Windows app and the Ubuntu laptop both on Saiph Cloud: a new phone notification
pops up as a Windows toast and a GNOME notification; an unchanged repeat does
not pop up again; clicking opens Saiph on the Phone page; dismissing the toast
dismisses it on the phone; dismissing on the phone clears the toast; dismissing
in Saiph clears both; the Notifications switch and quiet hours silence it; a
joined (non-main) computer behaves the same; low battery at 20% appears once.

## 2026-10-18: Settings → Connections layout and phone notification cards (development, unreleased)

Owner feedback on beta.32, desktop frontend only. Design rules:
[DESKTOP_DESIGN_SYSTEM.md](DESKTOP_DESIGN_SYSTEM.md#galleries-and-device-preferences).

- **Connections** is laid out like Settings → Phone: open sections **Phone and
  this computer**, **Quiet hours** and **Cloud folders** of switch rows that save
  as soon as they change (the shared `SwitchRow`). The old "Phone and clipboard
  preferences" dropdown and its single Save button are gone. Every preference and
  its `settings.save` key is kept; the quiet-hours times and Cloud folder path keep
  an explicit Save. An unpaired self-hosted Hub is one closed disclosure at the end.
- **No bare `<details>` or native `<select>` in Settings:** Recent device changes
  (now `Item` rows, newest first, count and relative times), Custom service, Join as
  another computer, Other sign-in options and Deskflow's trust setup use the
  design-system `Disclosure`; Send file to, Phone hotspot network, the Bluetooth
  lock phone and Deskflow's role use `Select`.
- **Phone notifications** (Phone page, Hub and Saiph Cloud, plus the newest Cloud
  notification previewed in Settings → Connections → Saiph Cloud) are cards: app
  tile, app name, relative time, title, body clamped to three lines with Show more,
  actions, and labelled Open/Dismiss icon buttons; several from one app are grouped
  with Clear; the empty state has an icon. **App icons are not sent by phones:**
  the tile is a monogram on a token tint. The protocol change (both transports
  reject unknown notification fields) is designed but not built.

Checks run in this worktree only (isolated npm install and Python 3.12 venv; no
device, Hub, installed app or account was used; Python and Android code untouched):

- Frontend: `tsc -b`, `oxlint` and `npm run build` passed. `vitest run` **258
  passed** in one full run. Later full runs, with the machine's CPU at 99% from
  parallel sessions, had 5–8 tests time out at 5 s (Settings, LegacyPhoneCamera,
  PhoneLayout, SetupWizard and others); each of those files passed when rerun on its
  own. New: `disclosure.test.tsx`, `PhoneNotifications.test.tsx`, Connections cases
  in `Settings.test.tsx` and `ContinuitySettings.test.tsx`, Recent device changes,
  latest-notification and Select cases in `HostedSettings.test.tsx`.
- Real Qt shell (`scripts/desktop-ui.py`, fresh isolated profile, offscreen): the
  new `tests/packaging/desktop_settings_polish.cjs` passed (sections visible, a
  switch and the quiet hours persisted in `settings.json` through the native
  bridge, the Hub disclosure opened with Enter and closed with Space), as did
  `desktop_layout_smoke.cjs` (updated for the Cloud folders card) and
  `desktop_control_smoke.cjs`. `desktop_ui_probe.cjs` was updated but not run.
- Notification cards were checked visually only in the synthetic browser preview
  (`/preview.html`); the isolated Qt profile has no phone.

**Not done:** the installed app, a real phone's notifications over the Hub and
Saiph Cloud, Settings → Connections on a signed-in Cloud account (Recent device
changes, Send file to, the latest-notification preview), Linux, and real app icons.

## 2026-10-18: Desktop idle CPU, window drag, flicker and camera preview (development, unreleased)

Details and synthetic measurements: [DESKTOP_PERFORMANCE.md](DESKTOP_PERFORMANCE.md).
The background strings are drawn once (redrawn on resize/theme only); the selected-tab
wave stays infinite but steps at 10 Hz; header/footer backdrop blur removed; periodic
dashboard refresh is a 3 s visible-only safety net held during window move/resize, with
camera/screen sessions announcing changes; page/window ground matches the dashboard; the
camera and phone-screen previews are pushed and loaded as bytes from a local
`saiph-frame:` scheme instead of polled base64. Offscreen synthetic idle: ~110 % → ~19 %
of one core; synthetic 20 fps camera preview shown 16.7 → 20.0 fps.

Checks (isolated venv/npm cache, no device, account or installed app): frontend `tsc -b`,
`oxlint`, `npm run build` passed, `vitest run` 246 passed (two long tests timed out once
under parallel load and passed on rerun with `--maxWorkers=4`). Python `pytest tests`:
1635 passed, 58 skipped, 3 failed: the known `test_native_notices` inventory precondition
and two `test_link_service` timing tests that passed alone (41/41). **Not done:** physical
acceptance on the installed app (checklist in DESKTOP_PERFORMANCE.md), GPU/visible-mode numbers.

## 2026-10-18: Android home quick actions, switch rows and a Find phone Stop screen (branch, unreleased)

Branch `android-ux-2` from the campaign tip `62722ac`, from owner feedback on the
real phone:

- **Find phone** opens a full-screen "Ringing to find your phone — <computer>"
  page (`FindPhoneActivity`) with one large Stop, over the lock screen through a
  full-screen-intent notification and directly when Saiph is in front. The ringing
  notification is ongoing with Stop; swiping it away re-posts it while ringing.
  Stop on the page, the notification, a volume key (page in front), the power
  button or Back stops it everywhere; it still ends by itself after 30 seconds.
  Cloud phones show the asking computer's name; Hub phones show no name yet.
  Rules live in `FindPhoneRing` (pure, `FindPhoneRingTest`).
- **Telling the computer (follow-up commit):** phones send `phone.ring.state
  {ringing, seconds}` to every computer on each start/stop (Cloud: each
  subscribed computer; Hub: broadcast). Released desktops ignore the type and
  older Hubs relay it unchecked; `phone.status` and `phone.capabilities` are
  unchanged. Desktops show it as `ringing` on the phone (memory only, ends by
  itself after `seconds`), and the Find phone tile becomes **Stop ringing**,
  sending `phone.ring.stop` (same "ring" control). Checks: pytest
  `test_phone_status_shared.py` + `test_hosted_phone.py` 165 passed; Hub
  `pytest hub/tests` 559 passed, 13 failed / 21 errors, all in untouched
  `test_hosted_download*`, `test_hosted_maintenance`, `test_hosted_service_migration`
  (Windows release-directory checks); vitest PhonePanel + PhoneLinkParity 26
  passed, `tsc -b` clean; Android build/tests/lint passed.
- **Home** (Cloud and Hub): a quick-actions strip at the top with Use as webcam,
  Share screen and Send a file (Hub: through the share screen's computer
  choice). The separate Phone camera and Phone screen cards are gone from the
  Cloud home.
- **Switch rows:** Photo gallery, Texts and calls, Share phone status and Sync
  over mobile data are switches; turning photos or texts and calls on still goes
  through owner verification and Android's permission request.
- **Shorter copy:** one summary line per feature, details behind Learn more.

Checks (JDK 22, independent mode, Firebase off, version code 1; no device):
`:app:assembleBeta :app:testDebugUnitTest :core:network:testDebugUnitTest
:app:compileDebugAndroidTestKotlin :app:lintBeta` passed: **unsigned** beta APK;
**56 app and 126 network JVM tests (2 skipped)** at `d1ef931`, including `FindPhoneRingTest` (7) and `PhoneStatusFramesTest` (12);
lint **0 errors**. **Not done:**
physical acceptance (full-screen intent over the lock screen, Android 14's
full-screen-intent access, power and volume stops, re-posting a swiped
notification, the new home layout at large text sizes).

## 2026-10-18: Phone screen in its own window, Apps grid with icons, request pop-up, red live indicators (development, unreleased)

Details: [PHONE_SCREEN.md](PHONE_SCREEN.md#the-phone-screen-window). From the owner's
real-device test of phone screen and apps:

- **Own window.** A live phone screen opens in a separate native Qt window
  (`phone_screen_window.py`), sized to the phone's aspect, movable and resizable,
  with Back/Home/Recents, a local Rotate, Stop and a red Live badge and outline; it
  remembers its position and size, forwards mouse and keyboard as before, and
  closing it stops the session. Frames are decoded once on the receiving thread
  into a `QImage`; the per-frame base64 data URI now exists only for the page's
  embedded fallback. Linux uses the same code.
- **Apps grid.** Tiles with icons and names, search, Pinned (per phone, on this
  computer) and Most used (local open counts; the phone holds no usage-access
  permission, so no phone usage data). Icons come from the phone over two new
  sealed Cloud events, `apps.icons.request` / `apps.icons` (static WebP ≤ 96 px and
  12,000 bytes, strict PNG/WebP header checks, cached by package and version,
  fetched for visible tiles, at most 24 per request). LAN-only phones show initials.
- **Requests on the phone.** Camera and phone screen requests show an in-app
  sheet (Allow → owner verification → start; Not now) while Saiph is open, and a
  heads-up notification with Allow otherwise (no full-screen intent: Android 14
  reserves it for calls and alarms). A new `session.close` event from the offering
  computer, the app's own expiry timer and "taken by any route" clear both, fixing
  a used or expired camera request that stayed in the shade.
- **Live indicators.** Desktop: red Live badge in the Phone header, red outline and
  badge on the live camera card and the phone screen card/window, red dot on the
  tray icon. Android: red LIVE banner on the camera and phone screen pages, red
  ongoing notification with Stop for both (the camera gained one). The phone
  screen page now uses the shared top-corner Back frame.

- **No scrcpy in normal use.** The Phone header's Mirror screen now starts the
  local phone screen (its own window) instead of scrcpy, and never shows an
  install prompt; pinned app shortcuts do the same. scrcpy windows remain only
  after Settings → Advanced → USB debugging (off by default); without it the
  desktop refuses `phone.mirror` and the scrcpy app routes. Bundling scrcpy/adb
  for that path was assessed, not done ([PHONE_SCREEN.md](PHONE_SCREEN.md#mirror-screen)).

Older desktops and phones ignore the three new event types; `apps.list`, the
screen socket messages and `phone.capabilities` are unchanged.

Checks run in this worktree only (isolated Python 3.12 venv, npm install and
Gradle home; no device, installed app, account or Hub was used):

- Python (after the Mirror screen change): `pytest tests` **1657 passed, 58 skipped,
  1 failed**; the failure was `test_phone_link_parity.py::test_preferences_default_on_except_the_wallpaper`,
  which lists the exact preference defaults and now includes `usb_debugging: False`
  (15 of 15 there after the update). `test_native_notices.py::test_packaged_inventory_fills_reviewed_gap_and_preserves_unknown_gap`
  was deselected (its frontend licence-inventory precondition, as in the entries below).
  An earlier run of the first commit also hit a load-only failure in
  `test_package_updates.py` that passed alone and in later runs.
  New: `test_phone_screen_window.py` (9: pointer mapping, gestures, sizing, geometry
  store, a real loopback session opening the window, refitting, input forwarding,
  stop on close, phone-ended close, tray live state), `test_phone_app_library.py`
  (11: icon checks, cache, tampering, lookup paging, pins and counts, event shapes,
  icons through the sealed relay), and in `test_phone_screen.py` `session.close`,
  `screen.invite` and the scrcpy routes refused without the USB debugging opt-in.
- Frontend: `tsc -b`, `oxlint src`, `npm run build` passed; `vitest run` **255 passed**
  (one full run had `PhoneSetup.test.tsx`, untouched, fail once; it passed alone
  10 of 10 and in the next full run). New `PhoneAppGrid.test.tsx` 11; window mode and
  a code for a session started elsewhere in `PhoneScreen.test.tsx`; header badge and
  Mirror screen (local session, never a scrcpy/install text in the header) in
  `PhoneLayout.test.tsx`; Apps tiles and no scrcpy option without the opt-in in
  `PhonePanel.test.tsx`. Design-token tests pass with the new `--live` tokens.
- Desktop shell: launched with `scripts/desktop-ui.py` in fresh isolated sessions
  (starts and quits cleanly with the window controller; no phone in those profiles);
  Settings → Advanced → USB debugging renders and its switch saved `usb_debugging`
  through the native bridge. The
  window was also rendered offscreen with a synthetic frame (portrait and rotated), and
  the grid was checked in the browser design preview with synthetic apps.
- Android (built at the first commit; the Mirror screen change touches no Android code;
  JDK 22, isolated Gradle home, restic libraries copied from the main checkout):
  `:core:network:testDebugUnitTest :app:testDebugUnitTest :app:assembleBeta :app:lintDebug`
  passed: **unsigned** beta APK built; **69 app and 117 network (2 skipped) JVM tests
  passed** (new `RequestPromptsTest` 7, `AppIconsTest` 6); lint **0 errors / 278
  warnings** (3 on new lines: KTX and string-literal style warnings of kinds the
  existing code already has).

**Not done:** every physical check below; Wayland window placement; OEM rendering
of colorized notifications and heads-up; the size of real app icons across many
apps; independent security review of the new events.

Physical checklist (signed tester build, owner verifies on the phone):
1. Phone → Apps on a Cloud-paired phone: icons replace initials within seconds.
2. Search filters; clearing it shows Pinned / Most used / All apps.
3. Right-click a tile → Pin to the top; restart Saiph: still pinned. Open an app twice: it is under Most used.
4. Show phone screen with Saiph open on the phone: the in-app sheet and the notification appear; Allow → verify → Start now.
5. Desktop: separate window sized like the phone, red LIVE badge and outline, tray red dot, header "Live · screen".
6. Move and resize; Back/Home/Recents, click, type, Esc work with Control on; Rotate turns the view.
7. Turn the phone: the window refits. Close the window: the phone stops sharing. Start again: same position and size.
8. Phone while sharing: red ongoing notification with Stop; Saiph → Phone screen shows the red banner; Stop there closes the desktop window.
9. Saiph closed on the phone: heads-up notification with Allow, no sheet.
10. Cancel on the desktop before answering: the phone's notification goes away.
11. Camera with Saiph open: sheet → Allow → verify → camera starts; red banner and red ongoing notification with Stop; desktop "Live · camera", red camera card outline, tray dot.
12. Let a camera request expire, or answer it by scanning instead: no notification remains.
13. Not now in the sheet removes the notification as well.
14. Phone header → Mirror screen: no install or scrcpy text appears; the request reaches the phone, Phone → Apps opens with its status (or a code to scan), and the window opens once live. Mirror screen again while live brings the window forward.
15. Settings → Advanced → USB debugging is off by default and Phone → Apps shows no scrcpy option; turning it on adds "Use USB debugging (scrcpy)" there.

## 2026-10-18: Saiph Cloud file transfers survive a network drop (development, unreleased)

Fixes from physical run 2026-10-18-r2. Desktop (`hosted_transfers.py`): a Cloud
file send is queued, not uploaded under the scheduler's lock. Every retry reuses
the same ciphertext, blob descriptor and sealed offer event, resumes after the
last chunk the relay accepted, and backs off (2, 4, 8, then 15 s) or retries at
once when the next Cloud pass succeeds; after 10 minutes it fails visibly with
Retry and a tray message. An offer that may already have been published is
never re-encrypted under a new event; one that never reached the relay is
prepared afresh if its roster changed or it nears expiry. Ciphertext in
`hosted/outgoing` (and `clipboard-outgoing`) is removed on success, final
failure and app start. The UI (phone Share tab and Settings → Saiph Cloud)
shows waiting / sending with progress / retrying / failed with Retry and
Dismiss / "Sent to <device>" for 20 s.

- Size: files over 20 967 424 bytes are refused before encryption: "Saiph Cloud
  sends files up to 19.9 MB. This file is N MB. Nothing was sent." Same wording
  on Android (`HostedTransferText`), which now checks the size before reading.
- Offers: the service caps offers and blobs at 300 s (`hub/orion_hub/hosted.py`,
  `hosted_blobs.py`), so the TTL is unchanged; the UI says how long is left.
  Offers already persisted in the encrypted inbox and reappear after a restart
  (now tested). Android adds one-tap Save to Downloads → Saiph (MediaStore,
  Android 10+), keeping Save as….
- Clipboard text over 16 384 bytes now shows "This clipboard text is too large
  to share. Send it as a file." on desktop and Android.
- Copied JPEGs keep EXIF orientation on the desktop (`oriented_png`, Windows and
  Linux share the code). Android sends clipboard and original image bytes
  unchanged; its API 26–27 gallery previews now apply EXIF rotation too.
- One received-files folder: Downloads → Saiph for Cloud and Hub files, saved
  photos and MMS pictures, using the Windows Downloads Known Folder (only for
  the signed-in profile) and `XDG_DOWNLOAD_DIR` on Linux. Earlier Downloads →
  Orion files stay openable.
- Send to phone from a file manager names the files and posts a tray message
  when the Cloud send finishes or fails.

Checks run in this worktree only (isolated venv and npm cache, shared Gradle
cache; no device, installed app, account or live service was used):

- Python: `pytest tests` **1648 passed, 58 skipped, 1 failed**
  (`test_native_notices.py::test_packaged_inventory_fills_reviewed_gap_and_preserves_unknown_gap`,
  the frontend licence-inventory precondition, as in the entries below). New:
  `tests/test_hosted_transfers.py` (8; the real Hub service in-process with a
  transport that drops after two chunks, then recovers: exactly one offer, upload
  resumed at chunk 2; a lost publish reply; the 10-minute failure and Retry;
  restart keeps offers and removes orphaned ciphertext),
  `tests/test_received_folder.py` (3), plus EXIF, dialog-wording and size cases.
- Frontend: `npm run build` (includes `tsc -b`) and `oxlint` on the new files
  passed; `vitest run` **243 passed** (`CloudTransfers.test.tsx` has 5).
- Android (JDK 22, unsigned beta): `:core:network:testDebugUnitTest
  :app:testDebugUnitTest :app:assembleBeta :app:lintDebug` passed: **117 network
  (2 skipped) and 59 app JVM tests** (`HostedTransferTextTest` has 3); lint **0
  errors / 281 warnings**; new ones are `ExifInterface` (framework class, used
  only on API 26–27) and existing-style `SetTextI18n`. `:app:lintBeta` failed
  inside lint itself on `:worker:lintAnalyzeRelease` (an internal lint crash,
  module untouched here).

**Not done:** physical acceptance (checklist in the commit report: a 20–30 s
network drop during a 19 MiB Linux→Windows and Windows→phone send, oversize
message, Sent state, offer countdown and restart, one-tap save on Android,
large clipboard text, a rotated JPEG copied on Linux, XDG and moved-Downloads
folders), the Qt shell, and Android phone→computer automatic retry (the phone
still shows an error instead of retrying).

## 2026-10-18: Desktop updates from the Saiph account (development, unreleased)

Details: [DESKTOP_UPDATES.md](DESKTOP_UPDATES.md). Windows and Linux
**Check for updates** can now use the signed-in Saiph account on this build's
packaged HTTPS origin as well as the paired Hub. The description is read
strictly; older or changed builds are refused; the download (fresh ticket,
progress) must match the published size and SHA-256 and the installed edition;
a Linux `.run` is checked without running it and its release archive is
staged; the existing handoff installs it after a separate **Restart to update**.
The Updates panel shows what's new and progress.

**The account routes do not exist yet** (proposal in DESKTOP_UPDATES.md, with
the Android routes and a recommended release signature); account computers
are told updates are not offered yet. No service, catalog or production change.
Windows silent upgrades re-create the Send to shortcut and invitation
association even if removed (existing installer behaviour, also on the Hub
path).

Checks run in this worktree only (isolated venv and npm cache; no installer
was run, no account or service was used):

- Python 3.12: `pytest tests` **1682 passed, 58 skipped, 1 failed**
  (`test_native_notices.py::test_packaged_inventory_fills_reviewed_gap_and_preserves_unknown_gap`,
  the same pre-existing licence-inventory precondition as in the entries
  below). New `tests/test_package_updates_cloud.py` has 47 cases, including a
  real `.run` made by `build-desktop-distribution.py`; with
  `test_package_updates.py` and `test_cloud_bridge.py`: 108 passed, 6 skipped
  (the actual Linux shell handoff tests, which skip on Windows).
- Frontend: `vitest run` **241 passed** (35 files; `Updates.test.tsx` has 8),
  `tsc -b`, `oxlint` on the changed files and `npm run build` passed (the
  existing large-chunk warning remains).

**Not done:** a real install on Windows or Linux through this path, the
proposed routes and release signature, independent security review.

## 2026-10-18: Android in-app updater (development, unreleased)

Details: [ANDROID_UPDATES.md](ANDROID_UPDATES.md). **Check for updates** now
opens one Update screen on both Saiph account and Hub phones: it checks the
phone's own source, shows the new version with what's new, downloads into
app-private storage with progress, pause and resume, refuses anything that is
not strictly newer, the published size and SHA-256, this package, the published
versionCode and signed by exactly the installed app's certificates, asks before
using a metered network, explains and opens Android's "Install unknown apps"
setting, and installs through a `PackageInstaller` session that always shows
Android's prompt. A daily check (a Settings switch, on by default) only
notifies. The Hub link's earlier silent background download is gone. A
debug-only test server field exists in `src/debug`; beta and release compile a
stub.

**The Saiph account source does not work yet**: the website's APK catalog is
reachable only with the website's sign-in client and has no version metadata.
The service routes and catalog entry it needs are a proposal in
ANDROID_UPDATES.md; no server, catalog or production change was made. Until
then Saiph account phones are told updates are not offered yet and pointed at
the downloads page (and Firebase App Tester in tester builds). Hub phones use
the existing `/v1/app/android` routes.

Checks run in this worktree only (JDK 22, independent mode, Firebase off,
version code 1, isolated Gradle home; no device, Hub, installed app or account
was used):

- Android: `:app:testDebugUnitTest :core:network:testDebugUnitTest
  :restic-android:testDebugUnitTest :app:assembleDebug :app:assembleBeta
  :app:lintDebug :app:lintBeta` passed: debug APK and **unsigned** beta APK
  built; **85 app (29 new in `AppUpdateTest`), 117 network (2 skipped) and 47
  restic JVM tests passed**; lint **0 errors** (283 warnings debug, 277 beta; 9
  on new lines in debug, 5 in beta, all `UseKtx`/`SetTextI18n`/`UseSwitchCompat`
  style matching existing code). The project has no beta unit-test task; the
  beta APK's dex contains none of the debug override's strings, the debug APK's
  does. Signer extraction from real APKs (`PackageFactsReader`) and the
  `PackageInstaller` session run only on Android and are untested here.

**Not done:** any physical install (the plan is in ANDROID_UPDATES.md: metered
prompt, pause/resume, install permission, Android's prompt accept/decline,
hash/signer/downgrade refusals, Hub and debug-server sources), the proposed
Hosted routes, and independent security review.

## 2026-10-18: One phone feature layer, second slice: Hub wallpaper and one Status switch (development, unreleased)

Details: [PHONE_LINK_PARITY.md](PHONE_LINK_PARITY.md#second-slice-wallpaper-on-the-hub-and-one-status-switch-built-acceptance-pending).
Hub phones now carry the opt-in wallpaper the same way Cloud phones do:
`phone.wallpaper.request` (a phone command needing the `wallpaper` control) and
`phone.wallpaper` (a private answer to exactly one computer, relayed by the Hub
and never stored). The wallpaper codec and the request window (ask every six
hours, accept an answer only within a minute of this computer's own request) now
live once in `phone_status.py` and serve both transports. The phone's Link
screen has the same "Share status and quick controls" switch as the Saiph Cloud
screen. Of the status layer, only Sync over mobile data remains Cloud only (a
Cloud sync setting); Hub media keeps its older path and shape.

Checks run in this worktree only (same isolated venv, npm cache and Gradle home;
no device, Hub, installed app or account was used):

- Python: `pytest tests` **1524 passed, 58 skipped, 1 failed**
  (`test_native_notices.py::test_packaged_inventory_fills_reviewed_gap_and_preserves_unknown_gap`,
  its frontend licence-inventory precondition, as in the entries below). New:
  wallpaper cases in `tests/test_phone_status_shared.py` (19 there). Hub:
  `pytest hub/tests` **592 passed, 6 skipped**.
- Frontend: `tsc -b`, `oxlint` on the changed files and `npm run build` passed;
  `vitest run` **213 passed, 1 failed** (`PhoneSetup.test.tsx`, untouched; it
  passed 9 of 9 when rerun alone). `PhoneLinkParity.test.tsx` has 15.
- Android (JDK 22, independent mode, Firebase off, version code 1):
  `:core:network:testDebugUnitTest :app:testDebugUnitTest
  :restic-android:testDebugUnitTest :app:assembleDebug :app:assembleBeta
  :app:lintDebug` passed: debug APK and **unsigned** beta APK built; **117
  network (2 skipped), 27 app and 47 restic JVM tests passed**
  (`PhoneStatusFramesTest` has 10); lint **0 errors / 255 warnings**, none on
  changed lines.

**Not done:** physical acceptance (the Hub wallpaper on Android 13+ with and
without All files access, the Link-screen switch hiding the header within one
status pass), a Cloud regression pass on a real phone, and the Qt shell.

## 2026-10-18: One phone feature layer for Hub and Saiph Cloud, first slice (development, unreleased)

Audit, design and outcome: [PHONE_LINK_PARITY.md](PHONE_LINK_PARITY.md#one-phone-feature-layer-hub-and-saiph-cloud).
The audit lists every phone event and command with its Hub and Cloud name and
shape and the side that lacks it. The design gives one codec per feature, one
capability model (quick actions listed in `phone.status` on both transports),
one Android publisher with Hub and Cloud implementations and one desktop
handler fed by both, keeping Cloud sealing, subscription checks, exact shapes,
"new event types over new fields" and compatibility with installed phones,
desktops and Hubs.

First slice, phone status and quick actions: the desktop's `phone_status.py`
(codec plus `StatusBook`) now serves both the Cloud path and the Hub path; the
Hub validates `phone.status`, `phone.status.request`, `phone.dnd` and
`phone.hotspot`, keeps each phone's latest status for reconnecting computers and
accepts a command the phone lists in its status; Android's `PhoneStatusFrames`,
`PhoneStatusPublisher` and `PhoneQuickControls` are shared, with
`LinkPhoneStatus` as the Hub transport and `HostedRuntime` as the Cloud one. Hub
phones therefore gain the Wi-Fi, Bluetooth and signal header, Refresh, the
phone's own Do Not Disturb and the hotspot request. The Cloud wire format is
unchanged; the desktop's Cloud status record moves to `phone_status` and reads
the older record once. Wallpaper and Sync over mobile data stay Cloud only; Hub
media keeps its existing path and shape; the phone's Link screen has no Status
switch yet (on by default).

Checks run in this worktree only (isolated Python 3.12 venv, npm cache and
Gradle home; no device, Hub, installed app or account was used):

- Python: `pytest tests` **1521 passed, 58 skipped, 2 failed**: the same two as the
  entry below. `test_native_notices.py::test_packaged_inventory_fills_reviewed_gap_and_preserves_unknown_gap`
  stops on its frontend licence-inventory precondition, and
  `test_camera_session.py::test_real_tls_round_trip_fits_rotated_preview_and_blanks_on_stop`
  passed when rerun alone. Neither touches the changed code. New:
  17 in `tests/test_phone_status_shared.py`; the existing Cloud status tests in
  `test_hosted_phone.py` pass unchanged. Hub: `pytest hub/tests` **591 passed,
  6 skipped** (10 new status cases in `hub/tests/test_phone_features.py`).
- Frontend: `tsc -b` and `oxlint` on the changed files passed; `vitest run`
  **211 passed, 2 failed** in the full run (`design-tokens.test.ts`,
  `PhoneCamera.test.tsx`, both untouched, both timed out while Gradle was
  compiling) and **16 of 16 passed** when those two files ran alone. 3 new Hub
  cases in `PhoneLinkParity.test.tsx`.
- Android (JDK 22, independent mode, Firebase off, version code 1, restic
  libraries copied from the owner's existing pinned build):
  `:core:network:testDebugUnitTest :app:testDebugUnitTest :app:assembleDebug
  :app:lintDebug` passed: debug APK built; **116 network (2 skipped) and 27 app
  JVM tests passed** (`PhoneStatusFramesTest`, renamed from
  `HostedPhoneStatusTest`, has 9, 3 new); lint **0 errors / 256 warnings**, none
  on changed lines.
- `check-public-data.py` (working tree) and `git diff --check` passed.
  `--history` reports `ready: false` only for blobs in two 2026-10-11 commits
  (`83bd57b`, `fe8fcd3`) that are in other local refs, not in this branch; this
  branch changes none of the flagged files.

**Not done:** physical acceptance on a Hub-paired phone (status accuracy, Do Not
Disturb and hotspot from the desktop, Refresh, status across an older Hub), a
Cloud regression pass on a real phone, and the Qt shell. Nothing was installed or
released. Next slices are listed under "Migration order" in the design.

## 2026-10-18: Phone Link quality-of-life parity (development, unreleased)

Gap table: [PHONE_LINK_PARITY.md](PHONE_LINK_PARITY.md#quality-of-life-parity-phone-link-screenshots-18-october-2026).
A Saiph Cloud phone now sends a rate-limited `phone.status` (battery and charging,
Wi-Fi, Bluetooth, signal bars, ringer, Do Not Disturb, the quick actions it
accepts, Sync over mobile data) and its media sessions to each subscribed
computer, and accepts Find phone, ring/vibrate/silent, Do Not Disturb, media
play/pause/next/previous, an opt-in wallpaper request, a hotspot-settings
notification, Refresh and the mobile-data switch. Controls travel inside
`phone.status`, not `phone.capabilities`, so older desktops keep working.
Sync over mobile data is enforced on Android: on a metered network with the
switch off the phone announces the pause once and makes no Cloud requests. The
desktop adds the header icons and Refresh, quick-action tiles with permission
hints, Settings → Phone (feature switches that hide and stop storing that data,
wallpaper, audio player, received-files folder, hotspot, clipboard link, taskbar
badge, tray recent content) and Settings → Help (feedback opens a new public
GitHub issue; troubleshooting topics mirror USER_GUIDE.md). Cloud tray menus now
include Cloud phones. Hub (Link) phones keep their existing events; Wi-Fi,
Bluetooth and signal for them are not built. Linux has no taskbar badge.

Checks run in this worktree only (isolated Python 3.12 venv, npm cache and
Gradle home; no device, installed app or account was used):

- Python: `pytest tests` **1502 passed, 58 skipped, 2 failed**. The two failures
  (`test_native_notices.py::test_packaged_inventory_fills_reviewed_gap_and_preserves_unknown_gap`
  and one `test_camera_session.py` WebSocket test, a different one on each run) also
  fail on the untouched checkpoint `d5cd902`; they are not caused by this work.
  New: 15 in `test_phone_link_parity.py`, 28 status/control cases in `test_hosted_phone.py`.
- Frontend: `tsc -b`, `oxlint` (0 findings), `vitest run` **210 passed** (11 new in
  `PhoneLinkParity.test.tsx`) and `npm run build` passed. Pages were also checked
  visually in the synthetic design preview, not in the Qt shell.
- Android (JDK 22, independent mode, Firebase off, version code 1):
  `:app:assembleDebug :app:assembleBeta :app:testDebugUnitTest
  :core:network:testDebugUnitTest :restic-android:testDebugUnitTest :app:lintDebug`
  passed: debug APK and **unsigned** beta APK built; **27 app, 113 network
  (2 skipped) and 47 restic JVM tests passed** (6 new in `HostedPhoneStatusTest`);
  lint **0 errors / 257 warnings**, none in the changed files.
- `check-public-data.py` and `git diff --check` passed.

**Not done:** physical phone and installed-desktop acceptance (status accuracy,
rate limit on a real battery, Do Not Disturb/ringer access prompts, media
sessions from real players, ringing on silent, wallpaper on Android 13+, hotspot
notification, mobile-data pause on a real metered network), the Windows taskbar
overlay on a real taskbar, and a live Cloud relay round trip. The checklist is
in [PHONE_LINK_PARITY.md](PHONE_LINK_PARITY.md#physical-acceptance-checklist-not-yet-run).

## 2026-10-18: connecting without a QR code (branch, not released)

Branch `claude/qrless-pairing-1ab996` adds two QR-less paths, keeping every QR
flow as a fallback; design and threat model in [QRLESS_CONNECT.md](QRLESS_CONNECT.md).
Camera sessions: the desktop also sends the one-use invitation to the linked
online phone as a sealed `session.offer`; the phone shows "Start camera for
<computer>?" and still requires the tap, screen-lock verification, camera access
and the foreground. Linking: on the same Wi-Fi, the phone finds the main computer
while Connect a phone is open; a commit-then-reveal handshake shows the same six
digits on both screens; both owners confirm and the computer still approves with
Windows Hello. Joining another computer is a **Join as another computer** button:
the main computer named by the account's roster is pinned only after its
fingerprint is compared, and the main computer approves in a global pop-up with an
unknown-device warning, Deny, Block, expiry and a many-requests warning; names and
phone/computer kinds now reach every computer. No server change; cross-network
linking, request locations and server-side Deny/Block are proposals only.

Checks actually run (2026-10-18, this PC, isolated venv/Gradle project): desktop
pytest 1532 passed, 58 skipped, 2 failed: `test_native_notices` packaged
inventory (fails identically without this branch: its temp frontend has no
package-lock.json) and an intermittent `test_camera_session` TLS timing case that
also fails on the unmodified base checkpoint. New suites cover the shared offer
vectors, LAN protocol attacks, loopback discovery/handshake, real-crypto
approval through the synthetic relay, button join with key substitution,
Deny/Block/flood and device names. Frontend vitest 212 passed, `tsc -b`,
`vite build` and oxlint clean. Android (JDK 22): app JVM 36 and network 107
passed (2 skipped), `assembleBeta` built (unsigned), `lintDebug` 0 errors /
254 warnings (existing categories).
Not done: any physical phone/computer run, Windows firewall behaviour for UDP
port 47390, installed-app upgrade, multi-network or multi-computer LANs, and
independent security review. Do not claim physical acceptance from these tests.

## 2026-10-18: phone screen and apps over the local network (development)

Phone → Apps no longer needs USB, adb or scrcpy. The installed Windows app failed
there because every Apps request first resolved an authorised adb serial and then
ran scrcpy, neither of which the installer ships; the full diagnosis with line
references is in [PHONE_SCREEN.md](PHONE_SCREEN.md). The tab now shows the phone's
screen using the webcam's design: a one-use, two-minute offer with an ephemeral
certificate pin and bearer secret for a private LAN address. Saiph Cloud phones
receive the offer as one sealed `session.offer` event (the same envelope, module and
shared vectors as the QR-less camera offers, service `screen`) and show a
notification carrying only the offer ID; a QR code is the fallback. The phone verifies its owner, asks Android's capture
consent every session (whole screen only on Android 14+), and streams bounded JPEG
frames from MediaProjection in a foreground service with a persistent Stop
notification. An opt-in accessibility service, explained before Android's
settings open, injects taps, swipes, long presses, Back/Home/Recents and text into
the focused field during a live session only; without it sessions are view only.
Apps are listed from the phone's launcher query over Cloud (paged sealed
`apps.list` answers to this computer only) or over the live session, and open
through their own launch intents. Pins and Start-menu shortcuts open the phone
screen with that app. scrcpy windows remain under Advanced in the tab.

Older desktops ignore the new `screen.capabilities` event, and the new names never
appear in `phone.capabilities`, which released desktops reject wholesale.

Checks on this branch (synthetic data, isolated environments, no device used):

- Desktop: `tests/test_phone_screen.py` 31 passed (real loopback TLS server with a
  synthetic client, input/launch/app-list messages, refusals, expiry, idle
  timeout, Cloud offer delivery and app-list pages through the sealed relay
  fixture). The full desktop suite (1,137 passed, 54 skipped) had two other
  failures: `test_native_notices` packaged inventory needs the source checkout's
  frontend licence inventory (environmental), and `test_package_updates` Windows
  handoff `[hash]` failed once under load and passed on rerun.
- TLS 1.3 test stalls, root-caused: the camera and screen TLS tests sometimes waited
  5 s and failed (7/30 camera, 5/30 screen connections in probes). The cause is the
  synthetic client, not the servers: CPython's `ssl` sockets are not safe for a
  concurrent recv() and send() under TLS 1.3, and the websockets sync client reads
  the server's post-handshake session tickets in a thread while writing its request.
  A plain client with a reader thread reproduced it against a minimal non-websockets
  server (11/30); sequential TLS 1.3 clients and TLS 1.2 clients did not (0/30). An
  OkHttp 4.12 client on JDK 22 (JSSE, standing in for Android's Conscrypt) completed
  30/30 full-duplex TLS 1.3 sessions against ScreenSession while the server sent
  messages in parallel, with every frame delivered. The servers keep TLS 1.3. The
  websockets test clients for both servers are TLS 1.2 (`tests/lan_tls.py`), and new
  regression tests drive both servers with sequential TLS 1.3 upgrades. Both suites
  passed five times in a row under 12 busy CPU processes, the load that made them
  fail before. The Android screen sender also retries each address once.
- Shared offer format: after aligning with the QR-less pairing branch's envelope
  (13ade91), `tests/test_session_offer.py` and Android `SessionOfferTest` read the
  same 32 vectors (6 screen cases added); desktop camera/screen/offer/Cloud suites
  206 passed; Android 146 JVM tests passed, lint 0 errors / 258 warnings.
- Frontend: vitest 210 passed (new `PhoneScreen.test.tsx`, Apps-tab tests; one run had an
  unrelated Settings timing failure that passed on rerun), `tsc -b`,
  production build and oxlint passed; the existing large-chunk warning remains.
- Android: `:app:assembleDebug :app:assembleBeta :app:testDebugUnitTest
  :core:network:testDebugUnitTest :app:lintDebug :app:lintBeta` with
  `-PorionFirebase=false -PorionIndependent=true -PorionPush=false` passed on JDK 22
  in an isolated Gradle home: 142 JVM tests, 0 failures (new `PhoneScreenTest` 8),
  lint 0 errors / 258 warnings. The beta APK is unsigned; nothing was installed.
  On JDK 17 the same lint tasks crash in lint's Java parser (`NoSuchMethodError`),
  independently of this change.

Not established: any physical phone session, MediaProjection consent and
accessibility behaviour on the Samsung test phone, Android 13+ restricted-settings
handling for a sideloaded tester build, frame rate/latency/thermal behaviour,
the installed Windows app, signing, and independent security review. The real Qt
shell was not driven for this change.

### Physical acceptance checklist (coordinator)

Prerequisites: the phone and computer on the same private Wi-Fi; a signed tester
build of this branch from `scripts/android/build-tester-apk.ps1` (never install a
debug-signed APK over the signed app); a desktop run of this branch signed in to
the test Saiph Cloud account with the phone approved (explicit live test scope).
`$s = '<test phone serial from adb devices>'`.

1. Install and confirm the components:
   `adb -s $s install -r <tester apk>`;
   `adb -s $s shell dumpsys package com.orionmini.mobile | findstr /i "mediaProjection SaiphInputService ScreenShareService"`.
2. Desktop → Phone → Apps: the list fills within about 10 s without adb on the
   desktop. Compare with
   `adb -s $s shell cmd package query-activities --brief -a android.intent.action.MAIN -c android.intent.category.LAUNCHER`.
3. Choose Show phone screen (1080p/20 fps/High). The phone shows "Show your phone
   screen on <computer>?". **On-phone taps:** the notification → Start sharing →
   owner verification (fingerprint/PIN; owner required, never automated) →
   Android's "Start now". Locate the system button with
   `adb -s $s shell uiautomator dump /sdcard/ui.xml` and
   `adb -s $s pull /sdcard/ui.xml`, then `adb -s $s shell input tap X Y`.
4. Confirm the session: `adb -s $s shell dumpsys media_projection`,
   `adb -s $s shell dumpsys activity services com.orionmini.mobile/.ScreenShareService`,
   `adb -s $s shell dumpsys notification --noredact | findstr orion_screen_share`.
   The desktop shows the live screen and "receiving N fps"; record N at each profile.
5. View only: with control off, clicks do nothing and the page says View only.
6. Control opt-in through the UI once: Saiph → Phone screen → Turn on control from
   computer → Open Android settings → Saiph phone screen control → On. If Android
   reports a restricted setting, App info → ⋮ → Allow restricted settings (record
   this). For repeat runs only, preserve the existing list and append:
   `adb -s $s shell settings get secure enabled_accessibility_services`, then
   `adb -s $s shell settings put secure enabled_accessibility_services "<existing>:com.orionmini.mobile/com.orionmini.mobile.SaiphInputService"`;
   restore the saved value afterwards.
7. With control on: tap an icon, swipe, long-press, scroll, Back (Esc), Home,
   Recents; check with `adb -s $s shell dumpsys activity activities | findstr mResumedActivity`.
   Focus a search field and type "synthetic"; check with a uiautomator dump.
8. Open an app from the list during a live session, then from an idle tab (new
   offer with launch), and from a pinned Start-menu shortcut. Repeat once with
   control off: expect the "Open <app>" phone notification.
9. Protected content: open Saiph itself and a FLAG_SECURE app; the desktop shows
   black. Confirm no recording or audio on the desktop.
10. Rotation: `adb -s $s shell settings put system accelerometer_rotation 0` and
    `adb -s $s shell settings put system user_rotation 1`; the desktop shows
    landscape; restore `user_rotation 0` and the previous accelerometer value.
11. Ending: Stop on the desktop, Stop in the phone notification,
    `adb -s $s shell input keyevent KEYCODE_POWER` (screen off), Wi-Fi off, and
    leaving the offer for 2 minutes; each must end or refuse the session on both
    sides and input must stop.
12. Start ten sessions in a row; record any that take 5 s or fail to connect
    (expected none: the earlier stall was a desktop test-client issue, and Android's
    Conscrypt itself is not established by the JVM probe).
13. QR fallback: turn off "Let my computers offer sessions" on the phone, start a
    session, choose Show a code to scan, scan with Saiph → Show phone screen.

## 2026-10-17: Cloud acceptance repairs (in progress)

An additional camera-quality change adds desktop choices for 720p/1080p,
15/20/30 fps and Standard/High detail, defaulting new sessions to 1080p/20 fps
with High detail. Android encodes the normal YUV capture directly to JPEG and
uses fractional sensor-frame scheduling; desktop decode/scaling runs outside
the preview/state lock. The Windows producer and advertised consumer formats
now support actual 1080p. Bounded version 2 invitations carry the chosen profile;
updated Android also accepts older 720p/15 fps invitations. Live diagnostics
separate target settings from source dimensions and measured received FPS.
Synthetic TLS samples sustained approximately 20 fps at both 720p and 1080p.
Both x86/x64 DirectShow checks pass at 720p and with 1080p/20 fps negotiation,
including invalid-frame rejection and Stop blanking. Physical phone capture,
quality comparison, thermal behavior and installed 20 fps acceptance are still
pending; this does not establish sustained physical performance.

The coordinated Windows/Android acceptance campaign has verified native clipboard
paste in both directions, repeated A–B–A text, Unicode, transparent PNG, lossless
WebP, JPEG orientation, malformed-image rejection and the image pixel bound.
Text at the 16 KiB boundary passes; larger text and empty clipboard changes do
not replace the receiving clipboard. These results apply to the designated
Windows/Android devices; Linux physical acceptance remains unavailable.

Packaged desktop defaults now request protected rotating refresh sessions.
Migration changes only an enabled profile matching all four bundled deployment
fields, retaining device identity, approval and explicit sign-out markers.
Native restart and compatible update reconnected without another browser login.
The provider's offline-access, refresh grant and rotation configuration remains
an operations responsibility and must be verified for each deployment.

An attended Windows/Android camera session delivered changing 1280×720 video to
the registered Saiph Camera browser consumer with no audio track. The desktop
preview remained choppy: frame reads incorrectly announced an app-state change,
causing a full dashboard refresh for every frame. Frame reads now omit that
broadcast and poll at 66 ms without overlapping requests. The installed beta27
warm preview passed at 9.7 fps with a simultaneous 1280×720 browser consumer;
a longer preview sample measured 10.2 fps. An initial sample was 7.7 fps, retained
as a startup limitation rather than a guaranteed 15 fps claim. The dedicated phone
Stop button clears the desktop preview and blanks an already-open consumer.
Another fresh session measured 7.2 fps, so cadence acceptance remains open across
starts. Preview scheduling now includes native response time in its 66 ms period
instead of adding a full delay after every response. Synthetic delayed-response,
non-overlap and unmount checks pass; this timing correction still needs an
installed physical retest. Private-LAN loss also clears the preview and blanks
an open consumer, with the phone's original Wi-Fi state restored. Camera
permission, rear-camera and other recovery checks remain incomplete. No video
was saved.

Profiling also found repeated legacy scrcpy/OBS discovery blocking desktop state
snapshots on Windows, independently of capture. Camera status now reuses that
availability probe for 15 seconds and invalidates it when camera preferences
change; starting a legacy capture still validates tools afresh. The same isolated
snapshot workload dropped from about 274 ms to 6 ms. Installed-profile comparison
reduced median native state latency from 327 ms to 68 ms; further interactive and
camera acceptance remains in progress. Visible UI tests now retain normal GPU
settings rather than forcing the offscreen software-rendering configuration.

Dashboard state keeps checking fresh state but sends a small
revision acknowledgement when the dashboard already has identical data. Changed
snapshots preserve unchanged React subtrees, and screen-usage counting no longer
triggers a full dashboard refresh. Phone tab drafts and real connection/permission
changes remain live. Background mouse ripples were removed at the owner's request,
and decorative drawing is bounded to 15 fps idle / 30 fps during loading effects.
The installed Windows build has verified compact replies and removed mouse
listeners. The owner subsequently reported smooth tabs and no flashing after the
desktop repairs. The feedback question named beta25 while beta26 was installed
at reply time; the exact observed intermediate version is uncertain. Final
installed feature regression remains pending.

Further synthetic profiling found that local record-store transactions retained
SQLite connections until garbage collection. Each completed or failed transaction
now closes its connection explicitly, preserving commit and rollback behavior.
The storage, phone, encrypted-transfer and usage regression checks pass on Windows;
this resource cleanup does not establish the cause or resolution of visual flashing.

Further native timing identified recurring tool-discovery stalls when the setup
and legacy camera probes expired. Their periodic refresh now runs on workers;
initial discovery and camera configuration changes retain direct validation, and
starting capture always checks its tools afresh. An older probe cannot replace a
new camera configuration. Installed responsiveness and visual acceptance remain
required; the probes contain availability data, not cached device authority.

Tab navigation also exposed synchronous local-summary counter writes on the GUI
thread. Screen counting now runs on a worker and completes without requesting
another dashboard refresh. Queued events are invalidated when summary counts are
cleared/disabled or anonymous-sharing consent changes, and counting checks the
current choice under its lock. No analytics preference is changed by this repair.
The owner subsequently reported smooth tabs and no flashing; full installed
feature regression remains open.

An installed rendering comparison also found sustained CPU cost from decorative
CSS animation. Status accents settle after one cycle, and modern navigation
receives one underline. Following owner feedback, selected navigation/tab waves
loop continuously again; their painting is confined to the small underline box.
The bounded background field and actual loading indicators remain.
Earlier coordinated one-minute Windows samples, before restoring continuous tab
waves, found that the native process accumulated about
35.6 CPU seconds before the finite accents and 21.2 seconds afterward; memory
and handles remained stable. These are observations on one designated computer,
not a cross-platform benchmark. The installed check also caught a remaining base
legacy underline rule, now excluded for modern navigation. The owner reported
smooth tabs and no flashing after the repairs. The final installed beta27 check
verifies one modern underline, finite settled accents and a visible background.
No graphics-driver diagnosis is established. The installed beta29 check verifies
that both selected tab waves continue moving beyond multiple cycles, each paints
inside its 40×8 underline box, modern navigation has one underline, and reduced
motion disables the waves. The related 39 UI regression checks also pass.

A separate disposable Qt profile also verified that an unreadable synthetic
cached original retains its thumbnail and actions, then opens at 240×160 after
Retry when the local original is repaired. Ten targeted synthetic recovery and
permission tests pass. These checks do not establish physical transfer recovery,
Android permission withdrawal, or the remaining final installed-device regression.

Cloud desktop preview has no automatic release feed. Its update check now reports
manual installation and never contacts retained, inactive Hub pairing. Both the
settings and tray checks use this boundary; Cloud cannot stage a Hub update.
This availability fix does not establish Cloud automatic updates or publication.

Android's external share sheet now selects a current approved Cloud computer.
Incoming Cloud offers are also available under Phone → Share, and successful
explicit saves enter that phone's received-file history. Physical empty-file,
Unicode-name and duplicate-name checks passed, including matching hashes and
preservation of an existing file. The installer retains foreign startup and
invitation associations. The packager now rejects a missing frontend source
lockfile rather than silently omitting its dependency notices.

Sign-in uses the system browser and returns to the app. A styled callback page
attempts to close itself and shows an accepted manual-close fallback when the
browser refuses. No universal browser-close guarantee is made. Full installed
regression, remaining recovery/camera checks and independent security review
remain incomplete. No publication is established by these local results.

## 2026-10-17: owner-installed update and Firebase preparation

The owner requested updating their installed Windows app and distributing the
Android changes through the existing Firebase channel. Planned versions are
Windows 0.1.0-beta.12/build 12 and Android 0.9.7/code 3575000, preserving existing
application IDs, data paths and signing identity. This authorization covers the
local update and Firebase distribution; it does not establish physical camera,
meeting-app, publisher-signing or independent review results. Actual build,
installation and upload receipts belong in the private operations record.

Before Firebase distribution, verify that the existing Auth0 API permits offline
access and the Android native client issues rotating refresh tokens: packaged
Android sign-in requires a persistent grant. No completed provider change or
publication is inferred from this preparation entry.

## 2026-10-17: integrated phone camera (development)

Android now has an explicit foreground CameraX session: scan the computer's
short-lived camera code, choose front/rear, verify the phone's owner, grant
camera access and start. Leaving the camera activity ends capture. The desktop
shows a fitted live preview and Stop. Camera and pairing codes are distinct;
this local session never changes roster trust or account keys. No audio is
captured and no video is saved. Both devices must share a private IPv4 LAN/Wi-Fi;
720p at up to 15 fps is the current target. Remote relay and USB-only camera
transport are not implemented. See [camera design and setup](PHONE_CAMERA.md).

Windows builds include Saiph Camera x64/x86 components derived from pinned
UnityCapture source, retaining upstream notices, source hashes and separate
Saiph class/IPC identities. Per-user registration is handled on first use;
installer upgrade/removal clears only package-hash-proven owned registrations.
Normal camera setup contains no OBS, scrcpy or additional-app installation.
Existing USB/OBS/loopback preferences remain in an advanced legacy disclosure.
Preview is available without the Windows virtual-camera component.

Actual isolated local checks:

- Frontend: 187 tests passed; TypeScript/Vite production build and changed-view
  lint passed. The existing large-chunk warning remains. The React checklist
  was applied to the camera views, polling cleanup, controls and shared QR.
- Python 3.12: affected camera, native-origin, installer and website suites:
  179 passed, 1 platform skip. This includes actual loopback TLS, wrong-secret
  rejection, single-use/replay checks, bounded JPEG parsing and explicit stop.
- Independent Android debug app and instrumentation APK assembly, 21 app JVM
  cases and lint passed (0 errors, 248 warnings).
- A new native Android 34 test passed with generated emulator cameras, exact
  certificate rejection, a paused approval-result lifecycle, CameraX frame
  transmission and release on leaving the screen. Real Qt/native bridge preview
  fitting and session cleanup passed against those frames. The final synthetic
  receiver recorded 126 bounded frames and closed. No physical camera/phone or
  account was used; the test invokes the controller and does not prove biometric
  acceptance. The disposable app/profile, emulator and Qt session were stopped.
- Both compiled Windows architectures passed an actual in-process DirectShow
  streaming graph, per-user registration redirected into a disposable registry
  subtree, camera-name enumeration, frame IPC, bounds and stop blanking. No
  system camera was installed on the owner's PC.
- A local Windows native review build and installer audit passed with both DLLs,
  upstream licence and matching source/hash receipt included. This is an unsigned
  development package; final post-commit artifact receipts are separate.

Initial checks exposed stale third-party UI expectations, a component prop type,
stop ordering, an emulator without cameras, a mismatched test-only debug signer,
test-runner permission revocation and paused ActivityScenario cleanup. These were
corrected and rerun. The first screenshot checks raced the deliberately short
capture interval; a longer synthetic interval passed DOM size/cleanup assertions.
The screenshot captured the already-stopped page, so it is not live-video visual
acceptance. One Python TLS handshake failed during concurrent builds; the final
complete rerun passed. Original logs remain in the ignored feature checkout.

Global Windows registration/installation/upgrade and Zoom/Teams/browser acceptance,
physical-phone performance, publisher signing and independent security/licensing
review remain pending. No Firebase upload, production deployment or public camera
release is claimed. The previous persistent-session Auth0 prerequisite remains.

## 2026-10-16: sharing reliability and desktop settings (source changes)

Approved phones automatically get a three-step sharing setup for photos,
notifications and texts/calls. Android consent and native owner verification
remain required. Activity Result permission requests have an explicit Settings
fallback after denial or when access is already granted. Selected photos can be
reselected. Permission state refreshes on return; locked screens stay protected,
and optional usage consent waits until sharing setup is complete. Recovery resets
the sharing wizard while retaining device keys and trust history. An expired
account has an explicit sign-in screen that retains computer approval.

Packaged Cloud profiles request Keystore-protected rotating refresh sessions.
Existing deployment migration requires every public configuration field to match;
custom deployments retain their choice. Transient refresh failures retry without
discarding the saved account or subscriptions. Before distributing this APK, the
operator must enable API offline access, the native refresh grant and refresh
token rotation. That provider configuration and live account acceptance remain
pending. Existing installs need one new sign-in to obtain a refresh session.

Photo previews use bounded image decoding, up to 384 pixels and 12,000 JPEG bytes,
with adaptive compression inside the existing sealed-frame budget. Originals
retain their on-demand encrypted transfer. Desktop viewers fit previews and
originals in the same frame. Gallery tiles have no filename captions; their
actions overlay the top-right corner and remain keyboard accessible. Cloud
notifications appear on the Phone page, filtered to the selected phone.
Connections and Devices share consistent preference cards and spacing. Pairing
and advanced fields are collapsed when appropriate. Direct phone-camera viewing
uses scrcpy; OBS configuration is optional Windows meeting-app setup. Saving
preferences never starts camera or microphone capture.

Local checks on Windows with isolated profiles and caches:

- Python 3.12: targeted Cloud/gallery suite, 197 passed; subsequent gallery
  boundary suite, 111 passed; camera suite, 31 passed. These commands overlap;
  their counts must not be added together.
- Node 24: final frontend suite, 181 passed. TypeScript/Vite build and lint on
  changed views passed. The existing large-chunk warning remains. The React
  checklist was applied to the changed components.
- JDK 22 / independent Android debug: 18 app JVM tests passed. Network results
  contain 106 tests, 2 optional fixture skips and no failures. Debug APK and
  instrumentation builds succeeded. Lint: 0 errors, 244 warnings.
- Agent-owned Android 34 emulator: 12 native tests passed, covering real Keystore
  refresh storage/rotation and account recreation, exact callback binding and
  pre-upgrade browser-result routing,
  SQLite/key recovery, root navigation, actual permission denial/Settings
  fallback, and bounded MediaStore previews. Synthetic grants never contacted an
  identity provider. This is not physical-phone or live-account acceptance.
- Real Qt shell and native bridge, controlled using `scripts/desktop-ui.py` and
  `.cjs`: gallery hover/menu placement, fitted preview-to-original loading, zoom,
  Connections/Devices navigation, hidden OBS configuration, native camera
  preference saves and folder-button alignment passed. Screenshots were
  inspected. No live camera, microphone or owner app was started.
- Public-data identifier check and `git diff --check` passed. The identifier
  check is not a full credential or history audit.

Initial checks exposed sandbox TEMP virtualization, platform-specific permission
control identifiers, MediaStore returning an undersized cached thumbnail, and
old camera-label/visibility expectations. Isolated TEMP, accessible button
matching, bounded image decoding and updated interaction expectations resolved
those checks. A later emulator System UI ANR interrupted one run; after the
system recovered, all 12 native cases passed again. The release builder also
caught the version-specific JVM fixture, which now expects Android 0.9.6. No
publisher-signed release, Firebase/server upload, physical
acceptance or independent security review is claimed here.

## 2026-10-16: verified Android callback and Cloud gallery update

Android 0.9.5 uses `https://usesaiph.com/android/oauth2redirect` through AppAuth with an exact verified App Link filter; its existing custom scheme remains for pre-upgrade in-flight attempts. Pending state, redirect, PKCE challenge and endpoints are bound before code exchange. The static website includes the existing beta certificate association and a minimal no-analytics/no-store callback fallback which clears query/fragment from browser history. Auth0 allowlisted the callback at the owner's request; Google connection/branding is unchanged. Actual domain verification and final publication results belong in the private operations record.

Cloud phones now offer an explicit Allow photos choice, separate from Texts and calls. With Android photo permission, up to 100 recent previews and their metadata travel in sealed envelopes to current subscribed computers. Original photos use the existing streaming-encrypted blob path only after an explicit open/copy/save request, bound to that request and recipient. The desktop reuses its existing Photos and Messages galleries; other apps' chat histories and MMS are not added. The bottom-right footer reads the installed distribution version. Visible app, account and website wording now uses Saiph Cloud; internal Hosted identifiers and routes remain compatible.

Actual local checks: five native Android instrumentation tests passed (callback state/PKCE/replay/expiry, legacy in-flight compatibility, exact manifest routing, and real MediaStore/permission/opt-in bounded previews). Earlier source checks passed app JVM/lint with 0 errors and 240 existing warnings. Desktop regression checks passed 236 cases except the new wrapper test's initially wrong synthetic TTL, corrected and rerun in the 169-case passing file/phone suite. The final combined desktop/gallery run passed 238 cases. Native Qt control/navigation/form persistence and bottom-right development-version layout passed in a fresh isolated shell. Frontend 178 tests and production build passed. Account 79 tests and typecheck passed; build first hit a local Next telemetry config EXDEV error, then passed with telemetry disabled and isolated config. Website 183 checks passed after excluding the callback from analytics-loading expectations. Original logs retained. Final build receipts will record later checks separately.

These are synthetic unit, emulator and native-shell checks, not physical-device acceptance, completed live Google login, independent review or trusted Windows signing. The existing friends-beta signing identity is preserved.

# Current release preparation status

2026-10-16 Cloud connection follow-up: user-facing service labels now say Cloud;
technical Hosted identifiers and stored formats are unchanged. Android shows an
in-app Back arrow only for nested Settings and security-code comparison screens.
Primary retry/recovery sign-in selects Google; other providers remain explicit.

An actual Android 14 emulator reproduced the enrollment failure in
AndroidHostedTrustStore.create after protected key creation. The code executed
the row-returning journal_mode PRAGMA through execSQL; the platform WAL API now
enables journaling before creating the schema. A failed old setup can explicitly
restart with a fresh device ID, preserving its earlier protected key/trust files
and account sign-in. Established checkpoints are never silently reset or repaired.

Checks: three Android instrumentation regressions passed with real Keystore and
SQLite: key reload/enrollment, synthetic root-signed approval and encrypted
exchange/inbox retention, failed-setup restart preservation and nested Back.
Debug assembly, 14 app JVM tests, 103 network JVM tests (2 optional interop skips)
and lint passed (0 errors, 240 warnings). Desktop targeted checks passed 152 tests
with 3 platform skips; frontend 177 tests and its production build passed. The
real Qt control/layout flows passed in an isolated profile. Initial attempts had
a missing Python temporary-directory parent, sandbox denial of the npm cache and
an unescaped SDK drive separator in ignored local.properties; these were fixed.

A live anonymous native authorization probe returned HTTP 302 directly to Google.
This is routing evidence, not completed sign-in. Auth0's extra authorization or
impersonation-confirmation screen remains provider work: native custom schemes
and desktop loopback callbacks can require it. Verified HTTPS callback setup,
provider consent configuration and development-key branding are not fixed by
the Google connection parameter. No live account/physical phone acceptance or
independent security review is claimed by these checks.

2026-10-16 Android connection recovery and desktop preferences follow-up:

Android distinguishes saved identity intent, interrupted setup, pending approval
and prior verified approval. A saved device ID or a status string cannot open
daily use. Comparison stays visible until its action finishes; duplicate actions
are refused, failures appear inline and interrupted setup has an explicit recovery
route that retains protected keys and trust history. Pending requests retry the
same identity at most every 30 seconds. Previously approved devices are not
automatically re-enrolled. Existing installs can restore their navigation state
from a verified saved root-signed roster containing their exact public keys;
this never activates an expired roster or authorizes content.

After sign-in, Back exits setup instead of opening the welcome menu. Approved
phones open daily use; account, subscription, permission and connection controls
live in Settings. First-use privacy acknowledgment is separate from usage consent
and feature permissions, including the self-hosted invitation route. Detailed
text/call privacy and limits now live at `account-privacy.html#app`, with short
scope and audio descriptions beside the phone opt-in. Publish that updated notice
alongside the Android update; this work did not deploy it.

Desktop sign-in offers Google directly through the Auth0 connection parameter,
with an explicit fallback for existing email/provider accounts and unchanged
custom issuers. No Auth0 tenant, Google credentials or consent branding was
changed. The installer refuses removal of a running owned executable or locked
release files before deleting files, and displays the reason in its main panel.
The Explorer option explains the right-click / Send to path. Cloud and General
preferences use consistent spacing and shorter copy; Your week is a visible
local summary with seven daily counts, rather than a collapsed disclosure.

Checks on Windows with isolated profiles and caches:

- Python 3.12: targeted hosted login/session/runtime, account boundary, insights,
  native distribution and website release tests passed: **227 passed / 4 skipped**.
  The skips cover platform-specific checks; these are not physical acceptance.
  The native installer fixture also executes a synthetic owned app and holds a
  release file open, checking that refusal preserves the installation marker and
  files. After the options-surface adjustment, distribution tests passed again:
  **11 passed / 1 skipped**.
- Node 24: `npm run test:unit -- --maxWorkers=2` passed **177 tests**;
  `npm run build` and targeted `npm run lint` passed. The existing large-chunk
  build warning remains. The React skill checklist was applied to changed views.
- `scripts/build-native.py --profile link --version 0.1.0-ui-review.1`, run from
  an isolated source/dependency copy with separate work/dist/cache paths, built
  the Windows native bundle and passed its native input-origin audit. It is an
  unsigned local review build, not a release or clean-machine acceptance result.
- The real Qt shell was driven using `scripts/desktop-ui.py` and `.cjs` in a new
  isolated session. Both `desktop_control_smoke.cjs` and the new
  `desktop_layout_smoke.cjs` passed: navigation, native settings persistence,
  Cloud path save, seven-day chart from a synthetic local SQLite fixture, summary
  on/off and deletion of local counts. Screenshots were inspected; no page errors.
  The first session stopped at its configured timeout; a final fresh session
  passed both flows again and was stopped through the controller. No installed
  owner app was used.
- A temporary Robolectric 4.14.1 / API 35 UI harness passed **13 checks**, including
  an actual enrollment failure on a JVM without Android Keystore, retention of
  identity intent on retry, readable recovery, account/approval separation,
  first-use policy choice, daily-use navigation and sign-in parameters. It used
  synthetic memory tokens and keys and did not start live services. The harness
  dependency and source were removed from the isolated product build afterward.
- Product Android checks use JDK 22, isolated SDK preferences, Gradle home and
  source tree, Firebase/push disabled, independent mode and version code 1:
  `:app:assembleDebug :app:testDebugUnitTest :core:network:testDebugUnitTest
  :restic-android:testDebugUnitTest :app:lintDebug --no-configuration-cache
  --no-daemon --max-workers=2`. The debug APK built successfully; **14 app,
  103 network and 47 restic JVM tests passed**, with 2 optional Python/Kotlin
  interoperability tests skipped because no fixture was supplied. Lint reported
  **0 errors / 239 warnings**. Existing pinned restic native libraries were reused
  from the earlier isolated Android check; they were not rebuilt or accepted on
  a phone by these checks.
- `scripts/public-release/check-public-data.py` passed its limited reviewed-token
  check; `git diff --check` passed. Neither is a complete credentials audit.

Initial check attempts included a wrong pytest file path, missing isolated Hub
dependencies, temporary-directory setup errors and a native source-copy build
without its frontend dependencies. These were corrected. The added installer
regression first exposed the early ownership-hash file-lock error; it now maps
to the visible quit/retry message. A Windows path separator error in the new
fixture was also corrected before the passing rerun.

No physical phone, installed-app upgrade/uninstall, live Google/account handoff,
production service, publisher signing or independent security review was tested
or operated. The debug APK uses an isolated development signing profile and is
not an update artifact for an existing publisher-signed installation.

2026-10-16 Android visual onboarding (source changes only): first install now
opens one illustrated welcome screen with Subscribe, Continue with Google and
a quiet Self-host instead route. The launcher no longer leaves a second sign-in
page beneath it. Plans open on the public website; prices and checkout are not
duplicated in the APK. Account → Scan → Approve steps use shared vector artwork,
short instructions and reachable welcome/scan action docks. Illustrations animate
only while visible and respect disabled system animations; enlarged text puts
the task ahead of decorative artwork. Paste-code and Hub-invitation options remain.
Hub setup has a Back arrow and an arrow-labelled Back to Saiph action; header
and Android Back agree. Activity reuse and rotation retain the intended route.

The normal Auth0 authorization request passes `connection=google-oauth2` to skip
the intermediary provider picker. Existing email/provider accounts retain Other
sign-in options, custom non-Auth0 issuers retain their original parameters, and
approved phones reuse the sign-in method recorded with their last accepted grant.
State, PKCE, redirect/audience validation, full security-code comparison, native
owner verification, pairing formats and identities remain intact. Auth0's Google
connection must be enabled for the native client; Google credentials and consent
branding (including any development-key branding) are private service operations
and were not changed here. No live provider handoff was tested.

Windows / JDK 22 / Android SDK 37.0, isolated source tree, Gradle home and temporary
profile: `:app:compileDebugKotlin :app:testDebugUnitTest :app:lintDebug` passed with
`-PorionFirebase=false -PorionIndependent=true -PorionPush=false
-PorionVersionCode=1 --no-configuration-cache --no-daemon --max-workers=2`.
11 JVM tests passed; lint reported 0 errors / 234 warnings. A separate temporary
Robolectric 4.14.1 / API 35 native-layout harness passed 10 checks: welcome/plan
intent, 320 dp and doubled text, Scan/Back/Continue without another sign-in,
approval code/identity retention, reused welcome and rotation, AppAuth request
state/PKCE/redirect/audience, accepted-provider preference and stale-grant refusal,
explicit Hub switching, Hub Back handler and locked navigation. Native renders
were inspected. The Hub handler check bypassed Hilt startup and does not establish
a full live Hub Activity/mesh flow. The harness and its dependencies were removed
from the isolated copy before final product checks; its SSH service-loader
exclusion applies only to the temporary UI harness. Existing generated restic
libraries were reused. `git diff --check` and the public-data check passed,
including new source files. No distributable APK was assembled, signed, installed
or released; no emulator, physical phone, account, browser or service was used.
Live Google sign-in, provider branding and physical acceptance remain pending.

2026-10-15 UX review follow-up (source changes only). Desktop: the Phone tab's
connection wizard watches for the phone's request on the Scan step and moves to
Approve by itself, with Continue to approval kept as a fallback and Back to
scanning holding on requests already seen; after approval it waits for the phone
to connect, names it when it does, and leaves the Phone page to Done. An empty
quick-controls card no longer renders for a Hosted phone, Settings → General
shows its Connect a phone shortcut only until a phone is connected, and the
optional guide starts at Choose features on a connected computer. Android: the
account-or-Hub choice appears once (the self-hosted home screen), the account
sign-in screen offers self-hosting as one secondary action, the connection
screen offers Sign out before approval, disclosures are quiet text rows with a
chevron, Hosted Settings run Account → Sharing permissions → Connection → This
phone → Security, the computer security-code comparison is an in-app themed
screen (grouped monospace code, Cancel, Every group matches through owner
verification, kept across rotation), received files redraw by themselves, and
people-facing copy says "Saiph account". Pairing, identities, permission
opt-in, explicit approval and owner verification paths are unchanged.

Windows / Node 24, isolated caches: frontend `vitest run` passed 177 tests
(four wizard tests rewritten or added), `tsc --noEmit` and oxlint on the changed
files passed. The Vite onboarding preview (`/onboarding.html`, synthetic client)
was walked through sign-in → set up → Scan auto-advance → Back to scanning hold
→ Approve → waiting → connected → Done → Phone page → Settings → guide at
Choose features, with no page errors from the final code. Windows / JDK 22,
SDK 37.0, isolated Gradle home: `:app:compileDebugKotlin :app:testDebugUnitTest
:app:lintDebug` passed with `-PorionFirebase=false -PorionIndependent=true
-PorionVersionCode=1 --no-configuration-cache --no-daemon`; 8 JVM tests passed
(`SaiphPaletteTest` included) and lint reported 0 errors, 232 warnings. The
only compiler warnings on the changed files are the pre-existing parameter-name
and deprecated-permission-callback notes. `git diff --check` and the
public-data check passed. No native desktop
installer or APK was assembled, installed or released; the Qt shell, a live
account, an emulator and a physical phone were not used for these checks.
Physical-device acceptance and independent security review remain pending.
2026-10-16 landing release: compact home, prominent downloads and Hosted card,
Account navigation, public-page analytics and sourced capability comparison.
Hosted texts and call controls are included in the released beta source; the
old "Coming" / "self-hosted only" labels were corrected. Physical acceptance
remains pending. This publication retains current checkout prices; the requested
price increase awaits a coordinated billing release. See the
[release record and validation](WEBSITE_RELEASE_2026-10-16.md).

2026-10-15 native desktop UI control (development tooling only): added a
disposable Qt launcher and a Playwright controller for accessible snapshots,
tabs/buttons, form entry, checkboxes/selects, keyboard input, screenshots and
reusable local test flows. The instance has its own data, browser-cache/storage
and temporary directories. Its debug endpoint binds to loopback, and the
controller verifies the dashboard and a per-session window marker before acting.
Clean shutdown is scoped to that session. Normal app startup and the existing
local automation API are unchanged. `AGENTS.md` and `docs/TESTING.md` direct
future agents to use these tools for routine desktop interaction. Explicit live
mode enables real services in a fresh test profile; native owner verification
and external-provider sign-in are preserved.

Windows / Python 3.12.10 / PySide6 6.12.0 / Node 24.18.0, isolated environment,
dependency caches and profiles: `python -m pytest tests/test_desktop_ui_control.py
tests/test_automation.py -q` passed 13 tests; `node --test
tests/packaging/desktop_control_session.test.cjs` passed 1 test. The native
`desktop_control_smoke.cjs` flow passed both without and with the Hosted extras
installed: Settings tab navigation, typed/saved computer name, on-disk native
bridge persistence, Phone setup navigation, mismatched-session refusal and
screenshots, with no page errors. Individual CLI click/fill/save/screenshot/stop
commands also passed, and the session reached `stopped` with the typed name
retained in its isolated profile. The previously validated production frontend
build was reused; no frontend implementation changed. Initial restricted Qt
launches aborted before WebEngine became ready; a scoped permitted launch
resolved this without disabling Chromium's sandbox. Qt logged GLES context
fallback errors while the native UI and screenshot checks succeeded.
No installed app was restarted, installed or modified. No real account/service,
physical device, OS owner-verification prompt, native file picker or live mode
was exercised. These are native isolated UI checks, not installation, Hosted
connection, cryptography or physical acceptance evidence.

2026-10-15 connection wizard follow-up (source changes only): the Phone tab,
add-phone dialog and optional guide now share an Account → Computer → Scan →
Approve wizard. Each screen has one task; Scan shows the QR automatically and
Continue opens approval. Back returns to scanning and clears the reviewed
request and comparison. Scan/approval navigation moves keyboard focus to the heading;
successful approval has a completion screen, while actual connection still
depends on the native phone state. The scan screen keeps the full-size QR and
full security code together and fits the main action in the reviewed desktop
viewports. Desktop and mobile design-system rules now require guided connection
steps. Native trust, owner verification and pairing formats are unchanged.

Windows / Node 24.18.0, isolated frontend dependencies/cache/TEMP/TMP:
`npm run test:unit -- --maxWorkers=2 --reporter=json
--outputFile=../wizard-unit-results.json` passed 175 tests. `npm run build`
passed TypeScript and production bundling with the existing 500 kB chunk-size
warning. Targeted Oxlint, React component review, `git diff --check` and the
public-data check (including new files) passed. Synthetic headless
Chromium checks passed the full wizard journey, returning to Scan and requiring
a fresh comparison, keyboard focus, the Settings shortcut, closing the QR
dialog, and layouts at 1280×1000 and 1024×768 without horizontal overflow or
scrolling to find Continue. No browser page errors occurred. These checks use
the dev-only simulated account/phone preview; real OAuth, Hosted service, native
owner verification and physical scanning were not exercised. No Android code
changed in this follow-up; Android checks were not repeated. No installer or APK
was assembled, installed, signed or released. Physical acceptance and independent
security review remain pending.

2026-10-15 desktop/phone connection flow (source changes only): a fresh desktop
opens connection setup in the Phone tab. It guides account sign-in, explicit
main-computer setup, QR scanning and device approval, then shows the connected
phone. The add-phone dialog and optional setup guide reuse the same Hosted flow;
Settings links to Phone instead of presenting a second pairing workflow. Manual
codes, connection details and device-management data are expandable. Android
points to Phone and calls fingerprints security codes, while retaining full
computer/device comparisons and owner verification. No identity, signing,
pairing format or native trust protocol changed. A late manual request inspection
can no longer replace a newer reviewed request or its comparison state.

Windows / Node 24.18.0, isolated frontend source/dependencies/cache/temp:
`npm run test:unit -- --maxWorkers=2 --reporter=json` passed 173 tests;
`npm run build` passed TypeScript and production bundling, with the 500 kB chunk
size warning. Initial test startup failed on sandbox temporary-file paths;
workspace-local TEMP/TMP resolved it. Changed visibility expectations and the
connected-phone fixture were corrected before the clean full run. A headless
Chromium check of `/onboarding.html` passed the simulated sign-in → QR → request
→ full-code confirmation → approval → connected-phone journey, the Settings
shortcut, closing the QR dialog, and 1280/1024 px widths with no page errors.
Every account, request and QR in that preview is synthetic; it does not contact
a Hosted service or exercise native account sign-in or owner verification.
Android JDK 22 checks in the isolated copy passed `:app:compileDebugKotlin
:app:testDebugUnitTest :app:lintDebug` with independent/Firebase/push-disabled
settings and version code 1: 8 JVM tests, lint 0 errors / 234 warnings.
Oxlint on changed TSX files, the React component review, `git diff --check`
and the public-data check passed, including the new source files.
No native desktop installer or APK was assembled, signed, installed or released.
Physical-device acceptance and independent security review remain pending.

2026-10-15 Android layout rework (source changes only): account and self-hosted
setup now use matching cards with short descriptions and full-width actions.
Shared controls use a consistent type scale, sentence-case section headings and
button rows that stack when labels cannot fit, including at larger font sizes.
Hosted daily use now focuses on files, texts and calls; account, permissions,
connection and device details live under Settings. Texts and calls have separate
icon rows, visible approved-computer scope and expandable privacy/limit details.
The existing palette, gradient actions, background, permission opt-in and owner
verification paths are retained. Refreshing a Hosted page keeps its scroll position.

Windows / JDK 22, SDK 37.0, isolated source copy and Gradle cache:
`:app:compileDebugKotlin :app:testDebugUnitTest :app:lintDebug` passed with
`-PorionFirebase=false -PorionIndependent=true -PorionPush=false
-PorionVersionCode=1 --no-configuration-cache`; 8 JVM tests passed and lint
reported 0 errors, 234 warnings. Initial lint failed on the temporary copy's
Windows SDK property escaping; it was corrected and lint analysis rerun without
build-cache reuse. A temporary Robolectric 4.14.1 / API 35 native-layout harness
passed 6 checks covering 320 dp width, doubled font size, button reflow,
disclosures, Settings/Back, the self-hosted route and locked-screen navigation.
Its initial API, SSH service-provider classloader and fixture/lifecycle failures
were corrected; SSH was excluded only from that UI harness's runtime. Native
synthetic screen renders were inspected. The harness and its dependencies were
removed from the validation copy before the final product checks; no product
dependency was added. Existing generated restic inputs were reused for validation.
`git diff --check` and `check-public-data.py` passed. No APK was assembled,
signed or installed; no emulator, physical device, real account or Hosted service
was used. Physical acceptance and independent security review remain pending.

2026-10-15 device approval without typing codes: a phone or second computer that
has scanned the main computer's code now also offers its signed request through
the service (`POST/GET /v1/devices/approval-requests`, bound to the pending
candidate's keys, expiring with it, signature checked). The main computer lists
offered requests, verifies each against its own pinned root and shows the
fingerprint; the owner still compares every group and approves explicitly, and
pasting stays as a fallback. Older services answer 404 and clients fall back to
pasting. The setup guide confirms the sign-in, moves on after Set up this
computer, shows the computer's code without another click and folds pairing away
once a phone is approved. Android shows one waiting screen until the computer
approves the phone, then moves on by itself; sharing permissions appear only
after approval. A dev-only onboarding preview (`frontend/onboarding.html`)
walks the desktop flow on a simulated account. Checks: Hub hosted tests 123,
desktop Hosted tests, frontend unit tests and `tsc`, Android `:core:network`
and `:app` unit tests with `:app:compileDebugKotlin`.

2026-10-15 Hosted onboarding correction (`codex/hosted-onboarding`, based on
`ca36587`, source changes only): a fresh desktop profile now reads validated
bundled public connection defaults without importing the crypto runtime or
creating keys. The wizard and account settings offer one Sign in to Saiph
action that enables the selected connection and opens the system browser.
Packaged account setup no longer asks for service URLs or client IDs. Android
opens the account screen directly, puts sign-in ahead of approval and permission
controls, and offers a regular-browser retry through AppAuth. Device identities,
state/PKCE checks, full fingerprint confirmation and explicit device approval
are retained. Windows beta.5 setup and Android browser trouble were reported by
the owner; see [the attended attempt](ACCEPTANCE_PENDING.md#attended-hosted-setup-attempt-2026-10-15).

Validation on Windows, Python 3.12 / Node 24.18.0, using synthetic profiles and
separate caches: `python -m pytest tests/test_hosted_distribution.py
tests/test_hosted_runtime.py tests/test_setup_guide.py tests/test_link_service.py
-q` passed 75; frontend `npm run test:unit` passed 164 and `npm run build`
passed. The first Python run failed the existing lazy-import boundary test;
reading defaults was moved to the lightweight distribution module, and the
full selected set passed on rerun. Initial npm cache and test-runner temporary
file access failures were resolved in the isolated clone. Android compilation
(`:app:compileDebugKotlin`) and app JVM tests (`:app:testDebugUnitTest`, 8 passed)
passed on JDK 22 with independent Firebase/push-disabled settings, version code
1 and an isolated Gradle cache. `:app:lintDebug` passed with 0 errors and 233
warnings. Initial Android checks could not find the SDK at the configured path;
an existing SDK was located and the existing ignored restic ABI binaries were
copied into the validation clone. Lint first rejected that clone's SDK property
escaping; the property was corrected and stale generated analysis was rerun
with build-cache reuse disabled. No corrected installer/APK has been built,
installed or distributed; the exact reported browser failure and physical
acceptance remain open. No real account, emulator or physical device was used
for these checks.

Review fixes on the same branch (2026-10-15): an approved phone keeps its daily
screen and keeps syncing when its short-lived account token has expired (the
sign-in screen is only for phones that are not yet approved; signing in again
stays available under Account). Android checks for app updates again before the
self-hosted pairing check. The runtime validates bundled connection defaults
before use. Setting up or joining with an account that has not redeemed an
invitation now says to activate the invitation instead of "unreachable", and the
desktop sign-in card points new testers to their invitation. Turning Hosted back
on keeps an existing desktop sign-in instead of reopening the browser. Hosted
desktop tests 81 passed, frontend unit tests and `tsc` passed.
The actual Windows `scripts/build-native.py --profile link --version
0.1.0-onboarding.1 --build-number 0 --hosted-config build/synthetic-hosted.json`
build passed, including the native-origin audit, with separate PyInstaller
cache/output and synthetic connection settings only. A new synthetic profile
read those built bundle defaults with Hosted off and no Hosted keys. The
executable was not launched, packaged as an installer or offered for account
sign-in. Candidate staged changes and public main history passed gitleaks;
the isolated clone passed `check-public-data.py --history`.

2026-10-14 the repository is public. The owner changed visibility after a fresh
audit clone of every GitHub branch passed `check-public-data.py --history` and
gitleaks; five fully merged branches were deleted first. `main` requires pull
requests with the DCO `sign-off` check (administrators may bypass); `production`
only moves by maintainers and cannot be force-pushed or deleted. Actions are on
with read-only tokens and approval for all external contributors' runs.
Private vulnerability reporting, secret scanning with push protection and
Dependabot alerts are enabled. The independent review of friends-beta mode was
not done before publication. The `Saiph checks` workflow has not yet run on
GitHub; make its jobs required once they pass.

2026-10-14 desktop executable rename: branch `feat/desktop-saiph-executable`
renames the desktop executable from `OrionMini.exe`/`OrionMini` to
`Saiph.exe`/`saiph` (PyInstaller bundle `dist/Saiph/`). Shortcuts, Send to,
the startup entry, the enrollment association and the Linux launcher now run the
new name; an upgrade moves beta.4 entries over. Packages still carry a
byte-identical `OrionMini(.exe)` because installed 0.1.0-beta.4 updaters and the
deployed Hub require that name. Install/data folders, registry and desktop-entry
names, the AppUserModelID and the `orion/` archive prefix are unchanged. Checked
on Windows 11, Python 3.12 venv: `verify-public.py` 1330 passed, 58 skipped
(a first run had 1 timing failure in `test_phone_features` while the Hub suite ran
alongside; it passed alone 3/3 and in the clean rerun); Hub 549 passed, 6
skipped; frontend 161 passed; Windows installer tests including a synthetic
beta.4-to-renamed upgrade, ownership and rollback probe. Linux installer, setup
and updater-handoff tests passed in a `python:3.12.14-slim-bookworm` container
(not a desktop session). `build-native.py --profile link` plus the Windows
packager built an unsigned `0.1.0-rename.1` test installer: version info names
`Saiph.exe`, the copy is identical, the current updater and the frozen beta.4
updater (`tests/fixtures/legacy_package_updates_beta4.py`) both accept it, and an
`--isolated` install/uninstall into a test folder succeeded. Not done: launching
the built app, a real (non-isolated) beta.4 upgrade with shortcuts and startup on
Windows or Linux, a Linux native build, signing (`signpath-app.xml` now names
`Saiph.exe`; SignPath is still unconfigured). Not released or deployed.

2026-10-14 deployment and publication preparation: the shared Hosted service
runs the security release `b1fd50b` and serves the 0.1.0-beta.4 desktop catalog
(operations record). The landing and account sites now deploy production only
from the `production` branch (created at `fa9b063`); `main` builds protected
previews, and fork pull requests need maintainer authorization in Vercel. A
fresh audit clone of GitHub plus local `main` passed
`check-public-data.py --history` and gitleaks (files and all history). Still
open before changing visibility: owner approval, independent review of
friends-beta mode, and enabling branch rules, private vulnerability reporting,
secret scanning and Actions with fork-PR approval right after the switch
(private free repositories cannot use them). Paid Hosted remains disabled; its
gates are tracked separately.

2026-10-14 paid Hosted entitlement: branch `feat/paid-hosted` connects verified
Stripe subscriptions to Hosted access ([design](PAID_HOSTED.md), agreed with the
owner). After a signed webhook, the account website pushes an Ed25519-signed
grant to a new `POST /v1/billing/grant` on the Hosted service, stored as a
`paid` grant beside beta codes; pushes are ordered by sequence, capped at 45
days by the service and rolled forward 35 days at a time by a daily cron. Plans
€3.99/month and €36/year; 3-day grace after a failed payment; open chargebacks
end access; sandbox checkout stays owner-only. Account page shows access source,
subscribe and Manage billing. Migration 0003 is additive. Actual local results
on Windows (Node 24.18.0, Python 3.12, Docker `postgres:16-alpine`): account
`npm test` 69/69 (DB suites skipped there), `npm run test:billing-db` 41/41,
typecheck, production build, HTTP smoke (30 checks) and beta HTTP smoke passed;
Hub full suite 572 passed, 6 skipped (29 new). Nothing is deployed: migration 0003 is
not applied to the development Neon database, no webhook endpoint or sandbox
prices exist for it, and no real Stripe sandbox run has reached the Hosted
service. Live payments stay off; owner-only activation steps, service readiness
and an independent review of the push endpoint remain.

2026-10-14 Hosted texts and calls: branch `feat/hosted-texts-calls` adds SMS
threads, replies, new texts, call alerts, answer/decline, dialing, contact
search and recent calls to Saiph Hosted inside the existing sealed envelopes,
with no hosted service change. Any approved computer that subscribes may act
(calls first come, first served on the phone); actions need a new phone-side
Texts and calls switch (off by default) plus Android permissions. A second
computer joins an account as a member (branch `feat/hosted-second-computer`):
it pins the main computer's code after a full fingerprint comparison and is
approved there; it never signs or renews rosters. Covered by
desktop, frontend and Android JVM unit tests only; physical-device acceptance
([beta steps 10-12](HOSTED_FRIENDS_BETA.md#test-sequence)),
a release and independent review are pending. Not deployed or released.

2026-10-14 phone webcam without a Hub: branch `feat/hosted-webcam` lets the
desktop phone camera use a phone allowed over USB or Android wireless debugging
(pairing code on the local network), so Saiph Hosted users no longer need a
self-hosted paired phone. It adds a camera preview for OBS setup, scrcpy 2.2 and
Android 12 checks and plain setup guidance. Synthetic unit tests only; the
0.1.0-beta.4 installers do not contain it. scrcpy, adb, OBS and v4l2loopback stay
user-installed. Physical acceptance on Windows and Linux is pending.

2026-10-13 account security: [account and device controls](ACCOUNT_SECURITY.md)
are in source with synthetic tests — Windows Hello before device changes,
device-list alerts on desktop and Android, Android biometric confirmation and
optional app lock, enforceable second-factor claims for the Hosted service and
account website, and an administrator workspace reset. They need a release and
physical acceptance; second-factor enforcement waits for a paid Auth0 plan and
stays off until configured. None is deployed.

2026-10-12 security update: [four hosted security fixes](SECURITY_FIXES_2026-10-12.md)
are prepared in source with offline regression tests. Updating installed desktop
and hosted service releases, production load checks and off-host recovery remain
separate work; this entry does not claim a deployed remediation.

2026-10-13: a hosted service bundle from `b1fd50b` (the four fixes plus beta-code
lockout protection) and desktop 0.1.0-beta.4 installers from `bf7105c` are built
and verified locally. They are not deployed yet; the hosted service still runs a
release from before the fixes. Deployment, restricted account sign-up and an
independent review of friends-beta mode must finish before this repository is
published.

2026-10-11. Reliability, Linux packaging/updater, desktop pairing QR, independent
Android beta, development website and guarded sandbox billing work are integrated
on private main. See [the integration record](INTEGRATION_2026-10-11.md).
Repository separation and passing unit checks do not establish release readiness.

- Earlier source snapshots passed their recorded boundary checks and secret scans.
  The current identifier scan passes, but private identifying fixtures remain in
  Git ancestry. Public publication requires reviewed clean export history and a
  passing secrets-history scan; deleting current fixtures does not clear history.
  The repository-wide secrets-history job remains owned by the product chat.
  Desktop unit checks, synthetic Hub checks and dependency audits have their own
  evidence; CI now runs while the repository is private.
  Unit suites and audits run on pushes/PRs; native installer packaging is an
  explicit workflow-dispatch check. Routine dependency version PRs are disabled
  during the initial audit; vulnerability alerts remain enabled.
- An earlier isolated Android source build failed at `:domain:compileDebugKotlin`
  with a serialization compiler plugin `NoSuchMethodError`; its log was not kept.
  It did not reproduce: clean CI builds on `8cc0606` and on the reliability
  branch, and a local owner build of 0.8.6, completed the debug APK, the app,
  network and restic JVM tests and lint. The cause is unexplained, not fixed.
  No generated APK or signing key is stored in this repository.
- Windows unit CI failed 31 hosted key/attachment tests because elevated tokens
  (GitHub's `runneradmin`) make `BUILTIN\Administrators` the owner of new
  objects; private material now sets the user as owner with its owner-only DACL.
  Verification of existing objects is unchanged.
- Public builds create no default delegate grants. Explicit owner configuration
  selects validated names/scopes; the scoped CLI requires a credential file.
  Owner-source legacy adoption is removed, while generic token-hash attribution
  remains. Link does not run the Workspace delegate broker.
- Public Windows signing is not configured. Native source obligations, dependency
  notices and compatible Qt replacement evidence remain release gates.
  2026-10-11: SignPath Foundation chosen (application not yet made; Azure Artifact
  Signing is unavailable to individuals in Ireland, Certum is the paid fallback).
  A maintainer-started `Signed Windows release` workflow is wired but unrun and
  refuses to start without SignPath configuration. Fixed: a signed installer could
  not find its payload. Checked locally only: a synthetic installer signed by SDK
  SignTool with a throwaway self-signed certificate installed in isolation, and
  unaligned or appended files were rejected. No trusted certificate, CI signing
  run, clean-machine install or SmartScreen result exists.
- Physical-device recovery, upgrade/pairing retention and prolonged stability
  remain acceptance work. A repository reorganisation does not fix device bugs.
  2026-10-11 owner phone/Windows checks (private record) passed repeated
  clipboard delivery in both directions, no clipboard echo, idle Hub CPU under
  5%, an in-place Android upgrade retaining pairing, a single verified photo
  Save after repeated clicks and notification dismissal on both devices. The
  stale-session replacement path was not exercised physically. A same-day
  attended Linux laptop/phone run on internal source (private record) passed
  text clipboard both directions with owner confirmation, one earlier
  phone-to-laptop mismatch still unexplained; laptop image, file and
  notification cases and seven-day stability remain open.
- Hosted steps 1-6 have development preview source on `feat/hosted-user-flow`,
  behind an off-by-default setting. See [scope and verification](HOSTED_PREVIEW.md).
  Physical-device and deployed identity-provider/relay acceptance and independent
  security review remain pending; this is not paid/public Hosted launch approval.
- The informational landing page is deployed at `usesaiph.com`. The account
  website moved to `account.dev.usesaiph.com` on 2026-10-12 and runs in
  friends-beta mode: sign-in plus a single-use beta code, with billing disabled.
  Its custom domain is public (Vercel Standard Protection); preview and
  deployment URLs still need a Vercel team login. Real browser login on the new
  domain is not yet verified. Public waitlist and checkout remain disabled.
- Account website security to do: limit or protect Auth0 sign-up (Attack
  Protection or invited emails only); independent review of friends-beta mode.
  Since `b1fd50b` the global code-redemption limit only throttles failed
  attempts, so other accounts can no longer lock out a valid code once that
  service release is deployed. The account site already sends a nonce-based
  Content-Security-Policy and redirects alias hostnames to the single canonical
  account origin (POSTs to aliases are refused); confirm both on the live site.
  Guarded Stripe sandbox checkout/webhook and durable billing code is integrated,
  but production activation, database migration and real provider acceptance are
  incomplete. Paid Hosted launch retains company, policy, payment and security
  conditions.
- Billing lifecycle (branch `feat/billing-lifecycle-acceptance`, 2026-10-11):
  migration 0002 adds `cancel_at`, customer/subscription indexes and an
  append-only event ledger. Sandbox billing standing comes only from
  subscription rows saved by the webhook (`lib/billing/entitlement.mjs`),
  never from the checkout return. Actual local results on Windows, Node 24.18.0,
  Docker `postgres:16-alpine`: `npm test` 34/34 passed (DB suites skipped there),
  `npm run test:billing-db` 32/32 passed, including 8 HTTP-handler lifecycle
  tests on real PostgreSQL with synthetic Stripe fixtures (bad/missing
  signatures, duplicate and concurrent delivery, out-of-order events, payment
  failure/past_due, cancel at period end and deletion, portal customer
  binding). Typecheck, production build, the 23-case HTTP smoke test and
  production `npm audit` (0 vulnerabilities) also passed. Neither migration has
  been applied to the development account Neon database. No webhook endpoint is
  registered. No real Stripe sandbox checkout, delivery, renewal failure or
  cancellation has been run. Billing standing is not Hosted entitlement or
  device approval. Independent security review is pending.
- The waitlist source now uses the published Tally form with single opt-in and
  a versioned consent URL. Signup stays disabled until the public controller
  contact, retention/suppression policy, sender/unsubscribe setup and actual
  provider/tracking configuration are confirmed. `privacy@usesaiph.com` is only
  a proposed contact; no working mailbox is established by these source changes.
  Privacy copy distinguishes EU form-data storage from optional providers that
  can process data elsewhere. See [website launch gates](../website/LAUNCH.md).

Use synthetic data for validation. Record the source commit, environment and
actual results for every build or security review; preserve failures visibly.
