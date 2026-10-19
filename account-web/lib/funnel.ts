// SPDX-License-Identifier: AGPL-3.0-or-later
import "server-only";
import {withBillingStore} from "./billing/db";
import {readBillingConfig} from "./billing/policy";

export type FunnelStep="signin_view"|"signin_done"|"checkout_started"|"purchase"|"trial_started";

/** Add one to today's aggregate count (migration 0006). Never fails the
 * request: without billing or the migration, nothing is counted. */
export async function countStep(step:FunnelStep,plan:"monthly"|"yearly"|"trial",test:string|null,variant:string) {
  const config=readBillingConfig(process.env);
  if (!config) return;
  try {await withBillingStore(config,store=>store.countFunnel({step,plan,test,variant}));}
  catch {/* Counting is optional; the funnel report shows the gap. */}
}
