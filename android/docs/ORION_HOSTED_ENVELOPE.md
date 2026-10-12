# Hosted encrypted envelope foundation

2026-10-10: this adds an isolated, client-side envelope implementation. It does
not connect the Android application to the hosted service or enable E2EE for
existing features. No APK release is made for this milestone.

The implementation uses `com.google.crypto.tink:tink-android:1.23.0`, checked
against [official Maven metadata](https://repo.maven.apache.org/maven2/com/google/crypto/tink/tink-android/maven-metadata.xml)
and the [Tink setup guide](https://developers.google.com/tink/setup/java).
It selects the standard
`DHKEM_X25519_HKDF_SHA256_HKDF_SHA256_AES_256_GCM` parameters with Tink's output
prefix. The existing P-256 device key signs the complete routing header and
payload using DER ECDSA/SHA-256. That signature is inside the HPKE ciphertext;
the routing header is also bound as context information.

`HostedEnvelope` exposes `generateRecipient`, `exportPublic`, `readPublic`,
`canonical`, `validateHeader`, `seal`, and `openEnvelope`. Recipient private
keys remain in caller-owned Tink `KeysetHandle` instances. The production API
only exports public keysets and never stores keys or content. Secure local key
storage, verified root pins and device rosters, expiration/replay enforcement,
atomic action queues, recovery and actual service integration remain required.
Static recipient HPKE keys do not provide forward secrecy after compromise.

The wire format matches desktop Python `hosted_crypto.py`: exact header keys
are `protocol_version`, `deployment_id`, `roster_version`, `roster_hash`, `id`,
`source`, `target`, `expires_at`. Protocol version is 1. Canonical JSON sorts
keys by Unicode code point and uses ASCII escaping, including surrogate pairs
for astral characters. It rejects floats and integers outside the exact
53-bit range. Plaintext, ciphertext, public keyset, JSON depth and node counts
are bounded; decrypted JSON must exactly match its canonical representation.

Run unit tests with JDK 22 and the local Android SDK:

```powershell
.\gradlew.bat :core:network:testDebugUnitTest -PorionIndependent=true -PorionFirebase=false --console=plain
```

For the optional isolated Python/Kotlin interoperability test, set
`ORION_HPKE_FIXTURE` to an ignored local JSON fixture containing only synthetic
test keys and content. Fields: `python_recipient_private_b64` (binary Tink
keyset), `python_recipient_public_b64`, `signing_private_pkcs8_b64`,
`signing_public_spki_b64`, `header`, `payload`, `python_ciphertext`, and an
absolute `output_path`. Never use production keys in this fixture or commit it.
The test imports secret key material only in unit-test code, decrypts the
Python ciphertext and writes a Kotlin ciphertext encrypted for the Python
recipient. The output contains public keys and synthetic content only. Python
must then decrypt and verify that Kotlin output to complete both directions.

Tink officially supports Android API 24 and newer; most functionality is
expected to work on API 23. This repository has API 23 as its module minimum
and enables core library desugaring. Local JVM tests do not establish physical
device compatibility. The Android Keystore and actual phone service flow still
require integration tests before enabling this transport.
