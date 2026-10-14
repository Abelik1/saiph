# Reviewed billing database migration

The account app stores billing observations separately from Hosted/device trust.
No schema statement contains deployment secrets or an owner identity.

- `0001_billing.sql`: versioned DDL, applied through the runner/export.
- `0002_billing_lifecycle.sql`: additive `subscriptions.cancel_at`, indexes
  `subscriptions_customer` and `processed_events_subscription`, and an
  append-only trigger on `processed_events` (deleting a receipt would allow a
  replay to be processed again). Backward compatible with the previous code.
- `0003_paid_hosted.sql` (docs/PAID_HOSTED.md): `settings` (one Stripe mode per
  database), `subscriptions.payment_failed_at`, `disputes`, dispute receipts in
  `processed_events` (exactly one subscription or dispute target), the
  `grant_sequence` sequence and `grant_state` delivery table, backfilled for
  existing subscriptions. Additive: code from 0002 keeps working against it.
- `manifest.json`: SHA-256 of the exact canonical LF SQL bytes.
- `reviewed-migration.sql`: generated **complete transaction** for the Neon SQL editor.
  It includes schema/ledger creation, an advisory transaction lock, migration
  history verification and guarded DDL. Do not run bare `0001_billing.sql`.
- `npm run db:plan`: verify the committed manifest locally; no database connection.
- `npm run db:export`: regenerate the reviewed SQL-editor transaction locally.
- `npm run db:migrate`: explicitly apply/verify via sensitive
  `DATABASE_URL_UNPOOLED` supplied privately in the process environment. The runner
  does not load env files, accept a URL argument or run during build/startup.

To apply through the SQL editor, open the intended isolated development account
database in Neon, review and execute the **entire** `reviewed-migration.sql` file.
No connection string needs to leave Neon. Verify the receipt with:

```sql
SELECT version, file, sha256 FROM saiph_billing.schema_migrations ORDER BY version;
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'saiph_billing' ORDER BY table_name;
SELECT indexname FROM pg_indexes WHERE schemaname = 'saiph_billing' ORDER BY indexname;
SELECT
  (SELECT count(*) FROM saiph_billing.customers) AS customer_count,
  (SELECT count(*) FROM saiph_billing.customer_creation_intents) AS creation_intent_count,
  (SELECT count(*) FROM saiph_billing.subscriptions) AS subscription_count,
  (SELECT count(*) FROM saiph_billing.processed_events) AS processed_event_count;
```

The receipt must show versions 1, 2 and 3 with the manifest checksums
(`manifest.json`), eight tables (`customer_creation_intents`, `customers`,
`disputes`, `grant_state`, `processed_events`, `schema_migrations`, `settings`,
`subscriptions`), the indexes `disputes_customer`, `processed_events_customer`,
`processed_events_subscription` and `subscriptions_customer` (plus primary/unique
keys), and on a fresh database zero business rows. Rerunning the complete
export is safe. Changed/unknown applied history fails the transaction. If the
editor reports an error with an open transaction, run `ROLLBACK;` before retrying.
Do not edit applied migrations or reset the ledger to force a match. This project
does not run a destructive automatic down migration.

## Storage contract

`lib/billing/db.ts` is the server-only entry point:
`withBillingStore(stripeAccountId, callback)` opens and closes a request-scoped
Neon WebSocket Pool, using TLS-required `DATABASE_URL`. It is lazy at build time.
Store APIs:

- `findCustomer(subject)`: exact account/subject mapping or null.
- `getOrCreateCustomer(subject, createCustomer)`: commits a durable creation
  intent first, then locks the subject before invoking the provider callback.
  The callback returns a verified customer ID and **must** use a deterministic
  account/subject Stripe idempotency key. If a remote creation succeeds but its
  database commit fails, the intent survives. Unresolved attempts older than
  23 hours refuse another automatic provider call, within Stripe's documented
  minimum 24-hour idempotency retention; verify/reconcile the existing customer.
- `bindCustomer({subject, customerId})`: explicit reconciliation of an
  independently verified provider customer. Existing mappings cannot change;
  uniqueness prevents cross-subject reuse.
- `withCustomer(subject, callback)`: serialize checkout/portal provider calls
  using the same customer row lock as webhook reconciliation. The callback
  receives only `{subject, customerId}`. Do not nest store calls within it.
