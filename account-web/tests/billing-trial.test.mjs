// SPDX-License-Identifier: AGPL-3.0-or-later
// Free trial on sign-up (docs/PAID_HOSTED.md): configuration and the optional
// cap, one trial per person, the start route and its signed grant, expiry and
// subscribing afterwards. Synthetic only; the real Postgres rules are covered by
// tests/billing-db.test.mjs (npm run test:billing-db).
import {test} from "node:test";
import assert from "node:assert/strict";
import {generateKeyPairSync} from "node:crypto";
import {trialAction} from "../lib/billing/http.ts";
import {readBillingConfig,subjectReference} from "../lib/billing/policy.ts";
import {checkout,withdrawalStatus,WITHDRAWAL_SECONDS} from "../lib/billing/service.ts";
import {syncGrants} from "../lib/billing/grant-sync.mjs";
import {CARRY_MIN_SECONDS,DEFAULT_TRIAL_DAYS,carriedTrialEnd,checkTrialConfig,daysLeft,normaliseEmail,readTrialConfig,
  trialDecision,trialEmailKey,trialUntil} from "../lib/billing/trial.mjs";

const NOW=1_800_000_000;
const grantKey=generateKeyPairSync("ed25519").privateKey.export({format:"der",type:"pkcs8"}).toString("base64url");
const secret="t".repeat(40);
const env={SAIPH_BILLING_MODE:"owner-sandbox",AUTH0_DOMAIN:"synthetic.us.auth0.com",AUTH0_CLIENT_ID:"syntheticclient",AUTH0_CLIENT_SECRET:"synthetic-not-real",AUTH0_SECRET:"ab".repeat(32),APP_BASE_URL:"https://account.saiph.test",SAIPH_OWNER_SUBJECT:"synthetic|owner",STRIPE_SECRET_KEY:"rk_test_synthetic123",STRIPE_WEBHOOK_SECRET:"whsec_synthetic123",STRIPE_EXPECTED_ACCOUNT_ID:"acct_synthetic",STRIPE_PRODUCT_ID:"prod_synthetic",STRIPE_PRICE_ID:"price_monthly",STRIPE_YEARLY_PRICE_ID:"price_yearly",STRIPE_PORTAL_CONFIGURATION_ID:"bpc_synthetic",DATABASE_URL:"postgresql://synthetic:synthetic@synthetic-pooler.eu-west-2.aws.neon.tech/synthetic?sslmode=require",
  SAIPH_HOSTED_API_URL:"https://api.saiph.test",SAIPH_BILLING_GRANT_KEY:grantKey,SAIPH_BILLING_GRANT_KEY_ID:"test-1",SAIPH_TRIAL_SECRET:secret};
const config=readBillingConfig(env);assert.ok(config);
const owner=config.ownerSubject;
const trialConfig={days:14,cap:null,secret};
const emailKey=trialEmailKey({email:"Someone.Synthetic+saiph@gmail.com",email_verified:true},trialConfig);

test("trials default to 14 days with no cap, can be switched off, and refuse unsafe settings",()=>{
  assert.equal(DEFAULT_TRIAL_DAYS,14);
  assert.deepEqual(readTrialConfig({SAIPH_TRIAL_SECRET:secret}),{days:14,cap:null,secret});
  assert.deepEqual(readTrialConfig({SAIPH_TRIAL_SECRET:secret,SAIPH_TRIAL_DAYS:" 7 "}),{days:7,cap:null,secret});
  assert.equal(readTrialConfig({SAIPH_TRIAL_SECRET:secret,SAIPH_TRIAL_DAYS:"0"}),null,"0 turns trials off");
  assert.deepEqual(checkTrialConfig({SAIPH_TRIAL_SECRET:secret,SAIPH_TRIAL_DAYS:"0"}).problems,[]);
  for (const SAIPH_TRIAL_DAYS of ["31","-1","14d","1.5"])
    assert.deepEqual(checkTrialConfig({SAIPH_TRIAL_SECRET:secret,SAIPH_TRIAL_DAYS}),{config:null,problems:["SAIPH_TRIAL_DAYS"]},SAIPH_TRIAL_DAYS);
  assert.deepEqual(checkTrialConfig({}),{config:null,problems:["SAIPH_TRIAL_SECRET"]},"no secret, no trials");
  assert.deepEqual(checkTrialConfig({SAIPH_TRIAL_SECRET:"short"}).problems,["SAIPH_TRIAL_SECRET"]);
});

