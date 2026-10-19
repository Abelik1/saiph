// SPDX-License-Identifier: AGPL-3.0-or-later
// Pure derivation checks. Entitlement input is only store.listSubscriptions()
// output, which is written exclusively by the signed webhook path.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { deriveEntitlement, PAYMENT_GRACE_SECONDS, RENEWAL_GRACE_SECONDS } from "../lib/billing/entitlement.mjs";

const now = 1_800_000_000;
const row = (status, overrides = {}) => ({ subscriptionId: "sub_synthetic", status, currentPeriodEnd: now + 1000,
  cancelAtPeriodEnd: false, cancelAt: null, canceledAt: null, endedAt: null, ...overrides });

test("no webhook-observed subscription means no entitlement", () => {
  assert.deepEqual(deriveEntitlement([], now), { entitled: false, state: "none", subscriptionId: null, until: null });
  assert.throws(() => deriveEntitlement([], -1));
  assert.throws(() => deriveEntitlement([], 1.5));
});

test("active and trialing are entitled until the observed period end", () => {
  for (const status of ["active", "trialing"]) {
    assert.deepEqual(deriveEntitlement([row(status)], now), { entitled: true, state: "active", subscriptionId: "sub_synthetic", until: now + 1000 });
  }
});

test("failed renewal, incomplete, paused and terminal states are not entitled", () => {
  for (const [status, state] of [["past_due", "payment_failed"], ["unpaid", "payment_failed"], ["incomplete", "pending"],
    ["paused", "paused"], ["canceled", "ended"], ["incomplete_expired", "ended"], ["invented", "ended"]]) {
    const result = deriveEntitlement([row(status)], now);
    assert.equal(result.entitled, false, status);
    assert.equal(result.state, state, status);
  }
});

test("a failed renewal stays entitled for the payment grace from the first observed failure", () => {
  const failed = row("past_due", { paymentFailedAt: now - 10 });
  assert.deepEqual(deriveEntitlement([failed], now),
    { entitled: true, state: "payment_failed", subscriptionId: "sub_synthetic", until: now - 10 + PAYMENT_GRACE_SECONDS });
  assert.equal(deriveEntitlement([failed], now - 10 + PAYMENT_GRACE_SECONDS).entitled, false);
});

test("an open dispute suspends an otherwise entitled subscription", () => {
  assert.deepEqual(deriveEntitlement([row("active")], now, { disputed: true }),
    { entitled: false, state: "disputed", subscriptionId: "sub_synthetic", until: null });
  assert.equal(deriveEntitlement([row("canceled")], now, { disputed: true }).state, "ended");
});

test("scheduled cancellation stays entitled only until the earliest scheduled end", () => {
  assert.deepEqual(deriveEntitlement([row("active", { cancelAtPeriodEnd: true })], now),
    { entitled: true, state: "ending", subscriptionId: "sub_synthetic", until: now + 1000 });
  assert.equal(deriveEntitlement([row("active", { cancelAtPeriodEnd: true })], now + 1000).entitled, false);
  assert.equal(deriveEntitlement([row("active", { cancelAt: now + 500 })], now).until, now + 500);
  assert.equal(deriveEntitlement([row("active", { cancelAt: now + 500 })], now + 500).state, "ended");
  assert.equal(deriveEntitlement([row("active", { cancelAtPeriodEnd: true, cancelAt: now + 2000 })], now).until, now + 1000);
});

test("an active row without a renewal observation past the grace window fails closed", () => {
  assert.equal(deriveEntitlement([row("active")], now + 1000 + RENEWAL_GRACE_SECONDS).entitled, true);
  assert.equal(deriveEntitlement([row("active")], now + 1001 + RENEWAL_GRACE_SECONDS).state, "renewal_unconfirmed");
  assert.equal(deriveEntitlement([row("active", { currentPeriodEnd: null })], now).entitled, false);
});

test("an entitled subscription wins over older ended ones", () => {
  const result = deriveEntitlement([row("canceled", { subscriptionId: "sub_old", endedAt: now - 10 }), row("active", { subscriptionId: "sub_new" })], now);
  assert.equal(result.subscriptionId, "sub_new");
  assert.equal(result.entitled, true);
});

test("checkout feedback is separate from the stored billing derivation", async () => {
  const view = await readFile(new URL("../lib/billing/view.ts", import.meta.url), "utf8");
  const page = await readFile(new URL("../app/account/page.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(view, /checkout|searchParams/);
  assert.match(view, /listSubscriptions/);
  assert.match(view, /deriveEntitlement/);
  // The page reads the return parameter only to choose a notice after loading billing.
  assert.ok(page.indexOf("billingView(") < page.indexOf("searchParams;"));
  assert.match(page, /const notice = checkout === "returned" \? "returned" : checkout === "cancelled" \? "cancelled" : trial === "started" \? "trial" : null;/);
});
