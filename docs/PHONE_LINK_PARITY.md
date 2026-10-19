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
| Send files phone ↔ PC, Send to from Explorer / file managers | Built, acceptance pending | H |
| Lock the PC from the phone | Built, acceptance pending (opt-in) | E |
| SMS: reply in existing one-to-one threads | Have | — |
| SMS: start a new conversation, contact search | Built, acceptance pending | A1 |
| MMS pictures (receive) | Built, acceptance pending | A2 |
| Group replies | Built, acceptance pending | A3 |
| Sending a picture by MMS from the computer | Not yet built (optional part of A3) | A3 |
| Calls: answer or decline | Have | — |
| Calls: dial from the PC, call history | Built, acceptance pending | B1 |
| Calls: talk through the PC's microphone and speakers | Missing on Windows: [gate test](CALL_AUDIO.md) ready, not run (needs a PC with Bluetooth). Linux prototype built, physical tests pending | B2 |
| Phone media controls (audio player) | Built, acceptance pending | D |
| Ringer mode (silent / vibrate) | Built, acceptance pending | C |
| Recent photos view: browse, save, drag | Have (kept as it is) | — |
| Phone storage in File Explorer (alongside the photos view) | Missing | F |
| New screenshots and photos offered on the PC | Built, acceptance pending | G |
| Phone panel in the Start menu, send-files drop zone | Partial (tray icon) | H |
| Screen mirroring | Partial (scrcpy; needs wireless or USB debugging) | J |
| Phone apps in their own windows, pin to the apps menu | Built, acceptance pending (needs debugging) | J |
| Instant hotspot | Partial (Android does not let apps switch it on) | — |
| Continue websites from the phone | Covered by browser sync; Saiph's Open on desktop share | — |
| Clipboard history sync (reported in testing) | Not planned until Microsoft ships it | — |

## Quality-of-life parity (Phone Link screenshots, 18 October 2026)

The owner compared Saiph with Phone Link's device header, quick actions and
settings pages. Audit of the code at checkpoint `d5cd902`, Saiph Cloud first.
"Link" means a phone on a self-hosted Hub; "Cloud" means the default Saiph
account. Before this work a Cloud phone sent no status at all: no battery, no
ringer, no media, no Find phone (`Phone.tsx` said so in a comment).

