# Shared friends-beta preparation evidence

Local work on `codex/friends-hosted-beta`, based on product revision
`a590fa034cd22ef77f2b370386412aa2ffcba821`. Follow-up checks on 2026-10-12 added
owner migration, packaged public defaults and authenticated installer downloads. This is
preparation evidence, not a deployment receipt or independent security review.

## Resulting behavior

The optional shared Hosted runner routes verified native identities to separate
durable account workspaces. Approved device IDs have immutable account ownership.
The optional account website mode admits signed-in friends to code entry and
redeems codes server-to-server using a separately allowed confidential web client.
Unknown login alone grants no Hosted access. Single-use, hash-stored access codes
expire within 90 days; revocation/expiry block account and signed-device requests.
The default owner-only API and website configuration remain separate and default.

The beta download preparer selects actual checksum-verified installers, matching
source archives and explicitly chosen dependency sources/notices. It stages a
small portal separately from large files and never uploads or deploys. Operations
contains the owner-provided Android group invite and a locally built website
preview includes it. The invitation's actual releases/group access are unverified.

## Completed local checks

- Full Hub suite: 456 passed, 6 skipped. Existing HTTP-client and tar extraction
  deprecation warnings were reported. Skips are not physical/provider acceptance.
- Targeted hosted account/auth/blob/runtime/transport/approval/crypto and download
  staging regression: 412 passed. This overlaps the full Hub suite.
- Operations suite with explicit product source: 86 passed, 1 skipped.
- Account website unit checks: 43 passed; optional PostgreSQL suites were not run
  for this change. TypeScript checks and production build passed.
- Default website production HTTP checks: 26 cases, using official SDK-encrypted
  synthetic sessions, including denied users, callback/query tampering and billing
  unavailable-store behavior.
- Beta production HTTP checks: non-owner code entry, no query-based access, CSRF
  and identity-override denial, same-account redemption, cross-account reuse
  denial, disabled checkout and hidden browser token endpoint. These use actual
  production HTTP and SDK cookies with a test-only synthetic backend transport.
- Static website preview: 16 files prepared using the owner-provided Android
  invitation. Nothing published.

Meaningful new security checks include actual RSA JWT validation, two independent
root-approved rosters, encrypted mailbox/file isolation, device-ID spoof refusal,
concurrent single-use code redemption, failed-redemption rollback, bounded attempt
accounting, restart identity stability, and expiry/revocation of cached routes.

## Follow-up checks (2026-10-12)

- Shared API, migration, download ticket, native defaults/runtime and staging:
  74 passed. Migration preserves deployment UUID, rosters and signed-device access.
  Downloads require web-client entitlement; expired/forged tickets, revoked accounts,
  altered release files, traversal and ticket flooding are refused.
- Account unit checks: 44 passed; typecheck and production build passed.
  Production build initially hit a Windows telemetry-cache rename error; rerun with
  telemetry disabled passed. This was a tooling failure, not provider acceptance.
- Operations shared bundle: 8 passed after adding the migration/download import closure.

## Required live and physical acceptance

1. Review/freeze an exact clean product revision and the private operations bundle.
2. Snapshot and migrate the existing owner's deployment ID, state and device directory
   with `hosted_service_admin import-owner` before switching the existing API proxy.
3. Verify real Auth0 web/native user identity and API-audience permissions, configure
   the shared service and account mode, and make the existing account custom domain
   reachable by friends while retaining app authentication. Current Vercel account
   Deployment Protection otherwise prevents ordinary customer access.
4. Build actual Windows/Linux installers and Android APK from the frozen source;
   preserve signer, corresponding source/notices and verify artifact hosting.
   Build scripts accept a checked, public-only deployment configuration. It never
   enables Hosted automatically or retargets an existing identity. Native artifacts
   and deployment receipts are recorded separately by operations.
5. Upload/distribute the matching Android build to the invite's group and verify a
   fresh tester can install it. A valid-looking invitation URL does not prove this.
6. Perform the clean-device/mobile-data/no-Tailscale and recovery checks in
   `HOSTED_FRIENDS_BETA.md`. Do not uninstall owner apps automatically.

Paid billing lifecycle is not connected to Hosted grants, and horizontal capacity
scaling is not implemented. Hosted feature scope remains text clipboard,
notifications/dismissal and selected file/photo transfer; SMS/calls, remote phone
actions, image clipboard and photo-library browsing remain outside the preview.
