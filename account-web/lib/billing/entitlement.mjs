// SPDX-License-Identifier: AGPL-3.0-or-later
// Billing entitlement is derived ONLY from subscription rows that the signed
// webhook path (store.applyEvent) persisted from a current Stripe snapshot.
// Checkout redirects, query strings and browser input never reach this function.
// The result is billing standing. Hosted access follows it only through the
// signed grant push (grant.mjs); it never approves devices or unlocks content.

/** An active subscription whose period ended this long ago without a renewal
 * observation is treated as unconfirmed rather than silently extended. */
export const RENEWAL_GRACE_SECONDS = 72 * 3600;
/** Access continues this long after a failed renewal while Stripe retries the
 * card (owner decision, 14 October 2026). */
export const PAYMENT_GRACE_SECONDS = 3 * 86400;

/** @typedef {{subscriptionId: string, status: string, currentPeriodEnd: number | null,
 *   cancelAtPeriodEnd: boolean, cancelAt?: number | null, canceledAt: number | null,
 *   endedAt: number | null, paymentFailedAt?: number | null}} StoredSubscription */
/** @typedef {{entitled: boolean, state: "none"|"active"|"ending"|"payment_failed"|"pending"|"paused"|"renewal_unconfirmed"|"disputed"|"ended",
 *   subscriptionId: string | null, until: number | null}} Entitlement */

/** @param {StoredSubscription} subscription @param {number} now @returns {Entitlement} */
function evaluate(subscription, now) {
  const base = { subscriptionId: subscription.subscriptionId, until: null };
  switch (subscription.status) {
    case "active":
    case "trialing": {
      const periodEnd = subscription.currentPeriodEnd;
      const cancelAt = subscription.cancelAt ?? null;
      const scheduledEnd = subscription.cancelAtPeriodEnd
        ? (cancelAt === null ? periodEnd : Math.min(cancelAt, periodEnd ?? cancelAt))
        : cancelAt;
      if (scheduledEnd !== null) {
        // Cancellation is scheduled: access ends at that time even if the
        // deletion webhook is delayed.
        return now < scheduledEnd
          ? { ...base, entitled: true, state: "ending", until: scheduledEnd }
          : { ...base, entitled: false, state: "ended", until: scheduledEnd };
      }
      if (periodEnd === null || now > periodEnd + RENEWAL_GRACE_SECONDS) {
        return { ...base, entitled: false, state: "renewal_unconfirmed", until: periodEnd };
      }
      return { ...base, entitled: true, state: "active", until: periodEnd };
    }
    case "past_due": {
      // Stripe is retrying the card: a short grace from the first observed
      // failure, then access stops until a webhook observes it active again.
      const failedAt = subscription.paymentFailedAt ?? null;
      if (failedAt !== null && now < failedAt + PAYMENT_GRACE_SECONDS) {
        return { ...base, entitled: true, state: "payment_failed", until: failedAt + PAYMENT_GRACE_SECONDS };
      }
      return { ...base, entitled: false, state: "payment_failed" };
    }
    case "unpaid":
      return { ...base, entitled: false, state: "payment_failed" };
    case "incomplete":
      return { ...base, entitled: false, state: "pending" };
    case "paused":
      return { ...base, entitled: false, state: "paused" };
    default:
      // canceled, incomplete_expired and anything unrecognised fail closed.
      return { ...base, entitled: false, state: "ended", until: subscription.endedAt ?? subscription.canceledAt ?? null };
  }
}

const PRIORITY = ["active", "ending", "payment_failed", "pending", "paused", "renewal_unconfirmed", "disputed", "ended"];

/** Pure derivation from persisted webhook observations.
 * @param {StoredSubscription[]} subscriptions output of store.listSubscriptions
 * @param {number} now Unix seconds
 * @param {{disputed?: boolean}} [options] an open or lost chargeback on the customer
 * @returns {Entitlement}
 */
export function deriveEntitlement(subscriptions, now, { disputed = false } = {}) {
  if (!Number.isSafeInteger(now) || now < 0) throw new Error("Invalid entitlement time");
  if (!Array.isArray(subscriptions) || subscriptions.length === 0) {
    return { entitled: false, state: "none", subscriptionId: null, until: null };
  }
  const results = subscriptions.map((subscription) => evaluate(subscription, now));
  results.sort((a, b) => Number(b.entitled) - Number(a.entitled)
    || PRIORITY.indexOf(a.state) - PRIORITY.indexOf(b.state)
    || (b.until ?? 0) - (a.until ?? 0));
  if (disputed && results[0].entitled) {
    // A chargeback ends paid access at once; a dispute closed in our favour restores it.
    return { entitled: false, state: "disputed", subscriptionId: results[0].subscriptionId, until: null };
  }
  return results[0];
}
