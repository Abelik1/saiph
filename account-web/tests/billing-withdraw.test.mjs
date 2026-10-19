// SPDX-License-Identifier: AGPL-3.0-or-later
// EU withdrawal (14 days, full refund) and the beta notice, with a synthetic
// Stripe stand-in. Not a real Stripe sandbox receipt.
import {test} from "node:test";
import assert from "node:assert/strict";
import {generateKeyPairSync} from "node:crypto";
import {withdrawAction} from "../lib/billing/http.ts";
import {readBillingConfig,subjectReference} from "../lib/billing/policy.ts";
import {BETA_CHECKOUT_NOTICE,WITHDRAWAL_SECONDS,checkout,withdrawalStatus} from "../lib/billing/service.ts";

const grantKey=generateKeyPairSync("ed25519").privateKey.export({format:"der",type:"pkcs8"}).toString("base64url");
const env={SAIPH_BILLING_MODE:"owner-sandbox",AUTH0_DOMAIN:"synthetic.us.auth0.com",AUTH0_CLIENT_ID:"syntheticclient",AUTH0_CLIENT_SECRET:"synthetic-not-real",AUTH0_SECRET:"ab".repeat(32),APP_BASE_URL:"https://account.saiph.test",SAIPH_OWNER_SUBJECT:"synthetic|owner",STRIPE_SECRET_KEY:"rk_test_synthetic123",STRIPE_WEBHOOK_SECRET:"whsec_synthetic123",STRIPE_EXPECTED_ACCOUNT_ID:"acct_synthetic",STRIPE_PRODUCT_ID:"prod_synthetic",STRIPE_PRICE_ID:"price_monthly",STRIPE_YEARLY_PRICE_ID:"price_yearly",STRIPE_PORTAL_CONFIGURATION_ID:"bpc_synthetic",DATABASE_URL:"postgresql://synthetic:synthetic@synthetic-pooler.eu-west-2.aws.neon.tech/synthetic?sslmode=require",
  SAIPH_HOSTED_API_URL:"https://api.saiph.test",SAIPH_BILLING_GRANT_KEY:grantKey,SAIPH_BILLING_GRANT_KEY_ID:"test-1"};
const config=readBillingConfig(env);assert.ok(config);
const owner=config.ownerSubject;
const metadata={saiph_billing:"owner-sandbox-v1",saiph_subject_ref:subjectReference(owner),saiph_account:config.accountId};
const NOW=1_800_000_000;

function fixture({startedAgo=86400,status="active"}={}) {
  const calls={update:[],cancel:[],refunds:[],checkout:[]};
  const sub={id:"sub_synthetic",object:"subscription",livemode:false,customer:"cus_synthetic",status,metadata:{...metadata},created:NOW-startedAgo,start_date:NOW-startedAgo};
  const charges=[
    {id:"ch_first",livemode:false,paid:true,status:"succeeded",amount:399,amount_refunded:0,refunded:false,currency:"eur"},
    {id:"ch_second",livemode:false,paid:true,status:"succeeded",amount:399,amount_refunded:0,refunded:false,currency:"eur"},
    {id:"ch_failed",livemode:false,paid:false,status:"failed",amount:399,amount_refunded:0,refunded:false,currency:"eur"},
  ];
  const stripe={
    customers:{retrieve:async()=>({id:"cus_synthetic",livemode:false,metadata})},
    subscriptions:{
      list:async()=>({has_more:false,data:[sub]}),
      update:async(id,params)=>{calls.update.push({id,params});Object.assign(sub.metadata,params.metadata);return sub;},
      cancel:async(id,params)=>{calls.cancel.push({id,params});sub.status="canceled";return sub;},
    },
    charges:{list:async(params)=>{calls.chargeQuery=params;return {has_more:false,data:charges};}},
    refunds:{create:async(params,options)=>{calls.refunds.push({params,options});
      const charge=charges.find(c=>c.id===params.charge);charge.amount_refunded+=params.amount;charge.refunded=charge.amount_refunded>=charge.amount;return {id:"re_"+params.charge};}},
    prices:{retrieve:async(id)=>({id,active:true,livemode:false,currency:"eur",unit_amount:999,type:"recurring",recurring:{interval:"month",interval_count:1},product:{id:config.productId,active:true,livemode:false}})},
    checkout:{sessions:{list:async()=>({has_more:false,data:[]}),create:async(params,options)=>{calls.checkout.push({params,options});
      return {...params,id:"cs_test_synthetic",livemode:false,url:"https://checkout.stripe.com/c/pay/cs_test_synthetic"};}}},
  };
  let mapping={subject:owner,customerId:"cus_synthetic"};let trial=null;
  const store={findCustomer:async()=>mapping,withCustomer:async(subject,callback)=>callback(mapping),
    getOrCreateCustomer:async()=>mapping,setMapping:(value)=>{mapping=value;},setTrial:(value)=>{trial=value;},
    trialFacts:async()=>({stored:trial,emailUsed:false,subscribed:false,started:trial?1:0})};
  const deps={env,getSession:async()=>({user:{sub:owner}}),createStripe:()=>stripe,pushGrant:async()=>true,
    withStore:async(cfg,callback)=>callback(store)};
  return {stripe,store,calls,sub,charges,deps};
}
const confirm=(body="confirm=withdraw",headers={})=>new Request(config.origin+"/api/billing/withdraw",{method:"POST",
  headers:{origin:config.origin,"sec-fetch-site":"same-origin","content-type":"application/x-www-form-urlencoded",...headers},body});