test("the cap switch is off by default and limits trials to the first N when set",()=>{
  assert.equal(readTrialConfig({SAIPH_TRIAL_SECRET:secret}).cap,null);
  assert.equal(readTrialConfig({SAIPH_TRIAL_SECRET:secret,SAIPH_TRIAL_CAP:""}).cap,null);
  const capped=readTrialConfig({SAIPH_TRIAL_SECRET:secret,SAIPH_TRIAL_CAP:"100"});
  assert.equal(capped.cap,100);
  for (const SAIPH_TRIAL_CAP of ["-5","ten","1e3"]) assert.deepEqual(checkTrialConfig({SAIPH_TRIAL_SECRET:secret,SAIPH_TRIAL_CAP}).problems,["SAIPH_TRIAL_CAP"]);
  const facts={stored:null,emailKey,emailUsed:false,subscribed:false,now:NOW};
  assert.equal(trialDecision({...facts,config:trialConfig,started:100000}).state,"available","no cap: never full");
  assert.equal(trialDecision({...facts,config:capped,started:99}).state,"available","place 100 is still free");
  assert.equal(trialDecision({...facts,config:capped,started:100}).state,"full");
  // Someone who already started a trial keeps it when the cap fills up.
  assert.equal(trialDecision({...facts,config:capped,started:100,stored:{startedAt:NOW,endsAt:NOW+86400}}).state,"active");
});

test("one trial per person: aliases of one mailbox share a key, and only verified email counts",()=>{
  assert.equal(normaliseEmail(" Someone.Synthetic+saiph@GoogleMail.com "),"someonesynthetic@gmail.com");
  assert.equal(normaliseEmail("first.last+x@example.org"),"first.last@example.org","dots matter outside Gmail");
  for (const bad of ["", "no-at", "@example.org", "a@", "a b@example.org", 42, null]) assert.equal(normaliseEmail(bad),null,String(bad));
  assert.match(emailKey,/^[a-f0-9]{64}$/);
  assert.equal(trialEmailKey({email:"someonesynthetic@gmail.com",email_verified:true},trialConfig),emailKey);
  assert.notEqual(trialEmailKey({email:"other.synthetic@gmail.com",email_verified:true},trialConfig),emailKey);
  assert.equal(trialEmailKey({email:"someonesynthetic@gmail.com",email_verified:false},trialConfig),null);
  assert.equal(trialEmailKey({email:"someonesynthetic@gmail.com"},trialConfig),null);
  assert.equal(trialEmailKey({email:"someonesynthetic@gmail.com",email_verified:true},null),null,"trials off");
  assert.notEqual(trialEmailKey({email:"someonesynthetic@gmail.com",email_verified:true},{...trialConfig,secret:"u".repeat(40)}),emailKey,"keyed, not a bare hash");
  const facts={config:trialConfig,stored:null,emailKey,subscribed:false,started:1,now:NOW};
  assert.equal(trialDecision({...facts,emailUsed:true}).state,"used");
  assert.equal(trialDecision({...facts,emailUsed:false,emailKey:null}).state,"sign_in_again");
  assert.equal(trialDecision({...facts,emailUsed:false,subscribed:true}).state,"subscribed");
  assert.equal(trialDecision({...facts,emailUsed:false,config:null}).state,"off");
});

test("a running trial counts down in whole days and ends exactly at its end",()=>{
  const stored={startedAt:NOW,endsAt:NOW+14*86400};
  const base={config:trialConfig,stored,emailKey,emailUsed:false,subscribed:false,started:1};
  assert.deepEqual(trialDecision({...base,now:NOW}),{state:"active",endsAt:stored.endsAt,daysLeft:14});
  assert.equal(trialDecision({...base,now:stored.endsAt-1}).daysLeft,1,"the last second reads 1 day");
  assert.deepEqual(trialDecision({...base,now:stored.endsAt}),{state:"ended",endsAt:stored.endsAt,daysLeft:0});
  // Turning trials off or filling the cap never hides a trial someone had.
  assert.equal(trialDecision({...base,config:null,now:NOW}).state,"active");
  assert.equal(daysLeft(NOW+86400+1,NOW),2);
  assert.equal(trialUntil(stored,NOW),stored.endsAt);
  assert.equal(trialUntil(stored,stored.endsAt),0,"expired trials grant nothing");
});

