// SPDX-License-Identifier: AGPL-3.0-or-later
// Aggregate billing funnel for the owner (docs/USAGE_DATA_RECOMMENDATIONS.md):
// trials, checkouts, subscriptions by status and plan, cancellations, failed
// payments, trial-to-paid conversion, and the Buy now funnel (sign-in page,
// sign-in done, Checkout started, purchase) by plan and price-test variant
// from the daily counts in migration 0006 (docs/LANDING_CONVERSION.md). Every query groups and counts; none
// selects a subject, customer, subscription or email. Counts below minCell are
// shown as "<minCell" so a shared report cannot single anyone out.

const PAID = ["active", "past_due", "canceled", "unpaid", "paused"];
const STEPS = ["signin_view", "signin_done", "checkout_started", "purchase"];
const TRIAL_STEPS = ["signin_view", "signin_done", "trial_started"];

/** @param {number} count @param {number} minCell */
export function hideSmall(count, minCell) {
  return count > 0 && count < minCell ? "<" + minCell : count;
}

/**
 * @param {{query: (sql: string, values: unknown[]) => Promise<{rows: any[]}>}} pool
 * @param {{stripeAccountId: string, plans: {monthly: string, yearly: string}, testPrices?: Record<string, string>, weeks?: number, minCell?: number}} options
 *   `testPrices` names price-test prices, e.g. {"price_…": "monthly/b"}.
 */
export async function billingReport(pool, { stripeAccountId, plans, testPrices = {}, weeks = 12, minCell = 5 }) {
  if (!/^acct_[A-Za-z0-9]+$/.test(stripeAccountId)) throw new Error("A Stripe account ID is required");
  if (!Number.isInteger(weeks) || weeks < 1 || weeks > 104) throw new Error("Choose 1 to 104 weeks");
  if (!Number.isInteger(minCell) || minCell < 1 || minCell > 100) throw new Error("Choose a minimum group size from 1 to 100");
  const since = `extract(epoch from now() - make_interval(weeks => $2::int))`;
  const week = (/** @type {string} */ column) => `to_char(date_trunc('week', ${column}), 'YYYY-MM-DD')`;
  // Queries with a time window take the weeks as $2; the others only the account.
  const run = async (/** @type {string} */ sql) => (await pool.query(sql, sql.includes("$2") ? [stripeAccountId, weeks] : [stripeAccountId])).rows;
  const [trials, checkouts, cancellations, subscriptions, conversion, problems] = await Promise.all([
    run(`SELECT ${week("to_timestamp(started_at)")} AS week, count(*)::int AS count FROM saiph_billing.trials
         WHERE stripe_account_id=$1 AND started_at >= ${since} GROUP BY 1 ORDER BY 1`),
    run(`SELECT ${week("created_at")} AS week, count(*)::int AS count FROM saiph_billing.customers
         WHERE stripe_account_id=$1 AND extract(epoch from created_at) >= ${since} GROUP BY 1 ORDER BY 1`),
    run(`SELECT ${week("to_timestamp(canceled_at)")} AS week, count(*)::int AS count FROM saiph_billing.subscriptions
         WHERE stripe_account_id=$1 AND canceled_at IS NOT NULL AND canceled_at >= ${since} GROUP BY 1 ORDER BY 1`),
    run(`SELECT status, stripe_price_id AS price, cancel_at_period_end AS ending, count(*)::int AS count
         FROM saiph_billing.subscriptions WHERE stripe_account_id=$1 GROUP BY 1, 2, 3 ORDER BY 1, 2, 3`),
    run(`SELECT count(*)::int AS trials, count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM saiph_billing.customers c JOIN saiph_billing.subscriptions s
             ON s.stripe_account_id = c.stripe_account_id AND s.stripe_customer_id = c.stripe_customer_id
           WHERE c.stripe_account_id = t.stripe_account_id AND c.auth_subject = t.auth_subject
             AND s.status IN (${PAID.map((status) => `'${status}'`).join(",")})))::int AS paid
         FROM saiph_billing.trials t WHERE t.stripe_account_id=$1`),
    run(`SELECT (SELECT count(*)::int FROM saiph_billing.subscriptions WHERE stripe_account_id=$1 AND payment_failed_at IS NOT NULL)
                AS payment_failing,
                (SELECT count(*)::int FROM saiph_billing.disputes WHERE stripe_account_id=$1) AS disputes`),
  ]);
  // Without migration 0006 there are no funnel counts yet; the rest still reports.
  const funnelRows = await run(`SELECT ${week("day")} AS week, step, plan, price_test AS test, variant, sum(count)::int AS count
       FROM saiph_billing.funnel_daily WHERE stripe_account_id=$1 AND day >= (now() - make_interval(weeks => $2::int))::date
       GROUP BY 1, 2, 3, 4, 5 ORDER BY 1, 2, 3, 4, 5`).catch(() => null);
  const plan = (/** @type {string} */ price) => price === plans.monthly ? "monthly" : price === plans.yearly ? "yearly"
    : Object.hasOwn(testPrices, price) ? testPrices[price] : "other";
  const weekly = (/** @type {{week: string, count: number}[]} */ rows) => rows.map((row) => ({ week: row.week, count: hideSmall(row.count, minCell) }));
  const byStatus = new Map();
  for (const row of subscriptions) {
    const key = row.status + "/" + plan(row.price) + (row.ending ? "/ending" : "");
    byStatus.set(key, (byStatus.get(key) || 0) + row.count);
  }
  const total = conversion[0] || { trials: 0, paid: 0 };
  return {
    weeks, minCell,
    trialsStarted: weekly(trials),
    checkoutsStarted: weekly(checkouts),
    cancellations: weekly(cancellations),
    // e.g. "active/monthly", "active/yearly/ending" (cancels at period end), "past_due/monthly".
    subscriptions: Object.fromEntries([...byStatus].sort().map(([key, count]) => [key, hideSmall(count, minCell)])),
    trialConversion: {
      trials: hideSmall(total.trials, minCell), paid: hideSmall(total.paid, minCell),
      rate: total.trials >= minCell && total.paid >= minCell ? Math.round((total.paid / total.trials) * 1000) / 10 : null,
    },
    paymentFailing: hideSmall(problems[0]?.payment_failing || 0, minCell),
    disputes: hideSmall(problems[0]?.disputes || 0, minCell),
    funnel: funnelRows === null ? null : funnelReport(funnelRows, minCell),
  };
}

