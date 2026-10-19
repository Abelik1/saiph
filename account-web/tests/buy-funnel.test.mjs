// SPDX-License-Identifier: AGPL-3.0-or-later
// Buy now → sign-in → Checkout, the price test and funnel measurement
// (docs/LANDING_CONVERSION.md). Synthetic fixtures only: no Stripe, Auth0,
// Neon or Google request is made.
import {test} from "node:test";
import assert from "node:assert/strict";
import {generateKeyPairSync} from "node:crypto";
import Stripe from "stripe";
import {accountAction, purchaseFrom, webhook} from "../lib/billing/http.ts";
import {planFor, planForPrice, readBillingConfig, subjectReference} from "../lib/billing/policy.ts";
import {checkPriceTest, euros, resolveOffer} from "../lib/billing/price-test.mjs";
import {afterSignIn, buyPath, parseBuyTarget} from "../lib/buy.mjs";
import {measurementBody, readConsent, readGaConfig, sendEvent} from "../lib/ga.mjs";
import {contentSecurityPolicy} from "../lib/security.mjs";

const origin = "https://account.saiph.test";
const grantKey = generateKeyPairSync("ed25519").privateKey.export({format: "der", type: "pkcs8"}).toString("base64url");
const priceTest = {id: "2026-11-price", variants: {b: {monthly: {price: "price_testBmonthly", amount: 799}, yearly: {price: "price_testByearly", amount: 6999}}}};
const env = {SAIPH_BILLING_MODE: "owner-sandbox", AUTH0_DOMAIN: "synthetic.us.auth0.com", AUTH0_CLIENT_ID: "syntheticclient",
  AUTH0_CLIENT_SECRET: "synthetic-not-real", AUTH0_SECRET: "ab".repeat(32), APP_BASE_URL: origin, SAIPH_OWNER_SUBJECT: "synthetic|owner",
  STRIPE_SECRET_KEY: "rk_test_synthetic123", STRIPE_WEBHOOK_SECRET: "whsec_synthetic123", STRIPE_EXPECTED_ACCOUNT_ID: "acct_synthetic",
  STRIPE_PRODUCT_ID: "prod_synthetic", STRIPE_PRICE_ID: "price_monthly", STRIPE_YEARLY_PRICE_ID: "price_yearly",
  STRIPE_PORTAL_CONFIGURATION_ID: "bpc_synthetic", DATABASE_URL: "postgresql://synthetic:synthetic@synthetic-pooler.eu-west-2.aws.neon.tech/synthetic?sslmode=require",
  SAIPH_HOSTED_API_URL: "https://api.saiph.test", SAIPH_BILLING_GRANT_KEY: grantKey, SAIPH_BILLING_GRANT_KEY_ID: "test-1",
  SAIPH_PRICE_TEST: JSON.stringify(priceTest), GA4_MEASUREMENT_ID: "G-SYNTHETIC1", GA4_API_SECRET: "synthetic_secret"};
const config = readBillingConfig(env);
assert.ok(config);
const NOW = Math.floor(Date.now() / 1000);
const consentCookie = `saiph_consent=v1.granted.${NOW - 60}; _ga=GA1.1.123456789.1790000000; other=x`;

test("only this site's /buy/<plan> pages survive sign-in", () => {
  assert.deepEqual(parseBuyTarget("/buy/monthly", origin), {plan: "monthly", offer: null});
  assert.deepEqual(parseBuyTarget(origin + "/buy/yearly?offer=b", origin), {plan: "yearly", offer: "b"});
  for (const bad of ["/account", "/buy/lifetime", "/buy/monthly/start", "/buy/monthly?offer=z", "/buy/monthly?offer=b&x=1",
    "/buy/monthly?returnTo=https://evil.test", "https://evil.test/buy/monthly", "//evil.test/buy/monthly", "/buy/monthly#x",
    "https://user:pw@account.saiph.test/buy/monthly", 42, undefined]) assert.equal(parseBuyTarget(bad, origin), null, String(bad));
  assert.equal(afterSignIn("/buy/yearly?offer=b", origin).href, origin + "/buy/yearly?offer=b&signed_in=1");
  // Ordinary sign-ins, and anything unexpected, still land on the account page.
  for (const other of [undefined, "/account", "https://evil.test/buy/monthly"]) assert.equal(afterSignIn(other, origin).href, origin + "/account");
  assert.equal(buyPath("monthly", null), "/buy/monthly");
});

