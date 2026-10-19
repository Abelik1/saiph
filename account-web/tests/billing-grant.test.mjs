// SPDX-License-Identifier: AGPL-3.0-or-later
// Paid grant rules, signing format and delivery (docs/PAID_HOSTED.md). Synthetic only.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createPublicKey, generateKeyPairSync, verify } from "node:crypto";
import { disputeBlocks, grantUntil, needsPush, GRANT_ROLL_SECONDS, REFRESH_BEFORE_SECONDS } from "../lib/billing/grant.mjs";
import { GRANT_CONTEXT, grantKey, pushGrant, signedGrant } from "../lib/billing/grant-push.mjs";
import { syncGrants } from "../lib/billing/grant-sync.mjs";
import { PAYMENT_GRACE_SECONDS, RENEWAL_GRACE_SECONDS } from "../lib/billing/entitlement.mjs";

const now = 1_800_000_000;
const row = (status, overrides = {}) => ({ subscriptionId: "sub_synthetic", status, currentPeriodEnd: now + 20 * 86400,
  cancelAtPeriodEnd: false, cancelAt: null, canceledAt: null, endedAt: null, paymentFailedAt: null, ...overrides });

test("a renewing monthly subscription is granted through its period plus the renewal grace", () => {
  assert.equal(grantUntil(row("active"), false, now), now + 20 * 86400 + RENEWAL_GRACE_SECONDS);
});

test("a yearly subscription is granted a rolling window, never the whole year in one push", () => {
  assert.equal(grantUntil(row("active", { currentPeriodEnd: now + 365 * 86400 }), false, now), now + GRANT_ROLL_SECONDS);
  assert.ok(GRANT_ROLL_SECONDS < 45 * 86400, "inside the Cloud service's horizon");
});

test("scheduled cancellation ends exactly at the scheduled time", () => {
  assert.equal(grantUntil(row("active", { cancelAtPeriodEnd: true }), false, now), now + 20 * 86400);
  assert.equal(grantUntil(row("active", { cancelAt: now + 86400 }), false, now), now + 86400);
});

test("a failed renewal keeps access for three days from the first failure, then ends it", () => {
  const failed = row("past_due", { paymentFailedAt: now - 86400 });
  assert.equal(grantUntil(failed, false, now), now - 86400 + PAYMENT_GRACE_SECONDS);
  assert.equal(PAYMENT_GRACE_SECONDS, 3 * 86400);
  assert.equal(grantUntil(failed, false, now - 86400 + PAYMENT_GRACE_SECONDS), 0);
  assert.equal(grantUntil(row("past_due"), false, now), 0, "no recorded failure time fails closed");
  assert.equal(grantUntil(row("unpaid", { paymentFailedAt: now }), false, now), 0);
});

test("ended, incomplete, paused and disputed subscriptions grant nothing", () => {
  for (const status of ["canceled", "incomplete_expired", "incomplete", "paused", "invented"]) assert.equal(grantUntil(row(status), false, now), 0, status);
  assert.equal(grantUntil(row("active"), true, now), 0);
  assert.equal(grantUntil(row("past_due", { paymentFailedAt: now }), true, now), 0);
});

test("open and lost disputes block; inquiries, won and unknown-safe statuses are explicit", () => {
  for (const status of ["needs_response", "under_review", "lost", "something_new"]) assert.equal(disputeBlocks(status), true, status);
  for (const status of ["warning_needs_response", "warning_under_review", "warning_closed", "won", "prevented"]) assert.equal(disputeBlocks(status), false, status);
});

test("pushes happen when undelivered, when shortening, and when a rolling grant runs low", () => {
  assert.equal(needsPush({ dirty: true, pushedUntil: now + 30 * 86400 }, now + 30 * 86400, now), true);
  assert.equal(needsPush({ dirty: false, pushedUntil: null }, 0, now), true);
  assert.equal(needsPush({ dirty: false, pushedUntil: now + 20 * 86400 }, now + 20 * 86400, now), false, "unchanged");
  assert.equal(needsPush({ dirty: false, pushedUntil: now + 30 * 86400 }, now + 35 * 86400, now), false, "plenty left");
  assert.equal(needsPush({ dirty: false, pushedUntil: now + REFRESH_BEFORE_SECONDS - 1 }, now + 35 * 86400, now), true, "roll forward");
  assert.equal(needsPush({ dirty: false, pushedUntil: now + 86400 }, 0, now), true, "shorten a running grant");
  assert.equal(needsPush({ dirty: false, pushedUntil: now - 1 }, 0, now), false, "already expired at the service");
});

