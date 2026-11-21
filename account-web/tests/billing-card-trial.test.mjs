// SPDX-License-Identifier: AGPL-3.0-or-later
import {test} from "node:test";
import assert from "node:assert/strict";
import {generateKeyPairSync} from "node:crypto";
import Stripe from "stripe";
import {trialAction,accountAction,webhook} from "../lib/billing/http.ts";
import {readBillingConfig,subjectReference} from "../lib/billing/policy.ts";

const env={SAIPH_BILLING_MODE:"owner-sandbox",AUTH0_DOMAIN:"synthetic.us.auth0.com",AUTH0_CLIENT_ID:"syntheticclient",
  AUTH0_CLIENT_SECRET:"synthetic-not-real",AUTH0_SECRET:"ab".repeat(32),APP_BASE_URL:"https://account.saiph.test",
  SAIPH_OWNER_SUBJECT:"synthetic|owner",STRIPE_SECRET_KEY:"rk_test_synthetic123",STRIPE_WEBHOOK_SECRET:"whsec_synthetic123",
  STRIPE_EXPECTED_ACCOUNT_ID:"acct_synthetic",STRIPE_PRODUCT_ID:"prod_synthetic",STRIPE_PRICE_ID:"price_monthly",
  STRIPE_YEARLY_PRICE_ID:"price_yearly",STRIPE_PORTAL_CONFIGURATION_ID:"bpc_synthetic",DATABASE_URL:"postgresql://synthetic:synthetic@synthetic-pooler.eu-west-2.aws.neon.tech/synthetic?sslmode=require",
  SAIPH_HOSTED_API_URL:"https://api.saiph.test",SAIPH_BILLING_GRANT_KEY:generateKeyPairSync("ed25519").privateKey.export({format:"der",type:"pkcs8"}).toString("base64url"),
  SAIPH_BILLING_GRANT_KEY_ID:"test-1",SAIPH_TRIAL_SECRET:"t".repeat(40),SAIPH_TRIAL_DAYS:"30"};
const config=readBillingConfig(env),subject=env.SAIPH_OWNER_SUBJECT;
const meta={saiph_billing:"owner-sandbox-v1",saiph_subject_ref:subjectReference(subject),saiph_account:config.accountId};
const request=(body="trial=start",extra={})=>new Request(config.origin+"/api/billing/trial",{method:"POST",body,
  headers:{origin:config.origin,"sec-fetch-site":"same-origin","content-type":"application/x-www-form-urlencoded",...extra}});
function fixture() {
  const calls={checkout:[],expired:[],counts:[],reservations:0,pushes:0},sessions=[],seen=new Set();
  const customer={id:"cus_synthetic",metadata:meta,livemode:false};
  let mapping=null,subscriptions=[],outcome="reserved",failAfterCreate=false,firstEventOutcome="applied";
  const store={trialFacts:async()=>({stored:null}),
    reserveCardTrial:async()=>{calls.reservations++;return {outcome,ref:outcome==="reserved"?"a".repeat(32):null};},
    getOrCreateCustomer:async(s,create)=>(mapping??={subject:s,customerId:await create()}),
    withCustomer:async(_s,callback)=>callback(mapping),
    countFunnel:async c=>calls.counts.push(c),
    applyEvent:async(event,load)=>{await load(mapping);const outcome=seen.has(event.eventId)?"duplicate":firstEventOutcome;seen.add(event.eventId);return {outcome};},
    grantCandidates:async()=>[],trialGrantCandidates:async()=>[]};
  const stripe={webhooks:new Stripe(env.STRIPE_SECRET_KEY).webhooks,
    customers:{create:async()=>customer,retrieve:async()=>customer},
    prices:{retrieve:async id=>({id,active:true,livemode:false,currency:"eur",unit_amount:999,type:"recurring",
      recurring:{interval:"month",interval_count:1},product:{id:config.productId,active:true,livemode:false}})},
    subscriptions:{list:async()=>({data:subscriptions,has_more:false}),retrieve:async()=>subscriptions[0]},
    checkout:{sessions:{list:async()=>({data:sessions.filter(s=>s.status==="open"),has_more:false}),
      listLineItems:async()=>({data:[{quantity:1,price:{id:"price_monthly",livemode:false,product:config.productId}}],has_more:false}),
      expire:async id=>{sessions.find(s=>s.id===id).status="expired";calls.expired.push(id);},
      create:async(params,options)=>{calls.checkout.push({params,options});const session={...params,id:"cs_test_synthetic"+calls.checkout.length,
        livemode:false,status:"open",url:"https://checkout.stripe.com/c/pay/cs_test_synthetic"};sessions.push(session);
        if(failAfterCreate){failAfterCreate=false;throw new Error("response lost");}return session;}}}};
  const deps={env,getSession:async()=>({user:{sub:subject,trialKey:"e".repeat(64)}}),createStripe:()=>stripe,
    withStore:async(_c,callback)=>callback(store),pushGrant:async()=>{calls.pushes++;return true;}};
  return {calls,sessions,stripe,store,deps,setOutcome:v=>outcome=v,setSubscriptions:v=>subscriptions=v,
    setFirstEventOutcome:v=>firstEventOutcome=v,loseResponse:()=>failAfterCreate=true};
}

