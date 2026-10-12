# Server source release contents and identity

The Saiph self-hosted server archive contains Hub Python source, its requirements,
the guided installer, the project AGPL licence and third-party notice summary.
It contains no Python interpreter, dependency wheels, Qt libraries or bundled
Tailscale/Seafile/Deskflow binaries. Dependency installers obtain their own
upstream packages when the administrator chooses to install the server; review
their current notices and supported versions separately.

`package.json` lists every source file's SHA-256. `SHA256SUMS` additionally hashes
the manifest and source metadata. `SOURCE.json` distinguishes an exact clean
reviewed public Git commit from a preparation snapshot identified by the scanned
export receipt hash. Local snapshots do not invent a public commit and are not
official releases. Checksums establish matching bytes, not publisher authenticity.

Build outputs must stay outside the clean source checkout. The builder rejects
changed or unrecorded source files, linked source paths, dirty Git state and a
source commit different from the checkout HEAD. The installer checks archive
contents before changing server state. The separate archive-verification command
does not install or run the server.

Keep the complete corresponding public source archive beside the server artifact.
The server archive is a focused component package, not a replacement for that
complete source handoff. Windows/Android signatures and native library review
remain separate release gates; a passing server source check does not close them.
