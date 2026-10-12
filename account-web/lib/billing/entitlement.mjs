// SPDX-License-Identifier: AGPL-3.0-or-later
// Billing entitlement is derived ONLY from subscription rows that the signed
// webhook path (store.applyEvent) persisted from a current Stripe snapshot.
// Checkout redirects, query strings and browser input never reach this function.
// The result describes sandbox billing standing only. It does not approve
// devices, unlock content or enable Hosted service.

/** An active subscription whose period ended this long ago without a renewal
 * observation is treated as unconfirmed rather than silently extended. */
export const RENEWAL_GRACE_SECONDS = 72 * 3600;

/** @typedef {{subscriptionId: string, status: string, currentPeriodEnd: number | null,
 *   cancelAtPeriodEnd: boolean, cancelAt?: number | null, canceledAt: number | null,
 *   endedAt: number | null}} StoredSubscription */
/** @typedef {{entitled: boolean, state: "none"|"active"|"ending"|"payment_failed"|"pending"|"paused"|"renewal_unconfirmed"|"ended",
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
    case "past_due":
    case "unpaid":
      // Conservative: a failed renewal suspends billing entitlement until a
      // webhook observes the subscription active again.
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

const PRIORITY = ["active", "ending", "payment_failed", "pending", "paused", "renewal_unconfirmed", "ended"];

/** Pure derivation from persisted webhook observations.
 * @param {StoredSubscription[]} subscriptions output of store.listSubscriptions
 * @param {number} now Unix seconds
 * @returns {Entitlement}
 */
export function deriveEntitlement(subscriptions, now) {
  if (!Number.isSafeInteger(now) || now < 0) throw new Error("Invalid entitlement time");
  if (!Array.isArray(subscriptions) || subscriptions.length === 0) {
    return { entitled: false, state: "none", subscriptionId: null, until: null };
  }
  const results = subscriptions.map((subscription) => evaluate(subscription, now));
  results.sort((a, b) => PRIORITY.indexOf(a.state) - PRIORITY.indexOf(b.state)
    || (b.until ?? 0) - (a.until ?? 0));
  return results[0];
}
