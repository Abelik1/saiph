# Keyboard and mouse sharing

Saiph uses upstream Deskflow's TLS certificates and fingerprint verification, and
expose its existing supervisor preferences only in Settings → Advanced. Saiph owns
clipboard sharing, so Deskflow clipboard sharing stays disabled. Saving preferences
does not establish that the physical laptop has connected.

Sharing is optional and off by default in new Link installations. Install upstream Deskflow separately; Saiph does not bundle its executable. Existing Workspace sharing preferences are retained.

## One-time setup

1. Join both computers to the mesh. For the examples below, the desktop is `100.64.0.2`; replace it with your actual assigned mesh address and use the laptop's
   assigned mesh address after joining it. In Saiph's Advanced settings, temporarily
   switch keyboard/mouse sharing off and save on both computers. This avoids two
   processes competing while you establish trust.
2. Open the upstream GUI. An existing pinned Windows portable installation may be under
   `%LOCALAPPDATA%\OrionMini\tools\deskflow\1.27.0`; open `deskflow.exe` within
   that extracted directory. On Linux, install the upstream-supported distribution
   package and open `deskflow`. Do not supply `--settings` to the GUI: that option
   belongs to `deskflow-core` in this release.
3. Deskflow creates its own TLS certificate when the GUI first opens. Keep TLS
   enabled and peer fingerprint checks enabled. In its settings, note the existing
   certificate filename; enter that path in Saiph without reading, copying or
   displaying the certificate's private key.
4. Configure the desktop as the server named `desktop` and the laptop as the
   client named `laptop`. Bind the server interface to `100.64.0.2`, with port
   `24800`; point the laptop at that same mesh address. Arrange the laptop to the
   right of the desktop. Disable Deskflow clipboard sharing on the server.
5. Start the GUI's server and client once. Open each computer's fingerprint display
   and compare its SHA-256 fingerprint against the prompt on the other computer.
   Accept only a match on each computer. Stop sharing and **quit** both GUIs;
   closing a window can leave the GUI running in the tray.
6. Transfer the **approved fingerprint database files only** if needed, as below.
   Never transfer a certificate private key, fabricate a fingerprint database, or
   disable peer verification to get connected.
7. In Saiph Advanced, select the correct role and desktop/local mesh addresses,
   enter the existing certificate path, enable sharing and save. Leave the core
   executable blank for automatic discovery, or give the existing
   `deskflow-core.exe` / `deskflow-core` path. After saving, Saiph supervises the
   core and retries automatically. Move the pointer across the right edge of the
   desktop and verify input on the real laptop.

## Trust-file locations

The approved files are named `trusted-servers` and `trusted-clients`; each
computer may only have the file relevant to its role. Copy the files that exist
on that same computer. Keep their permissions private. Repeat fingerprint
comparison and update the approved files if Deskflow regenerates a certificate.

| Platform | GUI trust directory | Saiph core trust directory |
| --- | --- | --- |
| Windows, ordinary upstream settings | `C:\ProgramData\Deskflow\tls` | Same directory; no copy |
| Windows, GUI/core installation has `settings\Deskflow.conf` | The installation's `settings\tls` | `<Saiph data>\deskflow\tls`; copy approved files once |
| Linux | Beside the GUI settings file: usually `~/.config/Deskflow/tls`, or `$XDG_CONFIG_HOME/Deskflow/tls` | `<Saiph data>/deskflow/tls`; copy approved files once |

If Linux uses `/etc/Deskflow/Deskflow.conf` instead of user settings, its GUI
trust directory is `/etc/Deskflow/tls`. Follow the actual settings location.
Saiph's data directory defaults to `%LOCALAPPDATA%\OrionMini` on Windows
and `~/.local/share/OrionMini` on Linux (`$XDG_DATA_HOME/OrionMini` when set).
`ORION_MINI_DATA_DIR` overrides it. The supervisor writes
`<Saiph data>/deskflow/settings.ini`; Linux and Windows portable mode derive the
core trust folder from this file's directory. Keep the existing certificate path
pointing to the GUI-generated certificate.

## Setup checks and recovery

Advanced settings show read-only setup checks: whether `deskflow-core` was
found, which `*.pem` certificates exist in Deskflow's default trust folder (file
names only; Saiph never opens them), whether the approved trust file for this
role exists, this computer's mesh address, and whether the core is running.
**Use detected settings** fills a single detected certificate and mesh address
into the form; nothing is saved until you choose Save. When the certificate path
is left blank and exactly one certificate is found, the supervisor uses it, and a
desktop with exactly one mesh address binds to it. With several candidates you
must choose.

If the core exits, Saiph restarts it after 15 seconds and doubles the wait after
each further crash, up to five minutes. A run of ten minutes resets the count.
After three quick crashes the status asks you to check trust setup. **Restart
sharing** clears the backoff and starts again on the next poll.

The Advanced status reports fixed supervisor errors. An empty error only means
that no supervisor error is currently recorded: connection and TLS/input acceptance
still need the real laptop. Restart and laptop sleep/resume checks remain pending.

## Official sources

- [Deskflow 1.27.0 release and original portable builds](https://github.com/deskflow/deskflow/releases/tag/v1.27.0).
- [Upstream GUI settings and configuration paths](https://github.com/deskflow/deskflow/wiki/GUI-Settings).
- [Upstream core command line](https://github.com/deskflow/deskflow/wiki/Command-Line).
- [Certificate generation implementation](https://github.com/deskflow/deskflow/blob/v1.27.0/src/lib/gui/TlsUtility.cpp).
- [GUI fingerprint approval and certificate creation](https://github.com/deskflow/deskflow/blob/v1.27.0/src/lib/gui/MainWindow.cpp).
- [Core settings and trust directory implementation](https://github.com/deskflow/deskflow/blob/v1.27.0/src/lib/common/Settings.cpp).
- [GUI supported command-line options](https://github.com/deskflow/deskflow/blob/v1.27.0/src/apps/deskflow-gui/deskflow-gui.cpp).
