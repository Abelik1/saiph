# Phone Link replacement plan

**Goal:** nobody with Saiph should need Microsoft Phone Link. On Windows, Saiph
covers everything Phone Link does for Android phones. The same features work on
Linux, on any phone brand, and without a Microsoft account.

**Filter for new work**

1. If Phone Link does it, Saiph must do it (on Windows, and on Linux where the
   platform allows).
2. If it is not in Phone Link and Google, Samsung or the browser already does it
   well, point to that instead of building it. Examples: Find My Device (locate,
   lock, erase), browser tab sync ("continue browsing"), document scanning in
   Google Drive/Lens, and sharing Wi-Fi by QR code.
3. Otherwise build it only where Saiph is the bridge nothing else provides:
   Linux, self-hosted, any phone brand, computer-to-computer.

Phone Link's feature list below comes from Microsoft's pages and third-party
reports as of October 2026. Microsoft changes it often; recheck before release.

## Where Saiph stands

| Phone Link feature | Saiph | Plan item |
| --- | --- | --- |
| Notifications: view, dismiss, reply, actions | Have | — |
| Phone battery and connection status | Have | C (panel) |
| Several phones, QR setup | Have | — |
| Phone as webcam | Have (scrcpy, OBS on Windows) | — |
| Clipboard sync (latest item) | Have | — |
| Do Not Disturb toggle | Have (shared DND) | C (panel) |
| Send files phone ↔ PC | Have | H (Windows Send to) |
| Lock the PC from the phone | Built, acceptance pending (opt-in) | E |
| SMS: reply in existing one-to-one threads | Have | — |
| SMS: start a new conversation, contact search | Built, acceptance pending | A1 |
| MMS pictures and group conversations | Missing | A2, A3 |
| Calls: answer or decline | Have | — |
| Calls: dial from the PC, call history | Built, acceptance pending | B1 |
| Calls: talk through the PC's microphone and speakers | Missing | B2 (research first) |
| Phone media controls (audio player) | Built, acceptance pending | D |
| Ringer mode (silent / vibrate) | Built, acceptance pending | C |
| Recent photos view: browse, save, drag | Have (kept as it is) | — |
| Phone storage in File Explorer (alongside the photos view) | Missing | F |
| New screenshots and photos offered on the PC | Partial (Photo to computer) | G |
| Phone panel in the Start menu, send-files drop zone | Partial (tray icon) | H |
| Screen mirroring | Partial (scrcpy; needs wireless or USB debugging) | J |
| Phone apps in their own windows, pin to taskbar | Missing (Phone Link: Samsung/Honor only) | J |
| Instant hotspot | Partial (Android does not let apps switch it on) | — |
| Continue websites from the phone | Covered by browser sync; Saiph's Open on desktop share | — |
| Clipboard history sync (reported in testing) | Not planned until Microsoft ships it | — |

## How the work is built

Most missing pieces already exist in the retained upstream Android code
(`android/features`): contacts lookup, MMS parts, call log, media sessions,
ringer state, the installed-app list and an SFTP server. Saiph's Orion bridge
(`PhoneFeatureFrames`, `OrionPhoneFeatures`) only carries SMS text and call
state today. Each item below therefore:

1. adds small, strictly validated Link events (Hub `features.py` models, fixed
   sizes, one target where it is a command, capability checks);
2. prefers **new event types over new fields**, because older Hubs relay unknown
   types but reject unknown fields in known ones;
3. keeps private content off the Hub where possible: contact search, call
   history and MMS pictures travel phone ↔ computer as short-lived events or
   direct peer transfers and are not added to the Hub snapshot;
4. gates every phone feature on its Android permission and advertises a
   capability, so the desktop hides what the phone cannot do;
5. ships with Hub, desktop, frontend and Android unit tests, and stays marked
   **acceptance** in the README until checked on real devices.

## Phase 1: everyday parity

### A1. New messages and contact search — S/M

- Desktop "New message" with a recipient field. Typing searches the phone's
  contacts: `contacts.search {query}` → phone replies `contacts.results` with up
  to 20 names and numbers. Results are kept in memory only, never stored.
- Sending: `sms.compose {addresses, text}` to the phone. One recipient first;
  the Hub requires the `sms` capability but not an existing thread. The new
  thread then appears through the existing SMS sync.
- Android: reuse `ContactsHelper` and `SmsFeature.sendTextMessage`; requires
  READ_CONTACTS and SEND_SMS (already requested in setup).
- Acceptance: send to a new number and to a saved contact; dual-SIM choice.

### A2. MMS pictures (receive) — M

