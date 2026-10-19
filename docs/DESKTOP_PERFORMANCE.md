# Desktop performance: idle CPU, window drag, flicker and camera preview

The desktop is a Qt WebEngine shell (`src/orion_mini/app.py`) around the React
dashboard. Every frame Chromium produces is handed to Qt and composited into the
window on the GUI thread, and the GUI thread also builds the dashboard's state
snapshot, runs the QWebChannel transport and pumps Windows' window-move loop. So
anything that makes Chromium draw continuously, or holds the GUI thread for tens
of milliseconds, shows up as CPU, a window that lags behind the pointer, and a
stuttering preview.

## What was wrong (owner report on beta.32, coordinator measurements)

Idle on the Phone tab, window visible: the Saiph process tree used about 57 % of
one core. Pausing only the selected-tab wave brought that to about 35 %; also
hiding the background canvas brought it to about 26 %.

1. **Background canvas.** `WaveField` redrew 30 strings with `requestAnimationFrame`
   at 15 fps forever (and 30 fps during ripples): a full-window canvas repaint,
   and a new compositor frame, 15 times a second, plus a blank frame after every
   resize (the canvas was cleared and only redrawn on the next loop tick).
2. **Selected-tab wave.** `.wave-underline::before` moved continuously (`linear`
   timing, so a new frame every display refresh) under a masked parent, and both
   the nav underline and the header sit in a bar with `backdrop-filter: blur(14px)`.
   A backdrop blur is recomputed for the whole bar whenever anything inside it
   changes, so a 40×8 px wave cost a full-width blur 60 times a second.
3. **Once-a-second full snapshot on the GUI thread.** `MainWindow.on_tick` emitted
   `changed` every second, hidden, minimised or not. Each one made the page ask
   for `state`, which builds the whole snapshot (all notifications, threads,
   messages, photo previews), serialises and hashes it on the GUI thread. On a
   synthetic 1.4 MB profile that is about 38 ms (see measurements), so once a
   second the GUI thread stalls for two or three display frames. During a window
   drag that is exactly the "lagging behind the pointer" hitch.
4. **A change announced while a snapshot was in flight was dropped** by the page
   (it only refreshed if no fetch was running), hidden by the 1 s tick.
5. **White flash.** The `QWebEnginePage` background was Qt's default white, shown
   wherever Chromium had not yet drawn (growing the window, first show).
6. **Camera preview.** The page polled `camera.frame` over QWebChannel. Each poll
   ran on the GUI thread and returned a base64 data URI (~130 KB as JSON text)
   that Python had produced by decoding the phone's JPEG, scaling it to 960 px
   and re-encoding it, for every frame. Polling also aliased against the phone's
   own cadence, so frames were shown twice or skipped (~12.6 distinct fps shown
   from ~19.5 received). The phone-screen view had the same polling transport.

## What changed and why

- **Static background** (`frontend/src/workspace/waves.tsx`). The string field is
  drawn once, and redrawn only on resize (coalesced to one redraw in the same
  animation frame, so a resize never shows a blank canvas) or a theme/token
  change. (The first pass still let it curl around working buttons and ripple
  after them; the third pass below made it completely still.) No listener
  follows the cursor (tested).
- **Cheap, endless tab wave** (`frontend/src/design-system/motifs.css`). First
  `steps(12)` over 1.2 s; in the second pass (below) one shared JavaScript timer
  moving every underline 1 px at 8 Hz, with no CSS animation running. Tested to
  keep moving forever.
- **No backdrop blur** on the header and footer (`frontend/src/workspace/waves.css`);
  their tint is a little denser instead. With the strings now still, the blur
  bought nothing and multiplied the cost of every wave step.
- **Event-driven dashboard refresh** (`src/orion_mini/app.py`). Phone, Cloud,
  bridge actions and now the camera and phone-screen sessions announce their own
  changes immediately. The periodic tick is only a safety net: every 3 s, only
  while the window is visible and not minimised, and held while the window is
  being moved or resized (until 400 ms after the last move/resize event). Showing
  or restoring the window refreshes at once. `state()` deliberately stays on the
  GUI thread (`automation.py` documents that invariant).
- **Coalesced page refresh** (`frontend/src/App.tsx`). A change announced during
  a fetch triggers exactly one more fetch afterwards.
- **Matching window ground** (`app.py`). The page and window background are the
  dashboard's darkest ground (`#040916`), so resizing never flashes white.