// In-memory stand-in for the store's trial rules (the real ones run in Postgres).
function trialFixture({cap=null,subscribed=false,usedEmails=[]}={}) {
  const trials=new Map();const pushes=[];let started=0;let pushFails=false;
  const store={
    async startTrial({subject,emailKey:key,now,days,cap:limit,ref}) {
      assert.equal(limit,cap);
      if (trials.has(subject)) return {outcome:"exists",trial:trials.get(subject)};
      if (subscribed) return {outcome:"subscribed",trial:null};
      if (usedEmails.includes(key) || [...trials.values()].some(t=>t.emailKey===key)) return {outcome:"used",trial:null};
      if (limit!==null && started>=limit) return {outcome:"full",trial:null};
      const trial={subject,emailKey:key,ref,startedAt:now,endsAt:now+days*86400,dirty:true,pushedUntil:null};
      trials.set(subject,trial);started++;return {outcome:"started",trial};
    },
    async trialGrantCandidates({subject}={}) {return [...trials.values()].filter(t=>(subject===undefined || t.subject===subject) && (t.dirty || t.pushedUntil===null));},
    async withTrialGrant(subject,push) {const t=trials.get(subject);const until=await push(t,pushes.length+1);t.dirty=false;t.pushedUntil=until;return {until};},
    async grantCandidates() {return [];},
  };
  const deps={env,getSession:async()=>({user:{sub:owner,trialKey:emailKey}}),createStripe:()=>{throw new Error("trials never call Stripe");},
    withStore:async(cfg,callback)=>callback(store),pushGrant:async(cfg,value)=>{if(pushFails)throw new Error("down");pushes.push(value);return true;}};
  return {store,deps,trials,pushes,setPushFails:(v)=>{pushFails=v;}};
}
const start=(body="trial=start",headers={})=>new Request(config.origin+"/api/billing/trial",{method:"POST",
  headers:{origin:config.origin,"sec-fetch-site":"same-origin","content-type":"application/x-www-form-urlencoded",...headers},body});

test("starting a trial records it and pushes a signed trial grant to the end of the trial, without a card",async(t)=>{
  t.mock.timers.enable({apis:["Date"],now:NOW*1000});
  const f=trialFixture();
  const response=await trialAction(start(),f.deps);
  assert.equal(response.status,303);
  assert.equal(response.headers.get("location"),config.origin+"/account?trial=started");
  const trial=f.trials.get(owner);
  assert.equal(trial.endsAt,NOW+14*86400);
  assert.equal(f.pushes.length,1);
  const [push]=f.pushes;
  assert.match(push.grant,/^trial:[a-f0-9]{32}$/);
  assert.equal(push.grant.includes(subjectReference(owner).slice(0,16)),false,"the reference does not reveal the subject");
  assert.deepEqual({...push,grant:undefined,sequence:undefined},{issuer:"https://synthetic.us.auth0.com/",subject:owner,grant:undefined,until:NOW+14*86400,sequence:undefined,livemode:false});
  // Pressing again neither starts a second trial nor pushes again.
  assert.equal((await trialAction(start(),f.deps)).status,303);
  assert.equal(f.trials.size,1);assert.equal(f.pushes.length,1);
});

test("a failed delivery answers 503 and pressing again delivers the same trial",async(t)=>{
  t.mock.timers.enable({apis:["Date"],now:NOW*1000});
  const f=trialFixture();f.setPushFails(true);
  const failed=await trialAction(start(),f.deps);
  assert.equal(failed.status,503);assert.match(await failed.text(),/again/);
  assert.equal(f.trials.get(owner).dirty,true);
  f.setPushFails(false);
  assert.equal((await trialAction(start(),f.deps)).status,303);
  assert.equal(f.pushes.length,1);assert.equal(f.pushes[0].until,f.trials.get(owner).endsAt);
});

