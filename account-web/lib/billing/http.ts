// SPDX-License-Identifier: AGPL-3.0-or-later
import type Stripe from "stripe";
import {billingHeaders,readBillingConfig,type BillingConfig} from "./policy.ts";
import {checkout,portal,processWebhook,eventDescriptor,type BillingStore} from "./service.ts";
export type Dependencies={env:NodeJS.ProcessEnv;getSession:()=>Promise<{user:{sub?:string}}|null>;
  createStripe:(config:BillingConfig)=>Stripe;
  withStore:<T>(accountId:string,callback:(store:BillingStore)=>Promise<T>)=>Promise<T>};
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
export async function ownerAction(request:Request,action:"checkout"|"portal",deps:Dependencies):Promise<Response> {
  if (request.method!=="POST") return reply(405,"Method not allowed.");
  const config=readBillingConfig(deps.env);if(!config) return reply(503,"Sandbox billing setup is pending.");
  if (request.headers.get("origin")!==config.origin || request.headers.get("sec-fetch-site") && request.headers.get("sec-fetch-site")!=="same-origin"
    || new URL(request.url).search) return reply(403,"Request rejected.");
  try {if ((await boundedBody(request,1024)).length!==0) return reply(400,"Request parameters are not accepted.");}
  catch {return reply(400,"Request rejected.");}
  try {
    const session=await deps.getSession();if(!session) return reply(401,"Sign in required.");
    // The customer is always looked up/created from the verified session subject;
    // no browser-supplied customer, price or subject is ever read.
    const subject=session.user.sub;
    if(typeof subject!=="string" || subject!==config.ownerSubject) return reply(403,"Access denied.");
    const url=await deps.withStore(config.accountId,store=>action==="checkout"?checkout(deps.createStripe(config),store,config,subject):portal(deps.createStripe(config),store,config,subject));
    return new Response(null,{status:303,headers:{...billingHeaders,Location:url}});
  } catch {return reply(503,"Sandbox billing is temporarily unavailable.");}
}
export async function webhook(request:Request,deps:Dependencies):Promise<Response> {
  if(request.method!=="POST") return reply(405,"Method not allowed.");
  const config=readBillingConfig(deps.env);if(!config) return reply(503,"Sandbox billing setup is pending.");
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
  try {await deps.withStore(config.accountId,store=>processWebhook(stripe,store,config,event));return reply(200,"Received.");}
  catch {return reply(503,"Event processing is temporarily unavailable.");}
}
