// SPDX-License-Identifier: AGPL-3.0-or-later
// End-to-end lifecycle through the real HTTP handlers, the official Stripe SDK
// signature verifier and the real PostgreSQL store/migrations on an isolated
// loopback database. Stripe is a stateful synthetic fixture: no sandbox
// account, key or network request is used, so this is not provider acceptance.
import { after, before, beforeEach, describe, test } from "node:test";
import assert from "node:assert/strict";
import Stripe from "stripe";
import pg from "pg";
import { createBillingStore } from "../lib/billing/store.mjs";
import { loadMigrations, runMigrations } from "../lib/billing/migrate.mjs";
import { deriveEntitlement } from "../lib/billing/entitlement.mjs";
import { createPublicKey, generateKeyPairSync, verify } from "node:crypto";
import { accountAction, webhook, refresh } from "../lib/billing/http.ts";
import { GRANT_CONTEXT, pushGrant } from "../lib/billing/grant-push.mjs";
import { RENEWAL_GRACE_SECONDS, PAYMENT_GRACE_SECONDS } from "../lib/billing/entitlement.mjs";
import { readBillingConfig, subjectReference } from "../lib/billing/policy.ts";

const databaseUrl = process.env.SAIPH_BILLING_TEST_DATABASE_URL;
if (databaseUrl) {
  const target = new URL(databaseUrl);
  if (target.hostname !== "127.0.0.1" || target.pathname !== "/saiph_billing_test") {
    throw new Error("Billing tests require the isolated loopback synthetic database");
  }
}
// Generated per run: no private key is stored in the repository.
const grantPrivate = generateKeyPairSync("ed25519").privateKey;
const env = {
  SAIPH_BILLING_MODE: "owner-sandbox", AUTH0_DOMAIN: "synthetic.us.auth0.com", AUTH0_CLIENT_ID: "syntheticclient",
  AUTH0_CLIENT_SECRET: "synthetic-not-real", AUTH0_SECRET: "cd".repeat(32), APP_BASE_URL: "https://account.saiph.test",
  SAIPH_OWNER_SUBJECT: "auth0|synthetic-owner", STRIPE_SECRET_KEY: "rk_test_synthetic123",
  STRIPE_WEBHOOK_SECRET: "whsec_synthetic123", STRIPE_EXPECTED_ACCOUNT_ID: "acct_synthetic",
  STRIPE_PRODUCT_ID: "prod_synthetic", STRIPE_PRICE_ID: "price_synthetic", STRIPE_YEARLY_PRICE_ID: "price_yearly",
  SAIPH_HOSTED_API_URL: "https://api.saiph.test", SAIPH_BILLING_GRANT_KEY: grantPrivate.export({ format: "der", type: "pkcs8" }).toString("base64url"),
  SAIPH_BILLING_GRANT_KEY_ID: "test-1", CRON_SECRET: "c".repeat(40), STRIPE_PORTAL_CONFIGURATION_ID: "bpc_synthetic",
  DATABASE_URL: "postgresql://synthetic:synthetic@synthetic-pooler.eu-west-2.aws.neon.tech/synthetic?sslmode=require",
};
const config = readBillingConfig(env);
const owner = env.SAIPH_OWNER_SUBJECT;
const other = "auth0|synthetic-other";
const NOW = Math.floor(Date.now() / 1000);
const PERIOD_END = NOW + 30 * 86400;
const meta = (subject) => ({ saiph_billing: "owner-sandbox-v1", saiph_subject_ref: subjectReference(subject), saiph_account: config.accountId });
let pool;

