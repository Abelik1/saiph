# Saiph Android

Saiph connects an Android phone to Saiph Link on Windows or Linux through a Hub
you control. This Android app is a fork of
[Sefirah Android](https://github.com/shrimqy/Sefirah-Android), whose feature modules,
copyright notices and [GPL licence](LICENSE) are retained. The original upstream
README is preserved in [UPSTREAM_README.md](UPSTREAM_README.md); its store badges,
support links and feature claims describe Sefirah, rather than a Saiph release.

**Status: beta preparation.** There is no public Saiph Android download yet.
Device approval, permission handling, background recovery and upgrades still need
physical-device acceptance. Hosted is planned; neither an independent security
review nor complete encryption integration across shipping features is claimed.

## Setup

1. Run your own Saiph Hub and join the same private Tailscale or Headscale network.
   The Hub must not be exposed directly to the internet.
2. Install an APK from a release whose publisher and signing identity you trust.
   Review permissions and grant only those needed for the features you use.
3. Open the Hub's short-lived invitation in Saiph and explicitly approve the server.
   Follow the official Tailscale app's sign-in and Android VPN-consent prompts.
4. Verify a synthetic notification and clipboard item before sharing personal data.

The current application ID is `com.orionmini.mobile`. Internal package names,
`orion://` invitations, device-key aliases and saved preferences remain unchanged.
An update must use the existing signing certificate to preserve installed identity
and pairing. Uninstalling the existing app removes its private data and device key.

The [independent enrollment guide](docs/ORION_UNIFIED_ANDROID_SETUP.md) explains
the invitation flow and permission limits. The public snapshot has no owner-specific Hub defaults or private milestone records.

## Build a development APK

The maintained build has been checked with JDK 22, Android SDK platform 37.0,
build-tools 36.0.0 and NDK 28.2.13676358. Set `JAVA_HOME` and `ANDROID_HOME` to
your own installations. Native restic outputs are generated rather than stored
in Git; see [its source and build instructions](restic-android/UPSTREAM.md).

On Windows, from the `android/` directory:

```powershell
python scripts/build-restic.py --android-root . --sdk $env:ANDROID_HOME
./gradlew.bat :app:assembleDebug :app:testDebugUnitTest :core:network:testDebugUnitTest :restic-android:testDebugUnitTest :app:lintDebug -PorionFirebase=false -PorionIndependent=true -PorionVersionCode=1 --no-configuration-cache
```

The fixed version code makes this example repeatable. It is for a fresh development
profile; an upgrade needs a version code greater than the installed build's code
and the same signing identity. Debug APKs are not official release artifacts.
Independent builds have no default owner Hub; an invitation supplies the address.
Firebase is explicitly disabled, and no `google-services.json` or signing key is
needed or supplied by this repository.

## Contributions and releases

UI work follows the [mobile design system](../docs/MOBILE_DESIGN_SYSTEM.md),
including shared typography, matching setup choices and accessible action layouts.

Contributions require a [DCO sign-off](CONTRIBUTING.md). Report security issues
privately using [SECURITY.md](SECURITY.md). See the
[release preparation checklist](docs/SAIPH_PUBLIC_RELEASE.md) for source, signing,
history review and physical-device gates.

Saiph changes retain the upstream licence; see [LICENSE](LICENSE). The bundled
ResticDroid wrapper and restic runtime retain their separate source attribution
and notices in [restic-android/UPSTREAM.md](restic-android/UPSTREAM.md). Source
releases must include the exact corresponding source and native build inputs.
No proprietary relicensing right is obtained through DCO.

Community participation follows [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
Modified distributions use their own names under the [branding policy](TRADEMARKS.md).

This is the Android component of the combined Saiph repository. Use the root issue tracker and [root contribution policy](../CONTRIBUTING.md); this directory retains its GPL-3.0-only licence.
