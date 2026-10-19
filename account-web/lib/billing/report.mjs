// SPDX-License-Identifier: AGPL-3.0-or-later
// Aggregate billing funnel for the owner (docs/USAGE_DATA_RECOMMENDATIONS.md):
// trials, checkouts, subscriptions by status and plan, cancellations, failed
// payments and trial-to-paid conversion. Every query groups and counts; none
// selects a subject, customer, subscription or email. Counts below minCell are
// shown as "<minCell" so a shared report cannot single anyone out.

const PAID = ["active", "past_due", "canceled", "unpaid", "paused"];

/** @param {number} count @param {number} minCell */
export function hideSmall(count, minCell) {
  return count > 0 && count < minCell ? "<" + minCell : count;
}

/**
 * @param {{query: (sql: string, values: unknown[]) => Promise<{rows: any[]}>}} pool
 * @param {{stripeAccountId: string, plans: {monthly: string, yearly: string}, weeks?: number, minCell?: number}} options
 */
export async function billingReport(pool, { stripeAccountId, plans, weeks = 12, minCell = 5 }) {
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
  const plan = (/** @type {string} */ price) => price === plans.monthly ? "monthly" : price === plans.yearly ? "yearly" : "other";
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
  };
}
