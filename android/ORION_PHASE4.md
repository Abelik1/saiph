# Phase 4 approach — 2026-10-08

Remove the Shizuku API/provider, launcher, permission model and setup UI. Keep the
bundled shell clipboard worker; correct its host package/bridge authority for Orion,
restrict provider and callback callers to shell/root, and have the desktop retry
launch through an already authorized ADB connection. Match the provider's paired
Orion device ID before launch; never execute a command supplied by a bus event.

Reuse the existing clipboard feature. Send bounded text over Link; images use a
direct mesh blob endpoint with a 25 MB clipboard limit and larger content becomes
a file send. Authenticate direct GETs with the existing P-256 request signature,
validated against the hub's paired device and replay store, with the destination
device ID included in the signed path. No separate keys, identities or crypto.

Use event ID, authenticated origin, SHA-256 content hash and a recent-content cache
to prevent a received clipboard write from being re-broadcast. The native Qt
clipboard runs on the GUI thread; the mesh loop runs independently in the tray.
Clipboard content is never written to diagnostic logs or displayed in Advanced.

Verify loop prevention in all six directions with synthetic clients, payload
bounds/hash checks, direct-transfer authorization and caller UID isolation on an
emulator. Physical Samsung background clipboard, authorized debugging availability
after reboot, laptop clipboard and Deskflow acceptance remain deferred.

Verified on 2026-10-08: full desktop checks passed (163 Python, 32 React, one
service integration, two native bridge checks, 13 native browser workflows).
Hub suite passed 106 tests. Android build, unit tests and lint passed; emulator
caller-isolation and command-receipt instrumentation passed two tests. Three
isolated, temporary paired clients on the live Pi passed six-way clipboard
fan-out, signed direct transfers, unsigned rejection and a 100-copy burst; all
probe identities were revoked afterwards. Valid image conversion and clipboard
echo suppression were separately exercised through the real Qt clipboard.

Shizuku has been removed from the maintained Android source. The next APK release
will follow the remaining shared integration and include a matching GPL source
archive; the currently published 0.5.0 APK predates this removal. Android's shell
worker still requires authorized USB/wireless debugging. Unattended worker recovery
on the physical Samsung after reboot has not been demonstrated.