- Phone sends `sms.attachments {thread, message, parts}` describing parts
  (name, MIME type, size), as a separate event type. The desktop asks for a part
  with `sms.attachment.request`; the phone offers it as a direct peer file,
  the same way photo originals travel now.
- Thumbnails come through the same direct path; no picture bytes go to the Hub.
- Android: `SMSHelper`/`SmsMmsUtils` already read MMS parts.

### A3. Group conversations — M/L

- Show group threads fully (they are already listed). Replying needs MMS sending,
  which is fiddly across manufacturers; do it after A2, with its own acceptance.

### B1. Dial and call history — S/M

- `call.dial {number}` → phone places the call with `TelecomManager.placeCall`
  (needs CALL_PHONE). Audio stays on the phone or its headset.
- `calls.log` with the last 50 calls from upstream `CallLogFeature`, on request
  only. Desktop "Calls" tab with redial and "message this number".
- Acceptance: background placement on Android 12–16, dual SIM.

### B2. Calls through the PC's audio — research spike first

- Phone Link uses Bluetooth Hands-Free (HFP) with the PC as the headset. Android
  does not let apps capture call audio, so there is no network route.
- **Windows:** `PhoneLineTransportDevice` and `PhoneLine.Dial` give call control,
  but routing call audio reportedly needs a custom user-mode profile driver, and
  community reports say the API broke on 22H2. **Linux:** BlueZ, PipeWire and
  oFono support the hands-free role.
- Spike (time-boxed): prove audio both ways on one Windows and one Linux PC.
  Decide go or no-go from that; do not promise this feature before then.

### C. Phone panel and quick toggles — S/M

- A compact panel (Phone page header and a tray flyout): battery, connection,
  ringer mode, Do Not Disturb, now playing, recent notifications.
- Ringer: `phone.ringer {mode: ring|vibrate|silent}` command and `ringer.state`
  updates (upstream `RingerModeState`; silent needs Do Not Disturb access).

### D. Phone media controls — S

- Phone publishes `media.state` (app, title, artist, playing, which controls are
  allowed, position; artwork as a small direct-peer image) from upstream
  `PlaybackFeature`. Desktop sends `media.command {play|pause|next|previous|seek}`.
- Shown in the panel and the tray. Requires notification access (media sessions).

### E. Lock this PC from the phone — S

- Phone Link offers it by default. Saiph: a "Lock <computer>" button on the phone
  home screen and quick-settings tile, using a dedicated `computer.lock` event.
- Decision needed: on by default for paired phones (locking is low risk) or
  behind the phone remote setting as now.

## Phase 2: files, photos and Windows integration

### F. Phone storage on the computer — L, design decision needed

Phone Link also shows the phone's storage, including its photo folders, in File
Explorer (online-only files; deleting one deletes it on the phone). Its photos
view remains, and Saiph's recent photos view stays as it is; this adds folder
access alongside it. Options:

