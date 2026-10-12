# Protected hosted recipient keys

2026-10-10: `HostedRecipientKeys` implements isolated key storage for the hosted
envelope foundation. It is not wired into active services or onboarding and no
APK is released for this milestone.

## Maintained API choice

The pinned Tink Android 1.23.0
[AndroidKeysetManager source](https://github.com/tink-crypto/tink-java/blob/v1.23.0/src/main/java/com/google/crypto/tink/integration/android/AndroidKeysetManager.java)
explicitly recommends `AndroidKeystore` instead. Its creation path can write
cleartext when Keystore is unavailable, and its loading path retries cleartext
after decryption failures. Checking `isUsingKeystore()` afterward cannot prevent
an earlier plaintext write.

Orion therefore uses maintained
[AndroidKeystore](https://github.com/tink-crypto/tink-java/blob/v1.23.0/src/main/java/com/google/crypto/tink/integration/android/AndroidKeystore.java)
and [TinkProtoKeysetFormat encrypted serialization](https://github.com/tink-crypto/tink-java/blob/v1.23.0/src/main/java/com/google/crypto/tink/TinkProtoKeysetFormat.java)
directly. No custom cryptographic primitive, cleartext keyset serializer, or
cleartext migration fallback is used in production code.

## API and behavior

`HostedRecipientKeys.forDeployment(context, deploymentId, deviceId)` creates a
store object. `create()` is an explicit first-creation operation;
`load(expectedRecipientPublic)` requires the recipient public key from a
verified enrolled-device roster and never generates keys. Both return a `HostedRecipientMaterial` containing the Tink
recipient handle and existing P-256 signing private/public objects, in memory.

The P-256 identity is the existing `Security` alias `orion_device_p256`. This
store never calls `Security.ensureKey()` or creates/replaces signing keys.
Missing, mismatched or unusable signing material fails closed. Initial signing
identity creation remains the responsibility of the existing identity flow.

Recipient keysets are encrypted with an AES-256-GCM key generated and used by
Android Keystore through Tink. Associated data binds the deployment UUID,
device ID, existing signing public key and enrolled recipient public key.
Loading also checks the derived recipient public key against that trusted pin.
Stored handles must contain exactly the selected HPKE private recipient suite;
public-only, substituted or unrelated encrypted keysets fail.

Storage lives under
`Context.noBackupFilesDir/orion-hosted-keys-v1/<deployment>/<device>/`. Native storage
restricts directories/files to their owner, refuses symlink paths, bounds reads
to 16 KiB, uses file/process locking and exclusive creation, and fsyncs file
contents and directory entries. A durable intent marker precedes creation of
the wrapping or recipient key. No API overwrites an existing keyset or silently
retries an interrupted creation. The existing master alias is explicitly
checked before Tink's generation API, which otherwise permits replacement.
Loading may create the private container directory and lock file, but never
creates key material, an intent marker or a recipient keyset.

Missing/corrupt keysets, partial state, missing/unusable Keystore entries and
restored ciphertext without matching keys fail with a generic error. Existing
evidence is retained. Recovery must be explicit and establish a newly approved
device; this foundation supplies no destructive reset or automatic migration.

Android [backup documentation](https://developer.android.com/identity/data/autobackup)
excludes the no-backup directory from cloud backup and normal device transfer.
The app already disables backup in its manifest. Merely copying ciphertext to
another device does not supply the app-bound Keystore wrapping key or existing
signing identity. Rooted devices, same-UID compromise and OEM behavior outside
Android's documented backup contract are outside these guarantees.

## Evidence and remaining tests

JVM unit tests use real Tink AEAD and encrypted-keyset serialization, injecting
storage/provider operations to exercise roundtrip persistence, plaintext and
wrong-suite rejection, corruption, missing/wrong master keys, provider errors,
deployment/device/signing-identity/recipient binding, missing identity,
interrupted creation, tombstones and refusal to overwrite existing state.

These tests do not run Android Keystore or a physical filesystem backend.
Physical Android evidence is pending for provider failures, restart/reboot,
permissions, file locking and fsync, backup/restore/device transfer and actual
Android Keystore P-256 objects. No hardware-backed or StrongBox guarantee is
claimed. A recipient's private key exists in application memory while loaded;
already returned handles cannot be retroactively erased by losing a master
key. There is no forward secrecy, recovery/export key mechanism or service
integration in this change. Full removal of app data and Keystore state cannot
be distinguished locally from a fresh installation and must not restore device
trust automatically.
