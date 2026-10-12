# Hosted friends beta acceptance

The shared-account implementation is merged; deployment and clean-install
acceptance must still be checked before invitations. Friends use the customer website/account/API, their own
login and a single-use beta code instead of paying. No personal server or Tailscale
is needed. An install adds an approved device to an account, never a new VM.
Infrastructure configuration and activation instructions belong in operations.

## Distribution prerequisites

Freeze one exact reviewed source revision. Build Windows Link `.exe`, Linux Link
`.run` and a nondebuggable Android beta APK with the existing Android signer.
Include the desktop `hosted` extras. Follow `RELEASING.md`,
`ORION_DESKTOP_DISTRIBUTION.md` and `ANDROID_BETA_TESTING.md` for signing, packaging
and licence requirements. Do not substitute an older self-host-only owner ZIP.

Stage the installers and matching source archives with
`scripts/beta/prepare-downloads.py`. The platform-map JSON contains exactly
`windows`, `linux`, `android`, `desktop_source`, `android_source`, mapped to actual
checksum-recorded files. Repeat `--supporting-file` for required third-party
sources, licences and notices. Supply the exact source commit, protected HTTPS
file-host base URL and actual Firebase group invitation. This stages files; it
does not build, sign, upload or publish them.

Host the small portal separately from large files and verify access control on
both locations. Give testers the account URL, unique access code and setup guide
at `/setup`. Build with the explicit public Hosted configuration so friends do
not enter service URLs or client IDs. Desktop `scripts/build-native.py` accepts
`--hosted-config`; Android `scripts/android/build-tester-apk.ps1` accepts
`-HostedConfiguration`. Defaults apply only on opt-in and never replace existing
enrollment. Native apps need no client secret.

## Test sequence

Use synthetic content and two independent accounts. Before deleting an existing
installation, coordinate with its owner and check backup/recovery. Uninstallation
can destroy device keys; lost desktop-root recovery is not implemented. Use spare
devices or disposable OS profiles for the first acceptance pass.

1. Open the actual website without development tooling. Download Windows/Linux
   installers and join Android distribution. Check hashes, source availability,
   Android signer/version, and installation without Python/Node/Git/compilers.
2. Sign in with a new account on the website. Verify no Hosted access before code
   entry. Redeem a code and confirm expiry without payment. Retry as the same
   account, then try reusing it as the other account. Unknown/expired/revoked
   codes must not create access. Checkout/query parameters cannot grant access.
3. On desktop open Settings → Advanced → Saiph Hosted preview. The hosted beta
   installer supplies public service settings. Turn on Hosted and sign in through the system browser. Initialize
   the desktop root and display its signed code and full fingerprint.
4. On Android open pairing or Advanced → Saiph Hosted preview. Sign in with the
   same account; the hosted beta APK supplies its service settings on opt-in. Paste the root code and compare its
   full fingerprint on the trusted desktop. Compare the phone request fingerprint
   and explicitly approve it on desktop. Login alone must never approve a device.
5. Stop Tailscale on every test device. Use mobile data on Android and an unrelated
   network on desktop. Exchange encrypted clipboard text both ways, including
   repeated values; test notifications/dismissal and selected file/photo transfer.
   Compare file hashes after receipt.
6. Repeat under the second account. Confirm rosters, clipboard, notifications,
   files and colliding ciphertext IDs cannot reach the other account. Check
   refused enrollment and phone revocation without interrupting the other user.
7. Restart apps/service; sign out/in; interrupt networking/transfers; test token
   expiry and roster renewal. Keep the root offline past the 12-hour roster TTL
   and check sync stops until renewal. Check Android notification permissions,
   background-service/battery limits and browser return after process recreation.
8. Expire/revoke beta access. Both bearer and signed-device requests must fail
   while the other account works. Restore a consistent server backup in isolation
   and check account/device identities and content remain stable.
9. Repeat clean installation on Windows and Linux. Check Linux Secret Service,
   system prerequisites, desktop entries, browser callbacks and uninstall. Record
   all manual steps and confusing messages as onboarding issues.

Record platform/build/source, fresh versus existing profile, network and results
without tokens, codes or private content. Passing builds/tests is not physical
installation acceptance. Do not remove owner apps or operate their devices from
an automated acceptance script.

## Scope and remaining gates

Hosted currently covers text clipboard, notifications/dismissal and explicitly
selected files/photos. SMS/call commands, remote phone actions, clipboard images
and photo-library browsing are outside the preview. Self-host feature parity is
an outstanding product decision.

The shared account boundary and entitlement enforcement are the proposed customer
design. Initial storage is one host with separate account SQLite workspaces;
horizontal routing/storage and automatic capacity scaling are not implemented.
Beta grants are durable and expire. Paid subscription webhooks are not connected
to these grants, so beta acceptance does not validate paid lifecycle behavior.
Physical acceptance and independent security review remain open.
