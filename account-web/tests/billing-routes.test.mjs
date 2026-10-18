// SPDX-License-Identifier: AGPL-3.0-or-later
// Synthetic provider fixtures exercise decisions and the official SDK signature
// verifier. These are not a real Stripe sandbox or Neon acceptance receipt.
import {test} from "node:test";
import assert from "node:assert/strict";
import {generateKeyPairSync} from "node:crypto";
import Stripe from "stripe";
import {accountAction,webhook,refresh,boundedBody} from "../lib/billing/http.ts";
import {readBillingConfig,subjectReference,customerIdempotency,stripeUrl,acceptedEvents} from "../lib/billing/policy.ts";
import {checkout,portal,processWebhook,eventDescriptor} from "../lib/billing/service.ts";
// Generated per run: no private key is stored in the repository.
const grantKey=generateKeyPairSync("ed25519").privateKey.export({format:"der",type:"pkcs8"}).toString("base64url");
const env={SAIPH_BILLING_MODE:"owner-sandbox",AUTH0_DOMAIN:"synthetic.us.auth0.com",AUTH0_CLIENT_ID:"syntheticclient",AUTH0_CLIENT_SECRET:"synthetic-not-real",AUTH0_SECRET:"ab".repeat(32),APP_BASE_URL:"https://account.saiph.test",SAIPH_OWNER_SUBJECT:"synthetic|owner",STRIPE_SECRET_KEY:"rk_test_synthetic123",STRIPE_WEBHOOK_SECRET:"whsec_synthetic123",STRIPE_EXPECTED_ACCOUNT_ID:"acct_synthetic",STRIPE_PRODUCT_ID:"prod_synthetic",STRIPE_PRICE_ID:"price_monthly",STRIPE_YEARLY_PRICE_ID:"price_yearly",STRIPE_PORTAL_CONFIGURATION_ID:"bpc_synthetic",DATABASE_URL:"postgresql://synthetic:synthetic@synthetic-pooler.eu-west-2.aws.neon.tech/synthetic?sslmode=require",
  SAIPH_HOSTED_API_URL:"https://api.saiph.test",SAIPH_BILLING_GRANT_KEY:grantKey,SAIPH_BILLING_GRANT_KEY_ID:"test-1",CRON_SECRET:"c".repeat(40)};
