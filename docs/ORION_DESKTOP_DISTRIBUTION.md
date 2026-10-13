# Saiph desktop distribution

The public edition is Link. Build natively on the target operating system with
Python 3.12, Node 24 and the dependencies in
[CONTRIBUTING.md](../CONTRIBUTING.md):

```text
python scripts/build-native.py --profile link --version 0.1.0-beta.1 --build-number 1
python scripts/packaging/build-desktop-distribution.py --platform windows-x86_64 --version 0.1.0-beta.1
```

Use `--platform linux-x86_64` for a native Linux build. The wrapper requires the
existing PyInstaller bundle under `dist/OrionMini/`. Windows also needs the .NET
Framework compiler; Linux needs the desktop runtime libraries listed in CI.

Release filenames and installer display names use Saiph. Internal executable,
application identity, install locations and `.orion-enrollment` associations
retain Orion compatibility names. Windows installs per user beneath
`%LOCALAPPDATA%/Programs/OrionMini`; Linux uses `~/.local/lib/orion` and its owned
launcher/menu integration. No target Python or Node development installation
should be required for the packaged app.

Native packages carry bounded manifests with paths, sizes and SHA-256 digests.
Packaging audits reject private runtime state and excluded Workspace modules.
A Workspace bundle needs a checkout of the separate add-on:
`--profile workspace --workspace-source <checkout>` takes its `orion_workspace`
package, skills and dashboard views from there, and the audit rejects a Workspace
bundle that lacks them. Link builds exclude the add-on even when it is installed.
Upgrades retain prior releases, application data, pairing keys and an existing
startup opt-out. Uninstall follows owned manifests and preserves personal data;
modified or unowned files must not be treated as disposable package content.

Linux archives include `orion/install.sh`; extract and run it on the target as
your normal desktop user. Standard shell, tar, sha256sum and `flock` are required.
Close Saiph before switching versions. Clean-platform installation and upgrade
checks remain distinct from the isolated native fixtures.

Add `--linux-setup` to also write `Saiph-Link-VERSION-linux-x86_64.run`, the
no-terminal setup described below. The `.tar.gz` is always produced as well.

Current CI outputs are unsigned development builds. Source and binary release
readiness also requires licence notices, matching upstream source obligations,
library replacement verification, publisher signing and actual clean-machine
acceptance. See [RELEASING.md](RELEASING.md) and
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## No-terminal Linux setup (design note)

Beta testers need to install without typing commands, while keeping the per-user,
manifest-owned and upgrade-safe `install.sh` behaviour. Options considered:

- **AppImage.** One file, but it runs from a FUSE mount that many current
  distributions do not provide by default, bypasses `install.sh` (no owned
  manifests, release retention or MIME/autostart integration) and makes Qt
  replacement an extract-modify-repack exercise. Its runtime also embeds
  third-party code (squashfuse, libfuse) with notices and source obligations of
  its own.
- **.deb.** Needs root and installs system-wide under `dpkg` ownership. That
  conflicts with per-user installs, owned per-user integration and `install.sh`
  upgrade and uninstall semantics, and covers only Debian-family systems.
- **Per-user setup wrapper (chosen).** `Saiph-Link-VERSION-linux-x86_64.run` is
  `scripts/packaging/linux-setup.sh` followed by the byte-identical release
  `.tar.gz`. It checks the archive's embedded size and SHA-256, unpacks it into a
  private folder under `~/.cache` and runs the archive's own `orion/install.sh`
  as the current user. Install location, manifests, packaging audits, notices,
  data/pairing/start-up opt-out retention and uninstall are therefore unchanged.
  It adds no third-party code. The installed tree is the same as the archive's,
  so Qt libraries stay replaceable, and `--extract DIR` recovers the identical
  `.tar.gz` for inspection or library replacement.

Testers download the `.run`, allow it to run as a program (file Properties →
Permissions, or "Run as a Program" from the right-click menu, depending on the
desktop) and open it. When started from a file manager it asks for confirmation,
then shows an options checklist (start at sign-in and the file-manager Send to phone
actions, defaulting to what is installed now) and passes the choices to
`install.sh` as `SAIPH_AUTOSTART` and `SAIPH_FILE_ACTIONS` (`on`/`off`). Unset,
as in a terminal run or an in-app update, keeps what is installed: a first install
adds both, and an upgrade never restores a start-up opt-out or a removed action. It then
shows progress and reports the result with `zenity` or `kdialog`, then offers to
open Saiph. Without either tool it reopens itself in a terminal window. The
latest dialog-mode output is kept in `~/.cache/saiph-setup.log`. Started from a
terminal, it prints plain text (`--text` forces this). Uninstall still uses
`~/.local/lib/orion/current/install.sh --uninstall`.

Distribute the `.run` beside the `.tar.gz`, `SHA256SUMS` and the corresponding
source (AGPL source offer). The embedded hash detects damaged downloads only. It
does not authenticate the publisher. In-app updates continue to use the
`.tar.gz`. File-manager behaviour (making the file executable, launching it and
the dialogs) still needs checking on real GNOME, KDE and Xfce desktops. Unit and
CI checks run the wrapper with synthetic dialog tools and an isolated install
root.
