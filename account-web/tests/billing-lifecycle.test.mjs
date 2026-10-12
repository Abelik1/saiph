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
import { ownerAction, webhook } from "../lib/billing/http.ts";
import { readBillingConfig, subjectReference } from "../lib/billing/policy.ts";

const databaseUrl = process.env.SAIPH_BILLING_TEST_DATABASE_URL;
if (databaseUrl) {
  const target = new URL(databaseUrl);
  if (target.hostname !== "127.0.0.1" || target.pathname !== "/saiph_billing_test") {
    throw new Error("Billing tests require the isolated loopback synthetic database");
  }
}
const env = {
  SAIPH_BILLING_MODE: "owner-sandbox", AUTH0_DOMAIN: "synthetic.us.auth0.com", AUTH0_CLIENT_ID: "syntheticclient",
  AUTH0_CLIENT_SECRET: "synthetic-not-real", AUTH0_SECRET: "cd".repeat(32), APP_BASE_URL: "https://account.saiph.test",
  SAIPH_OWNER_SUBJECT: "auth0|synthetic-owner", STRIPE_SECRET_KEY: "rk_test_synthetic123",
  STRIPE_WEBHOOK_SECRET: "whsec_synthetic123", STRIPE_EXPECTED_ACCOUNT_ID: "acct_synthetic",
  STRIPE_PRODUCT_ID: "prod_synthetic", STRIPE_PRICE_ID: "price_synthetic", STRIPE_PORTAL_CONFIGURATION_ID: "bpc_synthetic",
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
    prices: { retrieve: async () => ({ id: config.priceId, active: true, livemode: false, currency: "eur", unit_amount: 100,
      type: "recurring", recurring: { interval: "month", interval_count: 1 }, product: { id: config.productId, active: true, livemode: false } }) },
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
      listLineItems: async () => ({ has_more: false, data: [{ quantity: 1, price: { id: config.priceId, livemode: false, product: config.productId } }] }),
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
      items: { has_more: false, data: [{ quantity: 1, current_period_end: PERIOD_END, price: { id: config.priceId, livemode: false, product: config.productId } }] } };
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

function deps(stripe, sub = owner) {
  return { env, getSession: async () => (sub ? { user: { sub } } : null), createStripe: () => stripe,
    withStore: async (account, callback) => callback(createBillingStore(pool, { stripeAccountId: account })) };
}
const store = () => createBillingStore(pool, { stripeAccountId: config.accountId });
const browser = (path) => new Request(config.origin + path, { method: "POST", headers: { origin: config.origin, "sec-fetch-site": "same-origin" } });
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
  const response = await ownerAction(browser("/api/billing/checkout"), "checkout", deps(fixture.stripe));
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
    await pool.query("TRUNCATE saiph_billing.customer_creation_intents, saiph_billing.processed_events, saiph_billing.subscriptions, saiph_billing.customers");
  });
  after(async () => { await pool?.end(); });

  test("checkout redirect never grants entitlement; only the signed webhook does", async () => {
    const fixture = provider();
    const response = await ownerAction(browser("/api/billing/checkout"), "checkout", deps(fixture.stripe));
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
    assert.equal((await ownerAction(browser("/api/billing/checkout"), "checkout", deps(fixture.stripe))).status, 503);
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

  test("renewal payment failure suspends entitlement until a later paid invoice", async () => {
    const fixture = provider();
    const { sub } = await purchased(fixture);
    const live = fixture.subscriptions.get(sub.id);
    await deliver(fixture.stripe, subscriptionEvent("customer.subscription.created", sub, NOW));
    assert.equal((await standing()).entitled, true);
    live.status = "past_due";
    assert.equal((await deliver(fixture.stripe, invoiceEvent("invoice.payment_failed", live, NOW + 10))).status, 200);
    assert.deepEqual(await standing(), { entitled: false, state: "payment_failed", subscriptionId: sub.id, until: null });
    live.status = "unpaid";
    await deliver(fixture.stripe, subscriptionEvent("customer.subscription.updated", live, NOW + 20));
    assert.equal((await standing()).state, "payment_failed");
    live.status = "active"; live.items.data[0].current_period_end = PERIOD_END + 30 * 86400;
    await deliver(fixture.stripe, invoiceEvent("invoice.paid", live, NOW + 30));
    const recovered = await standing();
    assert.equal(recovered.entitled, true);
    assert.equal(recovered.until, PERIOD_END + 30 * 86400);
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
    assert.equal((await ownerAction(browser("/api/billing/checkout"), "checkout", deps(fixture.stripe))).status, 303);
  });

  test("portal is bound to the logged-in user's own customer only", async () => {
    const fixture = provider();
    const { mapping } = await purchased(fixture);
    // A second Auth0 user with their own customer in the same database.
    const foreign = fixture.foreignCustomer(other);
    await store().bindCustomer({ subject: other, customerId: foreign.id });
    const ownerPortal = await ownerAction(browser("/api/billing/portal"), "portal", deps(fixture.stripe));
    assert.equal(ownerPortal.status, 303);
    assert.equal(ownerPortal.headers.get("location"), "https://billing.stripe.com/p/session/synthetic_" + mapping.customerId);
    assert.deepEqual(fixture.calls.portal, [{ customer: mapping.customerId, configuration: config.portalId, return_url: config.origin + "/account" }]);
    // User B's session, or no session, cannot open any portal (including A's or B's).
    assert.equal((await ownerAction(browser("/api/billing/portal"), "portal", deps(fixture.stripe, other))).status, 403);
    assert.equal((await ownerAction(browser("/api/billing/portal"), "portal", deps(fixture.stripe, null))).status, 401);
    // Request-supplied identifiers are refused before any lookup.
    const injected = new Request(config.origin + "/api/billing/portal", { method: "POST",
      headers: { origin: config.origin, "sec-fetch-site": "same-origin", "content-type": "application/json" }, body: JSON.stringify({ customer: foreign.id }) });
    assert.equal((await ownerAction(injected, "portal", deps(fixture.stripe))).status, 400);
    assert.equal((await ownerAction(browser("/api/billing/portal?customer=" + foreign.id), "portal", deps(fixture.stripe))).status, 403);
    assert.equal(fixture.calls.portal.length, 1);
    // B's customer can never be rebound to A, by the store or by direct SQL.
    await assert.rejects(store().bindCustomer({ subject: owner, customerId: foreign.id }), { code: "CUSTOMER_ALREADY_BOUND" });
    await assert.rejects(pool.query("UPDATE saiph_billing.customers SET stripe_customer_id=$1 WHERE auth_subject=$2", [foreign.id, owner]), { code: "23514" });
    // Events on B's customer cannot change A's billing state.
    const foreignSub = { id: "sub_foreign", object: "subscription", customer: foreign.id, livemode: false, metadata: meta(other), status: "active",
      cancel_at_period_end: false, cancel_at: null, canceled_at: null, ended_at: null,
      items: { has_more: false, data: [{ quantity: 1, current_period_end: PERIOD_END, price: { id: config.priceId, livemode: false, product: config.productId } }] } };
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
    assert.equal((await ownerAction(browser("/api/billing/portal"), "portal", deps(fixture.stripe))).status, 503);
    assert.equal(fixture.calls.portal.length, 0);
    assert.equal((await ownerAction(browser("/api/billing/checkout"), "checkout", deps(fixture.stripe))).status, 503);
    assert.equal(fixture.calls.checkoutCreate, 0);
  });
});