test("a price test maps variants to configured Stripe prices and never turns billing off", () => {
  assert.deepEqual(config.priceTest.variants.b.monthly, {priceId: "price_testBmonthly", amount: 799});
  assert.equal(planFor(config, "monthly", "b").priceId, "price_testBmonthly");
  assert.equal(planFor(config, "yearly", "z").priceId, "price_yearly", "unknown variants get the standard price");
  assert.deepEqual(planForPrice(config, "price_testByearly"), {key: "yearly", priceId: "price_testByearly", amount: 6999, interval: "year", variant: "b"});
  assert.equal(planForPrice(config, "price_monthly").variant, "a");
  assert.deepEqual(resolveOffer(config.priceTest, "b"), {test: "2026-11-price", variant: "b"});
  assert.deepEqual(resolveOffer(config.priceTest, "a"), {test: "2026-11-price", variant: "a"});
  assert.deepEqual(resolveOffer(config.priceTest, "c"), {test: null, variant: "a"});
  assert.deepEqual(resolveOffer(null, "b"), {test: null, variant: "a"});
  assert.equal(euros(6999), "€69.99");
  const bad = [
    "not json", "[]", JSON.stringify({id: "x"}), JSON.stringify({...priceTest, extra: 1}), JSON.stringify({...priceTest, id: "Bad Id"}),
    JSON.stringify({id: "t", variants: {a: priceTest.variants.b}}), JSON.stringify({id: "t", variants: {}}),
    JSON.stringify({id: "t", variants: {b: {monthly: {price: "price_monthly", amount: 799}, yearly: priceTest.variants.b.yearly}}}),
    JSON.stringify({id: "t", variants: {b: {monthly: {price: "price_x", amount: 7.99}, yearly: priceTest.variants.b.yearly}}}),
    JSON.stringify({id: "t", variants: {b: {monthly: {price: "sk_live_x", amount: 799}, yearly: priceTest.variants.b.yearly}}}),
  ];
  for (const value of bad) {
    assert.equal(checkPriceTest({SAIPH_PRICE_TEST: value}, ["price_monthly", "price_yearly"]).test, null, value);
    const billing = readBillingConfig({...env, SAIPH_PRICE_TEST: value});
    assert.ok(billing, "a rejected price test leaves billing on");
    assert.equal(billing.priceTest, null);
  }
  assert.equal(readBillingConfig({...env, SAIPH_PRICE_TEST: undefined}).priceTest, null, "off by default");
});

test("analytics needs an explicit, recent Accept and reads only Google's client ID", () => {
  assert.deepEqual(readConsent(consentCookie, NOW), {granted: true, clientId: "123456789.1790000000"});
  assert.deepEqual(readConsent(`saiph_consent=v1.denied.${NOW}; _ga=GA1.1.123456789.1790000000`, NOW), {granted: false, clientId: null});
  assert.deepEqual(readConsent(`saiph_consent=v1.granted.${NOW - 200 * 86400}; _ga=GA1.1.1.1790000000`, NOW).granted, false, "six months");
  assert.deepEqual(readConsent(`_ga=GA1.1.123456789.1790000000`, NOW).granted, false);
  assert.deepEqual(readConsent(`saiph_consent=v1.granted.${NOW}; _ga=evil`, NOW), {granted: true, clientId: null});
  assert.deepEqual(readConsent(undefined, NOW).granted, false);
  assert.equal(readGaConfig({}), null);
  assert.equal(readGaConfig({GA4_MEASUREMENT_ID: "UA-1"}), null);
  assert.deepEqual(readGaConfig({GA4_MEASUREMENT_ID: "G-ABC123", GA4_API_SECRET: "x"}), {measurementId: "G-ABC123", apiSecret: null});
});

test("Measurement Protocol events carry a fixed list of fields and deny ad signals", async () => {
  const body = measurementBody("123.1790000000", "purchase", {plan: "yearly", value: 89.99, currency: "EUR", transaction_id: "abc", email: "x@y.z"});
  assert.deepEqual(body.consent, {ad_user_data: "DENIED", ad_personalization: "DENIED"});
  assert.deepEqual(Object.keys(body.events[0].params).sort(), ["currency", "engagement_time_msec", "plan", "transaction_id", "value"]);
  assert.throws(() => measurementBody("123.1790000000", "page_view", {}));
  assert.throws(() => measurementBody("not an id", "purchase", {}));
  assert.throws(() => measurementBody("123.1790000000", "purchase", {plan: "x y@z"}));
  const calls = [];
  const record = async (url, init) => { calls.push({url, init}); return new Response(null, {status: 204}); };
  assert.equal(await sendEvent(readGaConfig(env), "123.1790000000", "purchase", {plan: "monthly"}, record), true);
  assert.match(calls[0].url, /^https:\/\/region1\.google-analytics\.com\/mp\/collect\?measurement_id=G-SYNTHETIC1&api_secret=/);
  assert.equal(await sendEvent({measurementId: "G-SYNTHETIC1", apiSecret: null}, "123.1790000000", "purchase", {}, record), false);
  assert.equal(await sendEvent(readGaConfig(env), null, "purchase", {}, record), false);
  assert.equal(await sendEvent(readGaConfig(env), "123.1790000000", "purchase", {}, async () => { throw new Error("down"); }), false);
  assert.equal(calls.length, 1);
});

