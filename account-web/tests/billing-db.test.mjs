import { after, before, beforeEach, describe, test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import pg from "pg";
import { createBillingStore } from "../lib/billing/store.mjs";
import { exportMigrationSql, loadMigrations, runMigrations } from "../lib/billing/migrate.mjs";

const databaseUrl = process.env.SAIPH_BILLING_TEST_DATABASE_URL;
if (databaseUrl) {
  const target = new URL(databaseUrl);
  if (target.hostname !== "127.0.0.1" || target.pathname !== "/saiph_billing_test") {
    throw new Error("Billing tests require the isolated loopback synthetic database");
  }
}
let pool;
let migrations;
const accountId = "acct_synthetic";
const owner = "auth0|synthetic-owner";
const customerId = "cus_synthetic";
function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}
const event = (id = "evt_first", created = 100, overrides = {}) => ({
  eventId: id, type: "customer.subscription.updated", created, customerId,
  livemode: false, ...overrides,
});
const snapshot = (status = "active", overrides = {}) => ({
  subscriptionId: "sub_synthetic", customerId, priceId: "price_synthetic", status,
  currentPeriodEnd: 1000, cancelAtPeriodEnd: false, canceledAt: null, endedAt: null,
  livemode: false, ...overrides,
});
const store = () => createBillingStore(pool, { stripeAccountId: accountId });
const bind = () => store().bindCustomer({ subject: owner, customerId });
const observed = async () => (await store().listSubscriptions(owner))[0];
async function waitForDatabaseLock() {
  for (let attempt = 0; attempt < 100; attempt++) {
    const { rows } = await pool.query(
      "SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND pid<>pg_backend_pid()",
    );
    if (rows.length) return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error("Concurrent database operation never waited for the transaction lock");
}

describe("isolated PostgreSQL billing transactions", { skip: !databaseUrl ? "Run npm run test:billing-db for isolated Docker PostgreSQL checks" : false }, () => {
  before(async () => {
    pool = new pg.Pool({ connectionString: databaseUrl, max: 8 });
    migrations = await loadMigrations();
    await runMigrations(pool, migrations);
  });
  beforeEach(async () => {
    await pool.query("TRUNCATE saiph_billing.customer_creation_intents, saiph_billing.processed_events, saiph_billing.subscriptions, saiph_billing.customers");
  });
  after(async () => { await pool?.end(); });

  test("migration applies exactly once and verifies committed checksum history", async () => {
    assert.deepEqual(await runMigrations(pool, migrations), []);
    const { rows } = await pool.query("SELECT version,sha256 FROM saiph_billing.schema_migrations ORDER BY version");
    assert.equal(rows.length, migrations.length);
    assert.equal(rows[0].sha256, migrations[0].sha256);
    await pool.query("UPDATE saiph_billing.schema_migrations SET sha256=$1 WHERE version=1", ["0".repeat(64)]);
    try {
      await assert.rejects(runMigrations(pool, migrations), /differs from reviewed history/);
    } finally {
      await pool.query("UPDATE saiph_billing.schema_migrations SET sha256=$1 WHERE version=1", [migrations[0].sha256]);
    }
  });

  test("failed migration rolls back its DDL and ledger row together", async () => {
    await assert.rejects(runMigrations(pool, [...migrations, {
      version: migrations.length + 1, file: "0099_synthetic.sql", sha256: "1".repeat(64),
      sql: "CREATE TABLE saiph_billing.rollback_probe (id integer); SELECT 1/0;",
    }]), { code: "22012" });
    const { rows } = await pool.query("SELECT to_regclass('saiph_billing.rollback_probe') AS probe");
    assert.equal(rows[0].probe, null);
    assert.equal((await pool.query("SELECT count(*) FROM saiph_billing.schema_migrations")).rows[0].count, String(migrations.length));
  });

  test("changed SQL is rejected against the reviewed manifest before any DB access", async () => {
    const directory = await mkdtemp(join(tmpdir(), "saiph-migration-"));
    try {
      await writeFile(join(directory, "manifest.json"), JSON.stringify([{
        version: 1, file: "0001_billing.sql", sha256: migrations[0].sha256,
      }]));
      await writeFile(join(directory, "0001_billing.sql"), migrations[0].sql + "\n-- changed");
      await assert.rejects(loadMigrations(pathToFileURL(directory + "/")), /checksum/);
    } finally { await rm(directory, { recursive: true, force: true }); }
  });

  test("mapping is unique and cannot be rebound through application or direct SQL", async () => {
    assert.deepEqual(await bind(), { subject: owner, customerId });
    assert.deepEqual(await bind(), { subject: owner, customerId });
    await assert.rejects(store().bindCustomer({ subject: owner, customerId: "cus_other" }), { code: "CUSTOMER_ALREADY_BOUND" });
    await assert.rejects(store().bindCustomer({ subject: "auth0|other", customerId }), { code: "23505" });
    await assert.rejects(pool.query("UPDATE saiph_billing.customers SET stripe_customer_id='cus_other'"), { code: "23514" });
    await assert.rejects(pool.query("DELETE FROM saiph_billing.customers"), { code: "23514" });
    assert.deepEqual(await store().findCustomer(owner), { subject: owner, customerId });
    assert.equal(await store().findCustomer("auth0|other"), null);
  });

  test("two concurrent customer creations serialize before contacting the provider", async () => {
    const entered = deferred();
    const release = deferred();
    let calls = 0;
    const create = async () => {
      calls++;
      entered.resolve();
      await release.promise;
      return customerId;
    };
    const first = store().getOrCreateCustomer(owner, create);
    await entered.promise;
    const second = store().getOrCreateCustomer(owner, create);
    try {
      await waitForDatabaseLock();
      assert.equal(calls, 1);
    } finally { release.resolve(); }
    const results = await Promise.all([first, second]);
    assert.deepEqual(results[0], results[1]);
    assert.equal(calls, 1);
  });

  test("provider failure rolls customer creation back so it can retry", async () => {
    await assert.rejects(store().getOrCreateCustomer(owner, async () => { throw new Error("synthetic provider unavailable"); }));
    assert.equal(await store().findCustomer(owner), null);
    await bind();
  });

  test("event replay survives a new connection pool and skips another provider fetch", async () => {
    await bind();
    assert.deepEqual(await store().applyEvent(event(), async (mapping) => {
      assert.deepEqual(mapping, { subject: owner, customerId });
      return snapshot();
    }), { outcome: "applied", subscriptionId: "sub_synthetic" });
    const restartedPool = new pg.Pool({ connectionString: databaseUrl });
    try {
      const restarted = createBillingStore(restartedPool, { stripeAccountId: accountId });
      assert.equal((await restarted.applyEvent(event(), async () => { throw new Error("duplicate must not fetch"); })).outcome, "duplicate");
      assert.equal((await restarted.listSubscriptions(owner))[0].status, "active");
    } finally { await restartedPool.end(); }
    assert.equal((await pool.query("SELECT count(*) FROM saiph_billing.processed_events")).rows[0].count, "1");
  });

  test("concurrent duplicate deliveries make one update and one provider fetch", async () => {
    await bind();
    const entered = deferred(), release = deferred();
    let calls = 0;
    const load = async () => {
      calls++;
      entered.resolve();
      await release.promise;
      return snapshot();
    };
    const first = store().applyEvent(event(), load);
    await entered.promise;
    const second = store().applyEvent(event(), load);
    try { await waitForDatabaseLock(); assert.equal(calls, 1); }
    finally { release.resolve(); }
    const results = await Promise.all([first, second]);
    assert.deepEqual(results.map((result) => result.outcome).sort(), ["applied", "duplicate"]);
    assert.equal(calls, 1);
  });

  test("checkout customer lock also serializes webhook snapshot fetch", async () => {
    await bind();
    const entered = deferred(), release = deferred();
    let fetched = false;
    const checkout = store().withCustomer(owner, async (mapping) => {
      assert.equal(mapping.customerId, customerId);
      entered.resolve();
      await release.promise;
      return "provider result";
    });
    await entered.promise;
    const webhook = store().applyEvent(event(), async () => { fetched = true; return snapshot(); });
    try { await waitForDatabaseLock(); assert.equal(fetched, false); }
    finally { release.resolve(); }
    assert.equal(await checkout, "provider result");
    assert.equal((await webhook).outcome, "applied");
  });

  test("newer cancellation cannot be reversed by older or newer active snapshots", async () => {
    await bind();
    await store().applyEvent(event(), async () => snapshot());
    await store().applyEvent(event("evt_cancel", 200), async () => snapshot("canceled", { canceledAt: 200, endedAt: 200 }));
    for (const [id, created] of [["evt_old", 150], ["evt_late", 300], ["evt_tie", 200]]) {
      assert.equal((await store().applyEvent(event(id, created), async () => snapshot())).outcome, "terminal_ignored");
    }
    assert.equal((await observed()).status, "canceled");
    await assert.rejects(pool.query("UPDATE saiph_billing.subscriptions SET status='active'"), { code: "23514" });
    // A genuine new purchase has a different provider subscription ID.
    await store().applyEvent(event("evt_new", 400), async () => snapshot("active", { subscriptionId: "sub_new" }));
    assert.equal((await store().listSubscriptions(owner)).length, 2);
  });

  test("delayed terminal snapshot is accepted conservatively and stale nonterminal snapshots ignored", async () => {
    await bind();
    await store().applyEvent(event("evt_recent", 200), async () => snapshot("past_due"));
    assert.equal((await store().applyEvent(event("evt_older", 100), async () => snapshot("active"))).outcome, "stale");
    assert.equal((await observed()).status, "past_due");
    assert.equal((await store().applyEvent(event("evt_cancel", 150), async () => snapshot("canceled"))).outcome, "applied");
    assert.equal((await observed()).status, "canceled");
  });

  test("same-second events use fresh snapshots under lock, never lexicographic event IDs", async () => {
    await bind();
    await store().applyEvent(event("evt_z", 200), async () => snapshot());
    await store().applyEvent(event("evt_a", 200), async () => snapshot("canceled"));
    assert.equal((await observed()).status, "canceled");
  });

  test("failed renewal, scheduled cancellation and incomplete expiry are separate observations", async () => {
    await bind();
    await store().applyEvent(event("evt_due", 100, { type: "invoice.payment_failed" }), async () => snapshot("past_due"));
    assert.equal((await observed()).status, "past_due");
    await store().applyEvent(event("evt_schedule", 110), async () => snapshot("active", { cancelAtPeriodEnd: true }));
    assert.equal((await observed()).cancelAtPeriodEnd, true);
    await store().applyEvent(event("evt_expire", 120), async () => snapshot("incomplete_expired"));
    assert.equal((await store().applyEvent(event("evt_retry", 130), async () => snapshot("active"))).outcome, "terminal_ignored");
    assert.equal((await observed()).status, "incomplete_expired");
    assert.equal("entitled" in await observed(), false);
    assert.deepEqual(await store().listSubscriptions("auth0|other"), []);
  });

  test("provider failure and invalid snapshots leave no dedup marker or partial lifecycle state", async () => {
    await bind();
    for (const load of [
      async () => { throw new Error("synthetic provider failure"); },
      async () => snapshot("active", { customerId: "cus_other" }),
      async () => snapshot("active", { livemode: true }),
      async () => snapshot("invented"),
    ]) {
      await assert.rejects(store().applyEvent(event(), load));
      assert.equal((await pool.query("SELECT count(*) FROM saiph_billing.processed_events")).rows[0].count, "0");
      assert.deepEqual(await store().listSubscriptions(owner), []);
    }
    assert.equal((await store().applyEvent(event(), async () => snapshot())).outcome, "applied");
  });

  test("ledger insert failure rolls back a subscription write and the event can retry", async () => {
    await bind();
    await pool.query(`CREATE FUNCTION saiph_billing.synthetic_reject_event() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'synthetic failure'; END; $$;
      CREATE TRIGGER synthetic_reject_event BEFORE INSERT ON saiph_billing.processed_events
      FOR EACH ROW EXECUTE FUNCTION saiph_billing.synthetic_reject_event();`);
    try {
      await assert.rejects(store().applyEvent(event(), async () => snapshot()));
      assert.deepEqual(await store().listSubscriptions(owner), []);
    } finally {
      await pool.query("DROP TRIGGER synthetic_reject_event ON saiph_billing.processed_events; DROP FUNCTION saiph_billing.synthetic_reject_event()");
    }
    assert.equal((await store().applyEvent(event(), async () => snapshot())).outcome, "applied");
  });

  test("live, malformed and unknown-customer events fail before provider fetch", async () => {
    let calls = 0;
    const load = async () => { calls++; return snapshot(); };
    for (const candidate of [
      event("evt_live", 100, { livemode: true }),
      event("evt_type", 100, { type: "unknown.event" }),
      event("evt_negative", -1), event("invalid"),
      event("evt_unknown"),
    ]) await assert.rejects(store().applyEvent(candidate, load));
    assert.equal(calls, 0);
  });

  test("different customers cannot reuse a subscription or processed event ID", async () => {
    await bind();
    await store().bindCustomer({ subject: "auth0|other", customerId: "cus_other" });
    await store().applyEvent(event(), async () => snapshot());
    await assert.rejects(store().applyEvent(event("evt_other", 200, { customerId: "cus_other" }), async () =>
      snapshot("active", { customerId: "cus_other" })), { code: "SUBSCRIPTION_ALREADY_BOUND" });
    await assert.rejects(store().applyEvent(event("evt_first", 100, { customerId: "cus_other" }), async () =>
      snapshot("active", { customerId: "cus_other", subscriptionId: "sub_other" })), { code: "EVENT_ID_COLLISION" });
    assert.deepEqual(await store().listSubscriptions("auth0|other"), []);
  });

  test("account scopes isolate customer, subscription and event identifiers", async () => {
    await bind();
    const anotherAccount = createBillingStore(pool, { stripeAccountId: "acct_another" });
    assert.equal(await anotherAccount.findCustomer(owner), null);
    await anotherAccount.bindCustomer({ subject: owner, customerId });
    await store().applyEvent(event(), async () => snapshot());
    await anotherAccount.applyEvent(event(), async () => snapshot("past_due"));
    assert.equal((await observed()).status, "active");
    assert.equal((await anotherAccount.listSubscriptions(owner))[0].status, "past_due");
  });

  test("owner SQL-editor export applies from empty schema and is safely repeatable", async () => {
    const sql = exportMigrationSql(migrations);
    const checked = await readFile(new URL("../migrations/reviewed-migration.sql", import.meta.url), "utf8");
    assert.equal(checked, sql);
    await pool.query("DROP SCHEMA saiph_billing CASCADE");
    const client = await pool.connect();
    try {
      await client.query(sql);
      await client.query(sql);
      assert.equal((await client.query("SELECT count(*) FROM saiph_billing.schema_migrations")).rows[0].count, String(migrations.length));
      assert.ok((await client.query("SELECT to_regclass('saiph_billing.processed_events') AS table_name")).rows[0].table_name);
    } finally { client.release(); }
  });

  test("SQL-editor history mismatch fails atomically without executing pending DDL", async () => {
    const sql = exportMigrationSql([...migrations, {
      version: migrations.length + 1, file: "0099_synthetic.sql", sha256: "2".repeat(64),
      sql: "CREATE TABLE saiph_billing.export_probe (id integer);",
    }]);
    await pool.query("UPDATE saiph_billing.schema_migrations SET sha256=$1 WHERE version=1", ["0".repeat(64)]);
    const client = await pool.connect();
    try {
      await assert.rejects(client.query(sql), /differs from reviewed history/);
      await client.query("ROLLBACK");
      assert.equal((await client.query("SELECT to_regclass('saiph_billing.export_probe') AS probe")).rows[0].probe, null);
    } finally {
      client.release();
      await pool.query("UPDATE saiph_billing.schema_migrations SET sha256=$1 WHERE version=1", [migrations[0].sha256]);
    }
  });

  test("creation intent commits before provider call and survives ambiguous remote success", async () => {
    await assert.rejects(store().getOrCreateCustomer(owner, async () => {
      const { rows } = await pool.query(
        "SELECT 1 FROM saiph_billing.customer_creation_intents WHERE stripe_account_id=$1 AND auth_subject=$2",
        [accountId, owner],
      );
      assert.equal(rows.length, 1, "intent must be visible on a different connection before remote call");
      throw new Error("synthetic ambiguous provider success");
    }));
    assert.equal(await store().findCustomer(owner), null);
    assert.equal((await pool.query("SELECT count(*) FROM saiph_billing.customer_creation_intents")).rows[0].count, "1");
    await pool.query("UPDATE saiph_billing.customer_creation_intents SET created_at=clock_timestamp()-interval '24 hours'");
    let called = false;
    await assert.rejects(store().getOrCreateCustomer(owner, async () => {
      called = true; return customerId;
    }), { code: "CUSTOMER_RECONCILIATION_REQUIRED" });
    assert.equal(called, false);
    // Explicit reconciliation binds the independently verified existing customer.
    await bind();
    assert.deepEqual(await store().getOrCreateCustomer(owner, async () => { throw new Error("must reuse binding"); }), { subject: owner, customerId });
  });

  test("0002 upgrades an existing 0001 database with rows and keeps them", async () => {
    await pool.query("DROP SCHEMA saiph_billing CASCADE");
    assert.deepEqual(await runMigrations(pool, migrations.slice(0, 1)), [1]);
    await pool.query("INSERT INTO saiph_billing.customers (stripe_account_id,auth_subject,stripe_customer_id) VALUES ($1,$2,$3)", [accountId, owner, customerId]);
    await pool.query(`INSERT INTO saiph_billing.subscriptions (stripe_account_id,stripe_subscription_id,stripe_customer_id,stripe_price_id,status,
      current_period_end,cancel_at_period_end,canceled_at,ended_at,last_event_created,last_event_id)
      VALUES ($1,'sub_synthetic',$2,'price_synthetic','active',1000,false,null,null,100,'evt_first')`, [accountId, customerId]);
    assert.deepEqual(await runMigrations(pool, migrations), migrations.slice(1).map(({ version }) => version));
    assert.deepEqual(await runMigrations(pool, migrations), []);
    const row = await observed();
    assert.equal(row.status, "active");
    assert.equal(row.cancelAt, null);
  });

  test("lifecycle indexes exist and processed-event receipts are append-only", async () => {
    const { rows } = await pool.query("SELECT indexname FROM pg_indexes WHERE schemaname='saiph_billing' ORDER BY indexname");
    const names = rows.map((row) => row.indexname);
    for (const name of ["processed_events_customer", "processed_events_subscription", "subscriptions_customer"]) assert.ok(names.includes(name), name);
    await bind();
    await store().applyEvent(event(), async () => snapshot());
    await assert.rejects(pool.query("DELETE FROM saiph_billing.processed_events"), { code: "23514" });
    await assert.rejects(pool.query("UPDATE saiph_billing.processed_events SET outcome='stale'"), { code: "23514" });
    assert.equal((await store().applyEvent(event(), async () => { throw new Error("duplicate must not fetch"); })).outcome, "duplicate");
  });

  test("scheduled cancel_at is persisted with the snapshot and cleared when resumed", async () => {
    await bind();
    await store().applyEvent(event("evt_sched", 100), async () => snapshot("active", { cancelAt: 900 }));
    assert.equal((await observed()).cancelAt, 900);
    await store().applyEvent(event("evt_resume", 110), async () => snapshot("active", { cancelAt: null }));
    assert.equal((await observed()).cancelAt, null);
    await assert.rejects(store().applyEvent(event("evt_bad", 120), async () => snapshot("active", { cancelAt: -1 })), { code: "INVALID_TIMESTAMP" });
  });

});
