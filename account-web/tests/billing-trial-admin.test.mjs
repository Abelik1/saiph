// SPDX-License-Identifier: AGPL-3.0-or-later
// Owner extensions of a free trial (docs/PAID_HOSTED.md, "Extending a trial"): the
// extension rules, and the owner-only admin route that finds a trial by address and
// pushes the new end. Synthetic only; the Postgres rules are in tests/billing-db.test.mjs.
import {test} from "node:test";
import assert from "node:assert/strict";
import {generateKeyPairSync} from "node:crypto";
import {adminTrialAction} from "../lib/billing/admin.ts";
import {readBillingConfig} from "../lib/billing/policy.ts";
import {emailKeyFor,extendableDays,extendedTrialEnd,trialEmailKey} from "../lib/billing/trial.mjs";

const NOW=1_800_000_000, DAY=86400;
const grantKey=generateKeyPairSync("ed25519").privateKey.export({format:"der",type:"pkcs8"}).toString("base64url");
const secret="t".repeat(40);
const env={SAIPH_BILLING_MODE:"live",AUTH0_DOMAIN:"synthetic.us.auth0.com",AUTH0_CLIENT_ID:"syntheticclient",AUTH0_CLIENT_SECRET:"synthetic-not-real",AUTH0_SECRET:"ab".repeat(32),APP_BASE_URL:"https://account.saiph.test",SAIPH_OWNER_SUBJECT:"synthetic|owner",STRIPE_SECRET_KEY:"rk_live_synthetic123",STRIPE_WEBHOOK_SECRET:"whsec_synthetic123",STRIPE_EXPECTED_ACCOUNT_ID:"acct_synthetic",STRIPE_PRODUCT_ID:"prod_synthetic",STRIPE_PRICE_ID:"price_monthly",STRIPE_YEARLY_PRICE_ID:"price_yearly",STRIPE_PORTAL_CONFIGURATION_ID:"bpc_synthetic",DATABASE_URL:"postgresql://synthetic:synthetic@synthetic-pooler.eu-west-2.aws.neon.tech/synthetic?sslmode=require",
  SAIPH_HOSTED_API_URL:"https://api.saiph.test",SAIPH_BILLING_GRANT_KEY:grantKey,SAIPH_BILLING_GRANT_KEY_ID:"test-1",SAIPH_TRIAL_SECRET:secret,SAIPH_TRIAL_DAYS:"30"};
const config=readBillingConfig(env);assert.ok(config);
const owner=config.ownerSubject;
const trialConfig={days:30,cap:null,secret};
const address="Some.Person+saiph@gmail.com";
const key=emailKeyFor(address,trialConfig);

test("extensions count from the current end, or from now once ended, and never reach past 30 days ahead",()=>{
  assert.equal(extendedTrialEnd(NOW+5*DAY,7,NOW),NOW+12*DAY);
  assert.equal(extendedTrialEnd(NOW-10*DAY,7,NOW),NOW+7*DAY,"an ended trial restarts from now");
  assert.equal(extendedTrialEnd(NOW+25*DAY,5,NOW),NOW+30*DAY,"exactly 30 days ahead is allowed");
  assert.equal(extendedTrialEnd(NOW+25*DAY,6,NOW),null);
  for (const days of [0,-1,31,1.5,NaN]) assert.equal(extendedTrialEnd(NOW,days,NOW),null,String(days));
  assert.equal(extendableDays(NOW+25*DAY,NOW),5);
  assert.equal(extendableDays(NOW-DAY,NOW),30);
  assert.equal(extendableDays(NOW+30*DAY,NOW),0);
});

test("the address the owner types finds the same key as the person's verified sign-in",()=>{
  assert.match(key,/^[a-f0-9]{64}$/);
  assert.equal(key,trialEmailKey({email:"someperson@googlemail.com",email_verified:true},trialConfig),"aliases of one mailbox match");
  assert.equal(emailKeyFor("not an address",trialConfig),null);
  assert.equal(emailKeyFor(address,null),null,"no key without the trial secret");
});

// In-memory stand-in for the store's extension rules (the real ones run in Postgres).
function fixture({trial={startedAt:NOW-20*DAY,endsAt:NOW+10*DAY},migrated=true}={}) {
  const rows=new Map(trial ? [[key,{subject:"google-oauth2|person",ref:"a".repeat(32),dirty:false,pushedUntil:trial.endsAt,...trial}]] : []);
  const pushes=[];let pushFails=false;
  const store={
    async trialByEmail(emailKey) {return rows.get(emailKey) ?? null;},
    async extendTrial({emailKey,days,now}) {
      if (!migrated) throw Object.assign(new Error("Billing storage operation rejected"),{code:"MIGRATION_PENDING"});
      const row=rows.get(emailKey);if (!row) return {outcome:"not_found",trial:null};
      const end=extendedTrialEnd(row.endsAt,days,now);
      if (end===null) return {outcome:"too_long",trial:row,extendable:extendableDays(row.endsAt,now)};
      const previousEnd=row.endsAt;Object.assign(row,{endsAt:end,dirty:true});
      return {outcome:"extended",trial:row,previousEnd};
    },
    async trialGrantCandidates({subject}={}) {return [...rows.values()].filter(r=>(subject===undefined || r.subject===subject) && r.dirty);},
    async withTrialGrant(subject,push) {const r=[...rows.values()].find(v=>v.subject===subject);const until=await push(r,pushes.length+1);r.dirty=false;r.pushedUntil=until;return {until};},
    async grantCandidates() {return [];},
  };
  const deps={env,getSession:async()=>({user:{sub:owner}}),createStripe:()=>{throw new Error("trials never call Stripe");},
    withStore:async(cfg,callback)=>callback(store),pushGrant:async(cfg,value)=>{if(pushFails)throw new Error("down");pushes.push(value);return true;}};
  return {rows,deps,pushes,setPushFails:(v)=>{pushFails=v;}};
}
const post=(fields,headers={})=>new Request(config.origin+"/api/admin/trial",{method:"POST",
  headers:{origin:config.origin,"sec-fetch-site":"same-origin","content-type":"application/x-www-form-urlencoded",...headers},
  body:typeof fields==="string" ? fields : new URLSearchParams(fields).toString()});