test("Google domains reach the account CSP only when asked for", () => {
  const plain = contentSecurityPolicy("a".repeat(24));
  assert.doesNotMatch(plain, /google/);
  const buy = contentSecurityPolicy("a".repeat(24), false, {analytics: true});
  assert.match(buy, /connect-src 'self' https:\/\/\*\.google-analytics\.com/);
  assert.match(buy, /img-src 'self' data: https:\/\/\*\.google-analytics\.com/);
  assert.match(buy, /script-src 'self' 'nonce-a+' 'strict-dynamic';/, "the tag loads through the nonce, no host allow-list");
});

function fixture(deps = {}) {
  const meta = {saiph_billing: "owner-sandbox-v1", saiph_subject_ref: subjectReference(config.ownerSubject), saiph_account: config.accountId};
  const amounts = {price_monthly: [999, "month"], price_yearly: [8999, "year"], price_testBmonthly: [799, "month"], price_testByearly: [6999, "year"]};
  const calls = {checkout: [], counts: [], analytics: []};
  const customer = {id: "cus_synthetic", livemode: false, metadata: meta};
  let mapping = null;
  const store = {trialFacts: async () => ({stored: null}), findCustomer: async () => mapping,
    getOrCreateCustomer: async (subject, create) => (mapping ??= {subject, customerId: await create()}),
    withCustomer: async (subject, callback) => callback(mapping),
    countFunnel: async (count) => { calls.counts.push(count); },
    applyEvent: async (_event, load) => ({outcome: deps.outcome ?? "applied", snapshot: await load(mapping)}),
    grantCandidates: async () => [], trialGrantCandidates: async () => []};
  const sub = {id: "sub_synthetic", customer: customer.id, livemode: false, metadata: meta, status: "active", cancel_at_period_end: false, canceled_at: null, ended_at: null,
    items: {has_more: false, data: [{quantity: 1, current_period_end: 2000000000, price: {id: "price_testByearly", livemode: false, product: config.productId}}]}};
  const sdk = new Stripe(env.STRIPE_SECRET_KEY);
  const stripe = {webhooks: sdk.webhooks,
    prices: {retrieve: async (id) => ({id, active: true, livemode: false, currency: "eur", unit_amount: amounts[id][0], type: "recurring",
      recurring: {interval: amounts[id][1], interval_count: 1}, product: {id: config.productId, active: true, livemode: false}})},
    customers: {create: async (params) => ({...customer, metadata: params.metadata}), retrieve: async () => customer},
    subscriptions: {list: async () => ({has_more: false, data: []}), retrieve: async () => sub},
    checkout: {sessions: {list: async () => ({has_more: false, data: []}),
      create: async (params, options) => { calls.checkout.push({params, options}); return {...params, id: "cs_test_1", livemode: false, url: "https://checkout.stripe.com/c/pay/cs_test_1"}; }}}};
  return {calls, stripe, store, setMapping: (value) => { mapping = value; },
    deps: {env, getSession: async () => ({user: {sub: config.ownerSubject}}), createStripe: () => stripe, pushGrant: async () => true,
      withStore: async (_cfg, callback) => callback(store),
      analyticsFetch: async (url, init) => { calls.analytics.push(JSON.parse(init.body)); return new Response(null, {status: 204}); }}};
}
const post = (body, cookie) => new Request(origin + "/api/billing/checkout", {method: "POST", body,
  headers: {origin, "sec-fetch-site": "same-origin", "content-type": "application/x-www-form-urlencoded", ...(cookie ? {cookie} : {})}});

