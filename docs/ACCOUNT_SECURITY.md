# Account and device security controls

Added 13 October 2026 after the [hosted review](HOSTED_REVIEW_2026-10-11.md).
Saiph Hosted encrypts content end to end, so a Saiph account login cannot read
clipboard text, notifications or files: only devices approved by the root
computer can. The remaining risks are around that boundary — an unlocked root
computer, an unlocked phone, a stolen login before a root exists — and these
controls address them. Unit tests cover them with synthetic identities; none
of this is physical-device acceptance or an independent security review.

## Desktop: Windows Hello before a device is added or removed

Approving or removing a Hosted device, retiring the Hosted identity, showing a
self-hosted pairing QR and saving a pairing invitation ask Windows Hello (face,
fingerprint or PIN) first, in a prompt parented to the Saiph window
(`src/orion_mini/user_presence.py`, `UserConsentVerifier` through WinRT with no
added dependency). Cancelling, a busy verifier or too many attempts stops the
action before anything is signed or requested. Saiph receives only "verified".

Where no verifier exists — Linux, or Windows Hello not set up — the existing
on-screen confirmation still applies and Settings says that anyone using the
unlocked computer can add a device, with the steps to set up Windows Hello.
Headless and test workspaces never open a prompt.

## Alerts when the device list changes

The desktop records each verified Hosted device-list change as a security event,
shows it under **Recent device changes**, and raises a tray notification. The
Android app does the same with a high-priority **Saiph security alerts**
notification: an approval made on an unattended computer is visible on the phone.
The first list a device sees is its baseline. Alerts report counts on Android,
because device names are kept only on the root computer.

## Android: fingerprint, face or screen-lock confirmation

`AppLock` uses Android's own `BiometricPrompt` (strong biometrics or the screen
lock PIN, pattern or password; the Keyguard credential screen on Android 8–9).

- Always asked: trusting a Hosted root, showing a device request, changing the
  Hosted connection, retiring the Hosted identity and accepting a Hub pairing
  invitation. Hosted enrollment (root trust and device requests) refuses a phone
  without a screen lock; the other actions proceed there with a warning, as
  before, because Android has nothing to verify.
- Optional **Require fingerprint, face or PIN to open Saiph** (Settings and the
  Hosted screen). Changing it needs confirmation; leaving the app for more than a
  minute locks it again.
- The Hosted screen, and every screen while the app lock is on, is excluded from
  screenshots and the recent-apps preview.
- Background sync keys are deliberately not bound to verification, so
  notifications keep arriving while the phone is locked.

## Second factor (2FA) on the Saiph account

The identity provider performs 2FA; Saiph enforces that it happened.

- Hosted service: setting `ORION_AUTH0_MFA_CLAIM` (a namespaced HTTPS claim name)
  makes every account and website access token need that claim with the JSON
  value `true`. An invalid value refuses startup. Unset, behaviour is unchanged.
- Account website: `SAIPH_REQUIRE_MFA=true` refuses any session whose verified
  ID token `amr` claim lacks `mfa`, including the owner's. Only that boolean is
  kept in the session.

Turn both on only after the tenant requires a second factor on every login for
these clients, otherwise nobody can sign in. A post-login Action such as:

```js
exports.onExecutePostLogin = async (event, api) => {
  const claim = "https://<your-namespace>/mfa";
  const completed = (event.authentication?.methods || []).some((m) => m.name === "mfa");
  if (event.transaction?.protocol === "oauth2-refresh-token") {
    if (completed) api.accessToken.setCustomClaim(claim, true); // No prompt is possible here.
    return;
  }
  // Tokens are issued only after the challenge (or first-time enrollment) succeeds.
  if (!completed) api.multifactor.enable("any", { allowRememberBrowser: false });
  api.accessToken.setCustomClaim(claim, true);
};
```

Prefer passkeys/WebAuthn and authenticator apps over SMS. Restrict sign-up and
enable the provider's bot, brute-force and breached-password protections.
Verify with a real login that access and ID tokens carry the expected values,
including after a refresh if refresh tokens are enabled.

## Administrator reset of a Hosted workspace

`python -m orion_hub.hosted_service_admin reset-workspace --account <id>` keeps a
private copy under `retired-workspaces/`, then clears rosters, used device IDs,
pending requests and sealed content in one write transaction while the service
runs. The account, entitlement and immutable device ownership stay. It recovers
an account whose root computer was lost, or whose root was set up by someone
with a stolen login. Verify the requester out of band and secure their login with
a second factor first (suspend the account meanwhile), or the same attacker can
set up a root again. Afterwards the owner sets up a new root and re-approves
devices; old phone trust fails closed until its Hosted identity is retired.

## Do Not Disturb change times

The Hub refuses a shared Do Not Disturb change time more than 24 hours in the
future, so one device with a wrong clock cannot pin the shared state.

## Still open

- **Fingerprint comparison:** approval compares 64-character fingerprints, which
  people may not check fully. A short comparison code needs a commitment-based
  design so a malicious server cannot grind keys to match; it belongs in the
  independent review rather than an ad hoc change.
- **Hardware-bound desktop keys:** Windows keys are DPAPI-protected, so malware
  running as the user can use them. TPM-backed, non-exportable keys are a larger
  key-storage change.
- **Owner recovery codes:** recovery beyond the administrator reset needs a
  reviewed design.
- **Messages around renewals:** a device-list change drops queued messages and
  envelopes sealed to the previous list (at most five minutes old). Re-sealing
  would need retained plaintext or weaker roster binding; this is accepted.
- **No forward secrecy** for static recipient keys, as before.
- Physical acceptance on Windows (Hello prompt), Android 8–16 (prompt, lock,
  alerts) and a real Auth0 tenant, plus independent review, remain required.
