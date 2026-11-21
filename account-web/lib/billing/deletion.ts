// SPDX-License-Identifier: AGPL-3.0-or-later
// Account deletion requests (Google Play User Data policy; docs/DATA_RETENTION.md).
// The public page /account/delete explains what is deleted; a signed-in person
// presses "Request deletion", which stores one idempotent row (migration 0008).
// The owner deletes the account and data and marks the request done on the
// admin page. Nothing here deletes data by itself.
import {canUseAccount} from "../beta-policy.mjs";
import {readAuthConfig} from "../policy.mjs";
import {isOwner} from "./admin.ts";
import {boundedBody,type Dependencies} from "./http.ts";
import {billingHeaders,readBillingConfig,reportBillingConfig,subjectReference} from "./policy.ts";

export const DELETE_PAGE="/account/delete";
/** Days within which a request is carried out, as the page promises. */
export const DELETION_DAYS=30;

/** The Auth0 issuer this site signs people in with, as stored with a request. */
export function authIssuer(env:NodeJS.ProcessEnv):string|null {
  const auth=readAuthConfig(env);
  return auth.ok ? "https://"+auth.domain+"/" : null;
}

/** Bounded per-instance abuse control, the same shape as the app trial limiter
 * (docs/PAID_HOSTED.md): the database row stays idempotent whatever gets through.
 * Deployment-wide limits belong at the hosting edge, not in caller-controlled IP headers. */
export function deletionRateLimit(now=()=>Date.now()) {
  const entries=new Map<string,{until:number;count:number}>();
  return (key:string,maximum:number)=>{
    const time=now();
    for (const [name,value] of entries) if (value.until<=time) entries.delete(name);
    const name=subjectReference(key), current=entries.get(name);
    if (!current) {if (entries.size>=4096) return false;entries.set(name,{until:time+60000,count:1});return true;}
    return ++current.count<=maximum;
  };
}

export type DeletionDependencies=Pick<Dependencies,"env"|"getSession"|"withStore"> & {allow:(key:string,maximum:number)=>boolean};

function reply(status:number,message:string) {return new Response(message,{status,headers:billingHeaders});}
function sameOrigin(request:Request,origin:string) {
  return request.headers.get("origin")===origin && (!request.headers.get("sec-fetch-site") || request.headers.get("sec-fetch-site")==="same-origin")
    && !new URL(request.url).search;
}
/** Exactly these urlencoded fields, each once, or null. */
async function formFields(request:Request,names:string[],max=512):Promise<Map<string,string>|null> {
  const body=await boundedBody(request,max);
  if (request.headers.get("content-type")?.split(";")[0].trim()!=="application/x-www-form-urlencoded") return null;
  const fields=new Map<string,string>();
  for (const [name,value] of new URLSearchParams(body.toString("utf8"))) {
    if (fields.has(name) || !names.includes(name)) return null;
    fields.set(name,value);
  }
  return fields.size===names.length ? fields : null;
}
const migrationPending=(error:unknown)=>(error as {code?:unknown})?.code==="MIGRATION_PENDING";
const EMAIL_FALLBACK="Please try again shortly, or email support@usesaiph.com from the address you sign in with and we will delete your account.";

/** `POST /api/account/delete`: exactly `confirm=delete` from the page's own form. */
export async function deletionAction(request:Request,deps:DeletionDependencies):Promise<Response> {
  if (request.method!=="POST") return reply(405,"Method not allowed.");
  const config=readBillingConfig(deps.env), issuer=authIssuer(deps.env);
  if (!config || !issuer) return reportBillingConfig(deps.env), reply(503,"Deletion requests are not available here yet. "+EMAIL_FALLBACK);
  if (!sameOrigin(request,config.origin)) return reply(403,"Request rejected.");
  try {
    const fields=await formFields(request,["confirm"],256);
    if (!fields || fields.get("confirm")!=="delete") return reply(400,"Request deletion from the account deletion page.");
  } catch {return reply(400,"Request rejected.");}
  if (!deps.allow("deletion-requests",120)) return reply(429,"Too many requests just now. Try again in a minute.");
  try {
    const session=await deps.getSession();if (!session) return reply(401,"Sign in required.");
    // The subject comes only from the verified session, never the browser.
    const subject=session.user.sub;
    if (!canUseAccount(subject,deps.env.SAIPH_OWNER_SUBJECT,deps.env,session.user.mfa) || typeof subject!=="string") return reply(403,"Access denied.");
    if (!deps.allow("deletion-subject:"+subject,5)) return reply(429,"Too many requests just now. Try again in a minute.");
    await deps.withStore(config,store=>store.requestDeletion({subject,issuer,now:Math.floor(Date.now()/1000)}));
    // The page reads the stored request again; the query only selects wording.
    return new Response(null,{status:303,headers:{...billingHeaders,Location:config.origin+DELETE_PAGE+"?requested=1"}});
  } catch (error) {
    if (migrationPending(error)) return reply(503,"Deletion requests are not available here yet. "+EMAIL_FALLBACK);
    return reply(503,"Your request could not be saved just now. "+EMAIL_FALLBACK);
  }
}

/** `POST /api/admin/deletion`: exactly `action=done` and `subject`, from the owner admin page. */
export async function adminDeletionAction(request:Request,deps:DeletionDependencies):Promise<Response> {
  if (request.method!=="POST") return reply(405,"Method not allowed.");
  const config=readBillingConfig(deps.env);if (!config) return reportBillingConfig(deps.env), reply(503,"Billing is not configured.");
  if (!sameOrigin(request,config.origin)) return reply(403,"Request rejected.");
  let subject:string;
  try {
    const fields=await formFields(request,["action","subject"],1024);
    if (!fields || fields.get("action")!=="done") return reply(400,"Use the admin page.");
    subject=fields.get("subject")!;
    if (!/^[\x21-\x7e]{1,255}$/.test(subject)) return reply(400,"Use the admin page.");
  } catch {return reply(400,"Request rejected.");}
  // The subject is in the body only; the result page URL never names who.
  const back=(result:string)=>new Response(null,{status:303,headers:{...billingHeaders,Location:config.origin+"/account/admin?deletion="+result}});
  try {
    const session=await deps.getSession();if (!session) return reply(401,"Sign in required.");
    if (!isOwner(config,deps.env,session)) return reply(403,"Access denied.");
    const result=await deps.withStore(config,store=>store.completeDeletion({subject,now:Math.floor(Date.now()/1000)}));
    return back(result.outcome);
  } catch (error) {
    if (migrationPending(error)) return back("migration");
    return reply(503,"The request could not be changed just now. Try again in a minute.");
  }
}
