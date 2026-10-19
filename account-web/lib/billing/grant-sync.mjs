// SPDX-License-Identifier: AGPL-3.0-or-later
// Deliver paid and trial grants from stored observations to the Hosted service.
// Used after each webhook or trial start, by the daily refresh and by the manual resync.
import { grantUntil, needsPush } from "./grant.mjs";
import { trialGrant, trialUntil } from "./trial.mjs";

/** @typedef {{issuer: string, livemode: boolean, ownerOnly: string | null}} GrantPolicy */

/**
 * Without a filter every grant is considered. `customerId` limits delivery to one
 * Stripe customer's subscriptions (webhooks); `subject` to one person's trial.
 * @param {ReturnType<typeof import("./store.mjs").createBillingStore>} store
 * @param {GrantPolicy} policy
 * @param {(value: import("./grant-push.mjs").GrantValue) => Promise<boolean>} push
 * @param {{customerId?: string, subject?: string, force?: boolean, now?: () => number}} [options]
 * @returns {Promise<{pushed: number, failed: number}>}
 */
export async function syncGrants(store, policy, push, { customerId, subject, force = false, now = () => Math.floor(Date.now() / 1000) } = {}) {
  let pushed = 0, failed = 0;
  // In sandbox mode only the owner may hold a paid or trial grant (owner decision).
  const allowed = (/** @type {string} */ holder) => policy.ownerOnly === null || holder === policy.ownerOnly;
  const subscriptions = subject === undefined ? await store.grantCandidates(customerId === undefined ? {} : { customerId }) : [];
  for (const candidate of subscriptions) {
    if (!force && !needsPush(candidate, grantUntil(candidate, candidate.disputed, now()), now())) continue;
    try {
      await store.withGrant(candidate.subscriptionId, async (row, sequence) => {
        const until = allowed(row.subject) ? grantUntil(row, row.disputed, now()) : 0;
        await push({ issuer: policy.issuer, subject: row.subject, grant: "stripe:" + row.subscriptionId,
          until, sequence, livemode: policy.livemode });
        return until;
      });
      pushed++;
    } catch {
      // Left marked for the next webhook retry or daily refresh; never log details.
      failed++;
    }
  }
  const trials = customerId === undefined ? await store.trialGrantCandidates(subject === undefined ? {} : { subject }) : [];
  for (const candidate of trials) {
    if (!force && !needsPush(candidate, trialUntil(candidate, now()), now())) continue;
    try {
      await store.withTrialGrant(candidate.subject, async (row, sequence) => {
        const until = allowed(row.subject) ? trialUntil(row, now()) : 0;
        await push({ issuer: policy.issuer, subject: row.subject, grant: trialGrant(row.ref),
          until, sequence, livemode: policy.livemode });
        return until;
      });
      pushed++;
    } catch {
      failed++;
    }
  }
  return { pushed, failed };
}