- **Camera and phone-screen frames as pushed bytes** (`src/orion_mini/frame_feed.py`,
  `camera_session.py`, `screen_session.py`, `desktop_bridge.py`,
  `frontend/src/workspace/frameFeed.ts`). Each new frame is announced by a
  small `frame` signal (sequence, rotation, received fps, dimensions). The page
  then loads `saiph-frame://camera/<sequence>` as an image, so the JPEG arrives
  as bytes and Chromium decodes it off the main thread (`Image.decode()`); only
  the newest frame is ever loaded and one decodes at a time. The camera preview
  is drawn to a canvas without a React render per frame; the phone screen keeps
  its `<img>` (its input mapping reads the natural size) and swaps `src`.
  The camera preview is now the phone's own JPEG, untouched: the desktop still
  decodes every frame once to validate it (an undecodable frame still ends the
  session) and still builds the virtual webcam's upright RGBA frame, but no
  longer scales, re-encodes or base64-wraps a preview. The page rotates it.
  The status line shows "receiving N fps · showing M fps".
- **Security properties kept.** Pinned TLS, one-use invitations, the session
  lifetime and the no-audio, no-recording rules are unchanged. The frame scheme
  is a *local* scheme: only the dashboard's own `file:` page can load it (an
  `https:` page cannot; `fetch()` cannot read it). The handler serves only `GET`
  of `/<sequence>` for `camera` or `screen` from a file/qrc initiator, only while
  that session is live, from memory, with `Cache-Control: no-store`; Chromium's
  disk cache never stores custom schemes. `camera.frame` / `screen.frame`
  polling remains for older pages.

## Measurement scripts (synthetic)

All run in fresh disposable sessions with synthetic data; offscreen rendering is
software-only, so absolute numbers differ from an installed app on real
hardware. Compare variants within one machine and mode.

- `scripts/measure-render-cost.py`: synthetic header pages (background canvas,
  translucent bar, selected-tab wave variants) in a real `QWebEngineView`,
  sampling process-tree CPU per variant.
- `scripts/measure-desktop-state.py`: one dashboard refresh's GUI-thread cost on
  a synthetic profile (snapshot + JSON + revision hash); `--seed-only` fills a
  disposable test profile.
- `scripts/measure-desktop-idle.py`: the real shell via `scripts/desktop-ui.py`,
  idle on the Phone page, process-tree CPU; `--seed` adds synthetic rows,
  `--repo`/`--dashboard` run another checkout for before/after.
- `scripts/measure-presentation.py`: visible windows, normal GPU rendering; CPU
  per presented web frame and while the window moves, per hosting mode
  (`widget`, `widget-top`, `widget-native`, `quick`, `container`) and for the real
  shell (`--mode shell --repo <checkout> --dashboard <dist/index.html>`).
- `scripts/measure-camera-preview.py`: the real shell with a synthetic loopback
  "phone" streaming 1080p JPEGs at 20 fps over the real TLS camera server;
  counts distinct pictures the page displays, plus CPU.

### Results (2026-10-18, this Windows 11 desktop, offscreen software rendering, synthetic)

| Measurement | Before (62722ac) | After |
| --- | --- | --- |
| Idle on Phone, empty profile (`measure-desktop-idle.py`, 20 s) | 103–117 % of one core | 18–19 % |
| Idle on Phone, 1.4 MB synthetic rows (`--seed`) | 115 % | 21 % |
| Header page variants (`measure-render-cost.py`, 8 s): moving canvas + 60 Hz wave + blur / static, no blur, stepped wave / static only | 101 % / – / 0.4 % | – / 9–12 % / 0.4 % |
| One `state` snapshot on the GUI thread (`measure-desktop-state.py`) | 38 ms (1.4 MB) / 37 ms (empty), every second | same cost, every 3 s, visible only, never during drag |
| Camera preview, 1080p at 20 fps sent (`measure-camera-preview.py`) | received 20.0, shown 16.7 fps | received 19.9, shown 20.0 fps |

Camera-preview CPU (179 % before, 192 % after) is dominated by software
decoding and scaling of 1080p frames in offscreen mode and is not comparable to
GPU rendering; the new path also shows every frame instead of 84 % of them.
The empty-profile snapshot cost is mostly opening SQLite four to six times
(~12 ms each on this disk); reusing one read connection per snapshot is a
possible follow-up. A bug found while measuring (stopping an idle camera
session announced a change, so every snapshot requested the next) was fixed
before these numbers and has a regression test.

