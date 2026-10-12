# Combined development candidate - 2026-10-11

This work combines reliability revision `7e64942fe808e9e14ed8501bdc3ebfd8a3a22359`,
landing revision `cf3a4b810b30be44d93f3d6f7086f6566a8bb7cb`, and account revision
`2f74a2360c9d9c561edf694cb98dec3acdc1e1aa` in one product tree. Existing source
worktrees remain on their branches; no owner-installed app is replaced.

## Scope and boundaries

The reliability branch supplies the Windows private-key ownership fix, idle Hub
wakeups, stale-session replacement, clipboard repeat delivery, photo-save
idempotence and Android 0.8.6. The static website retains disabled downloads,
waitlist and checkout. The account app remains owner-only, with Auth0 controls
and synthetic session tests; it implements no Stripe checkout or webhooks.
Account workflow actions now use the same immutable revisions as product CI.

Internal `orion_mini` restart/automation helpers stay in the internal repository.
They call private Workspace actions, were used to drive acceptance tests, and
are not required to fix clipboard/photo delivery. Importing them would introduce
new product controls and needs a separate capability/security review. Likewise,
the saved legacy Hub event-pump experiment is a separate implementation; the
canonical reliability branch already contains its reviewed Hub fix.

Later on 2026-10-11 the owner chose to bring the opt-in automation and restart
endpoints and the attended acceptance scripts into this tree; see
[attended automation](TESTING.md#attended-automation).

The owner's physical checks used the Android tester APK, a staged Pi Hub file
and an internal source desktop. They do not establish acceptance of a packaged
build from this combined tree. Freeze source and artifacts before retesting.

## Validation

Source and complete candidate-history secret scans passed before dependency
installation. Fresh Python 3.12.14 and Node 24 tooling is isolated in this
worktree. The full Windows desktop suite passed: 715 passed, 43 skipped. Frontend checks: 55 passed across 13 files. Account checks: 7 policy/cookie tests
and 11 production HTTP cases passed, with a successful production build and zero
production dependency audit findings. These account cases use synthetic SDK
sessions, not provider-issued tokens. The corrected full Windows Hub suite passed: 428 passed, 6 skipped. Windows and
Linux native packaging CI passed at f757d7a, before the later database health,
roster renewal and CI commits arrived. Those changes are included in this
candidate and require a new source-specific build/check receipt; no public signed build or independent security
review is claimed. Native CI retains exact source, package/dependency manifests,
build metadata and verified checksums with its unsigned artifacts.

## Integration failure and correction

The first full local Windows Hub run terminated with a native SQLite access
violation during `test_socket_capacity_error_is_fixed_retryable_and_keeps_connection`.
Its worker was executing the watcher's `PRAGMA data_version` while watcher
cancellation closed the same connection. Cancelling `asyncio.to_thread` does not
stop its worker; the former cleanup could therefore close SQLite during a query.

`DataVersionReader` now serializes lazy connection creation, reads, cursor cleanup
and close under a lock. A read queued after shutdown does not recreate the
connection. Watcher cleanup is shielded and runs off the event-loop thread. The
regression tests hold a worker inside a query while shutdown starts and check
that the connection stays open until the query ends, and exercise task
cancellation with an outstanding worker. This is an additional Hub runtime fix
beyond the handed-off reliability source; no protocol or hosted API changes.
It has not been deployed to the owner's Pi or the hosted droplet.

The final integration review found that the startup integrity warning still
opened the known-corrupt store afterward, allowing its normal SQLite setup and
services to write to the profile. Startup now stops before constructing the
window when a check fails, and reports preservation/check I/O errors without
opening the profile or exposing exception details. Quarantine copies use unique
folders so retries within the same second cannot overwrite earlier evidence.
Synthetic startup tests substitute every GUI entry point; no installed app,
owner profile or physical device was opened.

## Next gates

1. Pass combined desktop, frontend, Hub, website and account checks and Android CI.
2. Build native Windows and Linux packages from one reviewed commit; retain
   checksums, exact source, package manifests and test results privately.
3. Use those artifacts for laptop, recovery, clean-install and stranger tests;
   retain pairing/signing identities and coordinate physical-device operations.
4. Finish sandbox billing only after protected runtime key and dedicated database
   are provisioned. The owner reports the restricted sandbox key is now set;
   the dedicated Neon Free database is provisioned in London with Neon Auth
   disabled, connected only to account Production. Schema migration and billing
   implementation remain pending. Preserve disabled billing and account
   protection meanwhile.
5. Configure monitoring and scheduled backups with actual restore evidence;
   finish release signing/notices and hosted integration/security gates separately.

The deployed hosted API keeps its existing clean product pin until a separately
reviewed operations update. Consolidating source does not deploy a service,
publish a repository, enable payments or change existing account admission.
