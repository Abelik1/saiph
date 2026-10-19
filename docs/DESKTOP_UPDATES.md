# Desktop in-app updates (Windows and Linux)

Saiph checks for a desktop update by itself two minutes after it starts and
then every six hours, from the place this computer already uses: its Saiph
account, or its paired self-hosted Hub. When a newer build is offered, a
glowing **Update to x.y.z** button appears in the window's footer, beside the
installed version. One click checks again, downloads and verifies the update,
then closes Saiph, runs the native installer and reopens the new version.

**Settings → Updates → Check for updates** does the same in two steps: it shows
**Saiph x.y.z is available**, what's new, and **Download update (size)**; the
download shows progress and is verified; then **Restart to update** installs.
The footer button and the panel share one state, so an update found or started
in one shows in the other.

Status (2026-10-19): the footer button, the six-hourly check and the Hosted
service routes are built and tested with synthetic fixtures (branch
`claude/desktop-update-button-0288fb`). **The routes are not deployed**, and no
catalog with release descriptions exists yet: until both are, a Saiph account
computer's background check finds nothing (no button) and its Settings check
says "Your Saiph account doesn't offer desktop updates yet. Download the latest
version from your account." Hub computers use the Hub's existing
`/v1/link/desktop/...` routes, unchanged. No real installer has been run by this
updater on Windows or Linux.

Android works the same way; see [ANDROID_UPDATES.md](ANDROID_UPDATES.md).

## Where updates come from

| Computer | Source |
| --- | --- |
| Saiph account | `CloudFeed`: the `service_url` packaged into this build (`hosted-defaults.json`, HTTPS on 443), only when the computer's Cloud settings use that same origin (`HostedController.update_feed`), with the account's own access token. No environment proxy, redirect, cookie or supplied URL. A custom deployment is never an update source. |
| Self-hosted Hub | Signed mesh requests to the paired Hub, as before. |

Reasons shown instead of an offer: `cloud_unavailable` (the service has no
update route yet: HTTP 404), `cloud_signed_out` (no token, 401/403),
`cloud_unofficial` (not the packaged origin, or no packaged defaults),
`cloud_manual` (this build has no Cloud support).

## The footer Update button and the six-hourly check

`src/orion_mini/update_schedule.py` keeps one update state for the footer, the
Settings panel and the tray's **Check for updates**: `none`, `checking`,
`available`, `downloading`, `ready` (downloaded from Settings), `installing` and
`failed`. The window starts it with one single-shot Qt timer two minutes after
start-up and one repeating six-hour timer (`FIRST_CHECK_MS`,
`CHECK_INTERVAL_MS`), not in test sessions (`ORION_MINI_TEST`). Idle cost is
those timers; nothing polls.

- **Background checks** run on a worker thread, only in packaged builds, and
  never while another check, download or install runs. They never download or
  install. Offline, signed out, not offered, or a refused description: no
  button and no message; the next check tries again. A downloaded update and an
  unretried failure are kept.
- **The button** (`frontend/src/workspace/UpdateButton.tsx`) is absent for
  `none`. `available` shows **Update to x.y.z** and `ready` **Restart to
  update**, both glowing. One click calls `app.update.now`, which takes no
  options from the page: check again (if the update was withdrawn, the button
  disappears and "Saiph is up to date." shows for six seconds), download and
  verify exactly as Settings does (a download Settings already verified for the
  same release is reused), then the existing installer handoff and restart.
  `checking`, `downloading` (percentage, polled once a second only while
  downloading) and `installing` show as plain status text. `failed` shows
  **Update failed · Try again** with the reason as its tooltip; it stays until
  retried, or until Settings checks again.
- **Cheap glow.** A still `box-shadow` plus three 2.4 s breaths when the button
  appears (`.update-glow` in `motifs.css`), no animation under reduced motion,
  and no spinner in any state: an endless animation would present new frames
  forever (see [DESKTOP_PERFORMANCE.md](DESKTOP_PERFORMANCE.md)).
- The state reaches the page in the dashboard snapshot (`app_update`); each
  change announces itself, so the snapshot is rebuilt only on transitions.

The footer click is the explicit consent to install: its tooltip says Saiph will
download, check, install and reopen, and the installer handoff and recovery are
unchanged (the old version reopens if anything fails).

## What is checked

1. The description is strict JSON (no repeated keys, no NaN, at most 16 KiB)
   with exactly `schema, platform, profile, build, version, sha256, bytes,
   notes`; the first seven follow the existing mesh rules; `notes` is at most
   4000 characters without control or text-direction characters.
2. Platform and edition must equal the installed ones; a newer build must use
   a new version; an equal or older build is never offered. Once a build is
   seen, an older build or different bytes under the same build number are
   refused ("older or conflicting").
3. Download: a fresh ticket per attempt, then `GET /v1/download/<ticket>`
   without `Authorization`. `Content-Length` must equal `bytes`; more bytes,
   fewer bytes or another SHA-256 delete the fresh staging folder. Progress is
   reported (`app.update.progress`).
4. Windows `.exe`: the existing checks (x86-64 PE, Saiph installer footer,
   embedded package manifest, edition and build equal to the offer).
5. Linux `.run`: never executed. Its header must be the Saiph setup template
   with one `version`, `archive_name`, `payload_bytes` and `payload_sha256`,
   the version must equal the offer, and the appended archive must have that
   size and hash. That `.tar.gz` is then checked and staged exactly as a Hub
   download. (`.run --text` does the same: unpack the archive and run its
   `install.sh` with no choices set, which keeps existing ones.)