## Second pass: what Qt costs per frame and per window move (beta.33)

Coordinator measurements of beta.33 (RTX 3060 Ti, Windows 11, 1320×900, Phone
tab idle): 35.9 % of a core (beta.32: 57.7 %); with the tab wave paused 15.5 %;
`steps(12)` at 1.2 s 32 %, at 2.4 s 26 %; a JavaScript timer moving 1 px every
100 ms with no CSS animation 24.8 %. About 1 % of a core per presented frame
per second, and the owner still saw drag jitter.

`scripts/measure-presentation.py` hosts a dashboard-shaped page (static canvas,
header, one element moved 1 px at 10 Hz by a timer) in visible windows with
normal GPU rendering, one process per configuration, and samples CPU with the
element still and moving, then moves the window every 16 ms for 5 s. Results on
this desktop (two or three runs each; ranges):

| Host | CPU per presented update | CPU while the window moves |
| --- | --- | --- |
| `QMainWindow` + `QWebEngineView` (beta.33) | 0.6–1.5 % | 58–77 % |
| top-level `QWebEngineView` | 0.8 % | 62 % |
| `QWebEngineView` with `WA_NativeWindow` | 1.3–1.5 % | 72 % |
| top-level `QQuickView` + QML `WebEngineView` | 1.1–1.5 % | 55–79 % |
| `QMainWindow` + `createWindowContainer(QQuickView)` | 0.9–1.35 % | 16–25 % |

`QSG_RHI_BACKEND` (default, `d3d11`, `opengl`) changed neither column beyond
noise. So:

- **The per-frame cost is not a widget readback.** A pure Qt Quick window with
  no widgets at all costs the same per presented frame. It is Chromium's
  frame production plus Qt WebEngine's hand-over (the GPU runs in the browser
  process), roughly 1 % of a core per frame per second at this size. The only
  lever is to present fewer frames.
- **Window moves are where hosting matters, and that is the drag jitter.** Qt
  WebEngine's view item follows its window's on-screen position and forwards
  every change to Chromium as new visual properties; Chromium answers with a
  full new frame. A `QWebEngineView` widget draws through a hidden Quick window
  that tracks the widget's screen position, and a top-level `QQuickView` *is*
  the moved window, so both pay a full Chromium frame and composition per few
  pixels of drag, on the GUI thread that also runs the window-move loop. A
  `QQuickView` embedded as a native child keeps its position relative to the
  main window, so a drag costs Chromium nothing.

What changed:

- **Native child-window view** (`src/orion_mini/dashboard_view.py`). The
  dashboard is a QML `WebEngineView` in a `QQuickView`, embedded in the main
  window with `QWidget.createWindowContainer`; web frames go to the child
  window's own GPU swap chain without widget composition. Behaviour kept: only
  local pages may load (`onNavigationRequested`), new windows are ignored,
  dropped files are taken by Qt before Chromium can navigate to them (an event
  filter on the Quick window), one web channel object (`orionMini`), the dark
  ground behind the page, the frame feed scheme on the default profile (the
  same off-the-record profile as before; the dashboard uses no browser storage).
  Right-click menus (Cut/Copy/Paste/Select all) and `title` tooltips are native
  Qt widgets as before; web dialogs, file and colour pickers and HTTP auth
  prompts are refused (the dashboard uses none), so Qt Quick Controls are not
  needed.
- **Popup position after a drag.** Because the child window never reports the
  main window's moves, Chromium would open a `<select>` list at the window's old
  position (verified: 300,302 instead of 692,400). When a move or resize settles
  (the existing 400 ms hold), the view re-announces its position once, and the
  list opens under the control (verified with a real click and a screen grab).
- **Tab wave on one timer** (`frontend/src/workspace/waves.tsx`,
  `startWaveTicker`). Every `.wave-underline` gets `--wave-shift` from one
  `setInterval` at 8 Hz (1 px per step, 12 px period); no CSS animation runs, so
  the compositor is not woken between steps. The timer stops while the page is
  hidden and for reduced motion.
- **Packaging** (`scripts/build-native.py`,
  `scripts/packaging/hooks/hook-PySide6.QtQml.py`). QtQml, QtQuick and
  QtWebEngineQuick are no longer excluded; a project hook replaces PyInstaller's
  QML hook and collects only the `QtQml` (+ `Models`, `WorkerScript`),
  `QtQuick`, `QtWebEngine` and `QtWebChannel` import directories without their
  sub-modules. Charts, Graphs, Data Visualization, the virtual keyboard and
  Quick Widgets stay excluded. These are Qt Declarative / WebEngine / WebChannel
  LGPL modules whose libraries (`Qt6Quick.dll`, `Qt6Qml.dll`) the WebEngine
  bundle already shipped; their notices are already in the Qt notice set.

