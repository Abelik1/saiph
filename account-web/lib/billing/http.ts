// SPDX-License-Identifier: AGPL-3.0-or-later
import {timingSafeEqual} from "node:crypto";
import type Stripe from "stripe";
import {billingHeaders,maySubscribe,readBillingConfig,reportBillingConfig,subjectReference,type BillingConfig,type PlanKey} from "./policy.ts";
import {BillingConflict,TrialUnavailable,WithdrawalUnavailable,checkout,grantPolicy,portal,processWebhook,eventDescriptor,startTrial,withdraw,type BillingStore} from "./service.ts";
import {checkTrialConfig,validEmailKey} from "./trial.mjs";
import {syncGrants} from "./grant-sync.mjs";
import type {GrantValue} from "./grant-push.mjs";
import {secondFactorRequired} from "../beta-policy.mjs";
import {readConsent,readGaConfig,sendEvent} from "../ga.mjs";
import {resolveOffer} from "./price-test.mjs";
export type Dependencies={env:NodeJS.ProcessEnv;getSession:()=>Promise<{user:{sub?:string;mfa?:unknown;trialKey?:unknown}}|null>;
  createStripe:(config:BillingConfig)=>Stripe;
  withStore:<T>(config:BillingConfig,callback:(store:BillingStore)=>Promise<T>)=>Promise<T>;
  pushGrant:(config:BillingConfig,value:GrantValue)=>Promise<boolean>;
  /** Google Analytics Measurement Protocol transport; tests pass a recorder. */
  analyticsFetch?:typeof fetch};
function reply(status:number,message:string) {return new Response(message,{status,headers:billingHeaders});}
export async function boundedBody(request:Request,max:number) {
  const length=request.headers.get("content-length");
  if (length && (!/^\d+$/.test(length) || Number(length)>max)) throw new Error("Body rejected");
  const reader=request.body?.getReader();if (!reader) return Buffer.alloc(0);
  const chunks:Uint8Array[]=[];let total=0;
  try {while (true) {const chunk=await reader.read();if (chunk.done) break;total+=chunk.value.byteLength;if(total>max) throw new Error("Body rejected");chunks.push(chunk.value);}}
  catch {await reader.cancel().catch(()=>{});throw new Error("Body rejected");}
  finally {reader.releaseLock();}
  return Buffer.concat(chunks,total);
}
/** Checkout takes exactly `plan=monthly|yearly`, optionally followed by a
 * price-test `offer=a|b|c|d`; the portal takes no body. */