const config=readBillingConfig(env);assert.ok(config);
const monthly=config.plans.monthly.priceId, yearly=config.plans.yearly.priceId;
const metadata={saiph_billing:"owner-sandbox-v1",saiph_subject_ref:subjectReference(config.ownerSubject),saiph_account:config.accountId};
const prices={[monthly]:{unit_amount:999,interval:"month"},[yearly]:{unit_amount:8999,interval:"year"}};
function fixture() {
 let mapping=null;let queue=Promise.resolve();const calls={customer:[],checkout:[],expire:[],portal:[],retrieveSubscription:0,apply:0,disputes:0,pushes:[]};
 let sessions=[];let subscriptions=[];let lineItemPrice=monthly;const candidates=[];
 const customer={id:"cus_synthetic",livemode:false,metadata};
 const sub={id:"sub_synthetic",customer:customer.id,livemode:false,metadata,status:"active",cancel_at_period_end:false,canceled_at:null,ended_at:null,items:{has_more:false,data:[{quantity:1,current_period_end:2000000000,price:{id:monthly,livemode:false,product:config.productId}}]}};
 const dispute={id:"dp_synthetic",livemode:false,status:"needs_response",charge:{id:"ch_synthetic",livemode:false,customer:customer.id}};
 async function lock(callback) {let release;const previous=queue;queue=new Promise(r=>release=r);await previous;try{return await callback();}finally{release();}}
 const store={getOrCreateCustomer:(subject,create)=>lock(async()=>{if(!mapping)mapping={subject,customerId:await create()};return mapping;}),findCustomer:async()=>mapping,
  withCustomer:(subject,callback)=>lock(async()=>callback(mapping)),
  applyEvent:async(event,callback)=>{calls.apply++;return lock(async()=>{if(!mapping||event.customerId!==mapping.customerId)throw Error("UNKNOWN_CUSTOMER");const snapshot=await callback(mapping);candidates.push(snapshot.subscriptionId);return {outcome:"applied",snapshot};});},
  applyDisputeEvent:async(event,callback)=>{calls.disputes++;return lock(async()=>{if(!mapping||event.customerId!==mapping.customerId)throw Error("UNKNOWN_CUSTOMER");return {outcome:"applied",dispute:await callback(mapping)};});},
  grantCandidates:async()=>candidates.map(subscriptionId=>({subscriptionId,dirty:true,pushedUntil:null})),
  withGrant:async(subscriptionId,push)=>({until:await push({subscriptionId,customerId:customer.id,subject:mapping.subject,status:"active",currentPeriodEnd:2000000000,
   cancelAtPeriodEnd:false,cancelAt:null,canceledAt:null,endedAt:null,paymentFailedAt:null,disputed:false,dirty:true,pushedUntil:null},7)})};
 const sdk=new Stripe(env.STRIPE_SECRET_KEY);
 const stripe={webhooks:sdk.webhooks,prices:{retrieve:async(id)=>({id,active:true,livemode:false,currency:"eur",unit_amount:prices[id].unit_amount,type:"recurring",recurring:{interval:prices[id].interval,interval_count:1},product:{id:config.productId,active:true,livemode:false}})},
  customers:{create:async(params,options)=>{calls.customer.push({params,options});return {...customer,metadata:params.metadata};},retrieve:async()=>customer},
  subscriptions:{list:async()=>({has_more:false,data:subscriptions}),retrieve:async()=>{calls.retrieveSubscription++;return sub;}},
  disputes:{retrieve:async()=>structuredClone(dispute)},
  checkout:{sessions:{listLineItems:async()=>({has_more:false,data:[{quantity:1,price:{id:lineItemPrice,livemode:false,product:config.productId}}]}),list:async()=>({has_more:false,data:sessions.filter(s=>s.status==="open")}),
   expire:async(id)=>{calls.expire.push(id);sessions.find(s=>s.id===id).status="expired";},
   create:async(params,options)=>{calls.checkout.push({params,options});lineItemPrice=params.line_items[0].price;const result={...params,id:"cs_test_synthetic"+calls.checkout.length,livemode:false,url:"https://checkout.stripe.com/c/pay/cs_test_synthetic",status:"open"};sessions.push(result);return result;}}},
  billingPortal:{sessions:{create:async(params)=>{calls.portal.push(params);return {...params,url:"https://billing.stripe.com/p/session/synthetic"};}}}};
 const push=async(value)=>{calls.pushes.push(value);return true;};
 const deps={env,getSession:async()=>({user:{sub:config.ownerSubject}}),createStripe:()=>stripe,pushGrant:async(cfg,value)=>push(value),
  withStore:async(cfg,callback)=>{assert.equal(cfg.accountId,config.accountId);return callback(store);}};
 return {stripe,store,calls,sub,customer,dispute,deps,push,setSubscriptions:(v)=>subscriptions=v,setSessions:(v)=>sessions=v,setMapping:(v)=>mapping=v};
}
const form=(plan="monthly")=>({headers:{origin:config.origin,"sec-fetch-site":"same-origin","content-type":"application/x-www-form-urlencoded"},body:"plan="+plan});
function request(path="/api/billing/checkout",options=form()) {return new Request(config.origin+path,{method:"POST",headers:{origin:config.origin,"sec-fetch-site":"same-origin"},...options});}
const portalRequest=()=>request("/api/billing/portal",{headers:{origin:config.origin,"sec-fetch-site":"same-origin"}});
function event(type="customer.subscription.updated",extra={}) {return {id:"evt_synthetic",object:"event",api_version:Stripe.API_VERSION,created:Math.floor(Date.now()/1000),livemode:false,type,data:{object:{id:"sub_synthetic",object:"subscription",customer:"cus_synthetic",livemode:false,status:"canceled"}},...extra};}
function signed(f,eventValue,options={}) {const payload=JSON.stringify(eventValue);const signature=f.stripe.webhooks.generateTestHeaderString({payload,secret:env.STRIPE_WEBHOOK_SECRET,...options});return request("/api/stripe/webhook",{headers:{"content-type":"application/json","stripe-signature":signature},body:payload});}

