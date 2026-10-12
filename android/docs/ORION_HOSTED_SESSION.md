# Android hosted trust and encrypted delivery adapter

2026-10-10 development milestone. This is isolated from `OrionLinkService` and
the app's existing self-hosted features. It supplies no sign-in SDK, QR camera,
root approval screen, background service or SMS/call action execution.

`HostedSession(root, deviceId, keys, store)` takes an explicit `HostedRoot`
containing deployment UUID and the root device's exact ID, P-256 signing public
key and HPKE public key. That root must already have been obtained from a trusted
device or independently compared full fingerprint. A root received from the
server or Auth0 response is not a trust anchor. `HostedRoot.fingerprint()`
matches Python's domain-separated SHA-256 full-root fingerprint. The constructor
pins both the root and this device's exact public identity in local state.

`acceptPage(chain, final)` verifies at most 16 root-signed successors from the
durable signed local anchor, starting at pinned genesis for a new profile.
Checks cover consecutive versions, predecessor hashes, exact genesis/root
member keys, sorted unique members, unchanged existing keys and no re-admission
of removed device IDs. The checkpoint, exact signed anchor and permanent used-ID
tombstones commit atomically with a compare-and-swap of the prior snapshot.
Restart or another session cannot erase verified progress or race a conflicting
successor into that snapshot. Original full root keys remain pinned in the
identity binding. Tombstones grow with lifetime enrollments; storage errors fail
closed rather than discarding them.

Every page clears ordinary content authority. Expired intermediate rosters are
historical evidence only. A final page activates content authority only for a
signed roster expiring within 24 hours with this device's exact public identity.
An empty final page may activate an already verified fresh anchor. Valid expired
or revoked final anchors commit before rejecting authority, preventing older
history from restoring it. There is no 128-roster lifetime cap: versions use the
protocol's 2^31−1 bound, with 32 devices per roster. Each member's public
encryption key must use the selected single HPKE suite. Bad pages invalidate
in-memory authority. Returned membership is detached from signed snapshots.

`acceptChain(chain)` retains full-genesis compatibility for at most 128 entries.
It cannot roll back a newer paged anchor or forget tombstones. Existing databases
with only a checkpoint keep that checkpoint during schema migration and require
one verified full compatible chain to establish their signed anchor before
paging; an unsigned server head cannot migrate them. Native migration still
requires physical Android evidence.
Root proposal signing/renewal is intentionally deferred until Python's durable
proposal-journal reconciliation model is ported; there is no per-instance
Android root signer that could create conflicting successors.

`encrypt(target, payload)` and `authenticate(envelope)` require an unexpired
approved roster whose digest matches the durable checkpoint. Envelope checks
bind deployment, current roster version/hash, approved sender, exact local
recipient and expiration within five minutes. `authenticate` verifies sender
signature and decrypts into memory without executing or storing an effect.

`receiveIntoEncryptedInbox(envelope)` authenticates first, then atomically
rechecks the high-water state and stores the replay identity with the exact
public header and ciphertext. Identical redelivery returns a duplicate receipt;
different content under the same ID fails. `pendingIncoming()` returns encrypted
envelopes only. The inbox retains at most 1,000 rows and prunes entries 24 hours
after expiry; expired content does not regain current execution authority.
No plaintext payload, account token or private key is written. An atomic
effect-state machine is still required before connecting this to irreversible
phone actions. This adapter deliberately cannot promise action execution after
crash, nor does it automatically retry uncertain SMS/call operations.

`AndroidHostedTrustStore.create(context, deployment, device)` explicitly creates
a fresh private database and creation marker under `noBackupFilesDir`.
`openExisting` requires existing state and does not silently recreate it.
SQLite transactions with FULL synchronous writes serialize checkpoint/inbox
changes; identity binding is required on every operation. No-backup location,
owner-only container files and explicit creation prevent accidental restore of
an unbound profile from masquerading as established trust. JVM tests inject a
state backend; native Android SQLite/fsync/backup behavior remains physically
untested. Device compromise or deliberately restoring/deleting local trust
state is outside the server-operator threat boundary.

`HostedHttpTransport.create(httpsOrigin, session)` supplies a blocking OkHttp
adapter to run on a worker. It rejects HTTP, URL credentials, paths, queries and
fragments; disables redirects, proxies, cookies and automatic retries; bounds
responses and JSON nesting; and rejects duplicate fields including escaped-key
aliases before JSON decoding. Account requests use only a caller-supplied
access token. Device requests require current trust and use only existing P-256
signed request headers. It adds no logging interceptor and never places account
tokens in URLs. `submitEnrollment` and `refreshTrust` do not provide an Auth0
browser flow or automatically approve enrollment.

`refreshTrust` fetches `/v1/devices/rosters/page` with `limit=16`, the verified
`after_version`, and its exact `after_hash` after genesis. Each response is
bounded to one megabyte. The server's `more` boolean is only a continuation hint;
it never replaces signed expiry, membership, ancestry or root checks. A call
performs at most 64 pages; exhausting that budget fails without content authority
and leaves verified progress available for an explicit subsequent refresh.
Network failure or malformed/empty continuation leaves authority disabled.

`pollIntoEncryptedInbox()` ACKs each remote event only after local encrypted
acceptance commits. Failed local acceptance produces no ACK. An uncertain ACK
can be safely retried on redelivery because the exact local ciphertext is
retained and duplicates are idempotent. Outgoing events are generated on `send`;
this Android adapter does not yet provide the desktop's durable outgoing queue.

Unit tests exercise signed trust changes, rollback/forks/revocation/expiry,
identity substitution, ciphertext-only inbox behavior, duplicate/conflicting
IDs, failed commits, ACK timeout redelivery, signed-versus-Bearer requests and
hostile JSON/URLs. Paging cases include 146 renewals, restart after a historical
page, cross-session compare-and-swap races, gaps/forks, persistent retired IDs,
failed writes, expired final anchors and legacy migration. Optional
`ORION_HPKE_FIXTURE` interoperability additionally pages a Python root-signed
chain, authenticates Python ciphertext and emits a
Kotlin session envelope to `<output_path>.session.json` for Python verification.
That test uses synthetic imported private keys only in test code. No raw
synthetic keys or content are printed or committed.

The interoperability runner verifies 146 Python-signed roster versions in
16-entry pages, with expired historical intermediates and a fresh final roster,
then verifies encrypted session delivery in both directions. Generated private
test fixtures are removed. Native Android filesystem behavior is outside that
JVM interoperability evidence.

Remaining gates include actual Android SQLite restart/concurrency evidence,
protected-key integration with the native Keystore, independent root-pinning
UI, Auth0 SDK/controller wiring, durable outgoing jobs, safe reconciliation and
action processing, physical device recovery/background behavior, and security
review. Do not describe hosted app sign-in or E2EE migration as complete.