test("used email, a full cap and existing subscribers are refused with a reason; a missing email key asks to sign in again",async()=>{
  const used=trialFixture({usedEmails:[emailKey]});
  const usedReply=await trialAction(start(),used.deps);
  assert.equal(usedReply.status,409);assert.match(await usedReply.text(),/already been used/);
  const full=trialFixture({cap:0});
  const fullReply=await trialAction(start(),{...full.deps,env:{...env,SAIPH_TRIAL_CAP:"0"}});
  assert.equal(fullReply.status,409);assert.match(await fullReply.text(),/places have been taken/);
  const paying=trialFixture({subscribed:true});
  assert.equal((await trialAction(start(),paying.deps)).status,409);
  const stale=trialFixture();
  const staleReply=await trialAction(start(),{...stale.deps,getSession:async()=>({user:{sub:owner}})});
  assert.equal(staleReply.status,401);assert.match(await staleReply.text(),/sign in again/);
  for (const f of [used,full,paying,stale]) assert.equal(f.pushes.length,0);
});

test("forged, cross-site, malformed and switched-off trial requests change nothing",async()=>{
  const f=trialFixture();
  assert.equal((await trialAction(start("trial=start",{origin:"https://evil.test"}),f.deps)).status,403);
  assert.equal((await trialAction(start("trial=start",{"sec-fetch-site":"cross-site"}),f.deps)).status,403);
  assert.equal((await trialAction(new Request(config.origin+"/api/billing/trial?x=1",{method:"POST",headers:{origin:config.origin}}),f.deps)).status,403);
  assert.equal((await trialAction(start("trial=start&days=365"),f.deps)).status,400);
  assert.equal((await trialAction(start("plan=monthly"),f.deps)).status,400);
  assert.equal((await trialAction(new Request(config.origin+"/api/billing/trial"),f.deps)).status,405);
  assert.equal((await trialAction(start(),{...f.deps,env:{...env,SAIPH_TRIAL_DAYS:"0"}})).status,503);
  assert.equal((await trialAction(start(),{...f.deps,env:{...env,SAIPH_TRIAL_SECRET:""}})).status,503);
  assert.equal((await trialAction(start(),{...f.deps,getSession:async()=>null})).status,401);
  assert.equal((await trialAction(start(),{...f.deps,getSession:async()=>({user:{sub:"synthetic|stranger",trialKey:emailKey}})})).status,403,"sandbox: owner only");
  assert.equal(f.trials.size,0);assert.equal(f.pushes.length,0);
});

test("sync delivers trial grants, ends a sandbox trial held by someone else, and leaves expired ones alone",async()=>{
  const trials=[{subject:owner,ref:"a".repeat(32),startedAt:NOW,endsAt:NOW+86400,dirty:true,pushedUntil:null},
    {subject:"synthetic|other",ref:"b".repeat(32),startedAt:NOW,endsAt:NOW+86400,dirty:true,pushedUntil:null},
    {subject:"synthetic|old",ref:"c".repeat(32),startedAt:NOW-30*86400,endsAt:NOW-16*86400,dirty:false,pushedUntil:NOW-16*86400}];
  const pushes=[];
  const store={grantCandidates:async()=>[],trialGrantCandidates:async()=>trials,
    withTrialGrant:async(subject,push)=>({until:await push(trials.find(t=>t.subject===subject),pushes.length+1)})};
  const policy={issuer:"https://synthetic.us.auth0.com/",livemode:false,ownerOnly:owner};
  assert.deepEqual(await syncGrants(store,policy,async(v)=>{pushes.push(v);return true;},{now:()=>NOW}),{pushed:2,failed:0});
  assert.deepEqual(pushes.map(p=>[p.grant,p.until]),[["trial:"+"a".repeat(32),NOW+86400],["trial:"+"b".repeat(32),0]]);
  // A webhook for one Stripe customer never touches trials.
  assert.deepEqual(await syncGrants(store,policy,async()=>true,{now:()=>NOW,customerId:"cus_synthetic"}),{pushed:0,failed:0});
});

