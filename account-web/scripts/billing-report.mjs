// SPDX-License-Identifier: AGPL-3.0-or-later
// Print the aggregate billing funnel (lib/billing/report.mjs) as JSON. Explicit
// invocation only, with the account website's server environment supplied
// privately in the process environment. Counts only: no subjects, customer or
// subscription IDs, emails or keys are read into the output.
//   npm run billing:report -- --weeks 12 --min-cell 5
import { parseArgs } from "node:util";
import { createNeonPool } from "../lib/billing/connection.mjs";
import { billingReport } from "../lib/billing/report.mjs";
import { readBillingConfig } from "../lib/billing/policy.ts";

const { values } = parseArgs({ options: { weeks: { type: "string", default: "12" }, "min-cell": { type: "string", default: "5" } } });
const config = readBillingConfig(process.env);
if (!config) {
  console.error("Billing configuration is incomplete; no report was made.");
  process.exit(1);
}
const pool = createNeonPool(process.env.DATABASE_URL);
try {
  const report = await billingReport(pool, {
    stripeAccountId: config.accountId,
    plans: { monthly: config.plans.monthly.priceId, yearly: config.plans.yearly.priceId },
    // Price-test prices are reported as "monthly/b" and so on.
    testPrices: Object.fromEntries(Object.entries(config.priceTest?.variants ?? {}).flatMap(([variant, prices]) =>
      Object.entries(prices).map(([plan, price]) => [price.priceId, plan + "/" + variant]))),
    weeks: Number(values.weeks), minCell: Number(values["min-cell"]),
  });
  console.log(JSON.stringify(report, null, 2));
} finally {
  await pool.end();
}