test("Checkout charges the variant shown, counts the start and reports it only with consent", async () => {
  const f = fixture();
  const response = await accountAction(post("plan=yearly&offer=b", consentCookie), "checkout", f.deps);
  assert.equal(response.status, 303);
  const {params, options} = f.calls.checkout[0];
  assert.equal(params.line_items[0].price, "price_testByearly");
  assert.deepEqual(params.metadata, {saiph_billing: "owner-sandbox-v1", saiph_subject_ref: subjectReference(config.ownerSubject),
    saiph_account: config.accountId, saiph_plan: "yearly", saiph_price_test: "2026-11-price", saiph_variant: "b", saiph_ga: "123456789.1790000000"});
  assert.equal(params.subscription_data.metadata.saiph_ga, undefined, "the subscription never gets analytics IDs");
  assert.match(options.idempotencyKey, /^saiph-checkout-v4-/);
  assert.deepEqual(f.calls.counts, [{step: "checkout_started", plan: "yearly", test: "2026-11-price", variant: "b"}]);
  assert.equal(f.calls.analytics.length, 1);
  assert.equal(f.calls.analytics[0].client_id, "123456789.1790000000");
  assert.equal(f.calls.analytics[0].events[0].name, "begin_checkout");
  assert.deepEqual(f.calls.analytics[0].events[0].params, {engagement_time_msec: 1, plan: "yearly", currency: "EUR", price_test: "2026-11-price", price_variant: "b"});
  assert.doesNotMatch(JSON.stringify(f.calls.analytics), /synthetic\|owner|cus_|cs_test|sub_/);

  // No Accept: same checkout, no analytics ID anywhere and nothing sent to Google.
  const g = fixture();
  assert.equal((await accountAction(post("plan=monthly"), "checkout", g.deps)).status, 303);
  assert.equal(g.calls.checkout[0].params.line_items[0].price, "price_monthly");
  assert.deepEqual(g.calls.checkout[0].params.metadata.saiph_ga, undefined);
  assert.equal(g.calls.checkout[0].params.metadata.saiph_variant, undefined);
  assert.equal(g.calls.analytics.length, 0);
  assert.deepEqual(g.calls.counts, [{step: "checkout_started", plan: "monthly", test: null, variant: "a"}]);

  // Unknown variants get the standard price, as the Buy page shows them.
  const h = fixture();
  assert.equal((await accountAction(post("plan=monthly&offer=d", `saiph_consent=v1.denied.${NOW}`), "checkout", h.deps)).status, 303);
  assert.equal(h.calls.checkout[0].params.line_items[0].price, "price_monthly");

  // A broken counter never blocks paying.
  const k = fixture();
  k.store.countFunnel = async () => { throw new Error("no migration 0006"); };
  assert.equal((await accountAction(post("plan=monthly"), "checkout", k.deps)).status, 303);
});

test("Checkout still accepts exactly plan, then an optional offer", async () => {
  for (const body of ["offer=b&plan=monthly", "plan=monthly&offer=z", "plan=monthly&offer=b&x=1", "plan=monthly&price=price_x", "offer=b"]) {
    const f = fixture();
    assert.equal((await accountAction(post(body), "checkout", f.deps)).status, 400, body);
    assert.equal(f.calls.checkout.length, 0);
  }
});

function completed(metadata, extra = {}) {
  return {id: "evt_synthetic", object: "event", api_version: Stripe.API_VERSION, created: NOW, livemode: false, type: "checkout.session.completed",
    data: {object: {id: "cs_test_1", object: "checkout.session", mode: "subscription", status: "complete", livemode: false, customer: "cus_synthetic",
      subscription: "sub_synthetic", amount_total: 6999, metadata, ...extra}}};
}

