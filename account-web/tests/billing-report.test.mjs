// SPDX-License-Identifier: AGPL-3.0-or-later
// The billing funnel report only groups and counts, and hides small groups.
// Synthetic rows through a recording pool; the SQL itself runs against the
// isolated database in tests/billing-db.test.mjs (npm run test:billing-db).
import { test } from "node:test";
import assert from "node:assert/strict";
import { billingReport, hideSmall } from "../lib/billing/report.mjs";

const plans = { monthly: "price_monthly", yearly: "price_yearly" };

function pool(answers) {
  const calls = [];
  return {
    calls,
    async query(sql, values) {
      calls.push({ sql, values });
      const key = Object.keys(answers).find((name) => sql.includes(name));
      return { rows: key ? answers[key] : [] };
    },
  };
}

const answers = {
  "funnel_daily": [
    { week: "2026-10-12", step: "signin_view", plan: "monthly", test: "", variant: "a", count: 40 },
    { week: "2026-10-12", step: "signin_done", plan: "monthly", test: "", variant: "a", count: 30 },
    { week: "2026-10-12", step: "checkout_started", plan: "monthly", test: "", variant: "a", count: 20 },
    { week: "2026-10-12", step: "purchase", plan: "monthly", test: "", variant: "a", count: 8 },
    { week: "2026-10-12", step: "signin_view", plan: "yearly", test: "2026-11-price", variant: "b", count: 10 },
    { week: "2026-10-12", step: "purchase", plan: "yearly", test: "2026-11-price", variant: "b", count: 2 },
  ],
  "FROM saiph_billing.trials\n": [{ week: "2026-10-05", count: 2 }, { week: "2026-10-12", count: 9 }],
  "FROM saiph_billing.customers\n": [{ week: "2026-10-12", count: 7 }],
  "canceled_at IS NOT NULL": [{ week: "2026-10-12", count: 1 }],
  "GROUP BY 1, 2, 3": [
    { status: "active", price: "price_monthly", ending: false, count: 6 },
    { status: "active", price: "price_yearly", ending: false, count: 5 },
    { status: "active", price: "price_monthly", ending: true, count: 2 },
    { status: "past_due", price: "price_other", ending: false, count: 1 },
  ],
  "AS paid": [{ trials: 20, paid: 6 }],
  "AS payment_failing": [{ payment_failing: 1, disputes: 0 }],
};

test("small counts are shown as a range, never exactly", () => {
  assert.equal(hideSmall(0, 5), 0);
  assert.equal(hideSmall(1, 5), "<5");
  assert.equal(hideSmall(4, 5), "<5");
  assert.equal(hideSmall(5, 5), 5);
  assert.equal(hideSmall(3, 1), 3);
});

test("the report groups by week, status and plan and hides small groups", async () => {
  const db = pool(answers);
  const report = await billingReport(db, { stripeAccountId: "acct_synthetic", plans, weeks: 4 });
  assert.deepEqual(report.trialsStarted, [{ week: "2026-10-05", count: "<5" }, { week: "2026-10-12", count: 9 }]);
  assert.deepEqual(report.checkoutsStarted, [{ week: "2026-10-12", count: 7 }]);
  assert.deepEqual(report.cancellations, [{ week: "2026-10-12", count: "<5" }]);
  assert.deepEqual(report.subscriptions, {
    "active/monthly": 6, "active/monthly/ending": "<5", "active/yearly": 5, "past_due/other": "<5" });
  assert.deepEqual(report.trialConversion, { trials: 20, paid: 6, rate: 30 });
  assert.equal(report.paymentFailing, "<5");
  assert.equal(report.disputes, 0);
  const raw = await billingReport(pool(answers), { stripeAccountId: "acct_synthetic", plans, minCell: 1 });
  assert.equal(raw.subscriptions["past_due/other"], 1);
  // No price IDs in the output: plans are named.
  assert.doesNotMatch(JSON.stringify(report), /price_/);
});

test("the Buy now funnel shows each step, the share reaching it and the variants", async () => {
  const report = await billingReport(pool(answers), { stripeAccountId: "acct_synthetic", plans,
    testPrices: { price_other: "monthly/b" } });
  assert.deepEqual(report.funnel.total.steps, { signin_view: 50, signin_done: 30, checkout_started: 20, purchase: 10 });
  assert.deepEqual(report.funnel.total.reachedFromPreviousPercent, { signin_done: 60, checkout_started: 66.7, purchase: 50 });
  assert.deepEqual(report.funnel.byPlan.yearly.steps, { signin_view: 10, signin_done: 0, checkout_started: 0, purchase: "<5" });
  assert.equal(report.funnel.byPlan.yearly.reachedFromPreviousPercent.purchase, null, "no rate from hidden counts");
  assert.deepEqual(Object.keys(report.funnel.byVariant), ["2026-11-price/b", "none/a"]);
  assert.equal(report.subscriptions["past_due/monthly/b"], "<5", "price-test prices are named by plan and variant");
  // Without migration 0006 the funnel is simply absent.
  const old = pool(answers);
  const query = old.query;
  old.query = async (sql, values) => { if (sql.includes("funnel_daily")) throw new Error("relation does not exist"); return query(sql, values); };
  assert.equal((await billingReport(old, { stripeAccountId: "acct_synthetic", plans })).funnel, null);
});

test("queries count and group but never select people or Stripe IDs", async () => {
  const db = pool(answers);
  await billingReport(db, { stripeAccountId: "acct_synthetic", plans });
  assert.equal(db.calls.length, 7);
  for (const { sql, values } of db.calls) {
    const outer = sql.replace(/EXISTS \([\s\S]*?\)\)\)/, "EXISTS (...)");
    const selected = outer.slice(outer.indexOf("SELECT") + 6, outer.search(/\bFROM\b/));
    assert.doesNotMatch(selected, /auth_subject|email_key|stripe_customer_id|stripe_subscription_id|trial_ref/);
    assert.match(sql, /count\(\*\)|sum\(count\)/);
    assert.equal(values[0], "acct_synthetic");
    assert.equal(values.length, sql.includes("$2") ? 2 : 1);
  }
});

test("bad options are refused before any query", async () => {
  const db = pool(answers);
  await assert.rejects(billingReport(db, { stripeAccountId: "acct_synthetic", plans, weeks: 0 }));
  await assert.rejects(billingReport(db, { stripeAccountId: "acct_synthetic", plans, minCell: 0 }));
  await assert.rejects(billingReport(db, { stripeAccountId: "'; DROP TABLE x; --", plans }));
  assert.equal(db.calls.length, 0);
});

test("the free-trial path is reported on its own: sign-in page, sign-in, trial started", async () => {
  const rows = [
    { week: "2026-10-19", step: "signin_view", plan: "trial", test: "", variant: "a", count: 50 },
    { week: "2026-10-19", step: "signin_done", plan: "trial", test: "", variant: "a", count: 40 },
    { week: "2026-10-19", step: "trial_started", plan: "trial", test: "", variant: "a", count: 30 },
  ];
  const report = await billingReport(pool({ ...answers, funnel_daily: [...answers.funnel_daily, ...rows] }), { stripeAccountId: "acct_synthetic", plans });
  assert.deepEqual(report.funnel.trial.steps, { signin_view: 50, signin_done: 40, trial_started: 30 });
  assert.deepEqual(report.funnel.trial.reachedFromPreviousPercent, { signin_done: 80, trial_started: 75 });
  assert.equal(report.funnel.total.steps.signin_view, 50, "the Buy now totals leave trial visits out");
  assert.equal(Object.hasOwn(report.funnel.byPlan, "trial"), false);
});
