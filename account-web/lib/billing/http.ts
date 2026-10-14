// SPDX-License-Identifier: AGPL-3.0-or-later
import {timingSafeEqual} from "node:crypto";
import type Stripe from "stripe";
import {billingHeaders,maySubscribe,readBillingConfig,type BillingConfig,type PlanKey} from "./policy.ts";
import {BillingConflict,checkout,grantPolicy,portal,processWebhook,eventDescriptor,type BillingStore} from "./service.ts";
import {syncGrants} from "./grant-sync.mjs";
import type {GrantValue} from "./grant-push.mjs";
import {secondFactorRequired} from "../beta-policy.mjs";
export type Dependencies={env:NodeJS.ProcessEnv;getSession:()=>Promise<{user:{sub?:string;mfa?:unknown}}|null>;
  createStripe:(config:BillingConfig)=>Stripe;
  withStore:<T>(config:BillingConfig,callback:(store:BillingStore)=>Promise<T>)=>Promise<T>;
  pushGrant:(config:BillingConfig,value:GrantValue)=>Promise<boolean>};
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
/** Checkout takes exactly `plan=monthly|yearly`; the portal takes no body. */
function planFrom(body:Buffer,contentType:string|null):PlanKey|null {
  if (contentType?.split(";")[0].trim()!=="application/x-www-form-urlencoded") return null;
  const fields=[...new URLSearchParams(body.toString("utf8")).entries()];
  return fields.length===1 && fields[0][0]==="plan" && (fields[0][1]==="monthly" || fields[0][1]==="yearly") ? fields[0][1] : null;
}
export async function accountAction(request:Request,action:"checkout"|"portal",deps:Dependencies):Promise<Response> {
  if (request.method!=="POST") return reply(405,"Method not allowed.");
  const config=readBillingConfig(deps.env);if(!config) return reply(503,"Subscriptions are not available yet.");
  if (request.headers.get("origin")!==config.origin || request.headers.get("sec-fetch-site") && request.headers.get("sec-fetch-site")!=="same-origin"
    || new URL(request.url).search) return reply(403,"Request rejected.");
  let plan:PlanKey|null=null;
  try {
    const body=await boundedBody(request,1024);
    if (action==="checkout") {plan=planFrom(body,request.headers.get("content-type"));if(!plan) return reply(400,"Choose a monthly or yearly plan.");}
    else if (body.length!==0) return reply(400,"Request parameters are not accepted.");
  } catch {return reply(400,"Request rejected.");}
  try {
    const session=await deps.getSession();if(!session) return reply(401,"Sign in required.");
    // The customer is always looked up/created from the verified session subject;
    // no browser-supplied customer, price or subject is ever read.
    const subject=session.user.sub;
    if(!maySubscribe(config,subject) || secondFactorRequired(deps.env) && session.user.mfa!==true) return reply(403,"Access denied.");
    const url=await deps.withStore(config,store=>action==="checkout"
      ?checkout(deps.createStripe(config),store,config,subject,plan!)
      :portal(deps.createStripe(config),store,config,subject));
    return new Response(null,{status:303,headers:{...billingHeaders,Location:url}});
  } catch (error) {
    if (error instanceof BillingConflict) return action==="checkout"
      ? reply(409,"You already have a subscription. Use Manage billing on your account page.")
      : reply(409,"No subscription has been started on this account yet.");
    return reply(503,"Billing is temporarily unavailable. Please try again shortly.");
  }
}
export async function webhook(request:Request,deps:Dependencies):Promise<Response> {
  if(request.method!=="POST") return reply(405,"Method not allowed.");
  const config=readBillingConfig(deps.env);if(!config) return reply(503,"Billing setup is pending.");
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
  try {await deps.withStore(config,store=>processWebhook(stripe,store,config,event,value=>deps.pushGrant(config,value)));return reply(200,"Received.");}
  catch {return reply(503,"Event processing is temporarily unavailable.");}
}
/** Daily Vercel Cron: roll long grants forward and retry undelivered ones. */
export async function refresh(request:Request,deps:Dependencies):Promise<Response> {
  if (request.method!=="GET") return reply(405,"Method not allowed.");
  const config=readBillingConfig(deps.env);if(!config || !config.cronSecret) return reply(503,"Billing setup is pending.");
  const expected=Buffer.from("Bearer "+config.cronSecret), given=Buffer.from(request.headers.get("authorization") ?? "");
  if (given.length!==expected.length || !timingSafeEqual(given,expected) || new URL(request.url).search) return reply(401,"Unauthorized.");
  try {
    const result=await deps.withStore(config,store=>syncGrants(store,grantPolicy(config),value=>deps.pushGrant(config,value)));
    return new Response(JSON.stringify(result),{status:result.failed?503:200,headers:{...billingHeaders,"Content-Type":"application/json"}});
  } catch {return reply(503,"Refresh is temporarily unavailable.");}
}
