# Current release preparation status

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