/**
 * The two funnels from usesaiph.com: Buy now (monthly and yearly) and Start
 * your free trial (plan "trial"). Totals per step for the window, the share
 * that reached each step from the one before, per plan and per price-test
 * variant. Visits and Buy now presses come from Vercel Web Analytics or GA4,
 * not from here (website/ANALYTICS.md).
 * @param {{week: string, step: string, plan: string, test: string, variant: string, count: number}[]} rows
 * @param {number} minCell
 */
export function funnelReport(rows, minCell) {
  /** @param {(row: typeof rows[number]) => boolean} keep @param {string[]} [list] */
  const totals = (keep, list = STEPS) => {
    const sums = Object.fromEntries(list.map((step) => [step, 0]));
    for (const row of rows) if (keep(row) && Object.hasOwn(sums, row.step)) sums[row.step] += row.count;
    const steps = Object.fromEntries(list.map((step) => [step, hideSmall(sums[step], minCell)]));
    // Share of the previous step, only when both counts are large enough to show.
    const reached = Object.fromEntries(list.slice(1).map((step, index) => {
      const before = sums[list[index]], after = sums[step];
      return [step, before >= minCell && after >= minCell ? Math.round((after / before) * 1000) / 10 : null];
    }));
    return { steps, reachedFromPreviousPercent: reached };
  };
  const buying = rows.filter((row) => row.plan !== "trial");
  const groups = (/** @type {(row: typeof rows[number]) => string} */ key) =>
    Object.fromEntries([...new Set(buying.map(key))].sort().map((name) => [name, totals((row) => row.plan !== "trial" && key(row) === name)]));
  return {
    total: totals((row) => row.plan !== "trial"),
    trial: totals((row) => row.plan === "trial", TRIAL_STEPS),
    byPlan: groups((row) => row.plan),
    // e.g. "2026-11-price/b"; visitors outside a test are "none/a".
    byVariant: groups((row) => (row.test || "none") + "/" + row.variant),
    weekly: rows.map((row) => ({ week: row.week, step: row.step, plan: row.plan, variant: (row.test || "none") + "/" + row.variant,
      count: hideSmall(row.count, minCell) })),
  };
}