6. **Restart to update** rechecks the staged file and starts the existing
   handoff: Windows `--silent --no-launch`, Linux the archive's `install.sh`;
   the old version reopens if anything fails. Linux keeps the autostart and
   file-action choices (the variables stay unset). Windows silent mode keeps
   the startup choice, but `WindowsSetup.cs` re-creates the Send to shortcut
   and the invitation-file association even if they were removed; this is
   existing behaviour shared with the Hub path and needs an installer change
   (for example a `--keep-integration` flag) to fix.

Without a release signature, integrity rests on the pinned HTTPS origin, the
account's authenticated request and the published SHA-256. The Windows
installer carries no publisher signature yet. See the proposal.

## Service routes (implemented, not deployed)

The desktop routes now exist on the shared Hosted service
(`hub/orion_hub/hosted_service.py`, `hosted_downloads.py`); deploying them and
publishing the catalog entries are owner/ops work. The Android half is still a
proposal in [ANDROID_UPDATES.md](ANDROID_UPDATES.md#proposal-android-release-description-in-the-hosted-catalog).

**Catalog.** `windows_release` and `linux_release` entries (existing
`{file, sha256}` format) name files such as:

```json
{"schema":1,"platform":"windows-x86_64","profile":"link","build":11,"version":"0.1.0-beta.11","sha256":"<the windows entry's sha256>","bytes":123456789,"notes":"Short what's new text."}
```

For Linux, `sha256`/`bytes` describe the `.run` file (the `linux` entry).
`build` and `version` are the `distribution-release.json` values inside the
package. `Downloads.__init__` refuses to load (so the service does not start)
unless each description is strict JSON with exactly the client's keys and rules
(schema 1, its own platform, edition, build, version, notes) and its
`sha256`/`bytes` equal the matching `windows`/`linux` installer entry. A
description without its installer, or a changed description file, also refuses.
Descriptions are held in memory and can never be ticketed as downloads.
Producing them belongs to the publishing scripts in the operations repository
(not done). One description per platform serves one edition; a computer of the
other edition refuses it (its background check stays quiet).

**Routes** for **native** client tokens (`self.tokens`, as `/v1/account` uses; a
website token gets 401), with the no-Origin/no-cookie/no-query rules (403) and
the active-and-entitled account check (403):

| Route | Answer |
| --- | --- |
| `GET /v1/app/desktop/windows-x86_64/release` and `.../linux-x86_64/release` | 200 with the exact description bytes (`application/json`, `no-store`), 204 when the catalog has none, 404 when the service has no download catalog |
| `POST /v1/app/desktop/<platform>/download` with `{}` | `{"ticket": "<43 chars>"}` for that platform's installer only; 404 without a description |
| `GET /v1/app/android/release`, `POST /v1/app/android/download` | not implemented (Android proposal) |

Other platforms and actions are 404, other methods 405. Tickets, Range, the
shared rate limits and refusal of `Authorization` on `/v1/download/<ticket>` are
unchanged. Usage totals count them as `desktop.release` and `desktop.download`.

**Release signature (recommended before leaving beta).** A key pair kept
offline by the owner (Ed25519). The publishing scripts write
`<description>.sig` (detached signature over the exact description bytes) as
another catalog entry, served with the description (for example as a
`Saiph-Release-Signature` header or a `/release.sig` route). Builds embed the
public key; clients then refuse unsigned or mis-signed descriptions. This
matters most for desktop: Android already refuses any APK not signed with the
installed app's certificate, but the Windows installer and Linux `.run` have no
publisher signature, so today a compromised service could serve a different
installer with a matching hash. Not implemented, because no key or signature
exists to verify against.

**Service tests:** `hub/tests/test_hosted_desktop_updates.py` covers the cases
above (native token accepted; website, unknown and revoked accounts refused;
browser-style requests refused; descriptions that disagree with their
installer, are malformed or lack their installer refuse to load; tickets only
for the described installer; Range resume; shared limits).

## Testing

`tests/test_update_schedule.py` (schedule constants and wiring, quiet background
checks, the one-click flow and every failure point, one update at a time,
Settings parity, bridge routing and the snapshot field),
`tests/test_desktop_update_feed.py` (the desktop's real `CloudFeed`, check and
stage against the real Hosted routes in process, Windows and a real Linux
`.run`), `hub/tests/test_hosted_desktop_updates.py`,
`frontend/src/workspace/UpdateButton.test.tsx` (button states none, available,
checking, downloading, ready, installing, failed; progress polling; finite glow
and reduced motion; Settings following the shared state; the footer in the
window), `tests/test_package_updates_cloud.py` (synthetic service for the proposed
routes: strict descriptions, reasons, downgrade and conflict refusals, origin
and token rules, ticket download, damaged/oversized/short/mislabelled
downloads, a real `.run` built by `build-desktop-distribution.py` around a
synthetic package, damaged `.run` files, source selection and origin pinning),
the existing `tests/test_package_updates.py`, `tests/test_cloud_bridge.py` and
`frontend/src/workspace/Updates.test.tsx`.

**Physical test plan (pending):** with a packaged build N installed from the
real installer, and a development service carrying these routes and build N+1:
wait two minutes after start-up (or use the tray's Check for updates) and see
the footer button glow; click it (Saiph downloads, closes, installs, reopens on
N+1); repeat through Settings: check (notes, size), download (progress), Restart
to update (startup and association choices kept), then
repeat with a damaged file, an older build and a signed-out account. Linux:
the same with the `.run`. A Hub computer: confirm the old path still works.