Real shell, visible window, GPU (`measure-presentation.py --mode shell`,
isolated profile idle on Phone, two runs each):

| | Idle | While the window moves |
| --- | --- | --- |
| c890b98 (beta.33: widget view, CSS-stepped wave) | 13.3 / 16.8 % | 69.2 / 60.9 % |
| this change | 14.2 / 8.0 % | 23.9 / 22.1 % |

Idle in this isolated profile has one wave on screen and is noisy; expect the
installed app's idle to fall roughly with the update rate (10 → 8 per second,
no compositor ticks between steps) and the drag to stop lagging.

## Third pass: "chunks of the screen twitching" and CPU while hidden (beta.37)

Owner report on 0.1.0-beta.37-acceptance.1 (includes the native child-window
view): parts of the window twitch, not tied to a tab or element. Coordinator:
19–20 % of a core idle whether the window is visible or hidden to the tray (main
process 15–17 %, QtWebEngineProcess about 9 %).

Findings, with the real shell in a fresh synthetic profile (seeded rows, a
synthetic online phone, a new notification and a change notice every 4 s like
Cloud polling):

- **Twitching.** Frame-by-frame grabs of the test window (kept above other
  windows; statistics only, no pixels saved) over 22 s showed nothing changing
  but the two tab waves and the notification list at each refresh, and no
  window-wide flashes (two runs). What the beta still did was move the *still*
  background: every action button curled the strings around itself while it
  worked and sent a ripple across the window for 4 s when it finished, and step
  changes plucked it. On an otherwise still field that reads as random chunks of
  the screen moving, wherever something happened to run, and it is a pointer
  effect in all but name. The field is now completely still (drawn once,
  redrawn on resize or theme change only); a working button shows its spinner.
- **CPU while hidden.** With the window hidden or minimised the page still
  reported `visible`, so its timers kept running, and every phone or Cloud
  change notice still made the page ask for a full snapshot. Now the window
  tells the web view it is hidden (`document.visibilityState` becomes `hidden`;
  the wave timer stops) and the bridge holds change notices, sending one
  refresh when the window is shown again. Measured with the churn: hidden
  6.6 % → 1.0 % (with an accessibility client walking the tree: 8.9 % → 1.8 %);
  visible 18–21 %, most of it the 4-second snapshot of 1.4 MB of synthetic rows.
- **Accessibility.** An active accessibility client (UI Automation tools, screen
  readers) adds 6–9 % while visible for both the old widget view and the new one,
  and Qt's accessible tree has the same nodes in both (no duplication from the
  child window). Measurements taken while UIA tooling inspects the app include
  that cost.
- **Not reproduced:** a window-wide flicker. One full-window change in an early
  run was the desktop behind the test window during the owner's own activity;
  the always-on-top reruns showed none.

## Fourth pass: main-process work while visible and idle (beta.39)

Coordinator on beta.39 (phone on USB, Cloud phone sharing calls and texts):
visible idle 29–35 % of a core, of which the Saiph main process 23 % and
QtWebEngineProcess 6 %; hidden 3.4 %. adb status calls every 10–20 s.

`py-spy` on an isolated offscreen run (seeded rows, synthetic phone, a change
notice every 4 s like Cloud polling) showed the main thread spending its time
rebuilding the dashboard snapshot (about 70 ms each, every 1.7 s): opening
SQLite five or six times per snapshot (~12 ms each here), JSON encoding and
decoding the rows, and walking PATH for the Deskflow check. Background
"orion-tool-inspection" threads rescanned the optional tools every 10 s
(~0.45 s of CPU each, competing for the GIL). The adb status polling runs on a
worker every 15 s, never announces a change, and is cheap.

What changed:

- **Fewer snapshots.** Cloud's fast poll (every 4 s while a phone shares calls or
  texts) announces a change only when it sent, received or expired something.
  Read-only Cloud questions the page asks on a timer (`hosted.approvals` every
  15 s, `hosted.requests` every 4 s, `hosted.link.status` every 1.5 s, and the
  inspect calls) no longer announce a change after answering.