// Stripe stand-in for subscribing during or after a trial.
function stripeFixture({trialEnd=null}={}) {
  const metadata={saiph_billing:"owner-sandbox-v1",saiph_subject_ref:subjectReference(owner),saiph_account:config.accountId};
  const calls=[];let trial=null;
  const mapping={subject:owner,customerId:"cus_synthetic"};
  const sub={id:"sub_synthetic",livemode:false,customer:"cus_synthetic",status:"trialing",metadata,start_date:NOW,trial_end:trialEnd};
  const stripe={customers:{retrieve:async()=>({id:"cus_synthetic",livemode:false,metadata})},
    prices:{retrieve:async(id)=>{const plan=Object.values(config.plans).find(p=>p.priceId===id);
      return {id,active:true,livemode:false,currency:"eur",unit_amount:plan.amount,type:"recurring",recurring:{interval:plan.interval,interval_count:1},product:{id:config.productId,active:true,livemode:false}};}},
    subscriptions:{list:async()=>({has_more:false,data:trialEnd===null?[]:[sub]})},
    charges:{list:async()=>({has_more:false,data:[]})},
    checkout:{sessions:{list:async()=>({has_more:false,data:[]}),create:async(params,options)=>{calls.push({params,options});
      return {...params,id:"cs_test_synthetic",livemode:false,url:"https://checkout.stripe.com/c/pay/cs_test_synthetic"};}}}};
  const store={getOrCreateCustomer:async()=>mapping,withCustomer:async(s,callback)=>callback(mapping),findCustomer:async()=>mapping,
    trialFacts:async()=>({stored:trial,emailUsed:false,subscribed:false,started:trial?1:0})};
  return {stripe,store,calls,setTrial:(v)=>{trial=v;}};
}

test("subscribing during the trial keeps the free days: the first charge is when the trial ends",async(t)=>{
  t.mock.timers.enable({apis:["Date"],now:NOW*1000});
  const f=stripeFixture();f.setTrial({startedAt:NOW-4*86400,endsAt:NOW+10*86400});
  await checkout(f.stripe,f.store,config,owner,"yearly");
  assert.equal(f.calls[0].params.subscription_data.trial_end,NOW+10*86400);
  assert.equal(f.calls[0].params.line_items[0].price,config.plans.yearly.priceId,"prices are unchanged");
  assert.equal(carriedTrialEnd({startedAt:NOW,endsAt:NOW+CARRY_MIN_SECONDS-1},NOW),null,"Stripe needs 48 hours");
  const late=stripeFixture();late.setTrial({startedAt:NOW-13*86400,endsAt:NOW+86400});
  await checkout(late.stripe,late.store,config,owner,"monthly");
  assert.equal("trial_end" in late.calls[0].params.subscription_data,false,"less than 48 hours left: charged at once");
});

test("after the trial ends, subscribing starts a normal paid subscription and nothing is carried",async(t)=>{
  t.mock.timers.enable({apis:["Date"],now:NOW*1000});
  const f=stripeFixture();const stored={startedAt:NOW-20*86400,endsAt:NOW-6*86400};f.setTrial(stored);
  const decision=trialDecision({config:trialConfig,stored,emailKey,emailUsed:false,subscribed:false,started:1,now:NOW});
  assert.equal(decision.state,"ended");
  await checkout(f.stripe,f.store,config,owner,"monthly");
  assert.equal("trial_end" in f.calls[0].params.subscription_data,false);
  assert.equal(f.calls[0].params.mode,"subscription");
});

test("withdrawal: the 14 days run from the first paid day when a subscription began in the trial",async()=>{
  const trialEnd=NOW+10*86400;
  const f=stripeFixture({trialEnd});
  const status=await withdrawalStatus(f.stripe,f.store,config,owner,NOW+20*86400);
  assert.equal(status.state,"eligible");
  assert.equal(status.deadline,trialEnd+WITHDRAWAL_SECONDS);
  assert.equal((await withdrawalStatus(f.stripe,f.store,config,owner,trialEnd+WITHDRAWAL_SECONDS)).state,"expired");
});

test("a database without the trial table still lets people subscribe (website deployed before migration 0004)",async(t)=>{
  t.mock.timers.enable({apis:["Date"],now:NOW*1000});
  const f=stripeFixture();f.store.trialFacts=async()=>{throw new Error("relation saiph_billing.trials does not exist");};
  await checkout(f.stripe,f.store,config,owner,"monthly");
  assert.equal(f.calls.length,1);assert.equal("trial_end" in f.calls[0].params.subscription_data,false);
});
