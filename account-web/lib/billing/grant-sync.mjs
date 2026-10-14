// SPDX-License-Identifier: AGPL-3.0-or-later
// Deliver paid grants from stored webhook observations to the Hosted service.
// Used after each webhook, by the daily refresh and by the manual resync.
import { grantUntil, needsPush } from "./grant.mjs";

/** @typedef {{issuer: string, livemode: boolean, ownerOnly: string | null}} GrantPolicy */

/**
 * @param {ReturnType<typeof import("./store.mjs").createBillingStore>} store
 * @param {GrantPolicy} policy
 * @param {(value: import("./grant-push.mjs").GrantValue) => Promise<boolean>} push
 * @param {{customerId?: string, force?: boolean, now?: () => number}} [options]
 * @returns {Promise<{pushed: number, failed: number}>}
 */
export async function syncGrants(store, policy, push, { customerId, force = false, now = () => Math.floor(Date.now() / 1000) } = {}) {
  let pushed = 0, failed = 0;
  for (const candidate of await store.grantCandidates(customerId === undefined ? {} : { customerId })) {
    if (!force && !needsPush(candidate, grantUntil(candidate, candidate.disputed, now()), now())) continue;
    try {
      await store.withGrant(candidate.subscriptionId, async (row, sequence) => {
        // In sandbox mode only the owner may hold a paid grant (owner decision).
        const until = policy.ownerOnly !== null && row.subject !== policy.ownerOnly ? 0
          : grantUntil(row, row.disputed, now());
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
  return { pushed, failed };
}
