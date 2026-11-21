// SPDX-License-Identifier: AGPL-3.0-or-later
// Account deletion requests (Google Play User Data policy): the public page's
// request route, the owner's "mark done" route, sign-in returning to the page,
// and that the page and its layout lead nowhere near plans or prices.
// Synthetic only; the Postgres rules are in tests/billing-db.test.mjs.
import {test} from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {generateKeyPairSync} from "node:crypto";
import {adminDeletionAction,authIssuer,deletionAction,deletionRateLimit,DELETE_PAGE} from "../lib/billing/deletion.ts";
import {readBillingConfig} from "../lib/billing/policy.ts";
import {afterSignIn,isDeleteTarget} from "../lib/buy.mjs";

const NOW=1_800_000_000;
const grantKey=generateKeyPairSync("ed25519").privateKey.export({format:"der",type:"pkcs8"}).toString("base64url");
const env={SAIPH_BILLING_MODE:"live",AUTH0_DOMAIN:"synthetic.eu.auth0.com",AUTH0_CLIENT_ID:"syntheticclient",AUTH0_CLIENT_SECRET:"synthetic-not-real",AUTH0_SECRET:"ab".repeat(32),APP_BASE_URL:"https://account.saiph.test",SAIPH_OWNER_SUBJECT:"synthetic|owner",STRIPE_SECRET_KEY:"rk_live_synthetic123",STRIPE_WEBHOOK_SECRET:"whsec_synthetic123",STRIPE_EXPECTED_ACCOUNT_ID:"acct_synthetic",STRIPE_PRODUCT_ID:"prod_synthetic",STRIPE_PRICE_ID:"price_monthly",STRIPE_YEARLY_PRICE_ID:"price_yearly",STRIPE_PORTAL_CONFIGURATION_ID:"bpc_synthetic",DATABASE_URL:"postgresql://synthetic:synthetic@synthetic-pooler.eu-west-2.aws.neon.tech/synthetic?sslmode=require",
  SAIPH_ACCOUNT_MODE:"friends-beta",SAIPH_HOSTED_API_URL:"https://api.saiph.test",SAIPH_HOSTED_API_AUDIENCE:"https://api.saiph.test/",
  SAIPH_BILLING_GRANT_KEY:grantKey,SAIPH_BILLING_GRANT_KEY_ID:"test-1"};
const config=readBillingConfig(env);assert.ok(config);
const person="google-oauth2|person";

// In-memory stand-in for the store's deletion rules (the real ones run in Postgres).
function fixture({renews=false,migrated=true}={}) {
  const rows=new Map();
  const calls=[];
  const pending=()=>{if (!migrated) throw Object.assign(new Error("Billing storage operation rejected"),{code:"MIGRATION_PENDING"});};
  const store={
    async requestDeletion({subject,issuer,now}) {
      pending();calls.push({subject,issuer,now});
      const row=rows.get(subject);
      if (row?.state==="pending") return {outcome:"pending",requestedAt:row.requestedAt,subscriptionRenews:renews};
      rows.set(subject,{issuer,requestedAt:now,state:"pending",completedAt:null});
      return {outcome:"recorded",requestedAt:now,subscriptionRenews:renews};
    },
    async completeDeletion({subject,now}) {
      pending();const row=rows.get(subject);
      if (row?.state!=="pending") return {outcome:"not_found"};
      Object.assign(row,{state:"done",completedAt:now});return {outcome:"done"};
    },
  };
  const deps={env,getSession:async()=>({user:{sub:person}}),withStore:async(cfg,callback)=>callback(store),allow:()=>true};
  return {rows,calls,deps};
}
const post=(path,fields,headers={})=>new Request(config.origin+path,{method:"POST",
  headers:{origin:config.origin,"sec-fetch-site":"same-origin","content-type":"application/x-www-form-urlencoded",...headers},
  body:typeof fields==="string" ? fields : new URLSearchParams(fields).toString()});
const request=(fields,headers)=>post("/api/account/delete",fields,headers);
const admin=(fields,headers)=>post("/api/admin/deletion",fields,headers);

test("a signed-in person's request is stored once, with the verified subject and Auth0 issuer, and shows the confirmation",async(t)=>{
  t.mock.timers.enable({apis:["Date"],now:NOW*1000});
  const f=fixture();
  const first=await deletionAction(request({confirm:"delete"}),f.deps);
  assert.equal(first.status,303);
  assert.equal(first.headers.get("location"),config.origin+"/account/delete?requested=1");
  assert.match(first.headers.get("cache-control"),/no-store/);
  assert.deepEqual(f.calls,[{subject:person,issuer:"https://synthetic.eu.auth0.com/",now:NOW}]);
  t.mock.timers.tick(3600*1000);
  assert.equal((await deletionAction(request({confirm:"delete"}),f.deps)).status,303,"asking again is fine");
  assert.equal(f.rows.size,1);
  assert.equal(f.rows.get(person).requestedAt,NOW,"a pending request keeps its first time");
  assert.equal(authIssuer({...env,AUTH0_DOMAIN:""}),null);
});