function planFrom(body:Buffer,contentType:string|null):{plan:PlanKey;offer:string|null}|null {
  if (contentType?.split(";")[0].trim()!=="application/x-www-form-urlencoded") return null;
  const fields=[...new URLSearchParams(body.toString("utf8")).entries()];
  if (fields.length<1 || fields.length>2 || fields[0][0]!=="plan" || (fields[0][1]!=="monthly" && fields[0][1]!=="yearly")) return null;
  if (fields.length===2 && (fields[1][0]!=="offer" || !/^[a-d]$/.test(fields[1][1]))) return null;
  return {plan:fields[0][1],offer:fields[1]?.[1] ?? null};
}
/** Optional funnel counting (migration 0006): never fails the request. */
async function count(deps:Dependencies,config:BillingConfig,step:"checkout_started"|"purchase"|"trial_started",plan:PlanKey|"trial",test:string|null,variant:string) {
  try {await deps.withStore(config,store=>store.countFunnel({step,plan,test,variant}));} catch {/* optional */}
}
export async function accountAction(request:Request,action:"checkout"|"portal",deps:Dependencies):Promise<Response> {
  if (request.method!=="POST") return reply(405,"Method not allowed.");
  const config=readBillingConfig(deps.env);if(!config) return reportBillingConfig(deps.env), reply(503,"Subscriptions are not available yet.");
  if (request.headers.get("origin")!==config.origin || request.headers.get("sec-fetch-site") && request.headers.get("sec-fetch-site")!=="same-origin"
    || new URL(request.url).search) return reply(403,"Request rejected.");
  let chosen:{plan:PlanKey;offer:string|null}|null=null;
  try {
    const body=await boundedBody(request,1024);
    if (action==="checkout") {chosen=planFrom(body,request.headers.get("content-type"));if(!chosen) return reply(400,"Choose a monthly or yearly plan.");}
    else if (body.length!==0) return reply(400,"Request parameters are not accepted.");
  } catch {return reply(400,"Request rejected.");}
  try {
    const session=await deps.getSession();if(!session) return reply(401,"Sign in required.");
    // The customer is always looked up/created from the verified session subject;
    // no browser-supplied customer, price or subject is ever read.
    const subject=session.user.sub;
    if(!maySubscribe(config,subject) || secondFactorRequired(deps.env) && session.user.mfa!==true) return reply(403,"Access denied.");
    if (action==="portal") {
      const url=await deps.withStore(config,store=>portal(deps.createStripe(config),store,config,subject));
      return new Response(null,{status:303,headers:{...billingHeaders,Location:url}});
    }
    // The price-test variant only selects among configured prices; an unknown
    // one gets the standard price, exactly as the Buy page showed it.
    const {test,variant}=resolveOffer(config.priceTest,chosen!.offer);
    // Analytics only for a visitor who pressed Accept on usesaiph.com, and only
    // Google's own client ID from that cookie: nothing about the account.
    const ga=readGaConfig(deps.env);
    const consent=ga?readConsent(request.headers.get("cookie")):{granted:false,clientId:null};
    const clientId=consent.granted?consent.clientId:null;
    const url=await deps.withStore(config,store=>checkout(deps.createStripe(config),store,config,subject,chosen!.plan,{variant,test,analyticsClientId:clientId}));
    await count(deps,config,"checkout_started",chosen!.plan,test,variant);
    await sendEvent(ga,clientId,"begin_checkout",{plan:chosen!.plan,currency:"EUR",
      ...(test?{price_test:test,price_variant:variant}:{})},deps.analyticsFetch);
    return new Response(null,{status:303,headers:{...billingHeaders,Location:url}});
  } catch (error) {
    if (error instanceof BillingConflict) return action==="checkout"
      ? reply(409,"You already have a subscription. Use Manage billing on your account page.")
      : reply(409,"No subscription has been started on this account yet.");
    return reply(503,"Billing is temporarily unavailable. Please try again shortly.");
  }
}
/** EU withdrawal confirmation: exactly `confirm=withdraw` from the account's own form. */
export async function withdrawAction(request:Request,deps:Dependencies):Promise<Response> {
  if (request.method!=="POST") return reply(405,"Method not allowed.");
  const config=readBillingConfig(deps.env);if(!config) return reportBillingConfig(deps.env), reply(503,"Subscriptions are not available yet.");
  if (request.headers.get("origin")!==config.origin || request.headers.get("sec-fetch-site") && request.headers.get("sec-fetch-site")!=="same-origin"
    || new URL(request.url).search) return reply(403,"Request rejected.");
  try {
    const body=await boundedBody(request,256);
    const fields=request.headers.get("content-type")?.split(";")[0].trim()==="application/x-www-form-urlencoded"
      ? [...new URLSearchParams(body.toString("utf8")).entries()] : [];
    if (fields.length!==1 || fields[0][0]!=="confirm" || fields[0][1]!=="withdraw") return reply(400,"Confirm the withdrawal on your account page.");
  } catch {return reply(400,"Request rejected.");}
  try {
    const session=await deps.getSession();if(!session) return reply(401,"Sign in required.");
    const subject=session.user.sub;
    if(!maySubscribe(config,subject) || secondFactorRequired(deps.env) && session.user.mfa!==true) return reply(403,"Access denied.");
    await deps.withStore(config,store=>withdraw(deps.createStripe(config),store,config,subject));
    // The page re-reads the outcome from Stripe; the query only selects wording.
    return new Response(null,{status:303,headers:{...billingHeaders,Location:config.origin+"/account/withdraw?done=1"}});
  } catch (error) {
    if (error instanceof WithdrawalUnavailable) return reply(409,"There is no subscription within its 14-day withdrawal period on this account.");
    return reply(503,"Withdrawal is temporarily unavailable. Please try again shortly or contact support@usesaiph.com.");
  }
}
/** Free trial: exactly `trial=start` from the account's own form, no card. */
export async function trialAction(request:Request,deps:Dependencies):Promise<Response> {
  if (request.method!=="POST") return reply(405,"Method not allowed.");
  const config=readBillingConfig(deps.env);if(!config) return reportBillingConfig(deps.env), reply(503,"Free trials are not available yet.");
  const {config:trial,problems}=checkTrialConfig(deps.env);
  if (!trial) {if (problems.length) console.error("Free trials are off; these settings were rejected: "+problems.join(", "));return reply(503,"Free trials are not available right now.");}
  if (request.headers.get("origin")!==config.origin || request.headers.get("sec-fetch-site") && request.headers.get("sec-fetch-site")!=="same-origin"
    || new URL(request.url).search) return reply(403,"Request rejected.");
  try {
    const body=await boundedBody(request,256);
    const fields=request.headers.get("content-type")?.split(";")[0].trim()==="application/x-www-form-urlencoded"
      ? [...new URLSearchParams(body.toString("utf8")).entries()] : [];
    if (fields.length!==1 || fields[0][0]!=="trial" || fields[0][1]!=="start") return reply(400,"Start the trial from your account page.");
  } catch {return reply(400,"Request rejected.");}
  try {
    const session=await deps.getSession();if(!session) return reply(401,"Sign in required.");
    const subject=session.user.sub;
    if(!maySubscribe(config,subject) || secondFactorRequired(deps.env) && session.user.mfa!==true) return reply(403,"Access denied.");
    // The email key comes only from the verified sign-in (lib/auth.ts), never the browser.
    const emailKey=session.user.trialKey;
    if (!validEmailKey(emailKey)) return reply(401,"Sign out and sign in again to start your free trial.");
    const before=Math.floor(Date.now()/1000);
    const started=await deps.withStore(config,store=>startTrial(store,config,trial,subject,emailKey as string,value=>deps.pushGrant(config,value)));
    // Count a trial once, when it really starts (pressing again returns the same trial).
    if (started.startedAt>=before-5) {
      await count(deps,config,"trial_started","trial",null,"a");
      const ga=readGaConfig(deps.env);
      const consent=ga?readConsent(request.headers.get("cookie")):{granted:false,clientId:null};
      await sendEvent(ga,consent.granted?consent.clientId:null,"trial_start",{plan:"trial"},deps.analyticsFetch);
    }
    return new Response(null,{status:303,headers:{...billingHeaders,Location:config.origin+"/account?trial=started"}});
  } catch (error) {
    if (error instanceof TrialUnavailable) return reply(409,{
      subscribed:"This account already has a subscription, so it does not need a free trial.",
      used:"A free trial has already been used with this email address. Subscribe on your account page to continue.",
      full:"All free trial places have been taken. You can still subscribe on your account page.",
    }[error.state]);
    return reply(503,"Your trial could not be activated just now. Press Start free trial again in a minute; you will not get a second trial or lose days.");
  }
}
export async function webhook(request:Request,deps:Dependencies):Promise<Response> {
  if(request.method!=="POST") return reply(405,"Method not allowed.");
  const config=readBillingConfig(deps.env);if(!config) return reportBillingConfig(deps.env), reply(503,"Billing setup is pending.");
  if (new URL(request.url).search || request.headers.get("content-type")?.split(";")[0].trim()!=="application/json") return reply(400,"Event rejected.");
  const signature=request.headers.get("stripe-signature");
  if (!signature || signature.length>4096) return reply(400,"Event rejected.");
  let raw:Buffer;try {raw=await boundedBody(request,262144);} catch {return reply(413,"Event body rejected.");}
  let event:Stripe.Event;let stripe:Stripe;
  try {
    stripe=deps.createStripe(config);
    // SDK checks signature and old timestamps. Explicitly reject future timestamps as well.
    const timestamps=signature.split(",").filter(s=>s.startsWith("t="));
    const timestamp=timestamps[0]?.slice(2);
    if(timestamps.length!==1 || !timestamp || !/^\d+$/.test(timestamp) || Math.abs(Date.now()/1000-Number(timestamp))>300) return reply(400,"Event rejected.");
    event=stripe.webhooks.constructEvent(raw,signature,config.webhookSecret,300);
  } catch {return reply(400,"Event rejected.");}
  try {eventDescriptor(event,config);} catch {return reply(400,"Event rejected.");}
  // A 503 makes Stripe retry; the retry is a duplicate for the ledger but still
  // delivers any grant the Hosted service has not accepted yet.
  // A completed Checkout is counted once, when its event is first applied
  // (before grant delivery, so a Stripe retry never counts it twice).
  const purchased=async(applied:{outcome?:string})=>{
    const purchase=purchaseFrom(event,config,applied);if (!purchase) return;
    await count(deps,config,"purchase",purchase.plan,purchase.test,purchase.variant);
    await sendEvent(readGaConfig(deps.env),purchase.clientId,"purchase",{plan:purchase.plan,currency:"EUR",value:purchase.value,
      transaction_id:purchase.transactionId,...(purchase.test?{price_test:purchase.test,price_variant:purchase.variant}:{})},deps.analyticsFetch);
  };
  try {await deps.withStore(config,store=>processWebhook(stripe,store,config,event,value=>deps.pushGrant(config,value),purchased));return reply(200,"Received.");}
  catch {return reply(503,"Event processing is temporarily unavailable.");}
}
/** What a newly applied `checkout.session.completed` says about the purchase,
 * for counting only. Its metadata was written by our own checkout (service.ts). */
