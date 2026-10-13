# Desktop UI review and approach

The desktop already uses React inside Qt WebEngine. The reported rough edges are
in the web UI and its native bridge, so this change keeps the existing shell.

- Contain scrolling within a fixed header/footer frame, with a quiet bottom edge
  and slim internal scroll indicators.
- Keep the photo grid lightweight. Open an accessible, window-filling viewer on
  click; download the original on demand, preserve its aspect ratio, and expose
  copy/save in the viewer and a custom context menu. Native clipboard image data
  must come from the original, with orientation applied and no resizing.
- Replace the settings tab strip and dense columns with consistent sidebar
  navigation, readable sections, and clear save feedback in both editions.
- Verify synthetic portrait/landscape originals through the Qt bridge, component
  interactions, production builds, and rendered desktop screenshots.

Qt remains a reasonable choice for the existing Python services and native
clipboard/tray/drop integrations. Tauri is a candidate for a future shell-only
prototype if package size becomes a priority; migration would need explicit
Windows/Linux acceptance for those integrations. A framework change alone would
not fix these UI issues.

## Framework recommendation

Keep Qt for this UI pass. React already provides the visible interface, while
Qt owns the window, QWebChannel, tray, clipboard, file drops and native dialogs.
Those integrations can be maintained independently of the React design.
[Qt WebEngine](https://doc.qt.io/qt-6/qtwebengine-overview.html) embeds Chromium;
continuing to ship it requires regular Qt/security and packaging updates.

If installer size or runtime memory becomes a measured problem, prototype a
small Tauri shell around the existing React frontend and Python service.
[Tauri](https://v2.tauri.app/concept/architecture/) uses Rust and platform
webviews; that brings another native toolchain and a need to test rendering and
clipboard/drag/tray behavior on each operating system. It is a migration
candidate, not a demonstrated performance improvement for this app.
[Electron](https://www.electronjs.org/docs/latest/) embeds Chromium and Node.js;
it would also need a Python process boundary and native integration work.
No shell migration is required to deliver the requested visual improvements.

## Verification

- 84 frontend tests pass with `LANG=en_GB.UTF-8 LC_ALL=en_GB.UTF-8 npm --prefix frontend run test:unit`.
  The existing Calendar test assumes a 24-hour locale; the host's en_US default
  causes that unrelated assertion to fail.
- 29 focused Python tests pass: original-photo bridge, existing bridge, and
  phone transfer/reducer behavior. Clipboard coverage includes landscape,
  portrait, EXIF rotation, original encoded bytes and unreadable files.
- Both Link and Workspace production frontend builds pass.
- The two existing native Qt startup/file-drop regression tests pass on Linux.
- The real offscreen Linux Qt/WebChannel window passes the synthetic photo and
  settings probe, including full-resolution loading/copy, context-menu actions,
  Escape/focus restoration, fixed footer, equal settings-card widths and compact
  checkbox rows. Screenshots use synthetic images and no personal data.
- Physical-phone downloads and Windows clipboard paste into external apps remain
  platform acceptance checks; the offscreen test does not certify them.

To repeat the visual check, build the frontend, run
`PYTHONPATH=src .venv-linux/bin/python tests/desktop_ui_fixture.py /tmp/saiph-ui-test`
in one terminal, then `node tests/packaging/desktop_ui_probe.cjs` in another.
The fixture exits automatically after three minutes. The probe saves screenshots
under `test-artifacts/desktop-ui-review/`. It requires local socket access and a
working Qt WebEngine runtime; the managed sandbox may block Chromium startup.


## Follow-up spacing and phone navigation

Settings now places its page title in the sidebar beside the selected section.
The General heading and subtitle start at the top of the content area, without a
full-width title row above them. Workspace search and activity stay available in
the top-right corner. Phone tabs use accent text and a short rounded underline;
hovering or selecting a tab keeps the ribbon background clear.

## Everyday UX follow-up

Preserve visited pages and settings sections for the current app session, retain SMS drafts per device/conversation, and restore page scroll positions. Add unsaved-change feedback to preference forms, explicit offline/permission states, settings shortcuts, native folder selection and timezone/time controls, and retry actions for message/original-photo failures. Keep deferred photo loading and native image quality intact. Verify navigation, drafts, retries and preference payloads with regression tests, then rebuild both editions and inspect synthetic native screens.

Follow-up verification: 95 frontend tests and 121 focused Python tests pass
(79 workspace/photo/bridge tests plus 42 Link service tests). The Link runtime
asyncio tests need local runtime access outside the managed network sandbox.
Both editions compile. The synthetic Qt probe now also checks restored Phone
scroll/tab selection, computer and Cloud drafts across navigation, direct Cloud
settings navigation, OS-specific camera fields and the timezone/time controls.
Drafts remain in memory for the current session; restarting Saiph clears them.