| Phone Link feature | Before (where) | Plan / outcome |
| --- | --- | --- |
| Header: phone name, online/offline | Have (`Phone.tsx` `DeviceSwitcher`, `DeviceStatus`) | Keep; add a Refresh button (Cloud: renews the subscription so the phone resends its status) |
| Header: battery % and charging | Link only (`phone.py` `battery` event) | Cloud: new `phone.status` event, shown in the header and tray |
| Header: Wi-Fi connected, Bluetooth on/off, cellular signal bars | Missing everywhere | Cloud: in `phone.status` (no SSID, so no location permission); Link: not yet |
| Header: wallpaper thumbnail | Missing | Cloud and (since the shared layer) Hub, opt-in: `phone.wallpaper.request` → small JPEG answer. Android only lets an app read the wallpaper with All files access (Android 13+) or storage access (12 and older); otherwise the setting says why |
| Quick action: Do Not Disturb | Link: shared DND across devices (`DoNotDisturb`) | Cloud: `phone.dnd` toggles the phone's own DND; needs Do Not Disturb access, requested from the phone's Cloud screen |
| Quick action: ring/vibrate/silent | Link only (`PhonePanel` `Ringer`) | Cloud: `phone.ringer` with the same control; needs Do Not Disturb access |
| Quick action: audio player | Link only (`media.state`, `phone.media`) | Cloud: `media.state` + `media.command` (play, pause, next, previous); needs notification access |
| Quick action: Find my phone (rings on silent) | Link only (`phone.ring`, `OrionRing` alarm stream) | Cloud: `phone.ring`, same 30-second alarm with Stop |
| Settings: Notifications / Messages / Photos / Apps / Calls toggles | Missing (only the phone-side permissions) | Desktop `link.phone.features`: hides the tab or card and stops storing that data; Calls shows off and disabled when the phone does not share calls |
| Sync over mobile data | Missing | Phone-side setting (enforced on Android: Cloud sync pauses on a metered network and says so first); the desktop shows it and can change it while connected |
| Wallpaper as app background | Missing | Desktop opt-in `link.phone.wallpaper`, blurred behind the Phone page |
| Transferred files | Partial (per-file "Show in folder") | "Open received files" opens Downloads → Saiph for Cloud and Hub (Windows Downloads Known Folder, `XDG_DOWNLOAD_DIR` on Linux) |
| Instant hotspot | Partial: the computer joins the phone's hotspot from a saved profile (`hotspot.py`) | Android does not let ordinary apps switch the hotspot on (no root). Cloud: `phone.hotspot` posts a notification on the phone that opens its hotspot settings |
| Audio player toggle | Missing | Desktop `link.phone.audio_player` hides now playing in the panel and tray |
| Cross-device copy and paste | Have (`link.clipboard`, Connections tab) | Link from the Phone settings card to it |
| Taskbar unread badge | Missing | Windows: overlay count of phone notifications through `ITaskbarList3` (ctypes, Qt 6 has no QWinTaskbarButton). Linux: not built (no common API besides Unity's LauncherEntry) |
| Recent content in Start | Missing (Start panel closed to other apps) | Equivalent: recent phone notifications in the tray Phone menu, on/off |
| Help: Send feedback | Missing | Opens a new issue on the public repository (no support mailbox is published yet, see `website/LAUNCH.md`) |
| Help: troubleshooting General, Apps, Calls, Messages, Notifications, Phone screen, Photos | Partial (`USER_GUIDE.md` "Troubleshooting and privacy") | Concise topics in the app and in that guide section |

Protocol rules kept: new Cloud event types instead of new fields, and the new
controls are listed inside `phone.status`, never in `phone.capabilities`,
because an older desktop rejects a capabilities event with names it does not
know. Status is sent on change, at most every 15 seconds (ringer, DND and
charging changes at once), with a 10-minute refresh; it piggybacks on the
existing sync loop, so it adds no wake-ups. Since the shared layer below, Hub
("Link") phones send the same `phone.status` and take the same Refresh, Do Not
Disturb, hotspot and wallpaper actions; only Sync over mobile data stays Cloud only.

### Physical acceptance checklist (not yet run)

Phone `com.orionmini.mobile` from this branch, signed in to Saiph Cloud and
approved by the desktop under test. "Within N s" allows for the phone's 5-second
sync loop and the desktop's 4-second poll.

| # | Step | Expected |
| --- | --- | --- |
| 1 | Open the desktop Phone tab | Header: name, Online, Bluetooth, Wi-Fi and signal icons, battery % (matches `adb shell dumpsys battery`), Refresh |
| 2 | `adb shell dumpsys battery set ac 1`, then `unplug`, then `reset` | "· charging" appears and goes within 10 s each |
| 3 | `adb shell dumpsys battery set level 42`, then `reset` | 42% within 25 s (15 s rate limit), then the real level |
| 4 | `adb shell cmd bluetooth_manager disable`, then `enable` | Bluetooth icon off, then on, within 10 s |
| 5 | Click Refresh twice quickly | No error; the second click within 10 s sends nothing |
| 6 | Before granting Do Not Disturb access | Quick actions show Find phone only, plus a hint naming Do Not Disturb access |
| 7 | Phone: Saiph → Status and quick controls → Allow Do Not Disturb access (or `adb shell cmd notification allow_dnd com.orionmini.mobile`) | Do Not Disturb tile and Ring / Vibrate / Silent appear within 10 s |
| 8 | Click the Do Not Disturb tile, then again | `adb shell settings get global zen_mode` reads 1, then 0; the tile follows |
| 9 | Click Silent, Vibrate, Ring | `adb shell dumpsys audio` ringer mode follows each click |
| 10 | Phone on Silent; click Find phone | Alarm sound for up to 30 s with a Stop notification; Stop ends it |
| 11 | Play audio in a phone media app | Now playing shows title and app within 10 s; Pause/Next work from the desktop; Settings → Phone → Audio player off hides it |
| 12 | Settings → Phone → Instant hotspot → Open on phone | Phone notification "Your computer wants to use your hotspot"; tapping opens hotspot settings |
| 13 | Settings → Phone → Sync over mobile data off, then `adb shell svc wifi disable` (mobile data on) | Desktop: phone offline with "Paused: Sync over mobile data is off…" within 15 s; phone notification says "Paused on mobile data" |
| 14 | `adb shell svc wifi enable`; turn the switch back on from the phone's Cloud screen | Phone online again within 15 s; switch shows on |
| 15 | Settings → Phone → Use phone wallpaper on (Android 13+ without All files access) | Reason under the switch; after granting All files access and toggling again, a thumbnail replaces the phone icon and the page gets a blurred background |
| 16 | Turn Messages, Photos, Apps, Calls off one by one | Each tab disappears; with Calls off an incoming call raises no desktop alert |
| 17 | Turn Notifications off | Notifications card replaced by a note; new notifications are not stored; badge clears |
| 18 | Windows: post `adb shell cmd notification post -t "Synthetic" parity "Synthetic body"` | Taskbar button shows a red count within 5 s; Unread badge off clears it |
| 19 | Right-click the tray icon → Phone | Cloud phone with battery, Do Not Disturb, Ring phone and up to 3 recent notifications; a recent item opens Saiph |
| 20 | Phone: Stop sharing status | Header icons and quick actions disappear within 10 s |

## One phone feature layer (Hub and Saiph Cloud)

The self-hosted Hub ("Link") and Saiph Cloud ("hosted") were meant to be one
system with a different server. They grew as two protocol stacks: the Hub relays
readable events and validates the types it knows (`hub/orion_hub/phone.py`,
`features.py`); Cloud carries end-to-end sealed envelopes with its own
exact-shape codec (`hosted_features.py`), roster and subscription checks
(`hosted_runtime.py`) and Android runtime (`HostedRuntime`, `HostedPhoneFrames`,
`HostedPhoneBridge`). Each feature was then ported by hand, and
`OrionNetworkManager.sendMessage` silently drops whatever the Cloud branch was
not taught. That is how Cloud phones had no battery, ringer, media or Find phone
until the Phone Link work above, and why Hub phones still lacked what was added
for Cloud only.

### Audit: every phone event and command

Code at this branch. Shapes are the event body; Cloud payloads also carry
`"type"` inside the sealed envelope. **Gap** names the side that lacks it; "by
design" marks a difference that follows from the transport.

| Feature | Direction | Hub (Link) type and shape | Cloud type and shape | Gap |
| --- | --- | --- | --- | --- |
| Capabilities | Phone → all | Socket `hello {capabilities[≤32]}`, any name | `phone.capabilities {capabilities}`, fixed names only | By design (the Hub keeps them per device) |
| Subscription | PC → phone | — (the Hub fans out to every paired device) | `phone.subscribe {label}`, renewed, kept 10 min | By design |
| Notification posted | Phone → PCs | `notification.upsert {key, app, package, title, text, timestamp, actions[≤10]{index, label}, reply_key?, silent}` | `notification.upsert {notification: {key, app, title, text, timestamp}}` plus `notification.actions {key, timestamp, actions, reply_key}` | **Cloud lacks** package, silent (actions and replies: Cloud parity below) |
| Notification removed | Phone → PCs | `notification.remove {key}` | `notification.remove {key}` | — |
| Notification reconcile | Phone → PCs | `notification.sync {keys[≤500]}` | — | **Cloud lacks** |
| Notification command | PC → phone | `notification.command {key, operation: dismiss/action/reply/open, index?, text?, reply_key?}` | `notification.dismiss {key}`, `notification.action {key, index}`, `notification.reply {key, reply_key, text}`, `notification.open {key}`, any approved computer | Closed by Cloud parity |
| Battery | Phone → PCs, PC → phones | `battery {battery_level, is_charging}` (phones and computers) | Phone: inside `phone.status`; computers: — | **Cloud lacks** computer batteries (item L) |
| Status header: battery, charging, Wi-Fi, cellular, metered, Bluetooth, signal, ringer, DND, controls, mobile_data, paused | Phone → PCs | `phone.status`, same body (**new in this slice**) | `phone.status {12 keys}` | Closed for the Hub by this slice |
| Wi-Fi and mobile bars | Phone → PCs | `phone.signal {wifi_level, cellular_level}` (0–4 or null), with every `phone.status` | Same | — |
| Ringer state | Phone → PCs | `ringer.state {mode}` (kept for older desktops) and inside `phone.status` | Inside `phone.status` | — |
| Now playing | Phone → PCs | `media.state {sessions[≤5]{source, app, title, artist, playing, can_play, can_pause, can_next, can_previous, can_seek, position_ms, length_ms, volume}}` | `media.state {sessions[≤5]{the first nine}}` | **Cloud lacks** seek position and volume |
| Media control | PC → phone | `media.command {source, action: play/pause/next/previous/seek/volume, value?}` | `media.command {source, action: play/pause/next/previous}` | **Cloud lacks** seek and volume |
| Refresh | PC → phone | `phone.status.request {}` (**new in this slice**) | `phone.status.request {}` | Closed for the Hub |
| Find phone | PC → phone | `phone.ring {}` | `phone.ring {}` | — |
| Ring / vibrate / silent | PC → phone | `phone.ringer {mode}` | `phone.ringer {mode}` | — |
| Phone's own Do Not Disturb | PC → phone | `phone.dnd {active}` (**new in this slice**) | `phone.dnd {active}` | Closed for the Hub |
| Shared continuity DND and quiet hours | Both ways | `focus.state {active, changed_at}`, `focus.plan {enabled, timezone, start/end hour and minute}` | — | **Cloud lacks** |
| Instant hotspot | PC → phone | `phone.hotspot {}` (**new in this slice**) | `phone.hotspot {}` | Closed for the Hub |
| Sync over mobile data | PC → phone | — | `phone.mobile_data {allowed}` | By design (a Cloud sync setting) |
| Wallpaper | PC → phone → asker | `phone.wallpaper.request {}` → `phone.wallpaper {preview}` to the asker only, never stored (**new, second slice**) | Same, sealed | Closed for the Hub |
| Find this computer | Phone → PC | `computer.ring {}` | — | **Cloud lacks** |
| Phone remote (touchpad, keys) | Phone ↔ PC | `remote.catalog.request`, `remote.catalog`, `remote.command`, `remote.result` | — | **Cloud lacks** |
| Conversation list | Phone → PCs | `sms.thread {thread, recipients[≤10], message}` | Same | — |
| Messages | Phone → PCs | `sms.messages {thread, messages[≤10]}` | Same | — |
| Conversation removed | Phone → PCs | `sms.remove {thread}` | Same | — |
| Message index | Phone → PCs | `sms.index {thread, ids[≤2000]}` | `sms.index {thread, ids[≤1000]}` | Limits differ |
| Ask for conversations | PC → phone | — (Hub snapshot) | `sms.sync {}` | By design |
| Open a conversation | PC → phone | `sms.open {thread}` | Same | — |
| Reply | PC → phone | `sms.send {thread, text}`; group threads need `sms-group` | Same; group threads need `sms-group` in `phone.features` | Closed by Cloud parity |
| New message | PC → phone | `sms.compose {addresses[1], text}` | Same | — |
| MMS parts | Phone → PCs, PC → phone | `sms.attachments {thread, message, parts[≤10]}`, `sms.attachment.request {thread, message, part}`, `sms.attachment.file` (direct peer) | Same first two; `sms.attachment.original` (sealed attachment, asker only) | By design (closed by Cloud parity) |
| Call state | Phone → PCs | `call.state {state, number, name}` | Same | — |
| Call race | Phone → PCs | — (the Hub checks "still ringing") | `call.handled {operation, by}`, `call.refused {request, reason, handled, by}` | By design |
| Answer or decline | PC → phone | `call.command {operation}` | Same | — |
| Dial | PC → phone | `call.dial {number}` | Same | — |
| Contact search | PC → phone → asker | `contacts.search {query}` → `contacts.results {query, contacts[≤20]}` | Same | — |
| Call history | PC → phone → asker | `calls.log.request {}` → `calls.log {calls[≤50]}` | Same | — |
| Recent photos | Phone → PCs | `photos.index {photos[≤10]{id, name, timestamp, thumbnail: direct file}}` | `photos.item {id, name, timestamp, preview: JPEG data URL}` | Shapes differ by transport |
| Photo list | Phone → PCs | `photos.sync {ids[≤100]}` | Same | — |
| Photo original | PC → phone → asker | `photo.request {id}` → `photo.original` (direct peer file) | `photo.request {id}` → sealed attachment | By design |
| Ready-to-paste photo | Phone → PC | `capture.insert {sha256}` | — | **Cloud lacks** |
| Send a file | Both ways | `file.offer` (direct peer, up to 2 GB) | `file.encrypted` (sealed attachment) | By design |
| Clipboard | Both ways | `clipboard {mime, text or direct blob}` | `clipboard.text {text, sha256}`, sealed `clipboard.image` attachment | By design |
| Handoff ("Open on desktop") | Phone → PC | `handoff` | — | **Cloud lacks** |

### Design: one codec, one capability model, two transports

**Goal:** a phone feature is defined once (its event types, exact shapes, limits
and the capability that gates it) and both transports carry it. A transport only
frames, authenticates and routes.

1. **One codec per feature, used by both transports.** Desktop:
   `src/orion_mini/phone_status.py` (this slice) is the pattern. Each later
   feature gets one module with `read_*` functions over the *body* (the payload
   without `"type"`). `hosted_features.py` keeps only Cloud framing (the type
   inside the sealed payload, the 20,000-byte plaintext limit) and calls the
   shared readers. The Hub's `features.py` validates the same shapes for relaying
   and storage; the desktop validates again because an older Hub relays new types
   unchecked. Android: one `*Frames` object per feature (`PhoneStatusFrames`), with
   `body()` for the Hub and `payload()` (body plus type) for Cloud. The same JSON
   literals in the desktop and Android tests pin the wire format.
2. **Dialects only for legacy differences.** Where installed Hubs or desktops
   already enforce a different shape (Hub media sessions with seek and volume,
   seek and volume commands), the codec names the dialect (`LINK`, `HOSTED`)
   instead of forking the feature. New features have no dialect.
3. **One capability model.** Long-lived data features keep a capability name
   (`sms`, `calls`, `photos` and so on), advertised by `hello` on the Hub and by
   `phone.capabilities` on Cloud. Quick actions are listed in the phone's
   `phone.status` `controls` on both transports, never in a capabilities list,
   because older Cloud desktops reject unknown capability names. Desktops merge
   both into one `capabilities` list per phone (`StatusBook.view`), so the UI
   checks one list whichever transport carried it. A current Hub accepts a
   command when the phone advertises the capability *or* lists the control in its
   stored status.
4. **One Android publisher interface, two implementations.** A feature asks the
   layer to publish and never branches on the transport. For status this is
   `PhoneStatusPublisher` (when and to whom, with the same rate limits), driven by
   `LinkPhoneStatus` (one broadcast through `OrionLink`; the Hub fans out) or by
   `HostedRuntime` (one sealed copy per subscribed computer). Quick actions run in
   one place (`PhoneQuickControls.apply`). The next step generalises this to a
   `PhoneFeatureTransport { targets(); send(target, type, body) }`, so that
   `OrionNetworkManager.sendMessage` stops silently dropping messages on Cloud
   and instead reports a feature the transport does not carry.
5. **One desktop handler fed by both.** The Hub path (`phone.py`) and the Cloud
   path (`hosted_runtime.py`) authenticate, then hand the validated body to the
   same handler (`StatusBook.apply`, `PhoneFeatures.event`), which stores it in
   the same records. Commands leave through `PhoneFeatures.command`, which routes
   to the Cloud mailbox or the Hub socket and applies the same shape check.
6. **What does not change.** Cloud stays end-to-end sealed, with roster
   membership, per-recipient subscription checks and request windows for private
   answers. Exact-shape validation stays on every receiving side. New behaviour
   arrives as new event types, never new fields. Orion identifiers, pairing and
   data paths are untouched.

Compatibility for the status slice:

| Phone | Hub | Desktop | Result |
| --- | --- | --- | --- |
| New | New | New | Header, Refresh, Do Not Disturb, hotspot and wallpaper on Hub phones; the Hub keeps the latest status for reconnecting computers |
| New | Older | New | The same, except a reconnecting computer waits for the phone's next status (at most 10 minutes) |
| New | Any | Older | Older desktops ignore `phone.status`; ring, ringer and media work as before, because the phone still advertises them and still sends `battery` and `ringer.state` |
| Older | Any | New | No status: the page shows what it did before (battery event, older capabilities) |
| Cloud phone | — | New | Unchanged wire format; the desktop moves its status record to `phone_status`, reading the older `hosted_phone_status` record once |

Migration order, one feature per slice, Cloud never regressing: status and quick
actions (done) → wallpaper on the Hub (done) → notifications (Cloud gains actions
and replies: built; reconcile still to do) → media seek and volume on Cloud (a new
`media.seek` type) → MMS parts and group replies on Cloud (built) → continuity DND and
computer batteries on Cloud → the generic Android transport interface, after
which a new feature is written once.

### First slice: status and quick actions (built, acceptance pending)

- **Desktop:** `phone_status.py` holds the codec (`read_status`, `read_media`,
  `read_command`), which transport carries which control, and `StatusBook` (one
  record per phone, one view). `hosted_features.py`, `hosted_runtime.py`,
  `phone.py` and `phone_features.py` use it. Hub phones now show Wi-Fi,
  Bluetooth and signal, Refresh, the phone's own Do Not Disturb and the hotspot
  request; the frontend gates these on the status instead of on Saiph Cloud.
- **Hub:** `features.py` validates `phone.status`, `phone.status.request`,
  `phone.dnd` and `phone.hotspot`, keeps each phone's latest status (returned in
  the phone snapshot as `statuses`) and accepts a command the phone lists in its
  status controls.
