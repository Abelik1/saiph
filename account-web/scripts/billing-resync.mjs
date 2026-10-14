// SPDX-License-Identifier: AGPL-3.0-or-later
// Re-push every current paid grant to the Hosted service, for example after the
// service was restored from a backup or the grant key was rotated. Explicit
// invocation only, with the account website's server environment supplied
// privately in the process environment (never as arguments or files here).
import { createNeonPool } from "../lib/billing/connection.mjs";
import { createBillingStore } from "../lib/billing/store.mjs";
import { syncGrants } from "../lib/billing/grant-sync.mjs";
import { pushGrant } from "../lib/billing/grant-push.mjs";
import { readBillingConfig } from "../lib/billing/policy.ts";
import { grantPolicy } from "../lib/billing/service.ts";

const config = readBillingConfig(process.env);
if (!config) {
  console.error("Billing configuration is incomplete; nothing was pushed.");
  process.exit(1);
}
const pool = createNeonPool(process.env.DATABASE_URL);
try {
  const store = createBillingStore(pool, { stripeAccountId: config.accountId, livemode: config.livemode });
  const result = await syncGrants(store, grantPolicy(config), (value) => pushGrant(config.grant, value), { force: true });
  // Counts only: never print subjects, subscription IDs or keys.
  console.log(JSON.stringify(result));
  process.exitCode = result.failed ? 1 : 0;
} finally {
  await pool.end();
}
