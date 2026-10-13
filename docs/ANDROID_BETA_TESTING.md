# Android beta testing with Firebase App Distribution

This is the publisher's procedure for giving outside beta testers an Android build
that has **no owner Hub defaults** and can receive tester updates through
Firebase App Distribution. It does not replace the [release checklist](../android/docs/SAIPH_PUBLIC_RELEASE.md)
or physical-device acceptance; a build that passes this procedure is verified for
identity and content, not for behaviour on a tester's phone.

Firebase project IDs, tester emails, group aliases, keystore paths, signer
fingerprints and owner hostnames are private operating values. Keep them in the
private operations repository or a local file, never in this repository.
The owner records where each of them lives, and the release history, in the
private operations repository's `docs/ANDROID_PUBLISHING.md`.

## What a tester build contains

A tester build uses the non-debuggable `beta` type with
`-PorionIndependent=true -PorionFirebase=true -PorionPush=false` from a clean,
recorded commit. Line references are to the source this document was written
against and may drift.

**No owner Hub.** `ORION_LEGACY_ORIGIN` and `ORION_LEGACY_HOST` are empty in every
variant (`android/core/network/build.gradle.kts:14-15`), so `MeshOrigin.DEFAULT` is
empty (`android/core/network/src/main/java/sefirah/network/orion/Enrollment.kt:12`)
and a fresh install connects only to the Hub named in the tester's own invitation.
`BuildVariantTest` asserts this. A scan of tracked `android/` sources and resources
found no owner address, hostname, email or Firebase project ID. The only personal
emails are upstream KDE Connect copyright headers (`android/features/src/main/java/sefirah/communication/sms/SMSHelper.kt:3`,
`SmsMmsUtils.kt:2`). Upstream Sefirah links remain in unreachable screens: the
GitHub release check in `android/data/src/main/java/sefirah/data/repository/ReleaseRepository.kt:76,128-129`
runs only from `com.castle.sefirah.MainActivity`, which is not declared in the manifest.

**Owner Firebase identifiers are compiled in.** The Google Services plugin turns the
private `google-services.json` into string resources: the owner's Firebase project
ID, project number (sender ID), Android app ID, API key and storage bucket. They are
not credentials, but every tester can read them from the APK and they identify
the owner's Firebase project. Restrict the API key in Google Cloud Console to the
Android app and the Firebase APIs it needs.

**Firebase starts; FCM push is disabled.** `FirebaseInitProvider` remains enabled
for App Distribution. Independent builds default `orionPush` to false, and the
publisher script explicitly passes `-PorionPush=false`. This disables FCM
auto-initialisation, `OrionMessagingService`, Firebase's own messaging service and
`FirebaseInstanceIdReceiver`. Both app token-fetch/upload paths require
`HAS_FIREBASE_PUSH`, so tester builds do not register or upload FCM tokens.
Whether App Distribution still creates a Firebase installation ID with push off
has not been verified; this is not a claim that Firebase receives no identifiers.