- **Android:** `PhoneStatusFrames` (codec for both transports),
  `PhoneStatusPublisher` (rate limits and Refresh), `PhoneQuickControls` (reading
  the status, running the actions) and `LinkPhoneStatus` (the Hub transport, run
  by `OrionLinkService`). Cloud's `HostedRuntime` uses the same publisher. The
  "Status and quick controls" switch is shared (shown on the Link screen since
  the second slice).
- **Not in this slice:** Hub media through the publisher (Hub media keeps its
  event-driven path and older shape).

### Second slice: wallpaper on the Hub and one Status switch (built, acceptance pending)

- **Codec:** `phone.wallpaper` (`read_wallpaper`, JPEG frame-size check
  `bounded_jpeg`) moved into `phone_status.py`; Cloud's `hosted_features.py`
  and photo thumbnails reuse it. Android has `PhoneStatusFrames.wallpaperBody`
  for the Hub and `wallpaper` (body plus type) for Cloud.
- **Request window, one place:** `StatusBook.wallpaper_due`, `wallpaper_asked`
  and `wallpaper_answer` decide when to ask an opted-in phone (every six hours,
  never twice a minute) and accept an answer only within a minute of this
  computer's own request, on both transports. Cloud keeps one book per runtime.
- **Hub:** `phone.wallpaper.request` is a phone command needing the
  `wallpaper` control; `phone.wallpaper` is a private answer to exactly one
  computer, relayed and never stored. With the setting off, the desktop's phone
  snapshot carries no picture.
