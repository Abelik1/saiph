# Phone screen and apps on the computer

Phone → Apps shows the phone's screen on the computer and opens the phone's apps,
over the same Wi-Fi or private LAN, with the camera's local trust design
([PHONE_CAMERA.md](PHONE_CAMERA.md)). It needs no USB cable, adb, scrcpy or
developer options. Every phone screen entry point uses it: the Phone header's
**Mirror screen**, Phone → Apps → **Show phone screen**, and pinned app shortcuts.
Nothing in normal use asks to install scrcpy or adb. The earlier scrcpy windows
remain only behind an explicit opt-in, Settings → Advanced → **USB debugging**
(`link.phone.usb_debugging`, off by default); without it the desktop refuses
`phone.mirror` and the scrcpy app routes, and Phone → Apps does not mention them.

## Why the Apps tab failed on the installed Windows app

Before this change the tab worked only for a phone attached over authorised USB
or wireless debugging with scrcpy installed. Every request ran
(line numbers at d5cd902):

1. `frontend/src/workspace/PhoneTabs.tsx:450` called `phone.apps`, and `:475`
   `phone.app.open`; the copy at `:460` already said it "needs ... the one-time
   debugging setup".
2. `src/orion_mini/desktop_bridge.py:328-335` handled both by constructing
   `AdbWorker()` and calling `paired_serial(device_id)` before anything else.
3. `src/orion_mini/adb_worker.py:25` finds adb only through
   `phone_debugging.adb_path(tool_path('scrcpy'))` (`phone_debugging.py:27`) or a
   source-checkout `.orion-mini/android-sdk`. `companion_tools.tool_path`
   (`companion_tools.py:27-55`) searches PATH, `ANDROID_HOME`, Saiph's optional
   portable tools under `%LOCALAPPDATA%\OrionMini\tools\scrcpy` (installed only
   from Settings) and `%LOCALAPPDATA%\Android\Sdk`. The installed app bundles
   neither adb nor scrcpy, so on a normal computer `self.adb` is `None`.
4. With no adb, `AdbWorker.run` returns `''` (`adb_worker.py:27-28`), so
   `paired_serial` finds no device and raises "Authorized debugging is
   unavailable for this phone. Connect it over USB or wireless debugging..."
   (`adb_worker.py:54-62`). With adb but no USB/wireless debugging session the
   same error appears. With adb and debugging but without scrcpy,
   `phone_apps._scrcpy` raises "Install scrcpy once in Settings → Advanced..."
   (`phone_apps.py:30-35`); an empty serial gives "Choose an authorized phone in
   Settings → Advanced." (`phone_apps.py:38-41`).
5. Even with all of that, `paired_serial` matches only a phone whose bundled
   worker provider reports the same device ID, and `list_apps`/`open_app`
   (`phone_apps.py:44-64`) shell out to `scrcpy --list-apps` and
   `scrcpy --new-display --start-app=...`.
6. Pinned shortcuts (`app.py:372-389`) used the same `AdbWorker` path and also
   required a `battery` capability that Saiph Cloud phones do not advertise.

The webcam does not have this problem because its default path is a
phone-initiated, pinned TLS connection on the local network; adb is used only by
its legacy tools. The Apps tab now uses that design.

## How it works

1. Phone → Apps → **Show phone screen** (or **Open** on an app, or a pinned app
   shortcut) starts a one-use session on the computer: an ephemeral P-256
   certificate, a 256-bit bearer secret, a 128-bit session ID and literal
   RFC1918 addresses, valid for two minutes (`screen_session.py`).
2. **Offer delivery.** If the phone is an approved Saiph Cloud phone that
   advertises `screen`, the offer goes to it as one sealed `session.offer` event,
   end-to-end encrypted between roster members, so nothing is scanned. The phone
   posts a notification "Show your phone screen on <computer>?". Otherwise, or
   if delivery fails, the computer shows the same offer as a QR code, scanned in
   Saiph → Show phone screen. The Cloud page always offers "Show a code to scan".
   This is the same envelope the camera uses without a QR:
   `{"type":"session.offer","version":1,"id","service":"screen","expires_at","invite"}`,
   where `invite` is exactly the QR text (`orion-screen:1:...`) and `expires_at`
   equals its deadline. `src/orion_mini/session_offer.py` and Android
   `SessionOffer.kt` define it once for every service, with shared vectors in
   `android/app/src/test/resources/session-offer-vectors.json`. The phone accepts
   it only from a subscribed computer, records a durable receipt per offer ID,
   keeps the invitation in memory, and puts only the offer ID in the notification;
   the invitation reaches the capture service in memory, never in an intent.
