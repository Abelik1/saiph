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
