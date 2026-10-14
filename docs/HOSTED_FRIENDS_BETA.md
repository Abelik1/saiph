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
   same account; the hosted beta APK supplies its service settings on opt-in. Scan the root QR (or paste the root code) and compare its
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
10. Texts: on the phone turn on Texts and calls in Saiph Hosted (it asks for the
    screen lock and Android permissions). Check the computer's Phone page lists
    the phone and its recent conversations, a received text appears within
    seconds, a reply and a new text to a second spare number are delivered from
    the right SIM, a group thread shows the "stays on your phone" note, and
    turning the switch off stops new texts and refuses replies. Revoke the phone
    and confirm its texts and calls disappear from the computer.
11. Calls: call the phone from a spare number. Check the computer's alert and
    Calls tab show the caller within about five seconds, Answer and Decline work
    while ringing (Android 12-16, dual SIM if available), a missed call raises a
    missed-call alert, dialing places the call with audio on the phone, `*`/`#`
    codes are refused and recent calls list on request. Repeat with the
    phone's Texts and calls switch off: nothing is shown or carried out.
12. Two computers (blocked until a second computer can join an account; the
    desktop app can only be the root today): with both showing the ringing
    call, press Answer on one and Decline on the other as close together as
    possible. Exactly one action happens on the phone; both computers stop
    ringing within a few seconds; the losing computer shows "Answered on
    <name>" or "Declined on <name>" (or "Already handled on another computer"),
    not an error. Repeat with Answer on both and Decline on both. Dial from both
    at once: one call is placed and the other computer says the phone is
    already placing a call; dial while on a call and check the "already on a
    call" note. Check texts reach both computers, a full resync of one computer
    does not resend everything to the other, a contact search or call history
    appears only on the computer that asked, and revoking one computer stops
    its texts at the phone's next roster refresh while the other keeps working.

Record platform/build/source, fresh versus existing profile, network and results
without tokens, codes or private content. Passing builds/tests is not physical
installation acceptance. Do not remove owner apps or operate their devices from
an automated acceptance script.

## Scope and remaining gates

Hosted covers text clipboard, notifications/dismissal, explicitly selected
files/photos and, since 2026-10-14 in source only, texts and calls: the phone's
conversations and call state on the computer, one-to-one replies, a new text to
one number, answering or declining a ringing call, dialing an ordinary number,
contact search and recent calls. All of it travels inside the existing sealed
envelopes; the service stores and forwards ciphertext and never sees message
text, numbers or names. The phone accepts these actions from any approved
computer that subscribed to it (root or not), only after its owner turns on
Texts and calls in Saiph Hosted on the phone (off by default) and grants the
Android permissions. Calls are first come, first served: the first answer or
decline wins, every computer is told at once and later attempts get a plain
"Answered on <computer>" note; a dial is refused while the phone is on or
placing a call. Joining an account as a second, non-root computer is not yet
implemented in the desktop app, so the multi-computer path is unit-tested only
(step 12 waits for it). MMS pictures,
group replies, call audio through the computer, other remote phone actions
(ringer, media, ring), clipboard images and photo-library browsing are outside
the preview. Texts and calls have unit tests only; they need the physical
acceptance in test steps 10 to 12 before friends are told they work. Once a
phone shares texts or calls, the desktop polls for sealed events every four
seconds instead of every fifteen, so a ringing call arrives in time.

The shared account boundary and entitlement enforcement are the proposed customer
design. Initial storage is one host with separate account SQLite workspaces;
horizontal routing/storage and automatic capacity scaling are not implemented.
Beta grants are durable and expire. Paid subscription webhooks are not connected
to these grants, so beta acceptance does not validate paid lifecycle behavior.
Physical acceptance and independent security review remain open.
