# Current release preparation status

2026-10-14 Hosted texts and calls: branch `feat/hosted-texts-calls` adds SMS
threads, replies, new texts, call alerts, answer/decline, dialing, contact
search and recent calls to Saiph Hosted inside the existing sealed envelopes,
with no hosted service change. Any approved computer that subscribes may act
(calls first come, first served on the phone); actions need a new phone-side
Texts and calls switch (off by default) plus Android permissions. A second,
non-root computer cannot yet join an account in the desktop app. Covered by
desktop, frontend and Android JVM unit tests only; physical-device acceptance
([friends beta steps 10-12](HOSTED_FRIENDS_BETA.md#test-sequence)),
a release and independent review are pending. Not deployed or released.

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