test("14-day trial collects a card and reuses checkout without granting access or counting a purchase",async()=>{
  const f=fixture();
  const response=await trialAction(request(),f.deps);
  assert.equal(response.status,303);assert.match(response.headers.get("location"),/^https:\/\/checkout.stripe.com\//);
  const p=f.calls.checkout[0].params;
  assert.equal(p.payment_method_collection,"always");assert.deepEqual(p.allowed_payment_method_types,["card"]);
  assert.equal(p.subscription_data.trial_period_days,14);assert.equal(p.subscription_data.trial_end,undefined);
  assert.equal(p.subscription_data.trial_settings.end_behavior.missing_payment_method,"cancel");
  assert.equal(p.metadata.saiph_trial,"card-v1");assert.match(p.custom_text.submit.message,/€9.99 every month unless you cancel/);
  assert.equal(p.cancel_url,config.origin+"/trial?checkout=cancelled");
  assert.equal(f.calls.pushes,0);assert.deepEqual(f.calls.counts.map(c=>c.step),["checkout_started"]);
  assert.equal((await trialAction(request(),f.deps)).status,303);assert.equal(f.calls.checkout.length,1);
});

test("a lost provider response safely resumes the existing checkout",async()=>{
  const f=fixture();f.loseResponse();
  assert.equal((await trialAction(request(),f.deps)).status,503);
  assert.equal((await trialAction(request(),f.deps)).status,303);
  assert.equal(f.calls.checkout.length,1);assert.equal(f.calls.pushes,0);
});

test("trial and immediate purchase sessions cannot be confused even at the same price",async()=>{
  const f=fixture();
  const buy=()=>accountAction(new Request(config.origin+"/api/billing/checkout",{method:"POST",body:"plan=monthly",
    headers:{origin:config.origin,"content-type":"application/x-www-form-urlencoded"}}),"checkout",f.deps);
  assert.equal((await buy()).status,303);
  assert.equal((await trialAction(request(),f.deps)).status,303);
  assert.equal(f.calls.expired.length,1);assert.equal(f.calls.checkout.length,2);
  assert.equal((await buy()).status,303);
  assert.equal(f.calls.expired.length,2);assert.equal(f.calls.checkout[2].params.subscription_data.trial_period_days,undefined);
});

test("eligibility, verified email, live readiness and CSRF fail closed",async()=>{
  for(const outcome of ["used","subscribed","full"]){const f=fixture();f.setOutcome(outcome);
    assert.equal((await trialAction(request(),f.deps)).status,409);assert.equal(f.calls.checkout.length,0);}
  const f=fixture();
  assert.equal((await trialAction(request(),{...f.deps,getSession:async()=>({user:{sub:subject}})})).status,401);
  assert.equal((await trialAction(request(),{...f.deps,env:{...env,SAIPH_BILLING_MODE:"live",STRIPE_SECRET_KEY:"rk_live_synthetic"}})).status,503);
  assert.equal((await trialAction(request("trial=start&days=365"),f.deps)).status,400);
  assert.equal((await trialAction(request("trial=start",{origin:"https://evil.test"}),f.deps)).status,403);
  assert.equal(f.calls.reservations,0);
  f.setSubscriptions([{status:"canceled",trial_end:123}]);
  assert.equal((await trialAction(request(),f.deps)).status,409,"provider history protects against a late webhook");
  assert.equal(f.calls.checkout.length,0);
});

test("only the verified completed checkout counts a trial; webhook replay is not a second start",async(t)=>{
  for (const firstOutcome of ["applied","stale"]) await t.test(firstOutcome,async()=>{
  const f=fixture();await trialAction(request(),f.deps);f.calls.counts.length=0;
  f.setFirstEventOutcome(firstOutcome);
  const session=f.sessions[0];session.status="complete";session.subscription="sub_synthetic";session.amount_total=0;
  f.setSubscriptions([{id:session.subscription,customer:session.customer,metadata:session.subscription_data.metadata,
    livemode:false,status:"trialing",cancel_at_period_end:false,canceled_at:null,ended_at:null,
    items:{has_more:false,data:[{quantity:1,current_period_end:Math.floor(Date.now()/1000)+14*86400,
      price:{id:"price_monthly",livemode:false,product:config.productId}}]}}]);
  const event={id:"evt_synthetic",object:"event",api_version:Stripe.API_VERSION,created:Math.floor(Date.now()/1000),livemode:false,
    type:"checkout.session.completed",data:{object:session}};
  const body=JSON.stringify(event),signature=f.stripe.webhooks.generateTestHeaderString({payload:body,secret:env.STRIPE_WEBHOOK_SECRET});
  const send=()=>webhook(new Request(config.origin+"/api/stripe/webhook",{method:"POST",body,
    headers:{"content-type":"application/json","stripe-signature":signature}}),f.deps);
  assert.equal((await send()).status,200);assert.equal((await send()).status,200);
  assert.deepEqual(f.calls.counts,[{step:"trial_started",plan:"trial",test:null,variant:"a"}]);
  });
});
