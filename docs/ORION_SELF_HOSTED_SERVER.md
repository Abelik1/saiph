# Install a Saiph Hub (beta)

The self-hosted Hub connects your computers and Android phone over your own
mesh network. Use a separate Ubuntu 24.04 server with systemd and Python 3.12
(the tested Hub runtime), at least 1 GiB free disk and 512 MiB available
memory. The installer supports amd64 and arm64. These checks do not establish
capacity for arbitrary workloads.

Ubuntu 22.04 and Debian 12/13 are alternative systemd hosts. Use their maintained
system Python (3.10 or newer) and keep distribution security updates enabled;
those host/runtime combinations require their own installation acceptance.
The public desktop build uses Python 3.12 separately from the Hub's system Python.

Build from this public source checkout:

```sh
python scripts/build-orion-server.py --release 0.1.0-beta.1 --source-commit FULL_PUBLIC_COMMIT_ID --output ../saiph-server.tar.gz
python scripts/build-orion-server.py --release 0.1.0-beta.1 --verify --output ../saiph-server.tar.gz
```

Use the exact commit from a clean public checkout containing its scanned
`PUBLIC_EXPORT.json`. For local preparation without a public commit, replace
`--source-commit FULL_PUBLIC_COMMIT_ID` with `--local-snapshot`; the archive records
that limited identity honestly. Outputs stay outside the source checkout. The
explicit `--private-preview` compatibility option is for private development and
must not be used for public releases. See [server release contents](SERVER_RELEASE.md)
for the licence, notices, final hashes and source identity included in the archive.

Transfer the archive to your server and extract it into a new directory:

```sh
tar -xzf saiph-server.tar.gz
sudo python3 orion-server/install.py
```

The installer creates versioned application directories, a dedicated service
account and private state/configuration directories. It detects an existing
official Tailscale profile or installs upstream Tailscale and guides its browser
login. An existing stopped profile resumes with its controller and preferences.
An alternative Headscale origin is an explicit advanced choice. Optional Cloud,
phone backup, camera, microphone and Deskflow are separate features.

The package creates no public HTTP listener, Cloudflare tunnel, DNS record or
firewall rule. Devices still require permission to join your mesh and pair with
your Hub. Keep the mesh and operating system updated.

The installer prints a private invitation file location. Transfer that
`.orion-enrollment` file privately to your desktop, or scan its private pairing
QR on Android. Open the desktop invitation and approve the displayed server.
Invitations contain expiring, one-use pairing secrets; never publish their
contents, commit them or put them in support logs. Create a separate invitation
for each additional device on a paired desktop from **Phone → Add a device**:
choose **Show pairing QR** for an Android phone, or **Save invitation file** to
save an `.orion-enrollment` file. For the server-side QR fallback, run
`sudo orion-server enroll`; it writes `phone.svg` on the server.

Saiph preserves the internal `orion://pair` URI, invitation format and Orion data
paths for existing installations. No account migration is required by branding.

Upgrades back up SQLite, preserve configuration and old release directories,
then check health. Failed activation restores the previous code/configuration;
it does not overwrite newer application data with an older database. Recovery
copies require deliberate administrator recovery and do not protect against
losing the server disk. Set up off-device backups separately.

This is beta software. Container and unit checks do not establish physical boot,
real Tailscale browser enrollment, Android background reliability or multi-day
acceptance. Read the [security model](SECURITY_MODEL.md) and
[testing guide](TESTING.md) before operating it for others.