const result=(response)=>{
  assert.equal(response.status,303);
  const location=new URL(response.headers.get("location"));
  assert.equal(location.origin+location.pathname,config.origin+"/account/admin");
  assert.equal(location.search.toLowerCase().includes("person"),false,"the address never goes into the URL");
  return Object.fromEntries(location.searchParams);
};

test("the owner extends a running trial and Saiph Cloud gets the new end at once",async(t)=>{
  t.mock.timers.enable({apis:["Date"],now:NOW*1000});
  const f=fixture();
  assert.deepEqual(result(await adminTrialAction(post({action:"extend",email:address,days:"7"}),f.deps)),
    {result:"extended",from:String(NOW+10*DAY),until:String(NOW+17*DAY)});
  assert.equal(f.pushes.length,1);
  assert.deepEqual({grant:f.pushes[0].grant,until:f.pushes[0].until,subject:f.pushes[0].subject},
    {grant:"trial:"+"a".repeat(32),until:NOW+17*DAY,subject:"google-oauth2|person"});
});

test("an ended trial is restarted from today; too many days are refused with how many are left",async(t)=>{
  t.mock.timers.enable({apis:["Date"],now:NOW*1000});
  const ended=fixture({trial:{startedAt:NOW-40*DAY,endsAt:NOW-10*DAY}});
  assert.equal(result(await adminTrialAction(post({action:"extend",email:address,days:"14"}),ended.deps)).until,String(NOW+14*DAY));
  const near=fixture({trial:{startedAt:NOW-5*DAY,endsAt:NOW+25*DAY}});
  assert.deepEqual(result(await adminTrialAction(post({action:"extend",email:address,days:"10"}),near.deps)),
    {result:"too_long",until:String(NOW+25*DAY),max:"5"});
  assert.equal(near.pushes.length,0);
});

test("lookup reports the trial's dates; unknown addresses, bad days and a pending migration say so",async(t)=>{
  t.mock.timers.enable({apis:["Date"],now:NOW*1000});
  const f=fixture();
  assert.deepEqual(result(await adminTrialAction(post({action:"lookup",email:address,days:""}),f.deps)),
    {result:"found",started:String(NOW-20*DAY),until:String(NOW+10*DAY)});
  assert.deepEqual(result(await adminTrialAction(post({action:"lookup",email:"nobody@example.com"}),f.deps)),{result:"not_found"});
  assert.deepEqual(result(await adminTrialAction(post({action:"extend",email:"nobody@example.com",days:"7"}),f.deps)),{result:"not_found"});
  assert.deepEqual(result(await adminTrialAction(post({action:"extend",email:"nope",days:"7"}),f.deps)),{result:"invalid_email"});
  for (const days of ["0","31","","7.5","x"])
    assert.deepEqual(result(await adminTrialAction(post({action:"extend",email:address,days}),f.deps)),{result:"invalid_days"},days);
  assert.deepEqual(result(await adminTrialAction(post({action:"extend",email:address,days:"7"}),fixture({migrated:false}).deps)),{result:"migration"});
  assert.equal(f.pushes.length,0);
});

test("a failed delivery keeps the extension and says delivery is pending",async(t)=>{
  t.mock.timers.enable({apis:["Date"],now:NOW*1000});
  const f=fixture();f.setPushFails(true);
  assert.equal(result(await adminTrialAction(post({action:"extend",email:address,days:"3"}),f.deps)).result,"extended_pending");
  assert.equal(f.rows.get(key).endsAt,NOW+13*DAY);
  assert.equal(f.rows.get(key).dirty,true,"left for the daily refresh");
});

test("only the owner, same-origin, with exactly the admin form's fields",async()=>{
  const f=fixture();
  const fields={action:"extend",email:address,days:"7"};
  assert.equal((await adminTrialAction(post(fields),{...f.deps,getSession:async()=>({user:{sub:"google-oauth2|someone"}})})).status,403);
  assert.equal((await adminTrialAction(post(fields),{...f.deps,getSession:async()=>null})).status,401);
  assert.equal((await adminTrialAction(post(fields),{...f.deps,env:{...env,SAIPH_REQUIRE_MFA:"true"}})).status,403,"second factor when required");
  assert.equal((await adminTrialAction(post(fields,{origin:"https://evil.test"}),f.deps)).status,403);
  assert.equal((await adminTrialAction(post(fields,{"sec-fetch-site":"cross-site"}),f.deps)).status,403);
  assert.equal((await adminTrialAction(post("action=extend&email=a%40b.ie&days=7&days=8"),f.deps)).status,400,"repeated field");
  assert.equal((await adminTrialAction(post({...fields,subject:"x"}),f.deps)).status,400,"unknown field");
  assert.equal((await adminTrialAction(post({...fields,action:"delete"}),f.deps)).status,400);
  assert.equal((await adminTrialAction(new Request(config.origin+"/api/admin/trial"),f.deps)).status,405);
  assert.equal((await adminTrialAction(post(fields),{...f.deps,env:{...env,SAIPH_TRIAL_SECRET:""}})).status,503,"trials off");
  assert.equal(f.pushes.length,0);
  assert.equal(f.rows.get(key).endsAt,NOW+10*DAY,"nothing changed");
});