test("billing requires explicit mode and every server-only prerequisite; live/unrestricted keys fail closed in sandbox",()=>{
 for (const key of Object.keys(env)) {if(key==="CRON_SECRET")continue;const candidate={...env};delete candidate[key];assert.equal(readBillingConfig(candidate),null,key);}
 for(const STRIPE_SECRET_KEY of ["sk_live_synthetic","rk_live_synthetic","sk_test_synthetic"])assert.equal(readBillingConfig({...env,STRIPE_SECRET_KEY}),null);
 assert.equal(readBillingConfig({...env,SAIPH_BILLING_MODE:"enabled"}),null);
 assert.equal(readBillingConfig({...env,STRIPE_YEARLY_PRICE_ID:monthly}),null,"plans need distinct prices");
 assert.equal(readBillingConfig({...env,SAIPH_BILLING_GRANT_KEY:"not-a-key"}),null);
 const rsa=generateKeyPairSync("rsa",{modulusLength:1024}).privateKey.export({format:"der",type:"pkcs8"}).toString("base64url");
 assert.equal(readBillingConfig({...env,SAIPH_BILLING_GRANT_KEY:rsa}),null,"only Ed25519 grant keys");
 for(const url of ["http://api.saiph.test","https://api.saiph.test/","https://api.saiph.test:444"])assert.equal(readBillingConfig({...env,SAIPH_HOSTED_API_URL:url}),null,url);
 assert.equal(readBillingConfig({...env,CRON_SECRET:"short"}),null);
 assert.equal(readBillingConfig({...env,CRON_SECRET:undefined}).cronSecret,null,"refresh optional");
 assert.equal(config.grant.issuer,"https://synthetic.us.auth0.com/");
 assert.deepEqual([config.plans.monthly.amount,config.plans.monthly.interval,config.plans.yearly.amount,config.plans.yearly.interval],[999,"month",8999,"year"]);
});
test("live mode needs live restricted keys and is never mixed with test keys",()=>{
 const live=readBillingConfig({...env,SAIPH_BILLING_MODE:"live",STRIPE_SECRET_KEY:"rk_live_synthetic123"});
 assert.ok(live);assert.equal(live.livemode,true);
 for(const STRIPE_SECRET_KEY of ["rk_test_synthetic123","sk_live_synthetic123"])assert.equal(readBillingConfig({...env,SAIPH_BILLING_MODE:"live",STRIPE_SECRET_KEY}),null);
});
test("the webhook endpoint must subscribe to subscription and dispute events",()=>{
 for(const type of ["customer.subscription.updated","invoice.payment_failed","charge.dispute.created","charge.dispute.closed"])assert.ok(acceptedEvents.has(type));
});
test("account actions reject CSRF, query and browser supplied billing identifiers before provider access",async()=>{
 for(const options of [{headers:{}},{headers:{origin:"https://evil.test"}},{headers:{origin:"null"}},{headers:{origin:config.origin,"sec-fetch-site":"cross-site"}},
   {...form(),body:"plan=monthly&price=price_other"},{...form(),body:"customer=cus_other"},{...form(),body:"plan=lifetime"},{...form(),body:""},
   {headers:{...form().headers,"content-type":"application/json"},body:JSON.stringify({plan:"monthly",customer:"cus_other"})}]) {
  const f=fixture();const response=await accountAction(request(undefined,options),"checkout",f.deps);assert.ok([400,403].includes(response.status));assert.equal(f.calls.customer.length,0);
 }
 const f=fixture();assert.equal((await accountAction(request("/api/billing/checkout?price=price_other"),"checkout",f.deps)).status,403);
 assert.equal((await accountAction(request("/api/billing/portal",form()),"portal",f.deps)).status,400,"portal takes no body");
});
test("sandbox: only a verified exact owner session can initiate provider requests",async()=>{
 for(const [session,status] of [[null,401],[{user:{sub:"synthetic|other"}},403],[{user:{}},403]]) {
  const f=fixture();f.deps.getSession=async()=>session;assert.equal((await accountAction(request(),"checkout",f.deps)).status,status);assert.equal(f.calls.customer.length,0);
 }
});
test("live: any signed-in user may subscribe, and second-factor policy still applies",async()=>{
 const liveEnv={...env,SAIPH_BILLING_MODE:"live",STRIPE_SECRET_KEY:"rk_live_synthetic123"};
 const f=fixture();f.deps.env=liveEnv;f.deps.getSession=async()=>({user:{sub:"synthetic|customer"}});
 f.deps.withStore=async()=>{throw Error("reached provider");};
 assert.equal((await accountAction(request(),"checkout",f.deps)).status,503,"allowed past the identity gate");
 f.deps.env={...liveEnv,SAIPH_REQUIRE_MFA:"true"};
 assert.equal((await accountAction(request(),"checkout",f.deps)).status,403);
 f.deps.getSession=async()=>({user:{sub:"synthetic|customer",mfa:true}});
 assert.equal((await accountAction(request(),"checkout",f.deps)).status,503);
});
test("billing stays disabled by default and responses never expose provider errors",async()=>{
 const f=fixture();assert.equal((await accountAction(request(),"checkout",{...f.deps,env:{...env,SAIPH_BILLING_MODE:undefined}})).status,503);
 f.deps.withStore=async()=>{throw Error("credential rk_test_do_not_expose DATABASE_URL");};
 const response=await accountAction(request(),"checkout",f.deps);assert.equal(response.status,503);assert.equal((await response.text()).includes("rk_test"),false);assert.match(response.headers.get("cache-control"),/no-store/);
});
test("checkout binds one customer and reuses one session across concurrent owner requests",async()=>{
 const f=fixture();const responses=await Promise.all(Array.from({length:6},()=>accountAction(request(),"checkout",f.deps)));
 assert.ok(responses.every(r=>r.status===303));assert.equal(f.calls.customer.length,1);assert.equal(f.calls.checkout.length,1);
 const {params,options}=f.calls.checkout[0];assert.deepEqual(params.line_items,[{price:monthly,quantity:1}]);assert.equal(params.customer,"cus_synthetic");assert.equal(params.mode,"subscription");assert.deepEqual(params.allowed_payment_method_types,["card"]);
 assert.equal(params.success_url,config.origin+"/account?checkout=returned");assert.equal(params.subscription_data.metadata.saiph_subject_ref,subjectReference(config.ownerSubject));
 assert.equal(params.consent_collection,undefined,"terms consent is required in live mode only");
 assert.equal(JSON.stringify(params).includes(config.ownerSubject),false);assert.ok(options.idempotencyKey);
 assert.equal(f.calls.customer[0].options.idempotencyKey,customerIdempotency(config.accountId,config.ownerSubject));
});
test("yearly checkout uses the yearly price; switching plans closes the unfinished session",async()=>{
 const f=fixture();
 assert.equal((await accountAction(request(),"checkout",f.deps)).status,303);
 assert.equal((await accountAction(request(undefined,form("yearly")),"checkout",f.deps)).status,303);
 assert.deepEqual(f.calls.expire,["cs_test_synthetic1"]);
 assert.deepEqual(f.calls.checkout.map(c=>c.params.line_items[0].price),[monthly,yearly]);
 assert.notEqual(f.calls.checkout[0].options.idempotencyKey,f.calls.checkout[1].options.idempotencyKey);
 assert.equal((await accountAction(request(undefined,form("yearly")),"checkout",f.deps)).status,303);
 assert.equal(f.calls.checkout.length,2,"same plan reuses the open session");
});
test("reused checkout validates persisted customer and actual provider line items",async()=>{
 for(const mismatch of ["customer","price"]){const f=fixture();await checkout(f.stripe,f.store,config,config.ownerSubject,"monthly");
  if(mismatch==="customer")f.setSessions([{id:"cs_test_synthetic",mode:"subscription",livemode:false,customer:"cus_other",metadata,url:"https://checkout.stripe.com/x",status:"open"}]);
  else f.stripe.checkout.sessions.listLineItems=async()=>({has_more:false,data:[{quantity:1,price:{id:"price_other",livemode:false,product:config.productId}}]});
  await assert.rejects(checkout(f.stripe,f.store,config,config.ownerSubject,"monthly"));assert.equal(f.calls.checkout.length,1);
 }
});
test("existing nonterminal subscription prevents a second purchase with a clear conflict",async()=>{
 for(const status of ["active","trialing","past_due","unpaid","incomplete","paused"]) {const f=fixture();f.setSubscriptions([{status}]);
  const response=await accountAction(request(),"checkout",f.deps);assert.equal(response.status,409);assert.match(await response.text(),/Manage billing/);assert.equal(f.calls.checkout.length,0);}
});
test("price amount, interval, mode and customer binding are checked before checkout",async()=>{
 for(const change of [{livemode:true},{unit_amount:100},{recurring:{interval:"year",interval_count:1}},{currency:"usd"}]) {
  const f=fixture();const original=f.stripe.prices.retrieve;f.stripe.prices.retrieve=async(id)=>({...await original(id),...change});
  await assert.rejects(checkout(f.stripe,f.store,config,config.ownerSubject,"monthly"));assert.equal(f.calls.customer.length,0);
 }
 for(const [plan,oldAmount] of [["monthly",399],["yearly",3600]]) {
  const f=fixture();const original=f.stripe.prices.retrieve;f.stripe.prices.retrieve=async(id)=>({...await original(id),unit_amount:oldAmount});
  await assert.rejects(checkout(f.stripe,f.store,config,config.ownerSubject,plan));assert.equal(f.calls.checkout.length,0,"old prices must not create checkout sessions");
 }
 const g=fixture();g.customer.metadata={...metadata,saiph_subject_ref:"other"};assert.equal((await accountAction(request(),"checkout",g.deps)).status,503);assert.equal(g.calls.checkout.length,0);
});
test("portal is scoped to persisted owner customer and fixed configuration/return URL",async()=>{
 const f=fixture();await assert.rejects(portal(f.stripe,f.store,config,config.ownerSubject));assert.equal(f.calls.portal.length,0);
 assert.equal((await accountAction(portalRequest(),"portal",f.deps)).status,409);
 await checkout(f.stripe,f.store,config,config.ownerSubject,"monthly");const response=await accountAction(portalRequest(),"portal",f.deps);
 assert.equal(response.status,303);assert.equal(response.headers.get("location"),"https://billing.stripe.com/p/session/synthetic");
 assert.deepEqual(f.calls.portal[0],{customer:"cus_synthetic",configuration:config.portalId,return_url:config.origin+"/account"});
});
test("provider redirects accept only exact HTTPS Stripe hosts",()=>{
 for(const url of ["http://checkout.stripe.com/x","https://checkout.stripe.com.evil.test/x","https://user@checkout.stripe.com/x","https://checkout.stripe.com:444/x","javascript:alert(1)","https://billing.stripe.com/x"])assert.throws(()=>stripeUrl(url,"checkout"));
});
test("webhook signature authenticates without an Auth0 browser session and pushes the grant",async()=>{
 const f=fixture();await checkout(f.stripe,f.store,config,config.ownerSubject,"monthly");f.deps.getSession=async()=>{throw Error("must not read browser session");};
 const response=await webhook(signed(f,event()),f.deps);assert.equal(response.status,200);assert.equal(f.calls.retrieveSubscription,1);
 assert.equal(f.calls.pushes.length,1);
 const [value]=f.calls.pushes;
 assert.deepEqual(Object.keys(value),["issuer","subject","grant","until","sequence","livemode"]);
 assert.equal(value.subject,config.ownerSubject);assert.equal(value.grant,"stripe:sub_synthetic");assert.equal(value.livemode,false);assert.equal(value.sequence,7);
 assert.ok(value.until>Math.floor(Date.now()/1000) && value.until<=Math.floor(Date.now()/1000)+35*86400);
});
test("an undelivered grant makes the webhook answer 503 so Stripe retries",async()=>{
 const f=fixture();await checkout(f.stripe,f.store,config,config.ownerSubject,"monthly");
 f.deps.pushGrant=async()=>{throw Error("service down");};
 assert.equal((await webhook(signed(f,event()),f.deps)).status,503);
});
test("webhook uses current Stripe snapshot rather than canceled event payload, for either plan",async()=>{
 const f=fixture();await checkout(f.stripe,f.store,config,config.ownerSubject,"monthly");const result=await processWebhook(f.stripe,f.store,config,event(),f.push);assert.equal(result.snapshot.status,"active");assert.equal(result.snapshot.currentPeriodEnd,2000000000);
 f.sub.items.data[0].price.id=yearly;assert.equal((await processWebhook(f.stripe,f.store,config,event(),f.push)).snapshot.priceId,yearly);
});
test("dispute events use the current dispute and its charge's customer, then push",async()=>{
 const f=fixture();await checkout(f.stripe,f.store,config,config.ownerSubject,"monthly");
 const disputeEvent=event("charge.dispute.created",{data:{object:{id:"dp_synthetic",object:"dispute",livemode:false,status:"won",charge:"ch_synthetic"}}});
 assert.equal(eventDescriptor(disputeEvent,config).kind,"dispute");
 const result=await processWebhook(f.stripe,f.store,config,disputeEvent,f.push);
 assert.equal(result.dispute.status,"needs_response","current provider status, not the payload's");
 assert.equal(f.calls.disputes,1);
 f.dispute.charge.customer="cus_other";
 await assert.rejects(processWebhook(f.stripe,f.store,config,disputeEvent,f.push));
 f.dispute.charge.customer="cus_synthetic";f.dispute.livemode=true;
 await assert.rejects(processWebhook(f.stripe,f.store,config,disputeEvent,f.push));
});
test("signature tampering, expired and future timestamps are rejected without storage",async()=>{
 for(const variant of ["tampered","old","future","unsigned","duplicate timestamp"]) {
  const f=fixture();let req=signed(f,event(),variant==="old"?{timestamp:Math.floor(Date.now()/1000)-600}:variant==="future"?{timestamp:Math.floor(Date.now()/1000)+600}:{});
  if(variant==="tampered")req=new Request(req.url,{method:"POST",headers:req.headers,body:JSON.stringify({...event(),id:"evt_tampered"})});
  if(variant==="duplicate timestamp"){const headers=new Headers(req.headers);headers.set("stripe-signature",headers.get("stripe-signature")+",t=1");req=new Request(req,{headers});}
  if(variant==="unsigned")req=request("/api/stripe/webhook",{headers:{"content-type":"application/json"},body:"{}"});
  assert.equal((await webhook(req,f.deps)).status,400,variant);assert.equal(f.calls.apply,0);assert.equal(f.calls.pushes.length,0);
 }
});
test("signed live, wrong account and incompatible API events fail closed",async()=>{
 for(const extra of [{livemode:true},{account:"acct_other"},{api_version:"2020-08-27"}]) {const f=fixture();assert.equal((await webhook(signed(f,event(undefined,extra)),f.deps)).status,400);assert.equal(f.calls.apply,0);}
});
test("own-account events may omit account; subscription customer/metadata/price must still match",async()=>{
 const f=fixture();await checkout(f.stripe,f.store,config,config.ownerSubject,"monthly");assert.ok(eventDescriptor(event(),config));
 for(const mutation of [()=>f.sub.customer="cus_other",()=>{f.sub.customer="cus_synthetic";f.sub.metadata={...metadata,saiph_account:"acct_other"};},()=>{f.sub.metadata=metadata;f.sub.items.data[0].price.id="price_other";}]) {mutation();await assert.rejects(processWebhook(f.stripe,f.store,config,event(),f.push));}
});
test("sandbox webhooks refuse a customer mapped to anyone but the owner",async()=>{
 const f=fixture();f.setMapping({subject:"synthetic|other",customerId:"cus_synthetic"});
 await assert.rejects(processWebhook(f.stripe,f.store,config,event(),f.push));assert.equal(f.calls.retrieveSubscription,0);
});
test("invoice shape resolves current subscription and no-subscription checkout is ignored",()=>{
 assert.equal(eventDescriptor(event("invoice.paid",{data:{object:{customer:"cus_synthetic",livemode:false,parent:{subscription_details:{subscription:"sub_synthetic"}}}}}),config).subscriptionId,"sub_synthetic");
 assert.equal(eventDescriptor(event("checkout.session.async_payment_failed",{data:{object:{customer:"cus_synthetic",livemode:false,mode:"subscription",subscription:null}}}),config),null);
});
test("bounded raw webhook reader stops oversized streaming bodies",async()=>{
 let cancelled=false;const stream=new ReadableStream({start(controller){controller.enqueue(new Uint8Array(100));controller.enqueue(new Uint8Array(100));},cancel(){cancelled=true;}});
 await assert.rejects(boundedBody(new Request(config.origin,{method:"POST",body:stream,duplex:"half"}),150));assert.equal(cancelled,true);
 const f=fixture();assert.equal((await webhook(request("/api/stripe/webhook",{headers:{"content-type":"application/json","stripe-signature":"t=1,v1=bad","content-length":"300000"},body:"{}"}),f.deps)).status,413);
});
test("GET cannot create checkout/portal or accept a webhook",async()=>{
 const f=fixture();const req=new Request(config.origin+"/api/billing/checkout");assert.equal((await accountAction(req,"checkout",f.deps)).status,405);assert.equal((await webhook(req,f.deps)).status,405);assert.equal(f.calls.customer.length,0);
});
test("daily refresh requires the exact cron secret and reports delivery",async()=>{
 const f=fixture();await checkout(f.stripe,f.store,config,config.ownerSubject,"monthly");await processWebhook(f.stripe,f.store,config,event(),f.push);
 const cron=(authorization,url=config.origin+"/api/billing/refresh")=>new Request(url,{headers:authorization===null?{}:{authorization}});
 for(const authorization of [null,"Bearer wrong","Bearer "+"c".repeat(39),"bearer "+"c".repeat(40),"c".repeat(40)])
  assert.equal((await refresh(cron(authorization),f.deps)).status,401,String(authorization));
 assert.equal((await refresh(cron("Bearer "+"c".repeat(40),config.origin+"/api/billing/refresh?all=1"),f.deps)).status,401);
 const before=f.calls.pushes.length;
 const ok=await refresh(cron("Bearer "+"c".repeat(40)),f.deps);
 assert.equal(ok.status,200);assert.deepEqual(await ok.json(),{pushed:1,failed:0});assert.equal(f.calls.pushes.length,before+1);
 f.deps.pushGrant=async()=>{throw Error("down");};
 assert.equal((await refresh(cron("Bearer "+"c".repeat(40)),f.deps)).status,503);
 assert.equal((await refresh(cron("Bearer "+"c".repeat(40)),{...f.deps,env:{...env,CRON_SECRET:""}})).status,503);
 assert.equal((await refresh(new Request(config.origin+"/api/billing/refresh",{method:"POST",headers:{authorization:"Bearer "+"c".repeat(40)}}),f.deps)).status,405);
});
test("surrounding whitespace in pasted settings is ignored; rejected settings are named, never echoed",async()=>{
 const padded={...env,SAIPH_BILLING_GRANT_KEY:env.SAIPH_BILLING_GRANT_KEY+"\n",CRON_SECRET:" "+env.CRON_SECRET+"\r\n",STRIPE_WEBHOOK_SECRET:env.STRIPE_WEBHOOK_SECRET+" ",SAIPH_BILLING_MODE:"owner-sandbox\n"};
 const tolerant=readBillingConfig(padded);assert.ok(tolerant);assert.equal(tolerant.cronSecret,env.CRON_SECRET);assert.equal(tolerant.webhookSecret,env.STRIPE_WEBHOOK_SECRET);
 const {checkBillingConfig,reportBillingConfig}=await import("../lib/billing/policy.ts");
 assert.deepEqual(checkBillingConfig(env).problems,[]);
 assert.deepEqual(checkBillingConfig({...env,SAIPH_BILLING_MODE:"disabled"}),{config:null,problems:[]},"disabled on purpose is silent");
 assert.deepEqual(checkBillingConfig({...env,SAIPH_BILLING_MODE:"enabled"}).problems,["SAIPH_BILLING_MODE"]);
 assert.deepEqual(checkBillingConfig({...env,SAIPH_BILLING_MODE:undefined}).problems,[]);
 const broken={...env,STRIPE_SECRET_KEY:"sk_live_synthetic123",SAIPH_BILLING_GRANT_KEY:"not-a-key-secretvalue",CRON_SECRET:"short"};
 const checked=checkBillingConfig(broken);assert.equal(checked.config,null);
 assert.deepEqual(checked.problems,["STRIPE_SECRET_KEY","CRON_SECRET","SAIPH_BILLING_GRANT_KEY"]);
 const logged=[];const original=console.error;console.error=(line)=>logged.push(String(line));
 try {reportBillingConfig(broken);reportBillingConfig(broken);} finally {console.error=original;}
 assert.equal(logged.length,1,"one line per server instance");
 assert.match(logged[0],/STRIPE_SECRET_KEY, CRON_SECRET, SAIPH_BILLING_GRANT_KEY/);
 assert.equal(/synthetic123|secretvalue|short/.test(logged[0]),false,"no value appears in the log");
});