test("the signed format matches the Cloud service's verifier (shared synthetic vector)", () => {
  // Mirrors hub/tests/test_hosted_billing.py; public key and signature only.
  const publicKey = createPublicKey({ key: { kty: "OKP", crv: "Ed25519", x: "6CcCelNP-UKWH3Wu9MYqSrEKEUHWx9i_N5VsLGNA4Ko" }, format: "jwk" });
  const body = '{"issuer":"https://synthetic.eu.auth0.com/","subject":"auth0|vector","grant":"stripe:sub_vector1","until":1800003600,"sequence":7,"livemode":false}';
  const signature = Buffer.from("0MvIjdn3EDTLi0yD1awAFg6GHZI1-G5EY0nmv9h75DP9NJg4q6KwU6L_Cfgq2ZrYlURT8R5sjddttb1UY2jDAg", "base64url");
  assert.equal(verify(null, Buffer.from(GRANT_CONTEXT + "1800000000." + body), publicKey, signature), true);
  // signedGrant produces the same body bytes and header layout for this value.
  const { privateKey } = generateKeyPairSync("ed25519");
  const value = { issuer: "https://synthetic.eu.auth0.com/", subject: "auth0|vector", grant: "stripe:sub_vector1", until: 1800003600, sequence: 7, livemode: false };
  const signed = signedGrant({ keyId: "vector", key: privateKey }, { ...value, extra: "ignored" }, 1800000000);
  assert.equal(signed.body, body);
  const match = /^t=1800000000,k=vector,v1=([A-Za-z0-9_-]+)$/.exec(signed.header);
  assert.ok(match);
  assert.equal(verify(null, Buffer.from(GRANT_CONTEXT + "1800000000." + body), createPublicKey(privateKey), Buffer.from(match[1], "base64url")), true);
});

test("grant keys must be base64url PKCS#8 Ed25519 and errors never echo them", () => {
  const good = generateKeyPairSync("ed25519").privateKey.export({ format: "der", type: "pkcs8" }).toString("base64url");
  assert.equal(grantKey(good).asymmetricKeyType, "ed25519");
  const rsa = generateKeyPairSync("rsa", { modulusLength: 1024 }).privateKey.export({ format: "der", type: "pkcs8" }).toString("base64url");
  for (const value of [undefined, "", "not a key", rsa.slice(0, 199), good + "=="]) {
    // A fixed message: the rejected value never appears in it.
    assert.throws(() => grantKey(value), (error) => error.message === "Invalid billing grant key");
  }
});

test("push accepts only an exact applied response from the service", async () => {
  const { privateKey } = generateKeyPairSync("ed25519");
  const target = { origin: "https://api.saiph.test", keyId: "test-1", key: privateKey };
  const value = { issuer: "https://synthetic.eu.auth0.com/", subject: "auth0|x", grant: "stripe:sub_x", until: now, sequence: 1, livemode: false };
  let seen;
  const respond = (status, text, type = "application/json") => async (url, init) => { seen = { url, init }; return new Response(text, { status, headers: { "content-type": type } }); };
  assert.equal(await pushGrant(target, value, { fetchImpl: respond(200, '{"applied":true}'), now }), true);
  assert.equal(seen.url, "https://api.saiph.test/v1/billing/grant");
  assert.equal(seen.init.redirect, "error");
  assert.match(seen.init.headers["Saiph-Billing-Signature"], /^t=1800000000,k=test-1,v1=/);
  assert.equal(seen.init.headers.Authorization, undefined, "no bearer or cookie credentials are sent");
  assert.equal(await pushGrant(target, value, { fetchImpl: respond(200, '{"applied":false}'), now }), false);
  for (const fetchImpl of [respond(409, '{"detail":"x"}'), respond(200, '{"applied":"yes"}'), respond(200, '{"applied":true,"x":1}'),
    respond(200, "not json"), respond(200, '{"applied":true}', "text/html"), respond(200, " ".repeat(300))]) {
    await assert.rejects(pushGrant(target, value, { fetchImpl, now }));
  }
});

test("sync pushes only what changed and ends any sandbox grant held by someone other than the owner", async () => {
  const candidates = [
    { ...row("active"), subscriptionId: "sub_owner", subject: "auth0|owner", disputed: false, dirty: true, pushedUntil: null },
    { ...row("active"), subscriptionId: "sub_other", subject: "auth0|other", disputed: false, dirty: true, pushedUntil: null },
    { ...row("active"), subscriptionId: "sub_quiet", subject: "auth0|owner", disputed: false, dirty: false, pushedUntil: now + 20 * 86400 + RENEWAL_GRACE_SECONDS },
  ];
  const recorded = [], pushes = [];
  const store = {
    grantCandidates: async () => candidates,
    trialGrantCandidates: async () => [],
    withGrant: async (id, push) => { const until = await push(candidates.find((c) => c.subscriptionId === id), recorded.length + 1); recorded.push([id, until]); return { until }; },
  };
  const policy = { issuer: "https://synthetic.eu.auth0.com/", livemode: false, ownerOnly: "auth0|owner" };
  const result = await syncGrants(store, policy, async (value) => { pushes.push(value); return true; }, { now: () => now });
  assert.deepEqual(result, { pushed: 2, failed: 0 });
  assert.deepEqual(recorded, [["sub_owner", now + 20 * 86400 + RENEWAL_GRACE_SECONDS], ["sub_other", 0]]);
  assert.deepEqual(pushes.map((p) => [p.grant, p.sequence, p.livemode]), [["stripe:sub_owner", 1, false], ["stripe:sub_other", 2, false]]);
  const failing = await syncGrants(store, policy, async () => { throw new Error("down"); }, { now: () => now });
  assert.deepEqual(failing, { pushed: 0, failed: 2 });
  assert.equal((await syncGrants(store, policy, async () => true, { now: () => now, force: true })).pushed, 3);
});