test("a purchase is counted once, from the verified webhook, and reported only with an analytics ID", async () => {
  const meta = {saiph_plan: "yearly", saiph_price_test: "2026-11-price", saiph_variant: "b", saiph_ga: "123456789.1790000000"};
  const purchase = purchaseFrom(completed(meta), config, {outcome: "applied"});
  assert.equal(purchase.plan, "yearly");
  assert.equal(purchase.variant, "b");
  assert.equal(purchase.value, 69.99);
  assert.match(purchase.transactionId, /^[a-f0-9]{32}$/);
  assert.equal(purchaseFrom(completed(meta), config, {outcome: "duplicate"}), null, "a Stripe retry is not a second purchase");
  assert.equal(purchaseFrom(completed(meta, {status: "open"}), config, {outcome: "applied"}), null);
  assert.equal(purchaseFrom(completed({}), config, {outcome: "applied"}), null);
  assert.equal(purchaseFrom({...completed(meta), type: "invoice.paid"}, config, {outcome: "applied"}), null);
  assert.deepEqual(purchaseFrom(completed({...meta, saiph_price_test: "old-test"}), config, {outcome: "applied"}).variant, "a");

  const f = fixture();
  f.setMapping({subject: config.ownerSubject, customerId: "cus_synthetic"});
  const payload = JSON.stringify(completed(meta));
  const signature = f.stripe.webhooks.generateTestHeaderString({payload, secret: env.STRIPE_WEBHOOK_SECRET});
  const response = await webhook(new Request(origin + "/api/stripe/webhook", {method: "POST", body: payload,
    headers: {"content-type": "application/json", "stripe-signature": signature}}), f.deps);
  assert.equal(response.status, 200);
  assert.deepEqual(f.calls.counts, [{step: "purchase", plan: "yearly", test: "2026-11-price", variant: "b"}]);
  assert.equal(f.calls.analytics.length, 1);
  assert.equal(f.calls.analytics[0].events[0].name, "purchase");
  assert.equal(f.calls.analytics[0].events[0].params.value, 69.99);
  assert.doesNotMatch(JSON.stringify(f.calls.analytics), /cs_test|cus_|sub_|synthetic\|owner/);

  // Without the analytics ID the purchase is still counted, and nothing goes to Google.
  const g = fixture({outcome: "applied"});
  g.setMapping({subject: config.ownerSubject, customerId: "cus_synthetic"});
  const plain = JSON.stringify(completed({saiph_plan: "monthly"}));
  await webhook(new Request(origin + "/api/stripe/webhook", {method: "POST", body: plain, headers: {"content-type": "application/json",
    "stripe-signature": g.stripe.webhooks.generateTestHeaderString({payload: plain, secret: env.STRIPE_WEBHOOK_SECRET})}}), g.deps);
  assert.deepEqual(g.calls.counts, [{step: "purchase", plan: "monthly", test: null, variant: "a"}]);
  assert.equal(g.calls.analytics.length, 0);
});

test("Start your free trial returns to /trial only, and a real start is counted once", async () => {
  assert.deepEqual(parseBuyTarget("/trial", origin), {plan: "trial", offer: null});
  assert.equal(parseBuyTarget("/trial?days=365", origin), null);
  assert.equal(parseBuyTarget("/trial/start", origin), null);
  assert.equal(afterSignIn("/trial", origin).href, origin + "/trial?signed_in=1");
  const {trialAction} = await import("../lib/billing/http.ts");
  const trialEnv = {...env, SAIPH_TRIAL_SECRET: "t".repeat(40), SAIPH_TRIAL_DAYS: "30"};
  const make = (existing) => {
    const counts = [], analytics = [];
    const store = {countFunnel: async (c) => { counts.push(c); }, grantCandidates: async () => [],
      trialGrantCandidates: async () => [], withTrialGrant: async (_s, push) => ({until: await push({}, 1)}),
      startTrial: async ({subject, now, days}) => ({outcome: existing ? "exists" : "started",
        trial: {subject, ref: "a".repeat(32), startedAt: existing ? now - 86400 : now, endsAt: now + days * 86400, dirty: false, pushedUntil: null}})};
    const deps = {env: trialEnv, createStripe: () => ({}), pushGrant: async () => true, withStore: async (_c, callback) => callback(store),
      getSession: async () => ({user: {sub: config.ownerSubject, trialKey: "e".repeat(64)}}),
      analyticsFetch: async (_url, init) => { analytics.push(JSON.parse(init.body)); return new Response(null, {status: 204}); }};
    return {counts, analytics, deps};
  };
  const start = (cookie) => new Request(origin + "/api/billing/trial", {method: "POST", body: "trial=start",
    headers: {origin, "sec-fetch-site": "same-origin", "content-type": "application/x-www-form-urlencoded", ...(cookie ? {cookie} : {})}});
  const fresh = make(false);
  assert.equal((await trialAction(start(consentCookie), fresh.deps)).status, 303);
  assert.deepEqual(fresh.counts, [{step: "trial_started", plan: "trial", test: null, variant: "a"}]);
  assert.equal(fresh.analytics.length, 1);
  assert.equal(fresh.analytics[0].events[0].name, "trial_start");
  assert.deepEqual(fresh.analytics[0].events[0].params, {engagement_time_msec: 1, plan: "trial"});
  const again = make(true);
  assert.equal((await trialAction(start(consentCookie), again.deps)).status, 303);
  assert.deepEqual(again.counts, [], "pressing again is not a second trial");
  assert.equal(again.analytics.length, 0);
  const declined = make(false);
  await trialAction(start(`saiph_consent=v1.denied.${NOW}; _ga=GA1.1.123456789.1790000000`), declined.deps);
  assert.equal(declined.counts.length, 1);
  assert.equal(declined.analytics.length, 0, "nothing to Google without Accept");
});
