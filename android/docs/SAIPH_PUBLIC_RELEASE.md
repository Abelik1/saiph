# Saiph Android release checklist

This source snapshot has passed its private-owner boundary and secret scans.
It omits private development history and defaults. It is not an official APK or
proof of physical-device acceptance. Public repository publication, publisher
signing and device testing remain release actions.

Build official public APKs with `-PorionIndependent=true -PorionFirebase=false`
and an explicit monotonically increasing `orionVersionCode`. Public source has
no owner Hub default in any variant. Confirm the final DEX/resources/manifest
contain no deployment credentials or Firebase configuration. Run JVM tests,
lint and the APK build from the exact reviewed public source, including pinned
native restic inputs. Retain upstream licences and copyright notices.

Use the existing Android signing identity for a data-preserving upgrade.
Keep its private key offline, restrict access and verify an offline backup.
Record the public source commit, native input hashes, APK SHA-256, application ID,
version name/code and signing certificate fingerprint. Supply the complete
matching GPL source archive and third-party notices with the APK.

On an explicitly chosen device, verify upgrade preserves application data,
device key, pairing, permissions and background behavior. Verify fresh invitation,
private mesh sign-in, explicit server approval, notification/clipboard transfer,
permission revocation, reboot recovery and update verification without Firebase.
Keep real-device evidence separate from JVM/lint/source scans. Never uninstall
the existing paired app merely to make a differently signed APK install.

Before publication, enable private vulnerability reporting and required DCO/CI
checks in the public repository. Preserve Sefirah attribution and upstream baseline.
Historical upstream store metadata and policy documents are not Saiph's current
publisher metadata or policy; review those before any store or service launch.