test("a renewing subscription is not a reason to refuse: the request is still recorded",async()=>{
  const f=fixture({renews:true});
  assert.equal((await deletionAction(request({confirm:"delete"}),f.deps)).status,303);
  assert.equal(f.rows.get(person).state,"pending");
});

test("only a same-origin POST of exactly confirm=delete from a permitted session",async()=>{
  const f=fixture();
  const ok={confirm:"delete"};
  assert.equal((await deletionAction(new Request(config.origin+"/api/account/delete"),f.deps)).status,405);
  assert.equal((await deletionAction(request(ok,{origin:"https://evil.test"}),f.deps)).status,403);
  assert.equal((await deletionAction(request(ok,{origin:""}),f.deps)).status,403,"missing Origin");
  assert.equal((await deletionAction(request(ok,{"sec-fetch-site":"cross-site"}),f.deps)).status,403);
  assert.equal((await deletionAction(post("/api/account/delete?subject=x",ok),f.deps)).status,403,"no query");
  assert.equal((await deletionAction(request({confirm:"yes"}),f.deps)).status,400);
  assert.equal((await deletionAction(request("confirm=delete&confirm=delete"),f.deps)).status,400,"repeated field");
  assert.equal((await deletionAction(request({confirm:"delete",subject:"google-oauth2|victim"}),f.deps)).status,400,"no browser-supplied subject");
  assert.equal((await deletionAction(request(ok,{"content-type":"text/plain"}),f.deps)).status,400);
  assert.equal((await deletionAction(request("confirm=delete&"+"x".repeat(400)),f.deps)).status,400,"bounded body");
  assert.equal((await deletionAction(request(ok),{...f.deps,getSession:async()=>null})).status,401);
  assert.equal((await deletionAction(request(ok),{...f.deps,env:{...env,SAIPH_ACCOUNT_MODE:""}})).status,403,"not permitted on an owner-only site");
  assert.equal((await deletionAction(request(ok),{...f.deps,env:{...env,SAIPH_REQUIRE_MFA:"true"}})).status,403,"second factor when required");
  assert.equal(f.calls.length,0,"nothing was stored");
});

test("rate limits answer 429 before storing, per instance and per subject",async(t)=>{
  t.mock.timers.enable({apis:["Date"],now:NOW*1000});
  const f=fixture();
  const allow=deletionRateLimit();
  const deps={...f.deps,allow};
  for (let i=0;i<5;i++) assert.equal((await deletionAction(request({confirm:"delete"}),deps)).status,303);
  const limited=await deletionAction(request({confirm:"delete"}),deps);
  assert.equal(limited.status,429);
  assert.equal(f.calls.length,5);
  const other={...deps,getSession:async()=>({user:{sub:"google-oauth2|other"}})};
  assert.equal((await deletionAction(request({confirm:"delete"}),other)).status,303,"someone else is not limited by that");
  t.mock.timers.tick(60_001);
  assert.equal((await deletionAction(request({confirm:"delete"}),deps)).status,303,"the window passes");
  let time=0;const global=deletionRateLimit(()=>time);
  for (let i=0;i<120;i++) assert.equal(global("deletion-requests",120),true);
  assert.equal(global("deletion-requests",120),false);
  time=60_000;assert.equal(global("deletion-requests",120),true);
});

test("billing off or migration 0008 missing: a clear 503 that points to email, never a SQL error",async()=>{
  const off=await deletionAction(request({confirm:"delete"}),{...fixture().deps,env:{...env,SAIPH_BILLING_MODE:"disabled"}});
  assert.equal(off.status,503);assert.match(await off.text(),/support@usesaiph\.com/);
  const unmigrated=await deletionAction(request({confirm:"delete"}),fixture({migrated:false}).deps);
  assert.equal(unmigrated.status,503);assert.match(await unmigrated.text(),/support@usesaiph\.com/);
  const failing=await deletionAction(request({confirm:"delete"}),{...fixture().deps,withStore:async()=>{throw new Error("connect ECONNREFUSED 10.0.0.1");}});
  assert.equal(failing.status,503);assert.doesNotMatch(await failing.text(),/ECONNREFUSED/);
});