- **Android:** a Hub phone lists `wallpaper` when Android lets Saiph read it and
  answers only the computer that asked. The Link screen's Settings has "Share
  status and quick controls" under Your computers, the same switch as on the
  Saiph Cloud screen.
- **Frontend:** Use phone wallpaper works for Hub phones; the reason under it
  names an old phone version or the Android access it needs.

### Third slice: Find phone state and Stop from the computer (built, acceptance pending)

- **Phone → every computer:** `phone.ring.state {ringing, seconds}` on each
  start and stop, wherever it was stopped (the phone's Stop screen or
  notification, a volume or power press, the computer, or the 30-second limit).
  `seconds` is 1–120 while ringing and 0 once stopped. Cloud seals one copy per
  subscribed computer; a Hub phone broadcasts it. It is a separate type, so
  `phone.status` and `phone.capabilities` keep their exact shapes: released
  desktops ignore the type and older Hubs relay it unchecked. A newer Hub checks
  its shape (`RingState`) and never stores it.
- **Desktop:** `phone_status.read_ring_state` and `StatusBook` keep "ringing
  until" per phone in memory only, from a phone offering `ring`; the phone view
  gains `ringing`, which ends by itself after `seconds` if "stopped" is lost and
  is false while offline.
- **Computer → phone:** `phone.ring.stop {}` under the same `ring` control (no new
  control name). The desktop offers it only while the phone reports ringing,
  which only phones that also take the command do. The Find phone tile becomes
  **Stop ringing** (a pressed switch) meanwhile.
