// SPDX-License-Identifier: AGPL-3.0-or-later
// Owner-only trial administration (docs/PAID_HOSTED.md, "Extending a trial"). The
// owner types a person's address; only its keyed hash is used to find the trial,
// and the address is never stored, logged or put into a URL.
import {billingHeaders,readBillingConfig,reportBillingConfig,type BillingConfig} from "./policy.ts";
import {grantPolicy,type BillingStore} from "./service.ts";
import {checkTrialConfig,emailKeyFor} from "./trial.mjs";
import {syncGrants} from "./grant-sync.mjs";
import type {GrantValue} from "./grant-push.mjs";
import {secondFactorRequired} from "../beta-policy.mjs";
import {boundedBody,type Dependencies} from "./http.ts";

type Session={user:{sub?:string;mfa?:unknown}}|null;

/** Only the configured owner, with a completed second factor when the site requires one. */
export function isOwner(config:Pick<BillingConfig,"ownerSubject">,env:NodeJS.ProcessEnv,session:Session) {
  return !!session && session.user.sub===config.ownerSubject && (!secondFactorRequired(env) || session.user.mfa===true);
}

/**
 * Add days to the trial started with this address and deliver the new end at once.
 * A failed delivery keeps the extension; the daily refresh delivers it.
 */
export async function extendTrialFor(store:BillingStore,config:BillingConfig,emailKey:string,days:number,
  push:(value:GrantValue)=>Promise<boolean>,now=Math.floor(Date.now()/1000)) {
  const result=await store.extendTrial({emailKey,days,now});
  if (result.outcome!=="extended") return {...result,delivered:false};
  const delivery=await syncGrants(store,grantPolicy(config),push,{subject:result.trial.subject});
  return {...result,delivered:!delivery.failed};
}

function reply(status:number,message:string) {return new Response(message,{status,headers:billingHeaders});}
function back(origin:string,query:Record<string,string|number>) {
  return new Response(null,{status:303,headers:{...billingHeaders,Location:origin+"/account/admin?"+new URLSearchParams(
    Object.entries(query).map(([key,value])=>[key,String(value)]))}});
}

/** `POST /api/admin/trial`: exactly `action=lookup|extend`, `email`, and `days` (1-30, extend only). */
export async function adminTrialAction(request:Request,deps:Dependencies):Promise<Response> {
  if (request.method!=="POST") return reply(405,"Method not allowed.");
  const config=readBillingConfig(deps.env);if(!config) return reportBillingConfig(deps.env), reply(503,"Billing is not configured.");
  const {config:trial}=checkTrialConfig(deps.env);if(!trial) return reply(503,"Free trials are off.");
  if (request.headers.get("origin")!==config.origin || request.headers.get("sec-fetch-site") && request.headers.get("sec-fetch-site")!=="same-origin"
    || new URL(request.url).search) return reply(403,"Request rejected.");
  let action:string,email:string,daysText:string;
  try {
    const body=await boundedBody(request,1024);
    if (request.headers.get("content-type")?.split(";")[0].trim()!=="application/x-www-form-urlencoded") return reply(400,"Use the admin page.");
    const fields=new Map<string,string>();
    for (const [name,value] of new URLSearchParams(body.toString("utf8"))) {
      if (fields.has(name) || !["action","email","days"].includes(name)) return reply(400,"Use the admin page.");
      fields.set(name,value);
    }
    action=fields.get("action") ?? "";email=fields.get("email") ?? "";daysText=(fields.get("days") ?? "").trim();
  } catch {return reply(400,"Request rejected.");}
  try {
    const session=await deps.getSession();if(!session) return reply(401,"Sign in required.");
    if (!isOwner(config,deps.env,session)) return reply(403,"Access denied.");
    const emailKey=emailKeyFor(email,trial);
    if (!emailKey) return back(config.origin,{result:"invalid_email"});
    if (action==="lookup") {
      const found=await deps.withStore(config,store=>store.trialByEmail(emailKey));
      return back(config.origin,found ? {result:"found",started:found.startedAt,until:found.endsAt} : {result:"not_found"});
    }
    if (action!=="extend") return reply(400,"Use the admin page.");
    const days=/^\d{1,2}$/.test(daysText) ? Number(daysText) : NaN;
    if (!(days>=1 && days<=30)) return back(config.origin,{result:"invalid_days"});
    const result=await deps.withStore(config,store=>extendTrialFor(store,config,emailKey,days,value=>deps.pushGrant(config,value)));
    if (result.outcome==="not_found") return back(config.origin,{result:"not_found"});
    if (result.outcome==="too_long") return back(config.origin,{result:"too_long",until:result.trial.endsAt,max:result.extendable});
    return back(config.origin,{result:result.delivered ? "extended" : "extended_pending",from:result.previousEnd,until:result.trial.endsAt});
  } catch (error) {
    if ((error as {code?:unknown})?.code==="MIGRATION_PENDING") return back(config.origin,{result:"migration"});
    return reply(503,"The trial could not be changed just now. Try again in a minute.");
  }
}
