// SPDX-License-Identifier: AGPL-3.0-or-later
import "server-only";
import {withBillingStore} from "./db";
import {deriveEntitlement,type Entitlement} from "./entitlement.mjs";
import {maySubscribe,planForPrice,readBillingConfig,reportBillingConfig,type BillingMode} from "./policy";
import {subscriptionSummary} from "./presentation.mjs";
import {readTrialConfig,trialDecision,type TrialState} from "./trial.mjs";

type StoredRow={status:string;priceId:string;currentPeriodEnd:number|null;cancelAtPeriodEnd:boolean};
export type TrialView={state:TrialState;days:number;endsAt:number|null;daysLeft:number|null};
export type BillingView={mode:BillingMode;standing:Entitlement;subscriptions:{label:string;period:string}[];
  hasCustomer:boolean;canSubscribe:boolean;trial:TrialView};

/** Subscription panel data from webhook-stored rows only. `null` when this user
 * is not offered subscriptions (billing off, or sandbox and not the owner);
 * "unavailable" when storage cannot be read. Never reads the checkout return. */
export async function billingView(subject:unknown,trialKey?:unknown):Promise<BillingView|null|"unavailable"> {
  const config=readBillingConfig(process.env);
  if (!config) {reportBillingConfig(process.env);return null;}
  if (!maySubscribe(config,subject)) return null;
  try {
    return await withBillingStore(config,async(store)=>{
      const customer=await store.findCustomer(subject);
      const snapshots=customer?await store.listSubscriptions(subject):[];
      const disputed=customer?await store.hasBlockingDispute(subject):false;
      const now=Math.floor(Date.now()/1000);
      const standing=deriveEntitlement(snapshots,now,{disputed});
      const trialConfig=readTrialConfig(process.env);
      const emailKey=typeof trialKey==="string"?trialKey:null;
      // Without migration 0004 the trial is simply off; the rest of the page still works.
      const facts=await store.trialFacts(subject,emailKey).catch(()=>null);
      const decision=facts ? trialDecision({config:trialConfig,stored:facts.stored,emailKey,emailUsed:facts.emailUsed,subscribed:facts.subscribed,started:facts.started,now})
        : {state:"off" as const,endsAt:null,daysLeft:null};
      return {mode:config.mode,standing,hasCustomer:Boolean(customer),trial:{...decision,days:trialConfig?.days ?? 0},
        // Checkout refuses while any subscription is not finished; mirror that here.
        canSubscribe:snapshots.every((s:StoredRow)=>s.status==="canceled" || s.status==="incomplete_expired"),
        subscriptions:snapshots.map((s:StoredRow)=>subscriptionSummary(s,{test:!config.livemode,plan:planForPrice(config,s.priceId)?.key ?? null}))};
    });
  } catch {return "unavailable";}
}
