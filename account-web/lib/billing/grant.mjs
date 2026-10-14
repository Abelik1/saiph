// SPDX-License-Identifier: AGPL-3.0-or-later
// Paid Hosted grant expiry pushed to the Hosted service (docs/PAID_HOSTED.md).
// Input is only webhook-persisted subscription rows and dispute observations.
import { deriveEntitlement, RENEWAL_GRACE_SECONDS } from "./entitlement.mjs";

/** One push grants at most this far ahead; the daily refresh rolls it forward.
 * The Hosted service refuses anything beyond its own 45-day horizon. */
export const GRANT_ROLL_SECONDS = 35 * 86400;
/** Refresh re-pushes a still-entitled grant once fewer than this many seconds remain. */
export const REFRESH_BEFORE_SECONDS = 25 * 86400;

/** Inquiries (warnings), disputes won and prevented ones leave access alone. Any
 * other status, including statuses Stripe adds later, blocks paid access. */
const HARMLESS_DISPUTES = new Set(["warning_needs_response", "warning_under_review", "warning_closed", "won", "prevented"]);
/** @param {string} status */
export function disputeBlocks(status) {
  return !HARMLESS_DISPUTES.has(status);
}

/** Unix seconds until which Hosted access is granted; 0 ends paid access now.
 * @param {import("./entitlement.mjs").StoredSubscription} subscription
 * @param {boolean} disputed
 * @param {number} now
 */
export function grantUntil(subscription, disputed, now) {
  const standing = deriveEntitlement([subscription], now, { disputed });
  if (!standing.entitled || standing.until === null) return 0;
  // A renewing subscription keeps access through a late renewal webhook.
  const end = standing.state === "active" ? standing.until + RENEWAL_GRACE_SECONDS : standing.until;
  return Math.min(end, now + GRANT_ROLL_SECONDS);
}

/** Whether the Hosted service needs a new push for this subscription.
 * @param {{dirty: boolean, pushedUntil: number | null}} state
 * @param {number} target grantUntil() now
 * @param {number} now
 */
export function needsPush(state, target, now) {
  if (state.dirty || state.pushedUntil === null) return true;
  if (target > state.pushedUntil) return state.pushedUntil < now + REFRESH_BEFORE_SECONDS;
  // Shorten a still-running grant (for example a dispute observed in the meantime).
  return target < state.pushedUntil && state.pushedUntil > now;
}