export function purchaseFrom(event:Stripe.Event,config:BillingConfig,applied:{outcome?:string}) {
  if (event.type!=="checkout.session.completed" || applied.outcome!=="applied") return null;
  const session=event.data.object as Stripe.Checkout.Session;
  if (session.mode!=="subscription" || session.status!=="complete") return null;
  const meta=session.metadata ?? {};
  const plan=meta.saiph_plan==="monthly" || meta.saiph_plan==="yearly" ? meta.saiph_plan : null;
  if (!plan) return null;
  const {test,variant}=resolveOffer(config.priceTest,meta.saiph_price_test && meta.saiph_price_test===config.priceTest?.id ? meta.saiph_variant : undefined);
  return {plan:plan as PlanKey,test,variant,value:typeof session.amount_total==="number"?session.amount_total/100:0,
    clientId:typeof meta.saiph_ga==="string"?meta.saiph_ga:null,
    transactionId:subjectReference("purchase:"+session.id).slice(0,32)};
}
/** Daily Vercel Cron: roll long grants forward and retry undelivered ones. */
export async function refresh(request:Request,deps:Dependencies):Promise<Response> {
  if (request.method!=="GET") return reply(405,"Method not allowed.");
  const config=readBillingConfig(deps.env);if(!config || !config.cronSecret) return reportBillingConfig(deps.env), reply(503,"Billing setup is pending.");
  const expected=Buffer.from("Bearer "+config.cronSecret), given=Buffer.from(request.headers.get("authorization") ?? "");
  if (given.length!==expected.length || !timingSafeEqual(given,expected) || new URL(request.url).search) return reply(401,"Unauthorized.");
  try {
    const result=await deps.withStore(config,store=>syncGrants(store,grantPolicy(config),value=>deps.pushGrant(config,value)));
    return new Response(JSON.stringify(result),{status:result.failed?503:200,headers:{...billingHeaders,"Content-Type":"application/json"}});
  } catch {return reply(503,"Refresh is temporarily unavailable.");}
}