- **Cheaper snapshots.** The bridge builds `state` inside `Store.reading()`: one
  SQLite connection on that thread for the whole snapshot, each access still in
  its own committed transaction. The Deskflow check refreshes on a worker thread
  (still every 30 s). The optional-tools scan still runs every 10 s, so a newly
  installed tool still appears within ten seconds, but it first compares the
  modification times of the folders it searches (PATH entries, Saiph's portable
  tools, Deskflow and Android SDK folders: 17 ms) and walks PATH (about 450 ms)
  only when one changed.

Measured (synthetic, offscreen, this desktop; `scripts/measure-visible-idle.py`,
60 s, two runs each; "before" is 37cd6b2 = beta.39's code, with a change notice
every 4 s standing in for its quiet Cloud polls):

| | Snapshots per minute | Average snapshot | Main process CPU |
| --- | --- | --- | --- |
| before (37cd6b2) | 53–54 | 101–168 ms | 19.2–21.4 % |
| after | 20 | 34–42 ms | 10.2–12.4 % |

`scripts/measure-desktop-state.py` (one snapshot of 1.4 MB of rows): median
62–82 ms with a connection per read, 48–53 ms with one shared connection. The
remaining 20 snapshots a minute are the visible-only 3 s safety net. The main
process figure includes offscreen software compositing of the tab wave, which a
GPU does more cheaply on the installed app.

## Desktop update checks and the footer Update button (2026-10-19)