test("within 14 days: one confirmation cancels at once and refunds every paid charge in full",async(t)=>{
  t.mock.timers.enable({apis:["Date"],now:NOW*1000});
  const f=fixture();
  const before=await withdrawalStatus(f.stripe,f.store,config,owner,NOW);
  assert.deepEqual(before,{state:"eligible",subscriptionId:"sub_synthetic",startedAt:NOW-86400,deadline:NOW-86400+WITHDRAWAL_SECONDS,refund:798,currency:"eur"});
  const response=await withdrawAction(confirm(),f.deps);
  assert.equal(response.status,303);
  assert.equal(response.headers.get("location"),config.origin+"/account/withdraw?done=1");
  assert.equal(f.calls.update[0].params.metadata.saiph_withdrawal_at,String(NOW));
  assert.deepEqual(f.calls.cancel[0].params,{invoice_now:false,prorate:false,cancellation_details:{comment:"Withdrawal within 14 days (EU right of withdrawal)"}});
  assert.deepEqual(f.calls.refunds.map(r=>[r.params.charge,r.params.amount,r.params.reason,r.options.idempotencyKey]),
    [["ch_first",399,"requested_by_customer","saiph-withdrawal-v1-ch_first-0"],["ch_second",399,"requested_by_customer","saiph-withdrawal-v1-ch_second-0"]]);
  assert.equal(f.calls.chargeQuery.created.gte,NOW-86400,"only charges since the subscription started");
  const after=await withdrawalStatus(f.stripe,f.store,config,owner,NOW+60);
  assert.deepEqual(after,{state:"withdrawn",at:NOW,refunded:798,outstanding:0,currency:"eur",complete:true});
  // A second click is refused and refunds nothing more.
  assert.equal((await withdrawAction(confirm(),f.deps)).status,409);
  assert.equal(f.calls.refunds.length,2);
});

test("after 14 days the page says so and nothing is cancelled or refunded",async(t)=>{
  t.mock.timers.enable({apis:["Date"],now:NOW*1000});
  const f=fixture({startedAgo:WITHDRAWAL_SECONDS});
  assert.deepEqual(await withdrawalStatus(f.stripe,f.store,config,owner,NOW),{state:"expired",deadline:NOW});
  assert.equal((await withdrawAction(confirm(),f.deps)).status,409);
  assert.equal(f.calls.cancel.length+f.calls.refunds.length+f.calls.update.length,0);
});

test("ended subscriptions and accounts without a customer have nothing to withdraw",async()=>{
  const ended=fixture({status:"canceled"});
  assert.deepEqual(await withdrawalStatus(ended.stripe,ended.store,config,owner,NOW),{state:"none"});
  const none=fixture();none.store.setMapping(null);
  assert.deepEqual(await withdrawalStatus(none.stripe,none.store,config,owner,NOW),{state:"none"});
});

