# Hosted security fixes prepared 12 October 2026

These source changes address four reproduced findings. They require an updated
desktop build and hosted service release; local checks do not establish that a
deployed service or installed desktop has been updated.

## Desktop sign-in

When account refresh requires sign-in, the desktop closes its transport,
invalidates the in-memory device session and clears queued clipboard data and
file offers. Sending files, saving offers and dismissing notifications check the
account token at the native operation boundary. Sending checks again after file
encryption, before upload. Expiry at that boundary removes the staged ciphertext.
Signing in again reloads the existing identity and verifies the saved roster;
the change does not rotate keys or change pairing identity.

## Installer downloads

Redemption now reserves usage and a stream lease atomically in the account
registry database. Limits survive process restarts and apply across processes.
The existing admission, ticket expiry and account-standing checks remain in force.

| Limit | Default |
| --- | --- |
| Rolling usage window | 300 seconds |
| Requests per ticket / account / service | 8 / 30 / 120 per window |
| Simultaneous streams per account / service | 2 / 8 |
| Bytes per account / service | 4 / 16 times the largest catalog artifact per window |
| Maximum stream duration | 300 seconds |

GET reserves the entire selected file size, including retries, interrupted
transfers and single Range requests. HEAD consumes a request and temporary stream
lease but no byte budget. Multipart Range requests are rejected. Limits return
429 with Retry-After; single ranges and bounded retries still work. Completion,
disconnect, cancellation and timeout release the lease. A crashed process's
lease expires after its stream timeout plus 30 seconds. The shared runner also
limits Uvicorn concurrency to 128. Monitor these limits against actual installer
sizes and authorized synthetic load before expanding the beta.

## Primary storage expiry

Both the owner-only and shared hosted apps start an expiry worker through their
ASGI lifespan. The shared worker visits up to 32 registered accounts per pass,
using keyset pagination, then wraps to the beginning. It runs immediately and
waits 60 seconds between completed passes. It includes idle and suspended
accounts and does not instantiate missing workspaces. Keep ASGI lifespan enabled.

Each workspace pass deletes at most 256 expired rows per event, candidate and
blob table, associated blob chunks, and at most 256 nonces older than the replay
window. It checks the stored deployment and account binding before deletion.
Failures are isolated and produce warnings without account identifiers or data;
later passes retry. Cleanup delay depends on account count, backlog, contention
and uptime. This is not a guarantee of deletion within one minute of expiry.

Logical SQLite deletion does not securely erase freed pages, backups, replicas
or exports. Roster and immutable device-ownership records are retained. Production
retention and account-erasure procedures still require separate verification.

## Beta-code lockout (13 October)

Any signed-in account could make five failed redemption attempts, so accounts
created through open sign-up could fill the global 1,000-attempt window and block
every invitation redemption. Codes carry 192 random bits, so since `b1fd50b`
the global limit only throttles failed attempts; a valid code still redeems
while it is full. The per-account limit of five attempts applies to every
request. Restricting account sign-up remains a separate provider setting.

## Operations and verification

The private operations repository adds registry-driven backup inventory checks.
Accounts with registered devices must have a workspace, matching deployment and
issuer/subject binding, matching immutable device inventory and a saved roster.
Snapshot and restore verification reject omissions and unexpected workspaces.
Admitted accounts with no devices may legitimately be uninitialized.

Regression tests use synthetic identities and offline ASGI clients, with real
device signatures and encrypted attachment round trips. They cover login expiry
before dispatch and during encryption, persistent download budgets/concurrency,
stream exit paths, missing or mismatched backup inventory, suspended-account
cleanup, pagination and both app lifespans. They do not establish physical-device
acceptance, production load behavior or independent-machine disaster recovery.
