# Saiph Link architecture

Saiph Link uses Electron with the existing React dashboard and a Qt-free Python
service. `desktop/src/main.cts` owns native lifecycle and windows; its sandboxed
preload adapts the existing frontend `Client` interface. `electron_service.py`
owns the private control protocol, and `electron_runtime.py` starts the actual
Link services. `desktop_actions.py` preserves the shared operation validators;
`link_service.py` and the device/service modules retain their business logic.
See [desktop/README.md](../desktop/README.md) for launch/build commands and the
[implementation record](DESKTOP_ELECTRON_MIGRATION.md) for compatibility details.

The public edition preserves Orion identifiers, data paths, pairing and native
owner verification. Its native lock excludes both Qt and Electron owners of the
same profile. Control uses inherited child pipes; JPEG/clipboard bytes use bounded
authenticated local binary channels. Browser storage is separate from application
identity and database storage. Production launches expose no DevTools endpoint.

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

Native Link packaging combines Electron and a frozen Python service, preserving
the existing installer/manifest and executable compatibility contracts. Package
audits reject Qt and private Workspace modules and retain Electron, Python,
frontend and native component notices/provenance. Previous Qt code remains for
explicit comparison/rollback and the separately owned private Workspace build.
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