test("the owner marks a pending request done; the result URL never names who",async(t)=>{
  t.mock.timers.enable({apis:["Date"],now:NOW*1000});
  const f=fixture();
  await deletionAction(request({confirm:"delete"}),f.deps);
  const owner={...f.deps,getSession:async()=>({user:{sub:config.ownerSubject}})};
  const done=await adminDeletionAction(admin({action:"done",subject:person}),owner);
  assert.equal(done.status,303);
  assert.equal(done.headers.get("location"),config.origin+"/account/admin?deletion=done");
  assert.deepEqual(f.rows.get(person),{issuer:"https://synthetic.eu.auth0.com/",requestedAt:NOW,state:"done",completedAt:NOW});
  assert.equal((await adminDeletionAction(admin({action:"done",subject:person}),owner)).headers.get("location"),config.origin+"/account/admin?deletion=not_found");
  assert.equal((await adminDeletionAction(admin({action:"done",subject:person}),{...owner,withStore:fixture({migrated:false}).deps.withStore})).headers.get("location"),
    config.origin+"/account/admin?deletion=migration");
});

test("only the owner, same-origin, with exactly the admin form's fields, can mark a request done",async()=>{
  const f=fixture();
  await deletionAction(request({confirm:"delete"}),f.deps);
  const owner={...f.deps,getSession:async()=>({user:{sub:config.ownerSubject}})};
  const fields={action:"done",subject:person};
  assert.equal((await adminDeletionAction(admin(fields),f.deps)).status,403,"the person themselves cannot");
  assert.equal((await adminDeletionAction(admin(fields),{...owner,getSession:async()=>null})).status,401);
  assert.equal((await adminDeletionAction(admin(fields),{...owner,env:{...env,SAIPH_REQUIRE_MFA:"true"}})).status,403);
  assert.equal((await adminDeletionAction(admin(fields,{origin:"https://evil.test"}),owner)).status,403);
  assert.equal((await adminDeletionAction(admin({action:"delete",subject:person}),owner)).status,400);
  assert.equal((await adminDeletionAction(admin({action:"done"}),owner)).status,400);
  assert.equal((await adminDeletionAction(admin({...fields,extra:"1"}),owner)).status,400);
  assert.equal((await adminDeletionAction(admin({action:"done",subject:"two words"}),owner)).status,400);
  assert.equal((await adminDeletionAction(new Request(config.origin+"/api/admin/deletion"),owner)).status,405);
  assert.equal(f.rows.get(person).state,"pending","nothing changed");
});

test("sign-in from the deletion page comes straight back to it, not to the account page with its plans",()=>{
  const origin="https://account.saiph.test";
  assert.equal(DELETE_PAGE,"/account/delete");
  assert.equal(afterSignIn("/account/delete",origin).href,origin+"/account/delete");
  assert.equal(afterSignIn(origin+"/account/delete",origin).href,origin+"/account/delete");
  for (const other of ["/account/delete?x=1","/account/delete#x","https://evil.test/account/delete","/account/deleted","//evil.test/account/delete"]) {
    assert.equal(isDeleteTarget(other,origin),false,other);
    assert.equal(afterSignIn(other,origin).href,origin+"/account",other);
  }
});

test("the deletion page says what is deleted, when, and to cancel first, and links to no plan, price or purchase",async()=>{
  const page=await readFile(new URL("../app/account/delete/page.tsx",import.meta.url),"utf8");
  for (const fact of [/Auth0/,/Saiph Cloud account/,/device records/,/encrypted content/,/Billing records/,/tax law requires/,
    /Cancel any subscription first/,/Manage billing/,/DELETION_DAYS/,/Request deletion/]) assert.match(page,fact);
  const links=[...page.matchAll(/(?:href|action)=["{]([^"}]+)["}]/g)].map(match=>match[1]);
  assert.deepEqual(links.sort(),["/account/delete/sign-in","/api/account/delete"]);
  assert.doesNotMatch(page,/\/buy|\/trial|hosted\.html|pricing|€|\/api\/billing/i);
  assert.doesNotMatch(page,/<Link|SignOut|next\/link/,"no client links, and no sign-out (it returns to the home page)");
  const sign=await readFile(new URL("../app/account/delete/sign-in/route.ts",import.meta.url),"utf8");
  assert.match(sign,/returnTo: "\/account\/delete"/);
  // The layout's plain branch for this page has no navigation and no links but the skip link.
  const layout=await readFile(new URL("../app/layout.tsx",import.meta.url),"utf8");
  const plain=layout.slice(layout.indexOf("if (plain) return ("),layout.indexOf("  return (\n    <html"));
  assert.ok(plain.length>100);
  assert.deepEqual([...plain.matchAll(/href=["{]([^"}]+)["}]/g)].map(match=>match[1]),["#main"]);
  assert.doesNotMatch(plain,/<Link|<nav/);
  const proxy=await readFile(new URL("../proxy.ts",import.meta.url),"utf8");
  assert.match(proxy,/\["x-saiph-chrome", deletionPage \? "plain" : "full"\]/,"the proxy always sets the layout header itself");
});