test("forged, cross-site or malformed requests are refused before Stripe is touched",async()=>{
  for (const [request,status] of [
    [confirm(undefined,{origin:"https://evil.test"}),403],
    [confirm(undefined,{"sec-fetch-site":"cross-site"}),403],
    [new Request(config.origin+"/api/billing/withdraw?confirm=withdraw",{method:"POST",headers:{origin:config.origin,"content-type":"application/x-www-form-urlencoded"},body:"confirm=withdraw"}),403],
    [confirm(""),400],[confirm("confirm=yes"),400],[confirm("confirm=withdraw&subscription=sub_other"),400],
    [confirm("confirm=withdraw",{"content-type":"application/json"}),400],
    [new Request(config.origin+"/api/billing/withdraw"),405],
  ]) {
    const f=fixture();assert.equal((await withdrawAction(request,f.deps)).status,status);
    assert.equal(f.calls.cancel.length+f.calls.refunds.length,0);
  }
  const f=fixture();f.deps.getSession=async()=>({user:{sub:"synthetic|other"}});
  assert.equal((await withdrawAction(confirm(),f.deps)).status,403,"sandbox: owner only");
  f.deps.getSession=async()=>null;
  assert.equal((await withdrawAction(confirm(),f.deps)).status,401);
});

test("a Stripe failure answers 503 with the support address and no details",async()=>{
  const f=fixture();f.stripe.refunds.create=async()=>{throw new Error("rk_test_secret_should_not_leak");};
  const response=await withdrawAction(confirm(),f.deps);
  assert.equal(response.status,503);
  const text=await response.text();
  assert.match(text,/support@usesaiph\.com/);
  assert.equal(text.includes("rk_test"),false);
});

test("checkout shows the beta notice above the pay button",async()=>{
  const f=fixture({status:"canceled"});
  await checkout(f.stripe,f.store,config,owner,"monthly");
  assert.deepEqual(f.calls.checkout[0].params.custom_text,{submit:{message:BETA_CHECKOUT_NOTICE}});
  assert.match(BETA_CHECKOUT_NOTICE,/beta/);assert.match(BETA_CHECKOUT_NOTICE,/14 days/);
  assert.ok(BETA_CHECKOUT_NOTICE.length<=1200,"Stripe's limit for custom text");
  assert.match(f.calls.checkout[0].options.idempotencyKey,/^saiph-checkout-v4-/);
});

test("a withdrawal interrupted part-way is shown as unfinished and a retry completes it without refunding twice",async(t)=>{
  t.mock.timers.enable({apis:["Date"],now:NOW*1000});
  const f=fixture();
  const create=f.stripe.refunds.create;let failSecond=true;
  f.stripe.refunds.create=async(params,options)=>{
    if (params.charge==="ch_second" && failSecond) {failSecond=false;throw new Error("timeout");}
    return create(params,options);
  };
  assert.equal((await withdrawAction(confirm(),f.deps)).status,503);
  assert.equal(f.calls.cancel.length,1);
  const half=await withdrawalStatus(f.stripe,f.store,config,owner,NOW+60);
  assert.deepEqual(half,{state:"withdrawn",at:NOW,refunded:399,outstanding:399,currency:"eur",complete:false},
    "not reported as finished while money is still owed");
  // The retry may come after the 14 days: the withdrawal was received in time.
  t.mock.timers.setTime((NOW+WITHDRAWAL_SECONDS+3600)*1000);
  assert.equal((await withdrawAction(confirm(),f.deps)).status,303);
  assert.deepEqual(f.calls.refunds.map(r=>r.params.charge),["ch_first","ch_second"],"ch_first is not refunded again");
  assert.equal(f.calls.cancel.length,1,"an already cancelled subscription is not cancelled again");
  assert.equal(f.calls.update.length,1,"the received time is recorded once");
  assert.deepEqual(await withdrawalStatus(f.stripe,f.store,config,owner,NOW+WITHDRAWAL_SECONDS+7200),
    {state:"withdrawn",at:NOW,refunded:798,outstanding:0,currency:"eur",complete:true});
  assert.equal((await withdrawAction(confirm(),f.deps)).status,409,"nothing left to do");
});

test("a cancellation failure after recording is also resumed",async(t)=>{
  t.mock.timers.enable({apis:["Date"],now:NOW*1000});
  const f=fixture();
  const cancel=f.stripe.subscriptions.cancel;let fail=true;
  f.stripe.subscriptions.cancel=async(id,params)=>{if(fail){fail=false;throw new Error("timeout");}return cancel(id,params);};
  assert.equal((await withdrawAction(confirm(),f.deps)).status,503);
  assert.equal(f.calls.refunds.length,0);
  assert.equal((await withdrawalStatus(f.stripe,f.store,config,owner,NOW+60)).complete,false);
  assert.equal((await withdrawAction(confirm(),f.deps)).status,303);
  assert.equal(f.sub.status,"canceled");
  assert.equal(f.calls.refunds.length,2);
});
