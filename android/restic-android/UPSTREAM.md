# Bundled Android restic runtime

Approach (2026-10-08): reuse ResticDroid's standalone AAR, compiling unmodified
restic for Android with CGO and the installed NDK. The extracted native executable
runs as Orion's ordinary app UID. No helper app, shell access, Shizuku, custom
cryptography or new identity system is involved.

- Wrapper: [JayXT/ResticDroid](https://github.com/JayXT/ResticDroid), commit
  `58e561e61859a242b1774004bd06a8c39fae7534`, GPL-3.0-or-later.
- Executable: [restic/restic](https://github.com/restic/restic), commit
  `6aa3a516ce654808a1f28f9fa21e9b7c8e6e90bf`, version 0.19.1, BSD 2-Clause.
- Go 1.26.7 Windows archive SHA256:
  `f4f534a486e4bc3387fa18f08208f2f854b7aaea8a08f2a2d829a914a05abb11`.
- Pinned restic source archive SHA256:
  `6318c51f187bafbaf33d1ab6dcb5abde9a94de11476651cbb2982f1ba89ca8a8`.

Upstream Kotlin and tests are unchanged. Orion adapts this module's Gradle file
to the existing build conventions and generates `restic_version.txt`; the
upstream manifest requires extracted native libraries. `LICENSE`, `NOTICE` and
the packaged `restic_license.txt` preserve attribution. Source releases must
include this module, Orion integration and the reproducible build script.

From this Android checkout:

```powershell
python scripts/build-restic.py --android-root . --sdk <installed-Android-SDK>
```

The Windows build uses NDK 28.2.13676358 by default and verifies Bionic linkage,
PIE/DYN type and 16 KB load alignment for arm64-v8a and x86_64. CGO is required:
Android DNS uses Bionic/netd, rather than Go's file-based Linux resolver. Native
outputs and downloaded toolchains are ignored. `preBuild` fails clearly when
either ABI executable is missing. There is no silent optional backup binary.
