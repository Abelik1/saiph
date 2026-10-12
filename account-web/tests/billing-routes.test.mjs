// SPDX-License-Identifier: AGPL-3.0-or-later
// Synthetic provider fixtures exercise decisions and the official SDK signature
// verifier. These are not a real Stripe sandbox or Neon acceptance receipt.
import {test} from "node:test";
import assert from "node:assert/strict";
import Stripe from "stripe";
import {ownerAction,webhook,boundedBody} from "../lib/billing/http.ts";
import {readBillingConfig,subjectReference,customerIdempotency,stripeUrl} from "../lib/billing/policy.ts";
import {checkout,portal,processWebhook,eventDescriptor} from "../lib/billing/service.ts";
const env={SAIPH_BILLING_MODE:"owner-sandbox",AUTH0_DOMAIN:"synthetic.us.auth0.com",AUTH0_CLIENT_ID:"syntheticclient",AUTH0_CLIENT_SECRET:"synthetic-not-real",AUTH0_SECRET:"ab".repeat(32),APP_BASE_URL:"https://account.saiph.test",SAIPH_OWNER_SUBJECT:"synthetic|owner",STRIPE_SECRET_KEY:"rk_test_synthetic123",STRIPE_WEBHOOK_SECRET:"whsec_synthetic123",STRIPE_EXPECTED_ACCOUNT_ID:"acct_synthetic",STRIPE_PRODUCT_ID:"prod_synthetic",STRIPE_PRICE_ID:"price_synthetic",STRIPE_PORTAL_CONFIGURATION_ID:"bpc_synthetic",DATABASE_URL:"postgresql://synthetic:synthetic@synthetic-pooler.eu-west-2.aws.neon.tech/synthetic?sslmode=require"};
const config=readBillingConfig(env);assert.ok(config);
const metadata={saiph_billing:"owner-sandbox-v1",saiph_subject_ref:subjectReference(config.ownerSubject),saiph_account:config.accountId};
function fixture() {
 let mapping=null;let queue=Promise.resolve();const calls={customer:[],checkout:[],portal:[],retrieveSubscription:0,apply:0};
 let sessions=[];let subscriptions=[];
 const customer={id:"cus_synthetic",livemode:false,metadata};
 const sub={id:"sub_synthetic",customer:customer.id,livemode:false,metadata,status:"active",cancel_at_period_end:false,canceled_at:null,ended_at:null,items:{has_more:false,data:[{quantity:1,current_period_end:2000000000,price:{id:config.priceId,livemode:false,product:config.productId}}]}};
 async function lock(callback) {let release;const previous=queue;queue=new Promise(r=>release=r);await previous;try{return await callback();}finally{release();}}
 const store={getOrCreateCustomer:(subject,create)=>lock(async()=>{if(!mapping)mapping={subject,customerId:await create()};return mapping;}),findCustomer:async()=>mapping,
  withCustomer:(subject,callback)=>lock(async()=>callback(mapping)),applyEvent:async(event,callback)=>{calls.apply++;return lock(async()=>{if(!mapping||event.customerId!==mapping.customerId)throw Error("UNKNOWN_CUSTOMER");return {outcome:"applied",snapshot:await callback(mapping)};});}};
 const sdk=new Stripe(env.STRIPE_SECRET_KEY);
 const stripe={webhooks:sdk.webhooks,prices:{retrieve:async()=>({id:config.priceId,active:true,livemode:false,currency:"eur",unit_amount:100,type:"recurring",recurring:{interval:"month",interval_count:1},product:{id:config.productId,active:true,livemode:false}})},
  customers:{create:async(params,options)=>{calls.customer.push({params,options});return {...customer,metadata:params.metadata};},retrieve:async()=>customer},
  subscriptions:{list:async()=>({has_more:false,data:subscriptions}),retrieve:async()=>{calls.retrieveSubscription++;return sub;}},
  checkout:{sessions:{listLineItems:async()=>({has_more:false,data:[{quantity:1,price:{id:config.priceId,livemode:false,product:config.productId}}]}),list:async()=>({has_more:false,data:sessions}),create:async(params,options)=>{calls.checkout.push({params,options});const result={...params,id:"cs_test_synthetic",livemode:false,url:"https://checkout.stripe.com/c/pay/cs_test_synthetic",status:"open"};sessions.push(result);return result;}}},
  billingPortal:{sessions:{create:async(params)=>{calls.portal.push(params);return {...params,url:"https://billing.stripe.com/p/session/synthetic"};}}}};
 const deps={env,getSession:async()=>({user:{sub:config.ownerSubject}}),createStripe:()=>stripe,withStore:async(account,callback)=>{assert.equal(account,config.accountId);return callback(store);}};
 return {stripe,store,calls,sub,customer,deps,setSubscriptions:(v)=>subscriptions=v,setSessions:(v)=>sessions=v,setMapping:(v)=>mapping=v};
}
function request(path="/api/billing/checkout",options={}) {return new Request(config.origin+path,{method:"POST",headers:{origin:config.origin,"sec-fetch-site":"same-origin"},...options});}
function event(type="customer.subscription.updated",extra={}) {return {id:"evt_synthetic",object:"event",api_version:Stripe.API_VERSION,created:Math.floor(Date.now()/1000),livemode:false,type,data:{object:{id:"sub_synthetic",object:"subscription",customer:"cus_synthetic",livemode:false,status:"canceled"}},...extra};}
function signed(f,eventValue,options={}) {const payload=JSON.stringify(eventValue);const signature=f.stripe.webhooks.generateTestHeaderString({payload,secret:env.STRIPE_WEBHOOK_SECRET,...options});return request("/api/stripe/webhook",{headers:{"content-type":"application/json","stripe-signature":signature},body:payload});}
test("billing requires explicit mode and every server-only prerequisite; live/unrestricted keys fail closed",()=>{
 for (const key of Object.keys(env)) {const candidate={...env};delete candidate[key];assert.equal(readBillingConfig(candidate),null,key);}
 for(const STRIPE_SECRET_KEY of ["sk_live_synthetic","rk_live_synthetic","sk_test_synthetic"])assert.equal(readBillingConfig({...env,STRIPE_SECRET_KEY}),null);
 assert.equal(readBillingConfig({...env,SAIPH_BILLING_MODE:"enabled"}),null);
});
test("owner actions reject CSRF, query and browser supplied billing identifiers before provider access",async()=>{
 for(const options of [{headers:{}},{headers:{origin:"https://evil.test"}},{headers:{origin:"null"}},{headers:{origin:config.origin,"sec-fetch-site":"cross-site"}},{body:JSON.stringify({customer:"cus_other",price:"price_other",subject:"synthetic|other"})}]) {
  const f=fixture();const response=await ownerAction(request(undefined,options),"checkout",f.deps);assert.ok([400,403].includes(response.status));assert.equal(f.calls.customer.length,0);
 }
 const f=fixture();assert.equal((await ownerAction(request("/api/billing/checkout?price=price_other"),"checkout",f.deps)).status,403);
});
test("only a verified exact owner session can initiate provider requests",async()=>{
 for(const [session,status] of [[null,401],[{user:{sub:"synthetic|other"}},403],[{user:{}},403]]) {
  const f=fixture();f.deps.getSession=async()=>session;assert.equal((await ownerAction(request(),"checkout",f.deps)).status,status);assert.equal(f.calls.customer.length,0);
 }
});
test("billing stays disabled by default and responses never expose provider errors",async()=>{
 const f=fixture();assert.equal((await ownerAction(request(),"checkout",{...f.deps,env:{...env,SAIPH_BILLING_MODE:undefined}})).status,503);
 f.deps.withStore=async()=>{throw Error("credential rk_test_do_not_expose DATABASE_URL");};
 const response=await ownerAction(request(),"checkout",f.deps);assert.equal(response.status,503);assert.equal((await response.text()).includes("rk_test"),false);assert.match(response.headers.get("cache-control"),/no-store/);
});
test("checkout binds one customer and reuses one session across concurrent owner requests",async()=>{
 const f=fixture();const responses=await Promise.all(Array.from({length:6},()=>ownerAction(request(),"checkout",f.deps)));
 assert.ok(responses.every(r=>r.status===303));assert.equal(f.calls.customer.length,1);assert.equal(f.calls.checkout.length,1);
 const {params,options}=f.calls.checkout[0];assert.deepEqual(params.line_items,[{price:config.priceId,quantity:1}]);assert.equal(params.customer,"cus_synthetic");assert.equal(params.mode,"subscription");assert.deepEqual(params.allowed_payment_method_types,["card"]);
 assert.equal(params.success_url,config.origin+"/account?checkout=returned");assert.equal(params.subscription_data.metadata.saiph_subject_ref,subjectReference(config.ownerSubject));
 assert.equal(JSON.stringify(params).includes(config.ownerSubject),false);assert.ok(options.idempotencyKey);
 assert.equal(f.calls.customer[0].options.idempotencyKey,customerIdempotency(config.accountId,config.ownerSubject));
});
test("reused checkout validates persisted customer and actual provider line items",async()=>{
 for(const mismatch of ["customer","price"]){const f=fixture();await checkout(f.stripe,f.store,config,config.ownerSubject);
  if(mismatch==="customer")f.setSessions([{id:"cs_test_synthetic",mode:"subscription",livemode:false,customer:"cus_other",metadata,url:"https://checkout.stripe.com/x"}]);
  else f.stripe.checkout.sessions.listLineItems=async()=>({has_more:false,data:[{quantity:1,price:{id:"price_other",livemode:false,product:config.productId}}]});
  await assert.rejects(checkout(f.stripe,f.store,config,config.ownerSubject));assert.equal(f.calls.checkout.length,1);
 }
});
test("existing nonterminal subscription prevents a second purchase",async()=>{
 for(const status of ["active","trialing","past_due","unpaid","incomplete","paused"]) {const f=fixture();f.setSubscriptions([{status}]);assert.equal((await ownerAction(request(),"checkout",f.deps)).status,503);assert.equal(f.calls.checkout.length,0);}
});
test("price and customer mode/binding are checked before checkout",async()=>{
 const f=fixture();f.stripe.prices.retrieve=async()=>({id:config.priceId,active:true,livemode:true});await assert.rejects(checkout(f.stripe,f.store,config,config.ownerSubject));assert.equal(f.calls.customer.length,0);
 const g=fixture();g.customer.metadata={...metadata,saiph_subject_ref:"other"};assert.equal((await ownerAction(request(),"checkout",g.deps)).status,503);assert.equal(g.calls.checkout.length,0);
});
test("portal is scoped to persisted owner customer and fixed configuration/return URL",async()=>{
 const f=fixture();await assert.rejects(portal(f.stripe,f.store,config,config.ownerSubject));assert.equal(f.calls.portal.length,0);
 await checkout(f.stripe,f.store,config,config.ownerSubject);const response=await ownerAction(request("/api/billing/portal"),"portal",f.deps);
 assert.equal(response.status,303);assert.equal(response.headers.get("location"),"https://billing.stripe.com/p/session/synthetic");
 assert.deepEqual(f.calls.portal[0],{customer:"cus_synthetic",configuration:config.portalId,return_url:config.origin+"/account"});
});
test("provider redirects accept only exact HTTPS Stripe hosts",()=>{
 for(const url of ["http://checkout.stripe.com/x","https://checkout.stripe.com.evil.test/x","https://user@checkout.stripe.com/x","https://checkout.stripe.com:444/x","javascript:alert(1)","https://billing.stripe.com/x"])assert.throws(()=>stripeUrl(url,"checkout"));
});
test("webhook signature authenticates without an Auth0 browser session",async()=>{
 const f=fixture();await checkout(f.stripe,f.store,config,config.ownerSubject);f.deps.getSession=async()=>{throw Error("must not read browser session");};
 const response=await webhook(signed(f,event()),f.deps);assert.equal(response.status,200);assert.equal(f.calls.retrieveSubscription,1);
});
test("webhook uses current Stripe snapshot rather than canceled event payload",async()=>{
 const f=fixture();await checkout(f.stripe,f.store,config,config.ownerSubject);const result=await processWebhook(f.stripe,f.store,config,event());assert.equal(result.snapshot.status,"active");assert.equal(result.snapshot.currentPeriodEnd,2000000000);
});
test("signature tampering, expired and future timestamps are rejected without storage",async()=>{
 for(const variant of ["tampered","old","future","unsigned","duplicate timestamp"]) {
  const f=fixture();let req=signed(f,event(),variant==="old"?{timestamp:Math.floor(Date.now()/1000)-600}:variant==="future"?{timestamp:Math.floor(Date.now()/1000)+600}:{});
  if(variant==="tampered")req=new Request(req.url,{method:"POST",headers:req.headers,body:JSON.stringify({...event(),id:"evt_tampered"})});
  if(variant==="duplicate timestamp"){const headers=new Headers(req.headers);headers.set("stripe-signature",headers.get("stripe-signature")+",t=1");req=new Request(req,{headers});}
  if(variant==="unsigned")req=request("/api/stripe/webhook",{headers:{"content-type":"application/json"},body:"{}"});
  assert.equal((await webhook(req,f.deps)).status,400,variant);assert.equal(f.calls.apply,0);
 }
});
test("signed live, wrong account and incompatible API events fail closed",async()=>{
 for(const extra of [{livemode:true},{account:"acct_other"},{api_version:"2020-08-27"}]) {const f=fixture();assert.equal((await webhook(signed(f,event(undefined,extra)),f.deps)).status,400);assert.equal(f.calls.apply,0);}
});
test("own-account events may omit account; subscription customer/metadata/price must still match",async()=>{
 const f=fixture();await checkout(f.stripe,f.store,config,config.ownerSubject);assert.ok(eventDescriptor(event(),config));
 for(const mutation of [()=>f.sub.customer="cus_other",()=>{f.sub.customer="cus_synthetic";f.sub.metadata={...metadata,saiph_account:"acct_other"};},()=>{f.sub.metadata=metadata;f.sub.items.data[0].price.id="price_other";}]) {mutation();await assert.rejects(processWebhook(f.stripe,f.store,config,event()));}
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
 const f=fixture();const req=new Request(config.origin+"/api/billing/checkout");assert.equal((await ownerAction(req,"checkout",f.deps)).status,405);assert.equal((await webhook(req,f.deps)).status,405);assert.equal(f.calls.customer.length,0);
});
