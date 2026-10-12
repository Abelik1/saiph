# Hosted development preview

2026-10-11, `feat/hosted-user-flow`. Source implementation of integration steps
1–6. This is a **draft, off-by-default development preview**. No deployment,
identity-provider setting, paid checkout or production feature is enabled by it.
The six real-device exit checks and independent security review are still open.

## What can be reached

Desktop: Settings → Advanced → Saiph Hosted preview. Android: the pairing screen
or Advanced → Saiph Hosted preview. Opening either screen does not enable it.
A desktop build needs the optional `hosted` Python extras. Deployment addresses,
issuer, audience and separate desktop/Android native client IDs are owner-entered;
public builds have no Hosted endpoint or tenant defaults.

1. System-browser native sign-in uses PKCE (Authlib on desktop, AppAuth/Custom
   Tabs on Android). Access tokens stay in memory. The owner can separately allow
   OS-protected rotating refresh tokens. Sign-out clears local session authority,
   cancels in-flight sign-in, and attempts refresh-token revocation. A failed
   local deletion cannot reactivate a signed-out session; desktop keeps a public
   signed-out tombstone and Android persists signed-out state before deletion.
   Without refresh tokens, restart/expiry requires another browser sign-in.
2. Explicit desktop root setup creates separate OS-protected keys, initializes
   genesis through the account API, and displays a signed root QR/code plus its
   full fingerprint. The server cannot provide the initial trust pin.
3. Android accepts a pasted fresh signed root code only after full fingerprint
   comparison on the trusted desktop screen. It displays its own signed request
   and full device fingerprint. Desktop checks the request and requires explicit
   fingerprint confirmation before approval; it also exposes revocation.
4. The desktop worker renews 12-hour rosters when four hours remain, retries
   journaled proposals, and catches up retained signed history. These are
   provisional preview choices. Clock-skew warnings are visible and excessive
   skew blocks sync. Android stops sending/applying content when trust expires
   and shows that it is waiting for root approval or renewal.
5. Clipboard text uses sealed envelopes, bounded UTF-8 payloads, integrity checks
   and the existing most-recent-value echo cache. A → B → A remains deliverable.
   No plaintext fallback to Link exists.
6. Phone notifications are displayed and dismissed through sealed payloads;
   dismissal requires the pinned desktop root and current notification access.
   Explicit file/photo selection uses the same Tink streaming AEAD suite and
   attachment binding on both platforms. Full content is verified privately
   before publication; Android uses the system document picker for saving.
   Android encrypted inbox completion is durable, so consumed/expired entries
   cannot starve new events or reappear as saved-file offers.

Each profile/device uses either a self-hosted Hub or Hosted. Existing self-hosted
pairing prevents enabling Hosted, and a retained Hosted identity prevents desktop
Hub pairing until explicitly retired. Retirement preserves encrypted key/trust
material for owner recovery; it is not account deletion. Root transfer and lost
root-key recovery are not implemented. SMS/call commands, remote phone actions,
photo-library browsing and clipboard images are outside this preview. Photos
can be shared explicitly through the file picker.

## Deployment and acceptance still required

Register the exact desktop callback `http://127.0.0.1:49172/orion/auth/callback`
and Android callback `com.orionmini.mobile.hosted:/oauth2redirect` on separate
public native Auth0 clients. Restrict issuer, API audience, native client IDs and
owner subject in the separate single-customer Hosted relay; use synchronized
server time. If refresh is permitted, configure rotation and reuse detection.
These settings are not provisioned or changed by this branch.

Run the build-order exit checks on real desktop/Android devices: sign-in,
restart, expiry and sign-out; initial root setup; approval/refusal/revocation;
root offline past TTL then recovery; clipboard repeat/echo/network-loss cases;
notification permission changes; and file/photo integrity, expired offers,
interrupted saves and duplicate saves. Android foreground-service/battery limits
and browser return/process recreation require device acceptance. QR scanning is
not added to Android in this preview: code entry plus full comparison is the
supported enrollment route. Independent review is required before paid/public use.

## Verification

Synthetic checks cover token rotation/restart/logout failures and races, renewal
boundaries/skew, default-off/no-network behavior, pairing exclusion, actual
root setup → phone approval → bidirectional encrypted clipboard → desktop
restart → phone revocation, native signed root-code validation, encrypted file
round-trip and ciphertext tamper refusal. Frontend tests cover default-off and
full-fingerprint approval confirmation. These checks do not establish a real
Auth0 sign-in, production relay operation, physical interoperability or review.

Final command results are recorded in the draft PR. Android module-only lint
also reports existing permission/minSdk errors in unchanged self-hosted sources;
that failure is reported separately from app-level lint and JVM/build checks.