| Option | Windows | Linux | Notes |
| --- | --- | --- | --- |
| Upstream SFTP server over the mesh | Needs a third-party SFTP client or driver | Native (GVFS `sftp://`, KDE KIO) | Keys pinned at pairing; quickest on Linux |
| Windows Cloud Files provider (placeholders) | Native File Explorer, like Phone Link | — | Best Windows result; needs a native helper (C#/Rust) |
| WebDAV mapped drive | Built-in WebClient, but it resists plain HTTP and signed requests | Native | Least work, weakest fit |

Recommendation: SFTP for Linux first, then a Cloud Files provider on Windows,
read-only at first and with explicit delete confirmation later.

### G. New screenshots and photos — S

- The recent photos view stays as it is.
- A new screenshot or camera photo on the phone shows a desktop notification
  with "Open", "Copy" and "Save", building on Photo to computer. A setting turns
  it off; nothing transfers until it is clicked.

### H. Windows and Linux integration — M

- **Send to:** the installer adds `Saiph (phone)` to Explorer's Send to menu.
  The shortcut passes files to the running app through its local interface.
  Linux: a file-manager action (Nautilus script / KDE service menu).
- **Windows share sheet:** needs app identity (MSIX or a sparse package). Decide
  together with the release packaging work.
- **Start menu panel:** Microsoft's panel is not open to other apps. Saiph's
  equivalent is the tray flyout from C with a drop zone for sending files.

## Phase 3: apps and mirroring

### J. Phone apps in their own windows — M

- Desktop "Apps" list from upstream `AppListHandler` (names and icons).
- Opening one starts scrcpy with `--new-display` and `--start-app` (Android 10+),
  giving a separate window per app on any brand. "Pin" creates a desktop or
  Start menu shortcut that opens that app.
- Requires wireless or USB debugging, as mirroring does now. Mirroring without
  debugging would need Android screen capture plus an accessibility service for
  input; not planned.

## Apple-style continuity

Apple ecosystem features that Google, Samsung, Windows or the browser do not
already cover. Already built: universal clipboard, handoff, Focus/Do Not Disturb
sync, Continuity Camera and Photo to computer, Universal Control (Deskflow), phone
remote, hotspot reconnection, ring my phone and verification codes. Not planned,
because native tools cover them: locating or erasing a lost phone, continuing
browser tabs, document scanning and Wi-Fi sharing by QR code.

### K. Sketch and markup to the computer — S/M

Draw on the phone, or mark up a photo, and it lands on the computer's clipboard
with a ready-to-paste notice, through the Photo to computer path.

### L. Batteries for all devices — S

Computers publish their own battery level; the phone shows every device's
battery on its home screen and in an optional widget.

### M. Phone as touchpad and keyboard — M

A phone remote adapter (off by default, like typing) for pointer movement,
clicks and scrolling, with the existing text box as the keyboard. Windows and
X11; Wayland does not allow generated input.

### N. Find this computer — S

The phone rings a paired computer for up to 30 seconds, with a Stop window on the
computer. Windows' own Find my device does not play a sound.

### O. Lock this computer when the phone leaves (Linux) — M

Opt-in: lock the session when the Bluetooth-paired phone has been gone for a
while; never unlock automatically. Windows already has Dynamic Lock.

Not this round: approving computer prompts from the phone (Apple Watch-style).
It is security-sensitive and needs its own design.

## Order and size

| Order | Item | Size | Main risk |
| --- | --- | --- | --- |
| 1 | D Media controls | S | Media session differences between apps |
| 2 | A1 New messages, contact search | S/M | Dual-SIM selection |
| 3 | C Panel and ringer | S/M | DND access for silent mode |
| 4 | E Lock PC | S | Default-on decision |
| 5 | B1 Dial and call history | S/M | Background call placement |
| 6 | G New screenshots and photos | S | Battery use of the media observer |
| 7 | H Send to and file-manager actions | M | Single-instance handoff to the running app |
| 8 | A2 MMS pictures | M | Manufacturer MMS storage differences |
| 9 | J App windows | M | scrcpy and Android version support |
| 10 | B2 Call audio spike | Spike | Windows audio routing may be impossible without a driver |
| 11 | F Phone storage | L | Native Windows helper |
| 12 | A3 Group replies | M/L | MMS sending reliability |

Phase 4 then adds K, L, N, M and O. After items 1–7 the everyday Phone Link features are covered except call audio
and File Explorer storage, which depend on decisions B2 and F.

## Decisions needed

1. **Lock PC (E):** on by default for paired phones, or opt-in?
2. **Phone storage (F):** accept SFTP on Linux first and a native Cloud Files
   helper for Windows?
3. **Call audio (B2):** approve a time-boxed spike before committing?
4. **Share sheet (H):** tie Windows share-sheet support to MSIX/sparse packaging?
5. **App windows (J):** acceptable that they need wireless debugging?

## Sources

- [Phone Link (Wikipedia)](https://en.wikipedia.org/wiki/Phone_Link)
- [Link to Windows on Google Play](https://play.google.com/store/apps/details?id=com.microsoft.appmanager&hl=en_US)
- [Microsoft: make and receive calls from your PC](https://support.microsoft.com/windows/apps/make-and-receive-phone-calls-from-your-pc)
- [Microsoft: setting up calls in Phone Link](https://support.microsoft.com/help/4531605)
- [Android Authority: Phone Link panel in the Start menu](https://www.androidauthority.com/phone-link-panel-windows-start-menu-3558774/)
- [Windows Forum: Phone Link photos move to File Explorer](https://windowsforum.com/news/windows-11-phone-link-photos-move-to-file-explorer.441338/)
- [Windows Forum: Android integration with File Explorer and Start](https://windowsforum.com/threads/windows-11-deepens-android-integration-with-file-explorer-and-start-menu.390895/)
- [Ubergizmo: new Android features explored for Windows 11](https://www.ubergizmo.com/2026/07/microsoft-explores-new-android-features-windows-11/)
- [Microsoft: PhoneLineTransportDevice API](https://learn.microsoft.com/en-us/uwp/api/windows.applicationmodel.calls.phonelinetransportdevice?view=winrt-26100)
- [MyPhone (HFP calling on Windows, community project)](https://gitblind.noratr.app/BestOwl/MyPhone)