**App Distribution update checks run in debug and beta.** Both types include the
full SDK and set `HAS_APP_DISTRIBUTION` when Firebase is enabled; release gets the
no-op API library. `AppUpdates` checks this flag. On launch it checks for a Firebase
update only if the tester has already signed in. **Settings → Check for updates**
first asks the paired Hub and then calls Firebase `updateIfNewReleaseAvailable`.
That call starts Google tester sign-in if needed. Declining sign-in does not
affect pairing. Firebase documents the beta dependency and warns against shipping
the full SDK in Play binaries, even unused:
[App Distribution alerts](https://firebase.google.com/docs/app-distribution/set-up-alerts?platform=android).

**Outside tester builds default to beta.** It is not debuggable and does not use R8
minification, which has not been accepted on devices. Supply the existing signing
key explicitly through `SAIPH_ANDROID_*`; changing build type preserves in-place
updates only when the package, signer and increasing version code also match.
`-BuildType debug` remains available for development and produces a debuggable APK;
authorised ADB access can read that app's private files. Do not use it for the
outside beta. The script does not offer release because it lacks in-app Firebase
updates and its minified behaviour is unaccepted.

**Push requires the publisher's Firebase project.** A tester's Hub could send FCM
only with a service-account credential for the APK's Firebase project. Never give
testers that credential. Mesh Link sync works without FCM. If explicitly enabled,
FCM can carry an inbox title and the first 300 characters of its body through
Google's servers. Private owner publishing scripts that use independent builds
must add `-PorionPush=true` to keep the owner's existing push channel. This does
not change the package, signing identity or debug build type.

**No Analytics, Crashlytics or Performance Monitoring** dependency is present. The
app does not call the App Distribution in-app feedback API.

## One-time Firebase setup

Do these in the Firebase console for the existing Android app `com.orionmini.mobile`.
Keep the same app: changing the Firebase app or the signing key breaks in-place
updates and pairing for existing installs.

1. **App Distribution → Testers & Groups → Add group.** Create a group for outside
   testers, for example `beta-testers`. Do not reuse an owner-only group, and do not
   add the owner's account to the outside group.
2. **Testers & Groups**: decide whether to turn on the setting that requires testers
   to accept with the same Google account the invitation was sent to.
3. **Invite links** (optional): create an invite link attached to the outside group so
   testers can sign up with their own email. Add a domain restriction if appropriate.
   A link without a group only grants the latest release, so attach the group.
   [Invite links](https://firebase.google.com/docs/app-distribution/create-invite-links).
4. Confirm that the **Firebase App Testers API** and **Firebase App Distribution API**
   are enabled for the project in Google Cloud Console. In-app alerts need the
   App Testers API ([set up alerts](https://firebase.google.com/docs/app-distribution/set-up-alerts?platform=android)).
5. **Google Cloud Console → APIs & Services → Credentials**: restrict the Android
   API key from `google-services.json` to package `com.orionmini.mobile` and your
   signing certificate SHA-1, and only to the Firebase APIs it needs.
6. Decide how long to keep tester data. Firebase keeps App Distribution tester data
   until you delete it (see Privacy). Remove testers when the beta ends.
7. Update the website privacy notice with the facts below before inviting anyone.

Limits: 500 testers per project and 200 per group. The limit can be raised on request
([manage testers](https://firebase.google.com/docs/app-distribution/add-remove-testers)).

## Build and verify a tester APK

Prerequisites: JDK 22 as `JAVA_HOME`. `ANDROID_HOME` with platform 37.0,
build-tools 36.0.0 and NDK 28.2.13676358. Native restic generated with
`python android/scripts/build-restic.py --android-root android`. A clean worktree.

The script works in Windows PowerShell 5.1 and PowerShell 7. Keep these private
inputs outside the repository:

| Input | Parameter / environment variable |
| --- | --- |
| Firebase config for `com.orionmini.mobile` | `-GoogleServicesJson` / `SAIPH_ANDROID_GOOGLE_SERVICES_JSON` |
| Existing signer certificate SHA-256 | `-ExpectedSignerSha256` / `SAIPH_ANDROID_SIGNER_SHA256` |
| Owner strings that must not ship (one per line: Hub address and port, Hub/mesh hostnames, owner emails) | `-ForbiddenStringsFile` / `SAIPH_ANDROID_FORBIDDEN_STRINGS_FILE` |
| Existing signing key (required for beta) | `-KeystorePath` / `SAIPH_ANDROID_KEYSTORE`, `-KeyAlias` / `SAIPH_ANDROID_KEY_ALIAS`; passwords only in `SAIPH_ANDROID_KEYSTORE_PASSWORD`, `SAIPH_ANDROID_KEY_PASSWORD` |

Choose the version first. `versionName` is in `android/app/build.gradle.kts`, and
the request must match the committed value. The version code must be greater
than every code already distributed to anyone through this Firebase app or a Hub.
Pass the previous highest code as `-MinimumVersionCode`.

```powershell
./scripts/android/build-tester-apk.ps1 -VersionName 0.8.6 -VersionCode 3564000 -MinimumVersionCode 3563000
```

The script copies the Firebase config into the Git-ignored `android/app/` only
for the build, then removes it. It assembles beta, runs debug unit tests (AGP
creates no beta unit-test tasks), and runs beta lint. `-SkipChecks` assembles only.
Signing values reach Gradle through its child environment. It verifies:

- the worktree is clean, the commit is recorded, and both are unchanged after the build
- no `google-services.json` is tracked and the local copy is ignored
- package, version name and version code match the request; beta is not debuggable
- there is exactly one signer, matching the expected fingerprint
- the Firebase app ID matches the config and FirebaseInitProvider is enabled,
  while all messaging components and FCM auto-init are disabled
- no forbidden owner string appears in DEX, resources, manifest or assets

It writes a new directory, by default `%LOCALAPPDATA%\saiph-android-beta\<name>-<code>`,
containing:

- the APK
- a Git archive of `android/` from that commit (the GPL corresponding source)
- `build.log`
- `release.json` with the APK SHA-256, source commit, signer, native restic hashes
  and `debuggable=false` / `firebasePush=false` for the default beta

**Nothing is uploaded by default.**

## Upload and grant access

Sign in once with the Firebase CLI in a normal local terminal (`firebase login`).
Never paste a login code into a chat or log. Then rerun with `-Upload`. You can
instead upload the verified APK from the output directory by hand in the
Firebase console.

```powershell
./scripts/android/build-tester-apk.ps1 -VersionName 0.8.6 -VersionCode 3564000 -MinimumVersionCode 3563000 -Upload -TesterGroups beta-testers
```

`-Upload` rebuilds and reverifies before uploading. It checks that the signed-in
account can see the Firebase app, then runs `firebase appdistribution:distribute`
with generated release notes (or `-ReleaseNotesFile`). Without `-TesterGroups` or
`-Testers`, it uploads without granting anyone access. A group gives access only
to its current members, so a group with no testers reaches nobody; add your own
tester address with `-Testers` to receive the release yourself. Firebase CLI output is suppressed
because it can contain account data and download tokens. Pass `-FirebaseCli` with
the path to `firebase.cmd` or `firebase-tools/lib/bin/firebase.js` if it is not
on `PATH`.

Firebase distributes only the APK. Make the matching source archive available to
every tester, for example as a release asset or on request. Do this before or
together with the build, as GPL-3.0 requires.

## Adding and removing testers

- **Add:** in the console, add emails to the group. The CLI equivalent is
  `firebase appdistribution:testers:add --project <id> --group-alias beta-testers a@example.com`.
  You can also share the group's invite link. New members get access to releases
  distributed to that group.
- **Remove:** remove the tester from the group to revoke releases they reached only
  through that group, or remove them from the project in **Testers & Groups** to
  revoke all access. The CLI equivalent is `appdistribution:testers:remove`.
  Removing a tester does not uninstall the app or unpair the phone. Revoke the
  device on the tester's own Hub if needed. That Hub belongs to the tester.
- **Delete data:** removing a tester from the project is presumably how you ask
  Firebase to delete their App Distribution data. This is unverified; confirm it
  in Firebase support documentation before stating it in the privacy notice.

## What testers see

1. An email from Firebase App Distribution inviting them to test Saiph. If they
   used an invite link, they enter their email address first.
2. On the Android phone they open the email, **sign in with a Google account** and
   accept. Any Google account works unless you require the invited address.
3. They may install the optional **Firebase App Tester** app from the browser prompt
   or `appdistribution.firebase.google.com`. Otherwise they download the APK from the
   browser.
4. Android asks them to allow **Install unknown apps** for App Tester or the browser,
   then confirm installation.
5. After pairing with their own Hub, **Settings → Check for updates** can enable
   in-app Firebase alerts (debug and beta tester builds). This requires a one-time
   Google sign-in. On Android 13 and later they must allow notifications to see
   download progress. Every update still needs Android's install confirmation.
   Saiph also allows its own unknown-app install permission once.
6. Later releases send a new email. Testers must **update in place and never
   uninstall**. Uninstalling deletes the device key and pairing.

Tester docs: [get set up as a tester](https://firebase.google.com/docs/app-distribution/get-set-up-as-a-tester?platform=android).

## Privacy facts for the website notice

The publisher is the controller for the beta tester list. Google processes data
as Firebase's processor under the Firebase terms.
Source: [Privacy and Security in Firebase](https://firebase.google.com/support/privacy), checked 2026-10-11.

- **App Distribution** collects testers' names, email addresses, Firebase installation
  IDs and secure Android IDs (and iOS UDIDs on Apple devices) among its supported
  data categories. The app does not enable in-app feedback. Data is retained until
  the publisher requests deletion, then removed within 180 days. Whether this
  push-disabled beta creates an installation ID remains unverified.
- **Cloud Messaging** is disabled in tester builds: no FCM registration token is
  fetched or uploaded by Saiph. Firebase App Distribution remains enabled.
- **What is not collected:** no Analytics, Crashlytics, Performance Monitoring or
  in-app feedback is included. Messages, notifications, clipboard, files and
  contacts go only to the tester's own Hub, never to Firebase, because tester
  Hubs cannot send FCM push (see above).
- **Unverified, confirm before publishing:**
  - whether App Distribution shows device model or OS version per tester in the console
  - what the App Distribution SDK sends when it checks for updates, beyond
    installation ID and sign-in state
  - whether App Distribution creates a Firebase installation ID when push is off
  - the remaining Firebase network requests with messaging disabled
  - Firebase's server log retention for the Installations service, which the
    privacy page does not list separately

Google's own processing as a sign-in provider and as Play services is covered by Google's
terms with the tester, not by Saiph.

## Later: Google Play closed testing

Firebase App Distribution does not count toward Play requirements. For a personal
Play developer account created after 13 November 2023, production access requires
a closed test with **at least 12 testers opted in for 14 consecutive days**
([Play Console Help](https://support.google.com/googleplay/android-developer/answer/14151465)).
A Play build must use the same package and a version code above every Firebase
build. Plan the key strategy before the first Play upload. The current tester
identity is an Android SDK debug certificate. Play Console rejects uploads signed
in debug mode. Whether Play App Signing accepts that certificate as an imported
app-signing key is unverified. If it does not, Play installs cannot update
sideloaded tester installs in place, and testers must move with a fresh pairing.

A Play build must not contain the full App Distribution SDK. Firebase warns that it
can cause removal even if it never runs. It must also not self-update outside Play.
That rules out both debug and beta tester types. The current `release` type also
still contains the Hub self-updater (`Updater.kt`, `UpdateActivity`) and
`REQUEST_INSTALL_PACKAGES`, needed for public sideloaded releases. A separate
Play variant must remove them before a Play submission; release alone is not
Play-ready.

These manifest permissions (`android/app/src/main/AndroidManifest.xml:17-55`) are
restricted or need a Play Console declaration:

| Permission / API | Play policy | Risk for Saiph |
| --- | --- | --- |
| `READ_SMS`, `RECEIVE_SMS`, `RECEIVE_MMS`, `SEND_SMS`, `READ_CALL_LOG` | [SMS and Call Log](https://support.google.com/googleplay/android-developer/answer/10208820): default handler only, unless an exception is approved. Listed exceptions include "Connected device companion apps" and "Cross-device synchronization or transfer of SMS or calls". | High: needs an approved exception and a declaration with video; rejection removes SMS/call features from the Play build |
| `REQUEST_INSTALL_PACKAGES` | [Restricted to core package install use](https://support.google.com/googleplay/android-developer/answer/12085295); self-updating is not allowed | Remove from the Play build |
| `QUERY_ALL_PACKAGES` | [Broad package visibility](https://support.google.com/googleplay/android-developer/answer/10158779), declaration form | Likely rejected; replace with `<queries>` |
| `MANAGE_EXTERNAL_STORAGE` | [All files access](https://support.google.com/googleplay/android-developer/answer/10467955), declaration form | Likely rejected; use the Storage Access Framework |
| `ACCESS_BACKGROUND_LOCATION` | [Background location](https://support.google.com/googleplay/android-developer/answer/9799150), declaration, video, prominent disclosure | Remove unless a core feature needs it |
| `USE_FULL_SCREEN_INTENT`, `FOREGROUND_SERVICE_CONNECTED_DEVICE`, `FOREGROUND_SERVICE_DATA_SYNC` | [Foreground service and full-screen intent](https://support.google.com/googleplay/android-developer/answer/13392821) declarations | Declarable; full-screen intent is granted automatically only to calling and alarm apps |
| `AccessibilityService` (`ClipboardAccessibilityService`) | [AccessibilityService API](https://support.google.com/googleplay/android-developer/answer/10964491): prominent disclosure and consent unless it is an accessibility tool | Declaration and disclosure required |
| `RECEIVE_SENSITIVE_NOTIFICATIONS` | Protected system permission (`tools:ignore="ProtectedPermissions"`), not grantable to third-party apps | Remove (no effect) |

`READ_CONTACTS`, `CAMERA`, `READ_PHONE_STATE`, `ANSWER_PHONE_CALLS`, the
notification listener and `SYSTEM_ALERT_WINDOW` are not declaration-gated. They do
require the Data safety form, a privacy policy and prominent disclosure under the
User Data policy. Confirm every row against current Play policy at the time of
submission; policies change.
