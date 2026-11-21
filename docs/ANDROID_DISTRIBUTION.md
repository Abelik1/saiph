# Android distribution

Saiph for Android ships two ways, built from the same code as two product flavors
of `android/app`:

| | Website download (`direct`) | Google Play (`play`) |
|---|---|---|
| Who installs it | Anyone, from usesaiph.com; Android asks once to allow installs from the browser | Anyone, from Google Play, with no extra setting |
| Updates | Saiph downloads and installs its own updates after the owner confirms | Google Play |
| Automatic clipboard sending (accessibility service) | Yes, optional | No; the clipboard bubble and the Clipboard action send on a tap |
| All files access for backups | Yes | No; photo access only |
| Background location (trusted Wi-Fi names while closed) | Yes | No |
| Full-screen Find phone alert | Yes | Heads-up notification |
| App list on the computer | Every installed app | Every app with a launcher icon (all the list shows anyway) |
| Texts and calls | Yes | Yes, under Play's cross-device sync exception (declared in Play Console) |
| Buying Saiph Cloud | "View plans and free trial" and plan links to usesaiph.com | None: Play does not allow steering to outside payment. Signing in with an existing account works |
| Format | Signed APK | Signed Android App Bundle (`.aab`) |

`BuildConfig.PLAY_STORE` tells the code which build it is.
Both distributions require a 64-bit Android ABI (`arm64-v8a` or `x86_64`) and
Android 8.0/API26 or newer. The bundled backup runtime supports these two ABIs;
packaging must not advertise 32-bit variants without that runtime.
[`app/src/play/AndroidManifest.xml`](../android/app/src/play/AndroidManifest.xml) removes what
Play's permission policies do not allow, and the matching features step aside. Beta
builds for testers are `direct` only.

The two builds are separate apps that one phone can hold side by side: Google Play's
**Saiph** keeps the application ID `com.orionmini.mobile`, and the website's **Saiph
Unlocked** is `com.orionmini.mobile.unlocked`, with its own name, sign-in callback and
data. Moving from one to the other is a new install, connected to the account and
approved on the computer again; data does not carry over between them. Keep signing
both with the keys under **Signing**.

## Building

Development:

```powershell
cd android
./gradlew.bat :app:assembleDirectDebug :app:assemblePlayDebug -PorionFirebase=false -PorionIndependent=true -PorionVersionCode=1 --no-configuration-cache
```

Releases are built by the maintainer with
[`scripts/android/build-release.ps1`](../scripts/android/build-release.ps1). It runs
the unit tests, then builds the signed website APK (`assembleDirectRelease`) and the
signed Play bundle (`bundlePlayRelease`). It also writes each signer's certificate
fingerprint and the files' SHA-256 to a `release.json` next to them. Tester builds
keep using [`scripts/android/build-tester-apk.ps1`](../scripts/android/build-tester-apk.ps1),
which now builds the `direct` flavor.

Use a clean committed checkout. Pass `-HostedConfiguration` with a JSON file
containing only the five public deployment fields; the script temporarily copies
it into the ignored asset directory and removes its copy on exit. An existing
different asset is preserved and stops the build. `-PasswordDialog` opens masked
Windows dialogs for the existing key passwords; run PowerShell with `-STA`.
Passwords never enter keytool command-line arguments. The script verifies the APK
and bundle signatures against the selected certificates, checks the APK identity
and version, checks both packaged public configuration files, and records the
exact source revision. It also prepares an `assetlinks.json` using the app signing
certificate; deployment is a separate step. Gradle, Android and Java temporary
directories default to isolated directories under `build/android-release`.

