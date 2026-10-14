// SPDX-License-Identifier: AGPL-3.0-or-later
import {createHash, type KeyObject} from "node:crypto";
import {readAuthConfig} from "../policy.mjs";
import {grantKey} from "./grant-push.mjs";
export type PlanKey="monthly"|"yearly";
export type Plan={key:PlanKey;priceId:string;amount:number;interval:"month"|"year"};
/** Owner-approved prices (14 October 2026), in euro cents. Stripe prices must match exactly. */
export const PLAN_TERMS:Record<PlanKey,{amount:number;interval:"month"|"year"}>={monthly:{amount:399,interval:"month"},yearly:{amount:3600,interval:"year"}};
export type BillingMode="owner-sandbox"|"live";
export type BillingConfig = {mode:BillingMode; livemode:boolean; secretKey:string; webhookSecret:string; accountId:string; productId:string;
  plans:Record<PlanKey,Plan>; portalId:string; origin:string; ownerSubject:string; automaticTax:boolean;
  grant:{origin:string; keyId:string; key:KeyObject; issuer:string}; cronSecret:string|null};
/** HTTPS origin without path, credentials or port, as the Hosted API is configured. */
export function hostedOrigin(value:unknown):string|null {
  try {
    if (typeof value!=="string") return null;
    const url=new URL(value);
    if (url.protocol!=="https:" || url.origin!==value || url.username || url.password || url.port || !url.hostname.includes(".")) return null;
    return value;
  } catch {return null;}
}
/**
 * Billing is off unless SAIPH_BILLING_MODE is exactly "owner-sandbox" (test keys,
 * owner only) or "live" (live keys, any signed-in user), and every prerequisite
 * for the mode is present. Mixed test/live configuration fails closed.
 */
export function readBillingConfig(env:NodeJS.ProcessEnv):BillingConfig|null {
  const auth=readAuthConfig(env);
  const mode=env.SAIPH_BILLING_MODE;
  if ((mode!=="owner-sandbox" && mode!=="live") || !auth.ok || !auth.appBaseUrl || !auth.ownerSubject || !auth.domain) return null;
  const livemode=mode==="live";
  const {STRIPE_SECRET_KEY:secretKey,STRIPE_WEBHOOK_SECRET:webhookSecret,STRIPE_EXPECTED_ACCOUNT_ID:accountId,
    STRIPE_PRODUCT_ID:productId,STRIPE_PRICE_ID:monthlyPrice,STRIPE_YEARLY_PRICE_ID:yearlyPrice,
    STRIPE_PORTAL_CONFIGURATION_ID:portalId,DATABASE_URL:databaseUrl,
    SAIPH_BILLING_GRANT_KEY:encodedKey,SAIPH_BILLING_GRANT_KEY_ID:keyId,CRON_SECRET:cronSecret}=env;
  const keyPattern=livemode?/^rk_live_[A-Za-z0-9]+$/:/^rk_test_[A-Za-z0-9]+$/;
  const grantOrigin=hostedOrigin(env.SAIPH_HOSTED_API_URL);
  if (!secretKey || !keyPattern.test(secretKey) || !webhookSecret || !/^whsec_[A-Za-z0-9]+$/.test(webhookSecret)
    || !accountId || !/^acct_[A-Za-z0-9]+$/.test(accountId) || !productId || !/^prod_[A-Za-z0-9]+$/.test(productId)
    || !monthlyPrice || !/^price_[A-Za-z0-9]+$/.test(monthlyPrice) || !yearlyPrice || !/^price_[A-Za-z0-9]+$/.test(yearlyPrice)
    || monthlyPrice===yearlyPrice || !portalId || !/^bpc_[A-Za-z0-9]+$/.test(portalId) || !databaseUrl
    || !grantOrigin || !keyId || !/^[a-z0-9-]{1,32}$/.test(keyId)
    || (cronSecret!==undefined && cronSecret!=="" && !/^[A-Za-z0-9_-]{32,256}$/.test(cronSecret))) return null;
  let key:KeyObject;
  try {key=grantKey(encodedKey);} catch {return null;}
  const plan=(planKey:PlanKey,priceId:string):Plan=>({key:planKey,priceId,...PLAN_TERMS[planKey]});
  return {mode,livemode,secretKey,webhookSecret,accountId,productId,portalId,origin:auth.appBaseUrl,ownerSubject:auth.ownerSubject,
    plans:{monthly:plan("monthly",monthlyPrice),yearly:plan("yearly",yearlyPrice)},
    automaticTax:env.SAIPH_BILLING_AUTOMATIC_TAX==="true",
    grant:{origin:grantOrigin,keyId,key,issuer:"https://"+auth.domain+"/"},cronSecret:cronSecret||null};
}
/** In sandbox mode only the owner may subscribe (owner decision, 14 October 2026). */
export function maySubscribe(config:BillingConfig,subject:unknown):subject is string {
  return typeof subject==="string" && /^[\x21-\x7e]{1,256}$/.test(subject) && (config.livemode || subject===config.ownerSubject);
}
export function planForPrice(config:BillingConfig,priceId:unknown):Plan|null {
  return Object.values(config.plans).find(plan=>plan.priceId===priceId) ?? null;
}
export const webhookPath="/api/stripe/webhook";
export const refreshPath="/api/billing/refresh";
export const billingHeaders={"Cache-Control":"private, no-store","Referrer-Policy":"no-referrer"};
export function subjectReference(subject:string) {return createHash("sha256").update(subject).digest("hex");}
export function customerIdempotency(account:string,subject:string) {return "saiph-customer-v1-"+subjectReference(account+":"+subject);}
export function stripeUrl(value:unknown,kind:"checkout"|"portal"):string {
  if (typeof value!=="string") throw new Error("Invalid provider response");
  const url=new URL(value); const host=kind==="checkout"?"checkout.stripe.com":"billing.stripe.com";
  if (url.protocol!=="https:" || url.hostname!==host || url.port || url.username || url.password) throw new Error("Invalid provider response");
  return url.toString();
}
export const subscriptionEvents=new Set(["checkout.session.completed","checkout.session.async_payment_succeeded","checkout.session.async_payment_failed",
  "customer.subscription.created","customer.subscription.updated","customer.subscription.deleted","invoice.paid","invoice.payment_failed"]);
export const disputeEvents=new Set(["charge.dispute.created","charge.dispute.updated","charge.dispute.closed"]);
/** Every event type the webhook endpoint must be registered for. */
export const acceptedEvents=new Set([...subscriptionEvents,...disputeEvents]);
export function resourceId(value:unknown,prefix:string):string|null {
  const id=typeof value==="string"?value:value && typeof value==="object" && "id" in value?value.id:null;
  return typeof id==="string" && new RegExp("^"+prefix+"_[A-Za-z0-9]+$").test(id)?id:null;
}