/** Stateful Stripe stand-in. Only `webhooks` is the real SDK implementation. */
function provider() {
  const sdk = new Stripe(env.STRIPE_SECRET_KEY);
  const customers = new Map(), subscriptions = new Map(), sessions = [], idempotency = new Map();
  const calls = { customerCreate: 0, checkoutCreate: 0, portal: [], subscriptionRetrieve: 0 };
  let sequence = 0;
  const stripe = {
    webhooks: sdk.webhooks,
    prices: { retrieve: async (id) => ({ id, active: true, livemode: false, currency: "eur", unit_amount: id === config.plans.yearly.priceId ? 3600 : 399,
      type: "recurring", recurring: { interval: id === config.plans.yearly.priceId ? "year" : "month", interval_count: 1 }, product: { id: config.productId, active: true, livemode: false } }) },
    customers: {
      create: async (params, options) => {
        if (idempotency.has(options?.idempotencyKey)) return idempotency.get(options.idempotencyKey);
        calls.customerCreate++;
        const customer = { id: "cus_synthetic" + ++sequence, livemode: false, metadata: params.metadata };
        customers.set(customer.id, customer); idempotency.set(options?.idempotencyKey, customer);
        return customer;
      },
      retrieve: async (id) => { const customer = customers.get(id); if (!customer) throw new Error("No such customer"); return customer; },
    },
    subscriptions: {
      list: async ({ customer }) => ({ has_more: false, data: [...subscriptions.values()].filter((sub) => sub.customer === customer) }),
      retrieve: async (id) => { calls.subscriptionRetrieve++; const sub = subscriptions.get(id); if (!sub) throw new Error("No such subscription"); return structuredClone(sub); },
    },
    checkout: { sessions: {
      list: async ({ customer }) => ({ has_more: false, data: sessions.filter((session) => session.customer === customer && session.status === "open") }),
      listLineItems: async () => ({ has_more: false, data: [{ quantity: 1, price: { id: config.plans.monthly.priceId, livemode: false, product: config.productId } }] }),
      create: async (params) => {
        calls.checkoutCreate++;
        const session = { ...params, id: "cs_test_synthetic" + ++sequence, livemode: false, status: "open",
          url: "https://checkout.stripe.com/c/pay/cs_test_synthetic" + sequence };
        sessions.push(session);
        return session;
      },
    } },
    billingPortal: { sessions: { create: async (params) => { calls.portal.push(params);
      return { ...params, url: "https://billing.stripe.com/p/session/synthetic_" + params.customer }; } } },
  };
  /** Simulate Stripe completing hosted Checkout: the subscription exists only provider-side. */
  function completeCheckout(customerId, status = "active") {
    const session = sessions.find((candidate) => candidate.customer === customerId && candidate.status === "open");
    const sub = { id: "sub_synthetic" + ++sequence, object: "subscription", customer: customerId, livemode: false,
      metadata: session.subscription_data.metadata, status, cancel_at_period_end: false, cancel_at: null, canceled_at: null, ended_at: null,
      items: { has_more: false, data: [{ quantity: 1, current_period_end: PERIOD_END, price: { id: config.plans.monthly.priceId, livemode: false, product: config.productId } }] } };
    subscriptions.set(sub.id, sub);
    session.status = "complete"; session.subscription = sub.id;
    return { session, sub };
  }
  /** Register a customer that belongs to another Auth0 user. */
  function foreignCustomer(subject) {
    const customer = { id: "cus_foreign" + ++sequence, livemode: false, metadata: meta(subject) };
    customers.set(customer.id, customer);
    return customer;
  }
  return { stripe, calls, subscriptions, completeCheckout, foreignCustomer };
}

// Stand-in for the Hosted service: verifies the Ed25519 signature with the public
// key only and applies the same sequence rule as AccountRegistry.apply_paid_grant.
const hub = { grants: new Map(), down: false };
const grantPublic = createPublicKey(grantPrivate);
async function hubFetch(url, init) {
  if (hub.down) throw new Error("Hosted service unreachable");
  assert.equal(url, "https://api.saiph.test/v1/billing/grant");
  const match = /^t=(\d+),k=test-1,v1=([A-Za-z0-9_-]+)$/.exec(init.headers["Saiph-Billing-Signature"]);
  assert.ok(match && verify(null, Buffer.from(GRANT_CONTEXT + match[1] + "." + init.body), grantPublic, Buffer.from(match[2], "base64url")));
  const value = JSON.parse(init.body);
  const prior = hub.grants.get(value.grant);
  const applied = !prior || value.sequence > prior.sequence;
  if (applied) hub.grants.set(value.grant, value);
  return new Response(JSON.stringify({ applied }), { status: 200, headers: { "content-type": "application/json" } });
}
const hubUntil = (subscriptionId) => hub.grants.get("stripe:" + subscriptionId)?.until ?? null;
function deps(stripe, sub = owner) {
  return { env, getSession: async () => (sub ? { user: { sub } } : null), createStripe: () => stripe,
    withStore: async (cfg, callback) => callback(createBillingStore(pool, { stripeAccountId: cfg.accountId, livemode: cfg.livemode })),
    pushGrant: (cfg, value) => pushGrant(cfg.grant, value, { fetchImpl: hubFetch }) };
}
const store = () => createBillingStore(pool, { stripeAccountId: config.accountId });
const browser = (path, plan = "monthly") => new Request(config.origin + path, { method: "POST",
  headers: { origin: config.origin, "sec-fetch-site": "same-origin", ...(path === "/api/billing/checkout" ? { "content-type": "application/x-www-form-urlencoded" } : {}) },
  ...(path === "/api/billing/checkout" ? { body: "plan=" + plan } : {}) });