- **Android:** `PhoneStatusFrames.ringState` / `ringStateBody` build the event
  from `OrionRing.state`; `HostedSyncService` and `OrionLinkService` send each
  change. `phone.ring.stop` runs through the shared layer on both transports
  (`LINK_COMMANDS` for the Hub) and stops the ring as the phone's own Stop does.
- **Tests:** `tests/test_phone_status_shared.py`, `tests/test_hosted_phone.py`,
  `hub/tests/test_phone_features.py`, `PhonePanel.test.tsx`,
  `PhoneStatusFramesTest`, `FindPhoneRingTest`; the wire literals match on both
  sides.

**Physical acceptance (not yet run), third slice:** Find phone from the desktop
shows Stop ringing within a sync pass on both transports; Stop ringing silences
the phone and closes its Stop screen; Stop on the phone (screen, notification,
volume, power) and the 30-second limit each turn the tile back to Find phone; an
older desktop still rings the phone and ignores the new event.

**Physical acceptance (not yet run), both slices:** with a Hub-paired phone, steps
1–12, 15 and 20 of the checklist above (step 7 and 20: use Settings → Your
computers on the phone's Link screen), plus: the Hub's phone snapshot lists the
phone in `statuses`; with an older Hub, the header appears within 10 minutes of
the desktop reconnecting.

### Signal bars: `phone.signal` (built, acceptance pending)

Owner report on the real phone: battery was live, but the header's Wi-Fi and
mobile bars did not match the phone. `phone.status` only says whether the
active network is Wi-Fi (`wifi`) or mobile (`cellular`), so the desktop drew a
full Wi-Fi icon whatever the strength, and mobile bars changed at most once a
minute. Now:

- The phone sends `phone.signal {wifi_level, cellular_level}` with every
  `phone.status`, over the Hub and Saiph Cloud alike. Wi-Fi bars come from the
  connection's RSSI, computed as Android's status bar does (null when Wi-Fi is not
  connected; no location access). Mobile bars come from the SIM's registered cell,
  whichever network is active (null without a ready SIM or registered cell).
- It is a new type, not new `phone.status` fields: older desktops ignore it and
  older Hubs relay it unchecked, while the unchanged `phone.status` keeps working
  for them. A current Hub validates it and keeps the latest one for reconnecting
  computers (`signals` in its snapshot).
- A change in bars alone is sent after 15 seconds (was 60), still rate limited;
  other changes keep their rules.
- The desktop draws Wi-Fi bars from `wifi_level` and mobile bars from
  `cellular_level`, so both show while on Wi-Fi, as on the phone. A phone that
  predates `phone.signal` still shows Wi-Fi as connected or not.

Physical check: compare the header with the phone's status bar on Wi-Fi near and
far from the router, and with Wi-Fi off; bars should match within about 20 seconds.

## Saiph Cloud feature parity

Goal (owner, 18 October 2026): Saiph Cloud and a self-hosted Hub offer the same
features. Audit of `main` at `df61dba`: Cloud lacked notification replies, MMS
pictures and group replies; the README also listed image clipboard and phone
controls as self-hosted only, which was out of date.

| Feature | Before | Now on Cloud | State |
| --- | --- | --- | --- |
| Notification buttons, inline reply, open on phone | View and dismiss only | `notification.actions`, `notification.action`, `notification.reply`, `notification.open` | Built, unit-tested; physical acceptance pending |
| Image clipboard | Already built (sealed `clipboard.image` attachment, `hosted_clipboard.py`, `HostedRuntime.syncClipboardImage`); README said text only | Unchanged | Built, unit-tested; physical acceptance pending |
| MMS pictures (receive) | Not defined | `sms.attachments` (the Hub's shape), `sms.attachment.request`, `sms.attachment.original` | Built, unit-tested; physical acceptance pending |
| Group replies | Refused on both sides | The same `sms.send`, allowed for up to 10 recipients when the phone lists `sms-group` | Built, unit-tested; physical acceptance pending |
| Phone controls (find phone, ringer, media, Do Not Disturb) | Built in the status slices above; README said self-hosted only | Unchanged | Built, unit-tested; physical acceptance pending |
| Cloud folder | Self-hosted only | Stays self-hosted | Decision below |
| Keyboard and mouse sharing (Deskflow) | Self-hosted only | Stays self-hosted | Decision below |

**Protocol.** New sealed event types, never new fields, each with an exact shape
on both sides (`hosted_features.py`, `HostedPhoneFrames.kt`,
`HostedNotificationFrames.kt`):

- `phone.features {features}`, phone → every approved computer, with each
  capabilities heartbeat. Names: `notification-actions` (notification access
  granted), `sms-mms` and `sms-group` (Texts and calls on, SMS permission). They
  are never added to `phone.capabilities`, because desktops released before this
  refuse unknown names there; older desktops ignore the new event type. A desktop
  skips names it does not know, so later phones can add features here without a
  new event. The desktop keeps the list with the phone's capabilities (so it
  survives a restart) and drops the `sms-*` names when `sms` leaves them.
- `notification.actions {key, timestamp, actions[≤10]{index, label}, reply_key}`,
  phone → every approved computer, sent just before the matching
  `notification.upsert`. `reply_key` is `""` when the notification takes no
  reply. The desktop shows buttons only while `timestamp` matches the stored
  notification, so a later post without buttons hides them. Computer → phone:
  `notification.action {key, index}`, `notification.reply {key, reply_key, text ≤4096}`
  and `notification.open {key}`. Like dismiss, any approved computer may send them
  (every computer receives the notifications); the phone checks roster
  membership, notification access and a receipt (at most once per event), and
  `NotificationFeature` checks the button index and reply key against the live
  notification. The desktop only sends a button or reply key it received.
- `sms.attachments {thread, message, parts[≤10]{part, mime, name}}`, phone → each
  subscribed computer, after the conversation or message it belongs to. Bytes
  never travel unasked: `sms.attachment.request {thread, message, part}` asks for
  one part, and the phone answers only that computer with
  `sms.attachment.original {thread, message, part, request, file}`, a sealed
  streaming attachment like `photo.original`. The desktop accepts it only for its
  own request in the last five minutes (memory only), then shows it in the
  conversation exactly as a Hub part (`phone_attachment_file`).
- Group replies reuse `sms.send {thread, text}`: an older phone still refuses a
  group thread, so the desktop allows it only when the phone lists `sms-group`.
  The phone sends through upstream's group MMS path, as on the Hub.

**Desktop:** `hosted_runtime.py` (`_phone_features`, `_notification_actions`,
`notification_command`, `_sms_attachment`), `hosted_files._manifest` (unwraps
`sms.attachment.original`), `phone_features.cloud_attachment`, `phone.py`
(Cloud toasts get buttons and the Windows reply field), bridge method
`hosted.notification`. **Frontend:** `NotificationList` takes `commands`
(`hosted.notification`, Open only with `notification-actions`); Messages already
keyed group replies and MMS parts on capabilities and stored parts.
**Android:** `HostedNotificationFrames`, `HostedPhoneFrames` (features, parts,
`SmsPart` command), `MmsParts` (shared with the Hub path), `HostedAttachments`
(`wrap`), `HostedRuntime` (advertises features, takes notification commands,
`sendSmsPart`), `HostedSyncService`, `OrionNetworkManager`.

**Tests:** `tests/test_hosted_phone.py` (shapes, wire literals, runtime gating,
an MMS part across the real sealed mailbox and streaming decryption, revocation),
`HostedParityFramesTest.kt` (the same literals), `HostedPhoneFramesTest.kt`,
`PhoneHosted.test.tsx`.

**Decisions.**

- **Cloud folder stays self-hosted.** It is a Seafile library served by the
  owner's Hub over its private mesh. Saiph Cloud is a relay for sealed envelopes
  and short-lived attachments (20 MB, minutes); it stores no files, and adding
  hosted file storage would be a new storage service with its own encryption,
  quotas and pricing: an owner decision, not a parity fix. With Cloud the folder
  still works as a local folder that any sync tool the owner chooses can sync.
- **Keyboard and mouse sharing stays self-hosted.** Deskflow needs a direct,
  low-latency TCP connection between computers; Saiph only lets it listen on the
  Hub's mesh address (`deskflow.py`). Saiph Cloud is store-and-forward with
  polling measured in seconds, so a pointer through it would be unusable and
  would put every keystroke through the relay. A later option: computers on the
  same local network exchange their address and Deskflow TLS fingerprint in
  sealed events and connect directly, without the relay. That needs its own
  design (LAN listening, fingerprint pinning), so it is not part of this work.

### Physical acceptance checklist, Cloud parity (not yet run)

Phone `com.orionmini.mobile` from this branch on Saiph Cloud, approved by the
desktop under test, with notification access and Texts and calls on.

| # | Step | Expected |
| --- | --- | --- |
| 1 | Receive a message in a chat app with Reply and Mark as read | The desktop card and the desktop notification show both buttons within a sync pass |
| 2 | Reply from the desktop card, then from the Windows notification's reply field | Each reply is sent by the chat app on the phone once |
| 3 | Mark as read from the desktop | The phone's notification updates or goes |
| 4 | Open on phone (the card's open icon) | The chat opens on the phone |
| 5 | An older desktop (beta.7) on the same account | Notifications still show; no errors |
| 6 | Receive an MMS picture in a one-to-one and a group thread | Show picture fetches it within a minute; Save puts it in Downloads → Saiph |
| 7 | Reply in a group thread from the desktop | Every member receives one MMS; the reply appears in the thread |
| 8 | Turn Texts and calls off on the phone | Within two minutes the group reply box says to reply on the phone, and Show picture says the feature is unavailable |
| 9 | Copy an image on the desktop, paste on the phone; then the other way | The image arrives within 30 seconds both ways |

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
- **Desk research done (14 October 2026):** see
  [research/CALL_AUDIO_SPIKE.md](research/CALL_AUDIO_SPIKE.md).
  - **Linux: go (prototype).** PipeWire takes the hands-free role without root.
    The role is on by default with WirePlumber 0.5 (Ubuntu 26.04); on 0.4
    (Ubuntu 24.04) one per-user file turns it on. PipeWire 1.4+ adds call control
    on the session bus.
  - **Windows: no-go for now.** The API needs package identity and a restricted
    capability, has been gated since 22H2, and Phone Link holds the registration.
    A 2-day gate test on the owner's PC decides.
  - **Ubuntu 22.04 (PulseAudio + oFono): no-go.**
  - **18 October 2026:** the owner put Windows + Android first and Linux second.
    [CALL_AUDIO.md](CALL_AUDIO.md) has the one-step Windows gate test (harness in
    `native/windows-call-audio-gate/`, not yet run: the owner's desktop has no
    Bluetooth radio), the Linux prototype built into the app, and the physical test
    steps for both.
  - A read-only probe, `src/orion_mini/call_audio_probe.py`, is ready for the
    owner's physical tests; it is not wired into the app.

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

### K. Sketch and markup to the computer — built, acceptance pending

Draw on the phone, or mark up a photo, and it lands on the computer's clipboard
with a ready-to-paste notice, through the Photo to computer path.

### L. Batteries for all devices — built, acceptance pending (widget not yet)

Computers publish their own battery level; the phone shows every device's
battery on its home screen and in an optional widget.

### M. Phone as touchpad and keyboard — built, acceptance pending

A phone remote adapter (off by default, like typing) for pointer movement,
clicks and scrolling, with the existing text box as the keyboard. Windows and
X11; Wayland does not allow generated input.

### N. Find this computer — built, acceptance pending

The phone rings a paired computer for up to 30 seconds, with a Stop window on the
computer. Windows' own Find my device does not play a sound.

### O. Lock this computer when the phone leaves (Linux) — built, acceptance pending

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
| 10 | B2 Call audio spike ([findings](research/CALL_AUDIO_SPIKE.md)) | Spike | Windows API gated to Phone Link since 22H2; Linux needs physical proof |
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
