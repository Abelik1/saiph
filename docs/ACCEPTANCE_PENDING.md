# Physical tests still owed

One list of everything merged into `main` that has passed unit tests only and
still needs a real phone, computer or account. Tick an item only with a recorded
result (device, build, source commit, what was seen). A unit-test pass is never
a tick. Detailed steps live in the linked documents.

Updated 2026-10-14, after merging the Hosted webcam, Hosted texts and calls,
call-audio research and website wording branches.

## Attended Hosted setup attempt, 2026-10-15

Owner-reported Windows desktop 0.1.0-beta.5 installed, with Android 0.9.0 intended
for the fresh Hosted run. Installer hash, Android version code, build source,
phone reinstall and network conditions have not yet been independently checked.
No acceptance checkbox below is completed by this attempt.

- Desktop onboarding blocked: the wizard did not provide a usable Hosted path;
  Settings presented manual connection fields. Source inspection found that a
  fresh profile's Hosted snapshot omitted the installer's bundled defaults.
- Android onboarding blocked: account sign-in was below phone approval controls
  after an extra Open Saiph screen. The owner also reported that the browser
  sign-in button did not work and the page it opened was broken; exact browser
  error and a successful callback are not yet recorded.
- Device approval, full fingerprint comparison, clipboard, notifications, file
  hashes, texts, calls and webcam remain unverified in this fresh install.
- Re-test the corrected builds from first launch: sign in without entering
  service settings, return from the browser, scan the computer's code, check that
  the phone appears on the computer by itself, then explicitly approve it by full
  fingerprint before testing sync. Webcam and call audio remain local.

The source correction and automated checks are recorded separately in
[release status](RELEASE_STATUS.md); they do not complete this physical run.

## Before inviting friends (current beta.4 build)

- [ ] Signed-in download of each beta.4 file from the account site; Windows
      installer SHA-256 `af8057f3…aebfed` matches.
- [ ] Second real account: code reuse refused, one account cannot see the
      other's devices or data, expiry and revocation stop access.
      ([steps 2, 6, 8](HOSTED_FRIENDS_BETA.md#test-sequence))
- [ ] One full device run: install on Windows, Hosted sign-in, set up the
      computer, approve the phone by full fingerprint, clipboard both ways,
      notification and dismissal, a file each way with matching hashes, over
      mobile data with Tailscale off. ([steps 1, 3–5, 7, 9](HOSTED_FRIENDS_BETA.md#test-sequence))
- [ ] Linux install of the `.run`, including Secret Service and browser return.

## Needs the next desktop and Android build

These are in source on `main` but not in beta.4. Build desktop and Android
together; phones on an older app never offer texts or calls.

### Texts and calls on Hosted

Steps 10 and onwards in [the Hosted beta test sequence](HOSTED_FRIENDS_BETA.md#test-sequence).

- [ ] Phone "Texts and calls" switch: off by default, screen-lock confirmation,
      each Android permission prompt (SMS, phone, call log, contacts).
- [ ] Incoming call shows on the computer within a few seconds; answer and
      decline work on Android 12–16; missed-call alert; media pauses.
- [ ] Two approved computers, first come first served: both ring, the first
      answer or decline wins, the other stops ringing and says where it was
      handled; two dials at once are refused with a reason.
- [ ] Second computer joins: same account, main computer's code pasted, full
      fingerprint compared both ways, approved on the main computer; clipboard
      and files between the two computers; removing it on the main computer
      shows "Removed by your main computer"; a code from another account is
      refused. Windows and Linux, each as the joining computer.
- [ ] Texts: conversation list, reply in a one-to-one thread, new text to a
      number and to a contact found by search, long and emoji messages.
- [ ] Dial from the computer, recent calls list, dual SIM.
- [ ] Background limits: phone screen off and on battery saver for 30 minutes,
      then a call and a text still arrive.
- [ ] Revoking the phone removes its texts and calls from each computer.
- [ ] Server load with the 4-second poll while texts or calls are shared.

### Phone webcam without a Hub

See the webcam section in the [user guide](USER_GUIDE.md) and the account
`/setup` page.

- [ ] USB debugging on Android 12+: Find my phone, Allow prompt, camera starts.
- [ ] Wireless debugging: six-digit pairing, connect, camera starts.
- [ ] Windows: OBS window capture of the preview, OBS Virtual Camera picked in a
      real meeting app (Teams, Meet or Zoom).
- [ ] Linux: v4l2loopback device picked in a real meeting app.
- [ ] Refusal messages for scrcpy older than 2.2 and Android older than 12.

## Research prototype (not built)

Call audio through the computer, [spike plan section 7](research/CALL_AUDIO_SPIKE.md):

- [ ] Linux, Ubuntu 26.04 (and 24.04): two-way call audio over Bluetooth
      hands-free without root; answer, hang up and dial from the computer.
- [ ] Windows 11 25H2: Phone Link baseline call, then the packaged test app
      gate (allowed or "DeniedBySystem").

## Open decisions recorded with the tests

- Webcam and call audio stay local (USB, same-network Wi-Fi, Bluetooth); they
  are never relayed through the hosted service.
- Do not publish the `/setup` webcam section or Hosted texts and calls wording
  on the live account site before a build containing them is in the catalog.