3. **On the phone** the owner taps Start sharing, verifies with biometrics or the
   screen lock (a secure lock screen is required), then accepts Android's own
   screen capture prompt. On Android 14+ the prompt is limited to the entire
   screen (`MediaProjectionConfig.createConfigForDefaultDisplay`), so it is a single
   "Start now" step; Android asks again for every session by design. The phone
   then shows its home screen, because Saiph's own protected windows appear black.
4. `ScreenShareService` (foreground service, type `mediaProjection`) connects to
   the computer with the camera's exact certificate pinning and bearer
   authentication, mirrors the display into an `ImageReader` and sends JPEG frames
   at the chosen 15/20/30 fps, 720p or 1080p (longest side 1280 or 1920, pixel
   budget 1280×720 or 1920×1080, aspect kept, never rotated) and Standard/High
   quality. A still screen repeats its last frame every 1.5 s so the computer can
   tell a quiet screen from a lost one. Rotation resizes the same virtual display.
5. The desktop app shows the frames in **their own window** (below); the Apps tab
   keeps a compact card with a red Live badge, Show window and Stop. Without the
   Qt shell (browser preview) the page embeds the picture as before. With control
   on, clicks become taps, holds of 500 ms long presses, drags swipes, the wheel a
   short swipe; Esc or a right-click is Back, a middle-click Home; buttons send
   Back, Home and Recents; typing and paste send text; Backspace and Enter edit
   the focused field.
6. **Opening an app** sends `launch` with a package name over the live session
   (or puts it in a new offer). The phone starts only that package's own launcher
   intent. Android blocks background activity starts unless Saiph's input service
   is on or "Display over other apps" was allowed; otherwise the phone shows a
   "Tap to open <app>" notification and the computer says so.