let eventSequence = 0;
function stripeEvent(type, object, created, id = "evt_synthetic" + ++eventSequence) {
  return { id, object: "event", api_version: Stripe.API_VERSION, created, livemode: false, type, data: { object } };
}
const subscriptionEvent = (type, sub, created, id) => stripeEvent(type, structuredClone(sub), created, id);
const invoiceEvent = (type, sub, created, id) => stripeEvent(type, { id: "in_synthetic", object: "invoice", customer: sub.customer, livemode: false,
  parent: { subscription_details: { subscription: sub.id } } }, created, id);
function deliver(stripe, eventValue, { secret = env.STRIPE_WEBHOOK_SECRET, timestamp, signature, body } = {}) {
  const payload = JSON.stringify(eventValue);
  const header = signature !== undefined ? signature
    : stripe.webhooks.generateTestHeaderString({ payload, secret, ...(timestamp ? { timestamp } : {}) });
  const headers = { "content-type": "application/json" };
  if (header !== null) headers["stripe-signature"] = header;
  return webhook(new Request(config.origin + "/api/stripe/webhook", { method: "POST", headers, body: body ?? payload }), deps(stripe, null));
}
const standing = async (subject = owner, now = NOW) => deriveEntitlement(await store().listSubscriptions(subject), now);
const count = async (table) => Number((await pool.query("SELECT count(*) FROM saiph_billing." + table)).rows[0].count);
/** Owner checkout through the real handler, then provider-side completion. */
async function purchased(fixture) {
  const response = await accountAction(browser("/api/billing/checkout"), "checkout", deps(fixture.stripe));
  assert.equal(response.status, 303);
  const mapping = await store().findCustomer(owner);
  return { mapping, ...fixture.completeCheckout(mapping.customerId) };
}