The six-hourly update check ([DESKTOP_UPDATES.md](DESKTOP_UPDATES.md#the-footer-update-button-and-the-six-hourly-check))
adds two Qt timers (two minutes after start-up, then every six hours) and a short
worker thread per check; nothing polls between checks. The page learns the result
through the existing change announcement, so a snapshot is built only when the
update state changes. The footer button's glow is a still `box-shadow` with three
2.4 s breaths when it appears (none under reduced motion), and its busy states use
still icons, never a spinner, so an offered update costs no frames while idle. While
a download runs, the footer asks for progress once a second (the Settings panel,
when open, every 500 ms as before). Not measured on the installed app.

## Open: blocks, stripes and pixelation under stress

`scripts/stress-render-check.py` runs the real shell with synthetic data behind
other windows and records only that window's frames with Windows Graphics
Capture (optionally Chromium's own frames over DevTools as well, `--chromium`).
It flags frames whose always-identical header or footer strips deviate; a
built-in self-test proves a missing tile column is caught. Broken frames look
like the owner's description: blank regions or columns, scattered pixelated
fragments, the background strings still drawn. Findings so far:

- At normal stress, the native child-window view broke occasionally (1 in a
  first 15 s run, 0 in later 60 s runs) and much more often with Chromium's GPU
  rasterisation off (about 5 a minute), while the widget view showed none.
- At three times the stress (`SAIPH_STRESS_SCALE=3`, 90 s, one run each) every
  setup broke: widget view without GPU rasterisation 24, native with Chromium's
  GPU off (software compositing, so no shared GPU texture) 41, native default
  12, native non-flip presentation 11, native OpenGL 15.
- So the fault is not the native window alone and not a shared-texture race
  (software compositing breaks too); the likeliest source is Chromium drawing
  frames before the page's content tiles are ready. Not yet confirmed with the
  Chromium-side capture under heavy stress, and no fix is in place. Run-to-run
  variance is high: compare setups over several runs.
- Offscreen (`--offscreen`, Chromium's own frames only) the same 3x stress
  produced no broken frames in 301, and a real window parked outside every
  monitor is not drawn at all, so the fault cannot be reproduced without a window
  on screen. `scripts/watch-render-glitches.py` reads a running instance's own
  frames over its loopback DevTools endpoint, passively (no input, no saved
  pictures, only timestamps and strip counts); verified on a test session (three
  blanked headers, three logged, none false over 288 frames). Run beside the
  installed app while the owner works: glitches it logs come from Chromium,
  glitches seen on screen but not logged happen in presentation (Qt/Windows).

### Installed beta.40: Chromium's frames stay intact

The passive watcher beside the installed beta.40 (10 minutes, 4727 frames from
Chromium) logged no broken frames. If blocks or stripes were seen on screen in
that window, they happen while Qt and Windows present Chromium's finished frames.

### Comparing presentation paths: `rendering.json`

`src/orion_mini/rendering.py` reads `rendering.json` from the profile before Qt
starts (installed: `%LOCALAPPDATA%\OrionMiniendering.json`). Without the file
nothing changes. Keys combine; unknown keys or values are ignored:

| Key | Values | Effect |
| --- | --- | --- |
| `present` | `flip` (default), `noflip` | `QT_D3D_NO_FLIP=1`: Direct3D blit swap chain instead of flip model |
| `backend` | `default`, `d3d11`, `opengl` | `QSG_RHI_BACKEND` for the dashboard's Qt Quick window |
| `loop` | `default`, `threaded`, `basic` | `QSG_RENDER_LOOP`; `basic` renders on the GUI thread |
| `host` | `native` (default), `widget` | `widget`: the dashboard in a QWebEngineView widget, as before beta.37 (no native child window; window drags cost more again) |

A/B on the installed app: write one choice, restart Saiph, use it as usual for
10–15 minutes and note any blocks or stripes; then the next. Suggested order:
`{"present": "noflip"}`, `{"loop": "basic"}`, `{"backend": "opengl"}`,
`{"host": "widget"}`. Delete the file to return to the shipped path. Each choice
boots the real shell offscreen with the dashboard, bridge and hide/show working
(smoke-tested); the stress test has matching configs (`switch-noflip`,
`switch-opengl`, `switch-basic-loop`, `switch-widget`) for a run with a window.

## Physical verification checklist (coordinator, installed build)

Not run by this change. On the installed build, visible window, normal GPU rendering:

1. **Idle CPU.** Open Phone (a paired phone online), leave it 1 min, then sample the
   Saiph process tree for 60 s (Task Manager details or `Get-Process Saiph*,QtWebEngineProcess`
   CPU deltas). Expect well under the old ~57 %: the background never redraws and
   the tab wave composites 10 times a second. Repeat minimised and in the tray: near zero.
2. **Tab wave.** The selected Phone/Messages underline still moves continuously (in
   1 px steps); the background strings are still; nothing reacts to the cursor.
3. **Window drag.** Drag the window left/right across the monitor for 10 s, at
   normal and maximised-then-restored size: it should follow the pointer without a
   once-a-second hitch. Resize from an edge: no white or black flashes, strings redrawn
   immediately.
4. **Camera preview.** Phone → Webcam → Preview camera at 1080p/20 fps; the status line
   reads "receiving N fps · showing M fps": expect M ≈ N (old build showed ~12.6 of 19.5).
   Rotate the phone: the preview stays upright. Repeat as a webcam in a meeting app.
5. **Phone screen (Apps).** Live phone screen: smooth, taps land where clicked.
6. **Responsiveness.** Notifications, call banner and camera start/stop still appear
   within about a second (they are announced, not polled).
7. **Second pass (native child-window view, 8 Hz wave).** Same idle sample as 1
   against beta.33's 35.9 %: expect roughly beta.33's wave-paused 15.5 % plus about
   8 % for the wave. While sampling, drag the window continuously for 30 s: CPU
   should stay far below beta.33's and the window should track the pointer.
8. **Popups and native bits after a drag.** Drag the window, release, wait half a
   second, then open a dropdown (Settings → a list such as a time or device
   choice): the list opens directly under it. Right-click a text field: Cut, Copy,
   Paste, Select all, and Paste works. Hover a button with a tooltip (phone screen
   Back/Home) for a second: a native tooltip appears at the pointer. Keyboard input
   works right after the window opens, without clicking first.
9. **Drop files** from Explorer onto the window: the send prompt appears and the
   dashboard never navigates away. Maximise, restore, move between monitors (if
   available): no white or black flash, popups still open under their control.
10. **Packaging.** The installed folder contains `PySide6/qml/QtQuick`,
   `QtWebEngine`, `QtWebChannel` and `QtQml` only (no `QtCharts`, `QtGraphs`,
   `VirtualKeyboard` or `QtQuick/Controls`), and the app opens without a
   "module is not installed" error.
11. **Third pass.** Use the app normally for a few minutes (open Phone, Cloud,
   Settings, run a few actions such as Refresh or Find phone): the background
   strings never move; only the selected-tab underline does. Hide to the tray
   for 60 s and sample the process tree: expect about 1–2 % (beta.37: 19–20 %),
   and the window shows current data immediately when reopened.
12. **Fourth pass.** Visible and idle on Phone with the phone on USB and a Cloud phone
   sharing calls/texts: sample 60 s; expect the Saiph main process well below
   beta.39's 23 % (synthetic: 19–21 % to 10–12 %). Settings → Setup guide still
   lists a tool installed while Saiph runs within about ten seconds.