- `applyEvent(event, loadSnapshot)`: call only after raw-body signature/account
  validation. Event fields are `eventId, type, created, customerId, livemode:false`.
  The callback receives the locked mapping and must fetch a **current** verified
  Stripe subscription snapshot inside the lock. It runs only for unseen event
  IDs. Snapshot fields: `subscriptionId, customerId, priceId, status,
  currentPeriodEnd, cancelAtPeriodEnd, cancelAt, canceledAt, endedAt, livemode:false`.
  Time values are integer Unix seconds, nullable where applicable.
- `listSubscriptions(subject)`: billing display fields scoped to the mapping;
  no entitlement Boolean. `lib/billing/entitlement.mjs` derives standing from
  this output only.

The event receipt and subscription update commit together. Duplicate delivery is
durably skipped. Older nonterminal observations are ignored; terminal cancellation
or incomplete expiry can still be accepted conservatively from a delayed event.
A terminal subscription ID cannot be reactivated. Same-second event IDs are not
ordered lexicographically; fresh snapshots are fetched under the transaction lock.
A genuine later purchase requires a different Stripe subscription ID.
Records contain identifiers, status, period/cancellation timestamps, receipt times
and outcomes only, never raw provider/profile/webhook payloads. Identity triggers
also reject direct SQL reassignment. Retention/removal policy for these immutable
development records must be reviewed before public onboarding.

## Applying to the development account database (owner)

Not applied by the billing-lifecycle change: no database credential was
available to it, and none should be copied into chat, Git or a command line
argument. Apply all versions **before** deploying code that needs them (0003
before `feat/paid-hosted`); older deployed code keeps working against the
migrated schema. Choose one:

1. Neon SQL editor (no connection string leaves Neon): open the
   isolated development account project/database, paste the **entire**
   `account-web/migrations/reviewed-migration.sql`, run it, then run the receipt
   queries above.
2. Checked runner from `account-web` (verifies `manifest.json` checksums and the
   applied history; prints only version numbers). PowerShell:

   ```powershell
   npm ci --ignore-scripts
   npm run db:plan
   $env:DATABASE_URL_UNPOOLED = (neonctl connection-string --project-id <account project id> --database-name <database> --role-name <role>)
   npm run db:migrate
   Remove-Item Env:DATABASE_URL_UNPOOLED
   ```

   Bash: `DATABASE_URL_UNPOOLED="$(neonctl connection-string --project-id <id> --database-name <db> --role-name <role>)" npm run db:migrate`.
   The value must be the direct (non `-pooler`) host with `sslmode=require`;
   Vercel's `DATABASE_URL_UNPOOLED` for the project is equivalent. The runner
   expects `{"appliedVersions":[1,2,3],"verifiedVersions":[1,2,3]}` on first run and
   `[]` applied on a repeat.
3. psql with the same private variable:
   `psql "$DATABASE_URL_UNPOOLED" -v ON_ERROR_STOP=1 -f account-web/migrations/reviewed-migration.sql`
   (the file contains its own `BEGIN`/`COMMIT`; do not add `--single-transaction`).

## Reproducible verification

From `account-web`, with Node24 and Docker running:

```sh
npm ci
npm test
npm run typecheck
npm run db:plan
npm run test:billing-db
```

The last command starts one fresh `postgres:16-alpine` container on a random
loopback port, with generated synthetic credentials, no host mounts and no
persistent volume. It stops only that named container afterward. It never reads
`DATABASE_URL`, pulls deployment secrets or connects to Neon. Account CI runs
this command explicitly. Plain `npm test` reports the PostgreSQL suite skipped
unless the isolated runner supplies its validated test URL.

Tests exercise real PostgreSQL DDL/transactions: migration repeat/checksum
rejection and rollback; owner SQL export from an empty schema/repeat; immutable
mapping; creation intent commit/expiry; concurrent creation and duplicate delivery;
cross-checkout/webhook locks; durable replay after a new pool; stale and same-second
ordering; cancellation/expiry; provider/ledger failure rollback; account isolation;
0001-to-0002 upgrade with rows; append-only receipts; `cancel_at` persistence.
`tests/billing-lifecycle.test.mjs` drives the real HTTP checkout/portal/webhook
handlers against the same database with signed synthetic events.
These checks do not prove actual Neon connectivity, applied remote schema,
restricted-key permissions, real webhook delivery or paid-product readiness.

References: [Neon interactive transactions](https://github.com/neondatabase/serverless#sessions-transactions-and-node-postgres-compatibility),
[PostgreSQL locks](https://www.postgresql.org/docs/current/explicit-locking.html),
[node-postgres transactions](https://node-postgres.com/features/transactions),
[Stripe idempotency retention](https://docs.stripe.com/api/idempotent_requests).