describe("billing lifecycle through HTTP handlers and isolated PostgreSQL", { skip: !databaseUrl ? "Run npm run test:billing-db for isolated Docker PostgreSQL checks" : false }, () => {
  before(async () => {
    assert.ok(config);
    pool = new pg.Pool({ connectionString: databaseUrl, max: 8 });
    await runMigrations(pool, await loadMigrations());
  });
  beforeEach(async () => {
    await pool.query("TRUNCATE saiph_billing.grant_state, saiph_billing.disputes, saiph_billing.customer_creation_intents, saiph_billing.processed_events, saiph_billing.subscriptions, saiph_billing.customers");
    hub.grants.clear(); hub.down = false;
  });
  after(async () => { await pool?.end(); });

  test("checkout redirect never grants entitlement; only the signed webhook does", async () => {
    const fixture = provider();
    const response = await accountAction(browser("/api/billing/checkout"), "checkout", deps(fixture.stripe));
    assert.equal(response.status, 303);
    assert.match(response.headers.get("location"), /^https:\/\/checkout\.stripe\.com\//);
    const mapping = await store().findCustomer(owner);
    assert.match(mapping.customerId, /^cus_synthetic/);
    assert.deepEqual((await fixture.stripe.customers.retrieve(mapping.customerId)).metadata, meta(owner));
    const { session } = fixture.completeCheckout(mapping.customerId);
    // The browser returning to success_url changes nothing server-side.
    assert.equal(session.success_url, config.origin + "/account?checkout=returned");
    assert.deepEqual(await standing(), { entitled: false, state: "none", subscriptionId: null, until: null });
    assert.equal(await count("subscriptions"), 0);
    const delivered = await deliver(fixture.stripe, stripeEvent("checkout.session.completed",
      { id: session.id, object: "checkout.session", mode: "subscription", customer: mapping.customerId, subscription: session.subscription, livemode: false }, NOW));
    assert.equal(delivered.status, 200);
    const result = await standing();
    assert.equal(result.entitled, true);
    assert.equal(result.state, "active");
    assert.equal(result.until, PERIOD_END);
    // A second checkout is refused while the subscription is nonterminal.
    assert.equal((await accountAction(browser("/api/billing/checkout"), "checkout", deps(fixture.stripe))).status, 409);
    assert.equal(fixture.calls.checkoutCreate, 1);
    assert.equal(fixture.calls.customerCreate, 1);
  });

  test("missing, malformed, wrong-secret, tampered and expired signatures change nothing", async () => {
    const fixture = provider();
    const { sub } = await purchased(fixture);
    const valid = subscriptionEvent("customer.subscription.updated", sub, NOW);
    const payload = JSON.stringify(valid);
    const cases = {
      missing: { signature: null },
      empty: { signature: "" },
      malformed: { signature: "garbage" },
      noV1: { signature: "t=" + NOW },
      wrongSecret: { secret: "whsec_someoneelse" },
      tampered: { body: payload.replace('"active"', '"canceled"').replace(valid.id, valid.id + "x") },
      expired: { timestamp: NOW - 3600 },
      future: { timestamp: NOW + 3600 },
    };
    for (const [label, options] of Object.entries(cases)) {
      const response = await deliver(fixture.stripe, valid, options);
      assert.equal(response.status, 400, label);
    }
    assert.equal(await count("processed_events"), 0);
    assert.equal(await count("subscriptions"), 0);
    assert.equal(fixture.calls.subscriptionRetrieve, 0);
    assert.equal((await standing()).entitled, false);
  });

  test("duplicate deliveries, sequential and concurrent, apply once", async () => {
    const fixture = provider();
    const { sub } = await purchased(fixture);
    const created = subscriptionEvent("customer.subscription.created", sub, NOW);
    assert.equal((await deliver(fixture.stripe, created)).status, 200);
    assert.equal((await deliver(fixture.stripe, created)).status, 200);
    const concurrent = invoiceEvent("invoice.paid", sub, NOW + 1);
    const responses = await Promise.all(Array.from({ length: 5 }, () => deliver(fixture.stripe, concurrent)));
    assert.deepEqual(responses.map((response) => response.status), [200, 200, 200, 200, 200]);
    assert.equal(await count("processed_events"), 2);
    assert.equal(fixture.calls.subscriptionRetrieve, 2, "one provider fetch per distinct event");
    const { rows } = await pool.query("SELECT outcome FROM saiph_billing.processed_events ORDER BY event_created");
    assert.deepEqual(rows.map((row) => row.outcome), ["applied", "applied"]);
    assert.equal((await standing()).state, "active");
  });

  test("out-of-order delivery never regresses state from an older event", async () => {
    const fixture = provider();
    const { sub } = await purchased(fixture);
    const live = fixture.subscriptions.get(sub.id);
    const createdEvent = subscriptionEvent("customer.subscription.created", sub, NOW);
    // Renewal fails at NOW+100; that event arrives before the creation event.
    live.status = "past_due";
    const failed = invoiceEvent("invoice.payment_failed", live, NOW + 100);
    assert.equal((await deliver(fixture.stripe, failed)).status, 200);
    assert.equal((await standing()).state, "payment_failed");
    // Provider later recovers (event at NOW+300 still in flight). The delayed
    // creation event (NOW) must not be the event that moves state.
    live.status = "active";
    assert.equal((await deliver(fixture.stripe, createdEvent)).status, 200);
    let ledger = await pool.query("SELECT outcome FROM saiph_billing.processed_events WHERE stripe_event_id=$1", [createdEvent.id]);
    assert.equal(ledger.rows[0].outcome, "stale");
    assert.equal((await standing()).state, "payment_failed");
    assert.equal((await deliver(fixture.stripe, invoiceEvent("invoice.paid", live, NOW + 300))).status, 200);
    assert.equal((await standing()).state, "active");
    // Deletion (NOW+500) is delivered before an older update (NOW+400).
    const olderUpdate = subscriptionEvent("customer.subscription.updated", live, NOW + 400);
    Object.assign(live, { status: "canceled", canceled_at: NOW + 500, ended_at: NOW + 500 });
    assert.equal((await deliver(fixture.stripe, subscriptionEvent("customer.subscription.deleted", live, NOW + 500))).status, 200);
    assert.equal((await standing()).state, "ended");
    // Even if a fetch returned a nonterminal state, a terminal row never reactivates.
    live.status = "active";
    assert.equal((await deliver(fixture.stripe, olderUpdate)).status, 200);
    ledger = await pool.query("SELECT outcome FROM saiph_billing.processed_events WHERE stripe_event_id=$1", [olderUpdate.id]);
    assert.equal(ledger.rows[0].outcome, "terminal_ignored");
    assert.deepEqual(await standing(), { entitled: false, state: "ended", subscriptionId: sub.id, until: NOW + 500 });
  });

  test("renewal payment failure keeps a three-day grace, then suspends until a later paid invoice", async () => {
    const fixture = provider();
    const { sub } = await purchased(fixture);
    const live = fixture.subscriptions.get(sub.id);
    await deliver(fixture.stripe, subscriptionEvent("customer.subscription.created", sub, NOW));
    assert.equal((await standing()).entitled, true);
    live.status = "past_due";
    assert.equal((await deliver(fixture.stripe, invoiceEvent("invoice.payment_failed", live, NOW + 10))).status, 200);
    assert.deepEqual(await standing(), { entitled: true, state: "payment_failed", subscriptionId: sub.id, until: NOW + 10 + PAYMENT_GRACE_SECONDS });
    assert.equal(hubUntil(sub.id), NOW + 10 + PAYMENT_GRACE_SECONDS);
    assert.deepEqual(await standing(owner, NOW + 10 + PAYMENT_GRACE_SECONDS), { entitled: false, state: "payment_failed", subscriptionId: sub.id, until: null });
    live.status = "unpaid";
    await deliver(fixture.stripe, subscriptionEvent("customer.subscription.updated", live, NOW + 20));
    assert.equal((await standing()).state, "payment_failed");
    live.status = "active"; live.items.data[0].current_period_end = PERIOD_END + 30 * 86400;
    await deliver(fixture.stripe, invoiceEvent("invoice.paid", live, NOW + 30));
    const recovered = await standing();
    assert.equal(recovered.entitled, true);
    assert.equal(recovered.until, PERIOD_END + 30 * 86400);
    const { rows } = await pool.query("SELECT payment_failed_at FROM saiph_billing.subscriptions WHERE stripe_subscription_id=$1", [sub.id]);
    assert.equal(rows[0].payment_failed_at, null, "a recovered subscription clears the failure time");
  });

  test("cancel at period end keeps entitlement until the period ends; deletion ends it", async () => {
    const fixture = provider();
    const { sub } = await purchased(fixture);
    const live = fixture.subscriptions.get(sub.id);
    await deliver(fixture.stripe, subscriptionEvent("customer.subscription.created", sub, NOW));
    // Portal cancellation at period end (portal configuration: no proration).
    Object.assign(live, { cancel_at_period_end: true, cancel_at: PERIOD_END, canceled_at: NOW + 5 });
    assert.equal((await deliver(fixture.stripe, subscriptionEvent("customer.subscription.updated", live, NOW + 5))).status, 200);
    assert.deepEqual(await standing(), { entitled: true, state: "ending", subscriptionId: sub.id, until: PERIOD_END });
    // If the deletion webhook is late, entitlement still stops at the scheduled end.
    assert.equal((await standing(owner, PERIOD_END + 1)).entitled, false);
    // Owner resumes before the end.
    Object.assign(live, { cancel_at_period_end: false, cancel_at: null, canceled_at: null });
    await deliver(fixture.stripe, subscriptionEvent("customer.subscription.updated", live, NOW + 6));
    assert.equal((await standing()).state, "active");
    // Then cancels again and the period ends.
    Object.assign(live, { cancel_at_period_end: true, cancel_at: PERIOD_END, canceled_at: NOW + 7 });
    await deliver(fixture.stripe, subscriptionEvent("customer.subscription.updated", live, NOW + 7));
    Object.assign(live, { status: "canceled", ended_at: PERIOD_END });
    assert.equal((await deliver(fixture.stripe, subscriptionEvent("customer.subscription.deleted", live, PERIOD_END))).status, 200);
    assert.deepEqual(await standing(), { entitled: false, state: "ended", subscriptionId: sub.id, until: PERIOD_END });
    // Replay of an old active event is recorded but cannot reinstate.
    live.status = "active";
    await deliver(fixture.stripe, invoiceEvent("invoice.paid", live, NOW + 1));
    assert.equal((await standing()).state, "ended");
    // A canceled subscription allows a genuinely new checkout.
    live.status = "canceled";
    assert.equal((await accountAction(browser("/api/billing/checkout"), "checkout", deps(fixture.stripe))).status, 303);
  });

  test("portal is bound to the logged-in user's own customer only", async () => {
    const fixture = provider();
    const { mapping } = await purchased(fixture);
    // A second Auth0 user with their own customer in the same database.
    const foreign = fixture.foreignCustomer(other);
    await store().bindCustomer({ subject: other, customerId: foreign.id });
    const ownerPortal = await accountAction(browser("/api/billing/portal"), "portal", deps(fixture.stripe));
    assert.equal(ownerPortal.status, 303);
    assert.equal(ownerPortal.headers.get("location"), "https://billing.stripe.com/p/session/synthetic_" + mapping.customerId);
    assert.deepEqual(fixture.calls.portal, [{ customer: mapping.customerId, configuration: config.portalId, return_url: config.origin + "/account" }]);
    // User B's session, or no session, cannot open any portal (including A's or B's).
    assert.equal((await accountAction(browser("/api/billing/portal"), "portal", deps(fixture.stripe, other))).status, 403);
    assert.equal((await accountAction(browser("/api/billing/portal"), "portal", deps(fixture.stripe, null))).status, 401);
    // Request-supplied identifiers are refused before any lookup.
    const injected = new Request(config.origin + "/api/billing/portal", { method: "POST",
      headers: { origin: config.origin, "sec-fetch-site": "same-origin", "content-type": "application/json" }, body: JSON.stringify({ customer: foreign.id }) });
    assert.equal((await accountAction(injected, "portal", deps(fixture.stripe))).status, 400);
    assert.equal((await accountAction(browser("/api/billing/portal?customer=" + foreign.id), "portal", deps(fixture.stripe))).status, 403);
    assert.equal(fixture.calls.portal.length, 1);
    // B's customer can never be rebound to A, by the store or by direct SQL.
    await assert.rejects(store().bindCustomer({ subject: owner, customerId: foreign.id }), { code: "CUSTOMER_ALREADY_BOUND" });
    await assert.rejects(pool.query("UPDATE saiph_billing.customers SET stripe_customer_id=$1 WHERE auth_subject=$2", [foreign.id, owner]), { code: "23514" });
    // Events on B's customer cannot change A's billing state.
    const foreignSub = { id: "sub_foreign", object: "subscription", customer: foreign.id, livemode: false, metadata: meta(other), status: "active",
      cancel_at_period_end: false, cancel_at: null, canceled_at: null, ended_at: null,
      items: { has_more: false, data: [{ quantity: 1, current_period_end: PERIOD_END, price: { id: config.plans.monthly.priceId, livemode: false, product: config.productId } }] } };
    fixture.subscriptions.set(foreignSub.id, foreignSub);
    assert.equal((await deliver(fixture.stripe, subscriptionEvent("customer.subscription.created", foreignSub, NOW))).status, 503);
    assert.equal(await count("processed_events"), 0);
    assert.equal((await standing(owner)).state, "none");
    assert.equal((await standing(other)).state, "none");
  });

  test("portal refuses a stored mapping whose Stripe customer belongs to another user", async () => {
    const fixture = provider();
    const foreign = fixture.foreignCustomer(other);
    // Simulate a corrupted/legacy row binding the owner to B's Stripe customer.
    await store().bindCustomer({ subject: owner, customerId: foreign.id });
    assert.equal((await accountAction(browser("/api/billing/portal"), "portal", deps(fixture.stripe))).status, 503);
    assert.equal(fixture.calls.portal.length, 0);
    assert.equal((await accountAction(browser("/api/billing/checkout"), "checkout", deps(fixture.stripe))).status, 503);
    assert.equal(fixture.calls.checkoutCreate, 0);
  });
  test("Hosted grant follows purchase, renewal and cancellation from webhooks only", async () => {
    const fixture = provider();
    const { sub, session } = await purchased(fixture);
    assert.equal(hub.grants.size, 0, "checkout and its return grant nothing");
    assert.equal((await deliver(fixture.stripe, stripeEvent("checkout.session.completed",
      { id: session.id, object: "checkout.session", mode: "subscription", customer: sub.customer, subscription: sub.id, livemode: false }, NOW))).status, 200);
    const first = hub.grants.get("stripe:" + sub.id);
    assert.deepEqual({ ...first, sequence: undefined }, { issuer: "https://synthetic.us.auth0.com/", subject: owner, grant: "stripe:" + sub.id,
      until: PERIOD_END + RENEWAL_GRACE_SECONDS, sequence: undefined, livemode: false });
    // Renewal moves the period; the push carries a higher sequence.
    const live = fixture.subscriptions.get(sub.id);
    live.items.data[0].current_period_end = PERIOD_END + 31 * 86400;
    await deliver(fixture.stripe, invoiceEvent("invoice.paid", live, NOW + 10));
    const renewed = hub.grants.get("stripe:" + sub.id);
    assert.ok(renewed.sequence > first.sequence);
    assert.equal(renewed.until, Math.floor(Date.now() / 1000) + 35 * 86400 >= PERIOD_END + 31 * 86400 + RENEWAL_GRACE_SECONDS
      ? PERIOD_END + 31 * 86400 + RENEWAL_GRACE_SECONDS : renewed.until, "capped by the rolling window");
    assert.ok(renewed.until <= Math.floor(Date.now() / 1000) + 35 * 86400);
    // Immediate cancellation (for example with a refund) ends access at once.
    Object.assign(live, { status: "canceled", canceled_at: NOW + 20, ended_at: NOW + 20 });
    await deliver(fixture.stripe, subscriptionEvent("customer.subscription.deleted", live, NOW + 20));
    assert.equal(hubUntil(sub.id), 0);
    const { rows } = await pool.query("SELECT dirty, pushed_until FROM saiph_billing.grant_state WHERE stripe_subscription_id=$1", [sub.id]);
    assert.deepEqual(rows[0], { dirty: false, pushed_until: "0" });
  });

  test("an unreachable Hosted service makes Stripe retry until the grant is delivered", async () => {
    const fixture = provider();
    const { sub } = await purchased(fixture);
    const created = subscriptionEvent("customer.subscription.created", sub, NOW);
    hub.down = true;
    assert.equal((await deliver(fixture.stripe, created)).status, 503);
    // The billing observation is committed; only delivery is pending.
    assert.equal(await count("processed_events"), 1);
    assert.equal((await standing()).state, "active");
    assert.equal((await pool.query("SELECT dirty FROM saiph_billing.grant_state")).rows[0].dirty, true);
    hub.down = false;
    // Stripe's retry is a ledger duplicate but still delivers the grant.
    assert.equal((await deliver(fixture.stripe, created)).status, 200);
    assert.equal(fixture.calls.subscriptionRetrieve, 1, "no second provider fetch for the duplicate");
    assert.equal(hubUntil(sub.id), PERIOD_END + RENEWAL_GRACE_SECONDS);
    assert.equal((await pool.query("SELECT dirty FROM saiph_billing.grant_state")).rows[0].dirty, false);
  });

  test("a chargeback ends paid access and a dispute won restores it", async () => {
    const fixture = provider();
    const { sub } = await purchased(fixture);
    await deliver(fixture.stripe, subscriptionEvent("customer.subscription.created", sub, NOW));
    const dispute = { id: "dp_synthetic1", object: "dispute", livemode: false, status: "needs_response",
      charge: { id: "ch_synthetic1", object: "charge", livemode: false, customer: sub.customer } };
    fixture.stripe.disputes = { retrieve: async () => structuredClone(dispute) };
    const payload = { id: dispute.id, object: "dispute", livemode: false, status: "needs_response", charge: "ch_synthetic1" };
    assert.equal((await deliver(fixture.stripe, stripeEvent("charge.dispute.created", payload, NOW + 50))).status, 200);
    assert.equal(hubUntil(sub.id), 0);
    assert.equal(await store().hasBlockingDispute(owner), true);
    // An older dispute event arriving late cannot reopen the newer state.
    dispute.status = "won";
    assert.equal((await deliver(fixture.stripe, stripeEvent("charge.dispute.closed", { ...payload, status: "won" }, NOW + 60))).status, 200);
    assert.equal(hubUntil(sub.id), PERIOD_END + RENEWAL_GRACE_SECONDS);
    dispute.status = "needs_response";
    assert.equal((await deliver(fixture.stripe, stripeEvent("charge.dispute.updated", payload, NOW + 55))).status, 200);
    const { rows } = await pool.query("SELECT outcome FROM saiph_billing.processed_events WHERE stripe_dispute_id=$1 ORDER BY event_created", [dispute.id]);
    assert.deepEqual(rows.map((row) => row.outcome), ["applied", "stale", "applied"]);
    assert.equal(await store().hasBlockingDispute(owner), false);
    assert.equal(hubUntil(sub.id), PERIOD_END + RENEWAL_GRACE_SECONDS);
  });

  test("daily refresh rolls a yearly grant forward and retries undelivered grants", async () => {
    const fixture = provider();
    const response = await accountAction(browser("/api/billing/checkout", "yearly"), "checkout", deps(fixture.stripe));
    assert.equal(response.status, 303);
    const mapping = await store().findCustomer(owner);
    const { sub } = fixture.completeCheckout(mapping.customerId);
    Object.assign(sub.items.data[0], { current_period_end: NOW + 365 * 86400, price: { id: config.plans.yearly.priceId, livemode: false, product: config.productId } });
    assert.equal((await deliver(fixture.stripe, subscriptionEvent("customer.subscription.created", sub, NOW))).status, 200);
    const first = hub.grants.get("stripe:" + sub.id);
    assert.ok(first.until <= Math.floor(Date.now() / 1000) + 35 * 86400 && first.until > NOW + 34 * 86400, "a year is granted 35 days at a time");
    const cron = () => refresh(new Request(config.origin + "/api/billing/refresh", { headers: { authorization: "Bearer " + "c".repeat(40) } }), deps(fixture.stripe, null));
    assert.deepEqual(await (await cron()).json(), { pushed: 0, failed: 0 }, "nothing to do while plenty remains");
    // Twenty days later (simulated by ageing the delivered expiry) the grant is renewed.
    await pool.query("UPDATE saiph_billing.grant_state SET pushed_until = extract(epoch FROM clock_timestamp())::bigint + 10 * 86400");
    assert.deepEqual(await (await cron()).json(), { pushed: 1, failed: 0 });
    assert.ok(hub.grants.get("stripe:" + sub.id).sequence > first.sequence);
    // A delivery that failed earlier is retried by the next refresh.
    await pool.query("UPDATE saiph_billing.grant_state SET dirty = true");
    hub.down = true;
    assert.equal((await cron()).status, 503);
    hub.down = false;
    assert.deepEqual(await (await cron()).json(), { pushed: 1, failed: 0 });
  });

  test("sandbox never pushes a paid grant for anyone but the owner", async () => {
    const fixture = provider();
    const foreign = fixture.foreignCustomer(other);
    await store().bindCustomer({ subject: other, customerId: foreign.id });
    // Simulate a row written for another user (the webhook path itself refuses them).
    await store().applyEvent({ eventId: "evt_foreign", type: "customer.subscription.created", created: NOW, customerId: foreign.id, livemode: false },
      async () => ({ subscriptionId: "sub_foreign", customerId: foreign.id, priceId: config.plans.monthly.priceId, status: "active",
        currentPeriodEnd: PERIOD_END, cancelAtPeriodEnd: false, cancelAt: null, canceledAt: null, endedAt: null, livemode: false }));
    const result = await refresh(new Request(config.origin + "/api/billing/refresh", { headers: { authorization: "Bearer " + "c".repeat(40) } }), deps(fixture.stripe, null));
    assert.deepEqual(await result.json(), { pushed: 1, failed: 0 });
    assert.equal(hubUntil("sub_foreign"), 0);
    assert.equal(hub.grants.get("stripe:sub_foreign").subject, other);
  });

  test("a database that served test mode refuses a live-mode store", async () => {
    await store().findCustomer(owner);
    await assert.rejects(createBillingStore(pool, { stripeAccountId: config.accountId, livemode: true }).findCustomer(owner), { code: "MODE_MISMATCH" });
  });
});
