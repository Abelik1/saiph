# Native release review evidence

Before external distribution, run the read-only native evidence check on the
final package directory (after signing its project executable and packaging):

```text
python scripts/public-release/check-release-readiness.py build/ci-distribution/package-VERSION-PLATFORM --qt-source-dir retained-source/qt-VERSION --review release-review/review.json
```

Keep review evidence outside the package. The command rejects changed or extra
package files, missing dependency or Python notices, an obsolete Python series,
incomplete or changed matching Qt/PySide source archives, and review evidence
that does not match its recorded hash. The Qt directory must contain all eight
archives recorded by `scripts/packaging/retain-qt-source.py`, matching the bundled
version. URLs and attribution extracts alone are insufficient.

The reviewer must inspect the actual bundle, native file/wheel matches and build
options, transitive notices (including Chromium, FFmpeg, OpenSSL and platform
runtimes), source delivery, and interface-compatible Qt replacement. Record real
replacement test results for the shipping platform and confirm the interpreter's
current security patch level and support status. Python 3.10 is no longer a
supported release build input; public desktop development/CI now uses Python 3.12.
The check's version floor does not replace checking current upstream support.

An inventory's unresolved items stay visible until a reviewer supplies real,
package-bound evidence. A passing review record does not remove those historical
notes or prove its own conclusions. Do not fill in passing results without doing
the work. Use this structure, with actual identity, date, hashes and evidence:

```json
{
  "schema": 1,
  "reviewer": "REVIEWER_IDENTITY",
  "reviewed_at": "ACTUAL_REVIEW_DATE",
  "package_manifest_sha256": "SHA256_OF_FINAL_PACKAGE_MANIFEST",
  "checks": {
    "native_notices": {"result": "pending", "evidence": []},
    "wheel_provenance": {"result": "pending", "evidence": []},
    "qt_replacement": {"result": "pending", "evidence": []},
    "supported_runtime": {"result": "pending", "evidence": []}
  }
}
```

After each review passes, set its `result` to `pass` and add evidence entries of
the form `{"path": "relative-report.txt", "sha256": "ACTUAL_REPORT_SHA256"}`.
Paths are relative to `review.json`; links, junctions and paths outside that
directory are rejected. Rebuilding, signing or modifying the package requires
a new bound review. Preserve review evidence with release records.

This check covers native notice, source and review evidence. Also complete the
separate [Windows signing and checksum checks](RELEASING.md), public source/history
scan, and clean-machine and physical-device acceptance. None of these checks
publishes a release or claims an independent security review.
