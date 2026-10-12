// SPDX-License-Identifier: AGPL-3.0-or-later
import {createHash} from "node:crypto";
import {readAuthConfig} from "../policy.mjs";
export type BillingConfig = {secretKey:string; webhookSecret:string; accountId:string; productId:string; priceId:string; portalId:string; origin:string; ownerSubject:string};
export function readBillingConfig(env:NodeJS.ProcessEnv):BillingConfig|null {
  const auth=readAuthConfig(env);
  if (env.SAIPH_BILLING_MODE!=="owner-sandbox" || !auth.ok || !auth.appBaseUrl || !auth.ownerSubject) return null;
  const {STRIPE_SECRET_KEY:secretKey,STRIPE_WEBHOOK_SECRET:webhookSecret,STRIPE_EXPECTED_ACCOUNT_ID:accountId,
    STRIPE_PRODUCT_ID:productId,STRIPE_PRICE_ID:priceId,STRIPE_PORTAL_CONFIGURATION_ID:portalId,DATABASE_URL:databaseUrl}=env;
  if (!secretKey || !/^rk_test_[A-Za-z0-9]+$/.test(secretKey) || !webhookSecret || !/^whsec_[A-Za-z0-9]+$/.test(webhookSecret)
    || !accountId || !/^acct_[A-Za-z0-9]+$/.test(accountId) || !productId || !/^prod_[A-Za-z0-9]+$/.test(productId)
    || !priceId || !/^price_[A-Za-z0-9]+$/.test(priceId) || !portalId || !/^bpc_[A-Za-z0-9]+$/.test(portalId) || !databaseUrl) return null;
  return {secretKey,webhookSecret,accountId,productId,priceId,portalId,origin:auth.appBaseUrl,ownerSubject:auth.ownerSubject};
}
export const webhookPath="/api/stripe/webhook";
export const billingHeaders={"Cache-Control":"private, no-store","Referrer-Policy":"no-referrer"};
export function subjectReference(subject:string) {return createHash("sha256").update(subject).digest("hex");}
export function customerIdempotency(account:string,subject:string) {return "saiph-customer-v1-"+subjectReference(account+":"+subject);}
export function stripeUrl(value:unknown,kind:"checkout"|"portal"):string {
  if (typeof value!=="string") throw new Error("Invalid provider response");
  const url=new URL(value); const host=kind==="checkout"?"checkout.stripe.com":"billing.stripe.com";
  if (url.protocol!=="https:" || url.hostname!==host || url.port || url.username || url.password) throw new Error("Invalid provider response");
  return url.toString();
}
export const acceptedEvents=new Set(["checkout.session.completed","checkout.session.async_payment_succeeded","checkout.session.async_payment_failed",
  "customer.subscription.created","customer.subscription.updated","customer.subscription.deleted","invoice.paid","invoice.payment_failed"]);
export function resourceId(value:unknown,prefix:string):string|null {
  const id=typeof value==="string"?value:value && typeof value==="object" && "id" in value?value.id:null;
  return typeof id==="string" && new RegExp("^"+prefix+"_[A-Za-z0-9]+$").test(id)?id:null;
}