7. **App list.** The computer sends `apps.request` over Saiph Cloud; the phone
   answers only that computer with `apps.list` pages built from a launcher query
   (`<queries>` MAIN/LAUNCHER intent), names and package names only, each page
   within one sealed event. Without Cloud, a live session can return the list
   over its socket. The Apps tab shows them as a grid of icons (below). The Start
   menu/applications-menu shortcut (a tile's menu → Add to Start menu) is
   unchanged; such a shortcut opens the phone screen with that app.

## Mirror screen

The Phone header's **Mirror screen** starts the same local session as Show phone
screen (1080p, 20 fps, High) for the selected phone and opens Phone → Apps, where
the request status, and the code to scan if the phone did not receive the
request, are shown (`screen.invite` hands the page the QR of a session it did not
start itself; never the invitation's secret). While the phone screen is live in its
own window, Mirror screen brings that window forward. A pinned app shortcut for a
phone that does not advertise `screen` also gets a local session with a code,
instead of scrcpy, unless USB debugging is turned on.

Bundling for the advanced path (not done; for a later decision): scrcpy and its
`scrcpy-server` are Apache-2.0 and could ship with their licence and notices.
scrcpy's Windows release also carries SDL2 (zlib), FFmpeg and libusb (LGPL), which
need their notices and the LGPL source/relinking terms. adb's source is
Apache-2.0, but Google's prebuilt platform-tools are distributed under the
Android SDK licence, which does not grant redistribution; shipping adb would mean
building it from AOSP source (as Linux distributions do) or a legal review of the
prebuilt binaries. None of this is needed for normal use.

## The phone screen window

`src/orion_mini/phone_screen_window.py` opens a separate native window as soon as a
session goes live. It is a plain `QWidget`: the session's receiving thread decodes
each JPEG into a `QImage` and hands over only the latest one, so frames never
become base64 data URIs, never cross the page bridge and are dropped (not queued)
if painting falls behind. The page builds a data URI only for the embedded
fallback, and only when it asks. The window:

- is sized to the phone's aspect ratio (82% of the screen height the first time),
  can be moved and resized (the picture letterboxes), refits when the phone turns,
  and remembers its position and size in `phone-screen-window.json` in the
  profile (validated on load; ignored when off every screen);
- has a compact toolbar: Back, Home, Recents (disabled while view only), Rotate
  view (a local 90° turn, with pointer mapping turned to match), a red **● LIVE**
  badge, the control state and measured fps, and **■ Stop**;
- has a red outline while live, and the tray icon gains a red dot (tooltip
  "Saiph · Live: phone screen and/or camera") while the phone screen or the phone
  camera is live;
- forwards mouse and keyboard as the same validated `input_message` shapes, in
  order on one sender thread, only while the phone reports control on;
- stops the session when closed (Stop, the window's close button or quitting
  Saiph); when the phone ends the session the window closes without a second stop.

The same window code runs on Linux (X11 and Wayland; Wayland compositors may
ignore the remembered position).

## The Apps grid

Phone → Apps shows the apps as tiles with each app's icon and name, a search box
(name or package name), a **Pinned** row and a **Most used** row (up to eight),
then All apps. Tiles lift on hover and press in; reduced motion turns that off.
A tile's menu (hover "…" or right-click) pins or unpins it or adds a Start menu /
applications-menu shortcut.

- **Pinned** apps are kept per phone on this computer (`phone-apps.json`, at most 24).
- **Most used** counts how often this computer opened each app, per phone, in the
  same file. Saiph on Android does not hold Android's usage-access permission, so
  the phone contributes no usage history; nothing about usage leaves the computer.
- **Icons** come from the phone, over Saiph Cloud only (a phone reached only through
  a live LAN session or the scrcpy path shows each app's initial instead). The page
  asks for the tiles it shows; the computer answers from its cache and asks the
  phone for at most 24 missing or unchecked icons per request with
  `{"type":"apps.icons.request","apps":[{"package","version"}]}`, `version` being
  the cached one (0 for none). The phone answers only that computer, only for its
  launcher apps and only while "Let my computers offer sessions" is on, with one
  or more sealed `{"type":"apps.icons","icons":[{"package","version","data"}],"same":[package]}`
  events. `data` is a base64 static WebP of at most 96 px and 12,000 bytes;
  `same` lists apps with nothing new (unchanged version, not listed, or no
  encodable icon). The computer accepts only packages it asked that phone about
  in the last minute, checks the exact shape and every image (PNG or WebP
  signature, container length, no animation, 16-128 px sides from the header)
  and caches it under the profile's `phone-app-icons/` by package and version
  (at most 600, oldest dropped; re-validated when read). It asks again whether
  an icon changed at most every six hours. Phones rate limit icon requests to 12
  a minute per computer. Older computers and phones ignore the new event types;
  `apps.list` keeps its exact shape.

## Requests on the phone

When a computer offers the camera or the phone screen, the phone posts a
high-priority notification (heads-up on Android), now with an **Allow** action.
If Saiph is open and unlocked, it also shows an in-app sheet: "<computer> wants
to use your camera" or "<computer> wants to show your screen", with **Allow**
and **Not now**. Allow opens the camera or phone screen page, which asks for
owner verification at once and then starts (the camera) or shows Android's
capture prompt (the screen); nothing starts from the sheet itself. Not now drops
the offer. Back or a tap outside hides the sheet but keeps the notification; a
request still pending when Saiph comes to the foreground pops up once.

The notification and sheet disappear when the offer is opened or the service
starts by any route, when it expires (Android's notification timeout plus the
app's own timer), when the computer is revoked, and when the computer sends
`{"type":"session.close","version":1,"id":<offer id>}` because its waiting
session was answered (for example by scanning the code instead), cancelled or
expired. Only the computer that sent an offer can close it. This fixes a used or
expired camera request staying in the notification shade. No full-screen intent
is used: Android 14 reserves it for calling and alarm apps, so heads-up is the
strongest permitted alert for this category.

## Live indicators

Whenever the camera or phone screen is live it is red and obvious. On the
computer: a red **Live** badge in the Phone header (naming camera, screen or
both), a red outline and badge on the live camera card and on the phone screen
card, the window's red outline and badge, and the tray icon's red dot. On the
phone: a persistent red **● LIVE** banner on the camera page while it streams and
on the phone screen page while sharing, and the ongoing notification styled as
live (red accent, colorized for the foreground service, running time and Stop);
the camera, which runs inside its page, gets its own ongoing live notification
with Stop. Photos, text and call sharing keep their usual look.

Older computers ignore the new `screen.capabilities` event; phones never add the
new names to `phone.capabilities`, which older computers would reject. Older
phones without the feature get the QR path, and their Saiph cannot scan it until
updated.

### Wire format

Frames: an 18-byte network-order SSF1 header (magic, width, height, rotation = 0,
64-bit increasing sequence) followed by a JPEG whose SOF dimensions must match;
at most 1,500,000 bytes. Camera SCF1 frames are refused on this socket.

Computer → phone text messages (exact keys; positions are integers 0-10000 of the
shown frame): `tap`/`long {x,y}`, `swipe {x,y,x2,y2,ms 50-3000}`,
`key {back|home|recents|backspace|enter}`, `text {1-256 printable characters}`,
`launch {package}`, `apps {}`. At most 60 per second; input types are refused by
the computer unless the phone reported control on.

Phone → computer text messages: `state {input}`, `apps {apps: [{package,name}]}`,
`launched {package, ok}`. Anything else, including any binary message to the
phone, ends the session.

Sealed Cloud events added for the grid and request cleanup (exact shapes above):
`apps.icons.request` and `apps.icons` (capability `apps`), and `session.close`
(the offer's computer only).

## Security and privacy

- Same bar as the camera: one-use, two-minute offers; pinned certificate and exact
  IP hostname; no proxies or redirects; the secret is sent only inside the pinned
  TLS connection and claimed before upgrade; one connection; replayed or
  out-of-bounds frames end the session; idle peers time out after eight seconds;
  sessions last at most an hour.
- Owner verification on the phone before every session, then Android's capture
  consent. A visible, persistent notification with Stop is shown while sharing,
  and Android shows its own screen-sharing indicator.
- MediaProjection renders `FLAG_SECURE` windows black. That includes Saiph's own
  screens, so the phone screen, PIN and banking apps are not visible remotely.
- Nothing is recorded. Each side keeps only the latest frame in memory; frames
  and offers are never logged or written to status/diagnostics. There is no audio.
  The dashboard loads the latest frame's bytes from the desktop's local frame
  feed (`saiph-frame:`, never cached to disk; see
  [DESKTOP_PERFORMANCE.md](DESKTOP_PERFORMANCE.md)).
- The session ends on Stop (either device), disconnect, screen off, keyguard lock,
  the projection being revoked, or the offer/session timeout.
- Input exists only while a session is live: the computer refuses input outside
  one, and `SaiphInputService` acts only while `ScreenShareService` is connected.
- Control is a separate opt-in Android accessibility service. Saiph shows an
  explanation screen first and sends the owner to Android's Accessibility settings;
  the service reads no events and keeps nothing. Without it, sessions are view only.
- Offers and app lists over Cloud are accepted only from current, subscribed
  roster members, and only while the owner's "Let my computers offer sessions"
  switch is on (default on). An offer only posts a notification.
- Apps open only through their own launch intent; the computer cannot name an
  activity, component or extra.

## Limits

- Phone and computer must share a private IPv4 LAN; no Internet relay or NAT
  traversal (as with the camera).
- JPEG frames rather than H.264: the desktop bundle has no H.264 decoder, and the
  JPEG path reuses the camera's bounded, validated pipeline. Fast-moving content
  costs more Wi-Fi than video would. Actual frame rate depends on both devices.
- One mirrored display: an opened app replaces what the phone shows, unlike
  scrcpy's separate virtual-display windows (still available under Advanced).
- Text entry edits the focused field (`ACTION_SET_TEXT`); some custom editors or
  games ignore it. Enter uses `ACTION_IME_ENTER` (Android 11+).
- Self-hosted Hub phones use the QR fallback; Cloud delivery needs Saiph Cloud.
- Physical-phone behaviour, performance, OEM accessibility/MediaProjection
  variations and independent security review are not established by the tests.

## Verification

Desktop: `python -m pytest tests/test_phone_screen.py` (real loopback TLS with a
synthetic client: frames, input forwarding, refusals, expiry, idle timeout,
Cloud offer delivery and app-list pages through the real sealed relay fixture).

The threaded websockets test client is capped at TLS 1.2 (`tests/lan_tls.py`):
CPython's `ssl` sockets are unsafe for a concurrent recv() and send() under TLS 1.3,
and that client writes its upgrade request while its reader thread receives the
server's session tickets, so about one in three requests never arrived and the
server timed out after 5 s. This is a property of the test client, not of the
servers. Sequential TLS 1.3 clients never stalled, and separate regression tests
use one for both servers. An OkHttp 4.12 client on a JVM (JSSE) completed 30/30
full-duplex TLS 1.3 sessions in a probe. Android's Conscrypt was not run here.
Also `tests/test_phone_screen_window.py` (pointer mapping with letterbox and
rotation, gestures, window sizing, geometry store, and a real loopback session
opening the native window, refitting on rotation, forwarding toolbar, click,
typing and Esc, stopping the session on close, closing without a second stop
when the phone ends it, and the tray live state) and
`tests/test_phone_app_library.py` (icon format checks with crafted WebP/PNG,
the package+version cache and tampering, lookup paging, pins and counts, the
icon event shapes, and icons through the sealed relay answering only this
computer's request). `test_phone_screen.py` covers `session.close`.
Frontend: `PhoneScreen.test.tsx` (including the window mode), `PhoneAppGrid.test.tsx`
(rows, search, icons with retries and unsafe values refused, pins, live badge),
the Apps tests in `PhonePanel.test.tsx` and the header badge in `PhoneLayout.test.tsx`.
Android JVM: `PhoneScreenTest` (desktop-produced offer, request validation, frame
header, capture sizing, text edits, app-list paging and screen command policy),
`RequestPromptsTest` (pop-up and notification plan, replacement, expiry, close,
take, revoke, hide, copy, `session.close` parsing and per-computer close) and
`AppIconsTest` (request shape, size fallbacks, unchanged/unlisted apps, sealed
paging, rate limit, permission).
The physical checklist is in [RELEASE_STATUS.md](RELEASE_STATUS.md).
