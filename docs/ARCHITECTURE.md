# Saiph Link architecture

The public desktop edition uses the existing Orion compatibility identifiers.
`frontend/src/App.tsx` renders Link navigation and pages, communicating through
the finite Qt WebChannel API in `desktop_bridge.py`. `app.py` owns the native
window, tray and process lifecycle. `link_service.py` dispatches Link operations;
personal Workspace services and pages are excluded from this public edition.

`phone.py`, clipboard, continuity, camera, microphone and peer components handle
their respective device features. Cloud clients and Deskflow integration reuse
the configured upstream services and executables. They do not replace a VPN,
identity system or third-party service implementation.

The self-hosted Hub package is `hub/orion_hub/`. Devices use existing P-256 signing
identities, pairing and revocation controls. The ordinary Hub processes readable
feature content inside the configured private network. Configure its bind and
network access using the [server guide](ORION_SELF_HOSTED_SERVER.md).

The isolated hosted application and `hosted_*` clients are development components
for account authorization, approved rosters and recipient-encrypted delivery.
They must not be treated as an accepted replacement for active app transport.
See [SECURITY_MODEL.md](SECURITY_MODEL.md) for the actual boundary and outstanding
integration work.

Native packaging uses a PyInstaller one-folder bundle. Frontend files and
distribution profile/version metadata travel with the bundle. Shared Qt libraries
remain replaceable. The installer keeps application releases separate from user
data, preserving internal data locations and identifiers across the public rename.
See [desktop distribution](ORION_DESKTOP_DISTRIBUTION.md).

The MIT SDK retains the local reporting contract. Personal plugin management and
Workspace functionality are outside Link's public user interface; see
[PLUGINS.md](PLUGINS.md) for that limitation.

## Workspace add-on

Saiph is Link only. A separately installed private add-on, the `orion_workspace`
Python package, may extend it with personal tools. `orion_mini/modules.py`
imports `orion_workspace.edition` when it is installed; the add-on supplies a
`MainWindow` subclass through `window_class()` and the background worker through
`worker_main()`. A frozen bundle loads the add-on only when its
`distribution-profile.json` selects the `workspace` profile. In the dashboard,
`frontend/src/workspace/edition.ts` exports `Workspace = null`; the add-on's own
build replaces that file with its views. Public source, tests and Link bundles
never contain the add-on. `tests/test_edition.py` covers the hook, and the Link
packaging audit rejects bundles that include `orion_workspace`.
