# Android in-app updates

**Settings → About & help → Version and updates → Check for updates** opens the
Update screen. It checks the place this phone already gets Saiph from,
shows **Update available: 0.9.x** with what's new, downloads the APK into
app-private storage with progress and resume, verifies it, and hands it to
Android's installer. Android always shows its own install prompt; Saiph never
installs anything silently.

Status (2026-10-18): built and JVM-tested on branch `claude/android-updater-39fe8a`.
**The Saiph account source needs the two service routes proposed below, which do
not exist yet.** Until they ship, a Saiph account phone's check ends with "Your
Saiph account doesn't offer app updates yet" and a link to the downloads page
(and, in Firebase-enabled tester builds, a **Check Firebase App Tester** button).
The Hub source uses the Hub's existing routes. No physical install has been tried.

## Where updates come from

The source is chosen by the phone's own setup, never by a URL it receives:

| Phone | Source | State |
| --- | --- | --- |
| Signed in to a Saiph account | The Hosted service origin packaged in this build (`hosted-defaults.json` `service_url`, HTTPS, port 443), and only when the phone uses that same origin. Requests carry the phone's own account token. | Needs the proposed routes |
| Paired with a self-hosted Hub | `GET /v1/app/android` and `GET /v1/app/android/apk`, signed with the phone's pairing key, as before | Existing routes |
| Debug builds only | A test server saved in Settings (see "Testing") | Compiled out of beta and release |
| Firebase App Tester | Firebase's own updater, from the Update screen when the source above is unavailable, and the existing tester alert at startup | Unchanged |

The website's **Standalone Android APK** is the same file: the account site
issues a ticket for catalog entry `android`. That route only accepts the
website's sign-in client, so the phone cannot use it today, and the catalog
carries no version number, size or release notes. Hence the proposal.

## What is checked, in order

1. The release description parses strictly (`UpdateManifest`): exact key set,
   no repeated keys, UTF-8, at most 16 KiB, versionCode 1–2 100 000 000,
   lowercase SHA-256, size at most 200 MB, notes without control or text-direction
   characters. Anything else is refused before downloading.
2. Only a strictly newer versionCode is offered; an equal one is "up to date"; a
   lower one is refused as a downgrade; a higher `min_sdk` than the phone's is
   refused (`UpdatePolicy`).
3. No network: "You're offline". Metered network: the screen asks first and
   downloads only after **Download on mobile data**.
4. The download goes to `noBackupFilesDir/updates/<sha256>.apk.part`, resuming
   with `Range: bytes=N-`. A 206 must continue at exactly N with the published
   total; a 200 restarts from zero; a 416 restarts once. More bytes than
   published, a wrong final size or a wrong SHA-256 deletes the file
   (`ResumableDownload`).
5. Android reads the APK (`getPackageArchiveInfo` with
   `GET_SIGNING_CERTIFICATES`, or `GET_SIGNATURES` on Android 8). Its package must
   be `com.orionmini.mobile`, its versionCode must equal the published one and be
   above the installed one, and its current signer set (`apkContentsSigners`, as
   SHA-256 of each certificate) must equal the installed app's. Otherwise the file
   is deleted (`UpdateVerifier`). A future signing-key rotation would be refused
   and needs an updater change first.
6. If Android does not yet allow Saiph to install apps, an explanation screen
   with picture steps opens **Install unknown apps** for Saiph; returning
   continues with the already verified file.
7. A `PackageInstaller` session receives the bytes, hashing them again as they
   are written, and is committed with `USER_ACTION_REQUIRED` on Android 12+.
   Declining Android's prompt keeps the verified file, so **Install update**
   works again without downloading.

**Check automatically** (on by default) runs a daily WorkManager check on any
network and the Hub link's six-hourly check. Both only post "Saiph 0.9.x is
available" once per version; neither downloads nor installs. Turning the switch
off cancels the daily check. This replaces the Hub link's earlier silent
background download.

## Proposal: Android release description in the Hosted catalog

Owner/ops work, not done here. Nothing below is deployed.

**Catalog.** Add entry `android_release` to the immutable download directory's
`catalog.json` (existing `{file, sha256}` format; the loader already hash-checks
it). Its file, for example `saiph-android-0.9.8-3575000-release.json`, is:

```json
{"schema":1,"package":"com.orionmini.mobile","version_code":3575000,"version_name":"0.9.8","sha256":"<the android entry's sha256>","bytes":57872502,"min_sdk":26,"notes":"Short what's new text."}
```

