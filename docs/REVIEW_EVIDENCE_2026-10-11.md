# Review evidence — 2026-10-11

Branch `fix/product-reliability-2026-10-11` on top of `8cc0606`. Candidate
revision for the hosting chat: the merge of this branch (code last changed at
`1f7e586`; later commits are documentation only).

## Changes and contracts

| Change | Component | Contract effect |
| --- | --- | --- |
| Private hosted key material gets the user as owner under elevated tokens | desktop `hosted_keys.py` | none; existing-object verification unchanged |
| Idle Link pumps wait for change (in-process wake plus shared `PRAGMA data_version` watcher) | Hub `link.py` | none on the wire; delivery and retry cadence unchanged while work is outstanding |
| A newer signed connection for a device replaces its stale session | Hub `link.py` | **changed**: a second connection for the same device no longer gets close code 1013 "Device already connected; retry" (except if the old session fails to stop within 10 s); the old socket is closed instead |
| Repeated clipboard content is delivered; only the immediate echo (10 s) is suppressed | desktop `clipboard.py`, `phone.py`; Android `ClipboardCache.kt` | behaviour change only; no message format change |
| One photo request and one saved copy per Save | desktop `phone_features.py` | none |
| Android 0.8.6 (3564000) | `android/app` | version only; application ID, signer and pairing unchanged |
| Sealed blob expiry test race | Hub tests | test only |
| Startup integrity check of desktop databases; failures quarantined with sidecars, never repaired | desktop `db_health.py`, `app.py` | none; new local files `db-health.jsonl` and `db-quarantine/` in the data folder |
| `RootApproval.expires_at` / `renewal_due()` | desktop `hosted_approval.py` | additive library API; no wire change |
| CI actions moved to current Node 24 releases (SHA-pinned); Gradle dependency submission job | `.github/workflows` | dependency graph covers Android after merge to `main` |

The hosted server API is unchanged. See [the hosted review](HOSTED_REVIEW_2026-10-11.md).

## Checks

| Check | Result |
| --- | --- |
| Private CI on `e4e9f8b` (run 38105640696) | Linux and Windows desktop suites, Hub, dependency audits, source/history secret scans: all passed |
| Windows CI before the fix (run 38096273678 on `8cc0606`) | 31 failures; reproduced locally under an elevated token (31 failed → 67 passed after the fix) |
| Android CI (runs 38096273645 on `8cc0606`, 38098609210 on the branch) | APK, app/network/restic JVM tests and lint passed |
| Local owner build of Android 0.8.6 | 127 JVM tests, 0 failures; lint passed; APK SHA-256 `669953d933c5deed674e9fa5cdc5680be30d81c2b968eefeaf41bb10c78ea4e6`, existing signer |
| Local Hub suite | 426 passed, 6 skipped |
| Local desktop suite (Python 3.12) | 709 passed; 1 local-only shortcut test failure that also fails at `8cc0606` in a long-path venv and passes in CI |
| Hub idle CPU, synthetic (4 idle devices) | 16.0% → 0.5% of a core |
| `pip-audit` (desktop, hosted and Hub dependencies) | no product findings; only the scratch venv's own `pip` 25.0.1 |
| `npm audit` (frontend) | 0 vulnerabilities; the website is static and has no npm dependencies |
| Gradle dependencies | submitted to GitHub's dependency graph by the new CI job (run 38106603330); alerts apply once it runs on `main` |
| CI after action updates (runs 38106601306, 38106601313, 38106603330) | all desktop, Hub, audit, secret-scan, Android build and dependency-graph jobs passed; no Node 20 deprecation warnings |
| DCO | every branch commit carries a `Signed-off-by` matching its author |
| Licences and notices | no files deleted; no dependencies added; `LICENSE`, `THIRD_PARTY_NOTICES.md`, Android GPL licence and upstream credits unchanged |

## Physical acceptance

Owner phone and Windows checks are recorded privately, and summarised in
[the release status](RELEASE_STATUS.md). They are not an independent review
and do not cover the laptop or prolonged stability.

## Not established

Independent security review; hosted features as user-reachable flows; a
physical exercise of the stale-session replacement; signed public Windows
packages.