The release gate checks every packaged native ELF library in both formats: only
the two supported ABIs, the correct ELF64 machine, a restic runtime for each ABI,
and LOAD segment alignment of at least 16 KB. It also runs APK `zipalign -c -P 16
4`. These static checks do not replace testing on an Android 16 KB environment;
see [Android's page-size guidance](https://developer.android.com/guide/practices/page-sizes).

The signing/configuration boundary checks use a fresh synthetic keystore:

```powershell
powershell -NoProfile -NonInteractive -File scripts/android/test-release-tools.ps1 -JavaHome 'C:\Program Files\Java\jdk-22' -Scratch 'build/release-tools-check-fresh'
```

The scratch directory must not already exist. These checks do not unlock owner
keys, upload a release or establish physical-device acceptance.

New trials require a card through website Stripe Checkout: 14 days free, then
€9.99/month automatically (see [the trial decision](CARD_REQUIRED_TRIAL.md)). Customers can cancel any time
in Manage billing; cancellation before trial end avoids the first charge.
Both Android flavors read Cloud access after sign-in; neither starts a card-free
trial. The Play build is consumption-only and keeps purchase links hidden.

For a Cloud release, place the distributor's five public deployment fields in
the ignored `android/app/src/beta/assets/hosted-defaults.json` and pass
`-AccountOrigin https://account.example.test` to `build-release.ps1`. Release
builds include that public asset too. The account origin is compiled through
`-PorionAccountOrigin` for compatibility with existing release tooling. Neither
flavor sends automatic trial-activation requests. Tester builds accept the same
optional `-AccountOrigin` parameter.

Release builds read their key from the environment (`SAIPH_ANDROID_KEYSTORE`,
`SAIPH_ANDROID_KEY_ALIAS`, `SAIPH_ANDROID_KEYSTORE_PASSWORD`,
`SAIPH_ANDROID_KEY_PASSWORD`). The build script sets them for its own process only. A
release build without them is unsigned. R8 shrinking stays off for releases, matching the
beta builds that have been tested on devices.

## Signing

Two keys, both kept outside the repository:

- **App signing key.** It signs the website APK. Google Play also uses it to sign the
  APKs it delivers. Choose Play App Signing's **Use a key from Java keystore**
  (upload it with Google's PEPK tool) rather than letting Google generate one;
  otherwise the two builds cannot replace each other on a phone.
- **Upload key.** It signs the bundle you upload to Play. If it is lost or leaked,
  Google can reset it; the app signing key cannot be reset.

Earlier tester builds were signed with a development key. Phones with those builds
must uninstall once before installing a release build. Their pairing is lost and they
are approved again on the computer.

## Google Play review notes

- **Account deletion:** Settings > Account & devices > **Delete account** (both builds)
  opens `<account origin>/account/delete` in the browser. That public page explains
  what is deleted and, once signed in, records the request; the owner completes it
  from the account admin page within 30 days. It shows no plans, prices or purchase
  links. Enter the same URL as the data deletion link in Play Console's Data safety
  form. A build without `-PorionAccountOrigin` shows the support address instead.
- **Location:** the Play flavor removes `ACCESS_BACKGROUND_LOCATION` and never asks
  for it (`LocationPolicy`, set from `BuildConfig.PLAY_STORE`); trusted Wi-Fi names are
  read with foreground location while Saiph is open. Declare foreground location only.
- **Accessibility:** the Play flavor removes automatic clipboard accessibility,
  but retains `SaiphInputService` for optional phone screen control. It declares
  `isAccessibilityTool=false`; do not report that the Play app has no accessibility
  service. Prepare the AccessibilityService declaration, listing disclosure and a
  video covering the separate in-app explanation, accept/decline paths, Android
  enablement and owner-started control session. Review the actual shipping flow
  and data access against [Google's accessibility requirements](https://support.google.com/googleplay/android-developer/answer/10964491).
  Source inspection does not establish consent/UI acceptance or Play approval.
- **Texts and calls:** declare `READ_SMS`, `SEND_SMS`, `RECEIVE_SMS`, `RECEIVE_MMS` and
  `READ_CALL_LOG` under the **cross-device synchronization or transfer of SMS or
  calls** exception, with a video of a text and a call shown on the computer. Google
  decides these case by case; KDE Connect was refused in 2019. If Saiph is refused,
  remove those five permissions in `src/play/AndroidManifest.xml` the same way as the
  others. Texts and calls then stay in the website build only.
- **Foreground services:** declare `connectedDevice` (staying connected to your
  computers), `dataSync` (Saiph Cloud sync and file transfer) and `mediaProjection`
  (Share screen, started by the owner each time), each with a short video.
- **Display over other apps** (the clipboard bubble) needs no declaration; the
  owner turns it on in Settings → Clipboard.
- **Data safety:** messages, notifications, photos, files and clipboard leave the
  phone only end-to-end encrypted to the owner's own approved devices. The account
  email is used for sign-in and billing. Usage statistics are opt-in and anonymous.
- **Target API:** the app targets API 36 (Android 16). Check Play Console's current
  target API requirement before each release.