Exactly these keys. `build-tester-apk.ps1` already has every value except
`notes` and `min_sdk` in `release.json` (`versionCode`, `versionName`,
`apkSha256`, APK size); it should write this file next to it, with notes from the
release record. `Downloads.__init__` should refuse to start unless the description
parses with the same rules as the app and its `sha256` and `bytes` match the
`android` entry, so the two can never disagree.

**Routes** on the shared Hosted service, for the **native** client tokens
(`self.tokens`, as `/v1/account` uses; not the website's `web_tokens`), with the
same no-`Origin`, no-cookie, no-query rules and the same entitlement check as
downloads:

- `GET /v1/app/android/release` → 200 with the description's bytes
  (`Cache-Control: private, no-store`), or 204 when no description is installed.
  401/403 for a bad or unentitled token.
- `POST /v1/app/android/download` with body `{}` → `{"ticket": "<43 chars>"}`,
  exactly `Downloads.issue(identity, "android")`.

The APK then comes from the existing `GET /v1/download/<ticket>`, which already
supports a single `Range` for resume, rate limits per account and refuses
`Authorization`, cookies and queries. The phone asks for a new ticket for every
resume attempt, so the five-minute ticket lifetime and eight requests per ticket
are enough.

Hosted service tests to add with it: unauthenticated, website-token, unentitled
and revoked requests refused; description/APK mismatch refuses to load; ticket
for `android` only (no artifact field accepted); Range resume through the ticket.

## Testing

JVM: `AppUpdateTest` (manifest parsing and every refusal, version policy, hash
vectors, signer and package checks with synthetic certificates, the resumable
downloader against a fake server, and that only debug builds can be redirected).

**Debug test server (debug builds only).** Settings → About & help → Version and
updates shows **Debug update server**. Save a base address ending in `/`; the
server must serve `release.json` (the Hosted schema above) and `saiph.apk`.
Python's `http.server` works (it ignores Range, so resume restarts from zero).
Clear the field to return to the normal source. Beta and release builds compile
`src/beta` / `src/release` stubs instead, so they cannot be redirected.

Synthetic manifest for a test APK built with a higher version code:

```powershell
$apk = 'app-debug.apk'   # built with -PorionVersionCode=<installed + 1>
$hash = (Get-FileHash $apk -Algorithm SHA256).Hash.ToLowerInvariant()
$size = (Get-Item $apk).Length
Copy-Item $apk saiph.apk
Set-Content release.json -NoNewline -Encoding ascii ('{"schema":1,"package":"com.orionmini.mobile","version_code":<code>,"version_name":"0.9.7","sha256":"' + $hash + '","bytes":' + $size + ',"min_sdk":26,"notes":"Synthetic test build."}')
python -m http.server 8000
```

### Physical test plan (pending; needs the coordinator's phone)

Use a debug build signed with the same key as the installed debug build. Nothing
here touches production, the catalog or the owner's installed release app.

1. Install debug build A (version code N). Serve build B (N+1) as above; save
   `http://<laptop LAN IP>:8000/` in the debug field.
2. **Check for updates** shows "Update available: … " with the notes and size.
3. On mobile data (or a metered Wi-Fi), confirm the metered question appears and
   nothing downloads until **Download on mobile data**.
4. Start, then **Pause download**; leave the screen; return: **Resume download**
   continues (with a Range-capable server) or restarts (http.server).
5. With "Install unknown apps" off for Saiph: the explanation screen appears;
   **Open Android settings**, allow, press Back: Android's prompt appears.
6. Decline the prompt: **Install update** returns and installs without a new
   download. Accept: Saiph restarts on N+1, pairing/account intact, the updates
   folder is emptied.
7. Refusals, each expecting the stated message and the file deleted: change one
   byte of `saiph.apk` (hash); serve a build signed with another key (signer);
   serve version N or N−1 with a matching manifest (up to date / downgrade);
   set `bytes` 1 too high (size); add an unknown key to `release.json`
   (invalid update information); stop the server mid-download (Try again
   resumes); airplane mode (offline).
8. **Check automatically** on: after the daily window (or
   `adb shell cmd jobscheduler run -f com.orionmini.mobile <job id>`), one
   notification per version; off: none.
9. Hub phone: publish build B on a test Hub (`publish-android <apk> --version-code … --version-name …` in the Hub CLI) and
   repeat 2 and 6 with the debug field cleared.
10. After the proposed routes are on a development service: repeat 2–7 on a
    Saiph account phone with the debug field cleared.
