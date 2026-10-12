# Android public snapshot

This snapshot is prepared from the private maintained Sefirah-derived Android
fork. It contains no private Git history, owner deployment records, Firebase
configuration or signing keys. The original upstream README and GPL licence,
copyright notices, feature modules and native dependency attribution are retained.
The Sefirah Android upstream baseline is commit
`300229e30d32636c087857adc8e8c5793df78ef5`; `UPSTREAM_README.md` preserves that
baseline's original README. The retained Gradle wrapper JAR also matches that
baseline byte for byte (SHA-256
`e996d452d2645e70c01c11143ca2d3742734a28da2bf61f25c82bdc288c9e637`).
`PUBLIC_EXPORT.json` records the exact file hashes and completed source scans.
The Android app is conservatively identified as GPL-3.0-only: the retained upstream
GPL version 3 text is not evidence of an additional later-version grant. Separately
licensed upstream components retain their own explicit terms and notices.

Public Gradle defaults select independent operation and disable Firebase.
Legacy Hub/controller defaults are empty in every public variant, including if
an independent flag is explicitly disabled. A fresh installation requires its
own short-lived invitation. Saved numeric Hub origins, existing Android package
and device-key identifiers, signatures and `orion://` protocol stay unchanged.
The historical private hostname shortcut is absent; invalid/hostname-only saved
origins fail closed instead of silently selecting a different server.

Tests and documentation use explicit synthetic mesh examples. Private milestone
and physical-device receipts are omitted. Source-only checks and scanner results
are not Android build, signing, physical upgrade or fresh-install acceptance.
This snapshot has not been committed to or published in a public repository.

A future public repository should start with this reviewed snapshot. Preserve
the Sefirah attribution and upstream baseline in the README; keeping the private
fork private avoids publishing its development history. Whether to transfer or
publish any existing fork is a separate reviewed owner decision.
