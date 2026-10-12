# Desktop updates through your own Hub

The existing update protocol uses a paired device's configured mesh Hub and
P-256 authentication. Checking or staging a package does not execute it;
installation is a separate user action. A publicly hosted update channel is not
configured by these source files.

Build and wrap a package with a new version and increasing positive build number,
then publish it using your managed server's administrator command:

```sh
sudo orion-server publish-desktop /path/to/Saiph-Link-0.1.0-beta.1-windows-x86_64.exe \
  --platform windows-x86_64 --profile link \
  --version 0.1.0-beta.1 --build-number 1
```

For a Linux archive use `--platform linux-x86_64`. Package metadata, target
platform, profile and immutable build identity must match. Complete artifacts
retain immutable digest locations; the latest pointer updates atomically.
Use only packages whose source and publisher you have verified.

The client checks size, digest, profile, platform, build ordering and embedded
metadata. A changed digest for an already seen build or a lower offered build is
refused. Staging stays in the private data directory. Redirects and proxy routing
are refused for the release transport. These checks do not establish a trusted
Windows publisher for an unsigned installer.

Installation uses the normal native installation location, a detached helper and
the existing installer. The helper waits for the app to exit; on a failed update
it attempts to reopen the prior executable when available. Portable copies can
check and stage but need a standard native installation for automatic install.

Normal installed Windows and Linux update handoffs, startup preferences,
pairing and recovery need explicit platform acceptance. Component and synthetic
tests are not proof that every installed-device update path has passed.
