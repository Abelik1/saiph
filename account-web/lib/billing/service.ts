// SPDX-License-Identifier: AGPL-3.0-or-later
import Stripe from "stripe";
import {customerIdempotency,disputeEvents,planForPrice,resourceId,stripeUrl,subjectReference,subscriptionEvents,type BillingConfig,type Plan,type PlanKey} from "./policy.ts";
import {syncGrants} from "./grant-sync.mjs";
import type {GrantValue} from "./grant-push.mjs";
export type Mapping={subject:string;customerId:string};
export type Snapshot={subscriptionId:string;customerId:string;priceId:string;status:string;currentPeriodEnd:number|null;cancelAtPeriodEnd:boolean;cancelAt:number|null;canceledAt:number|null;endedAt:number|null;livemode:boolean};
export type DisputeSnapshot={disputeId:string;customerId:string;status:string;livemode:boolean};
export type StoredEvent={eventId:string;type:string;created:number;customerId:string;livemode:boolean};
export type BillingStore=ReturnType<typeof import("./store.mjs").createBillingStore>;
export type GrantPush=(value:GrantValue)=>Promise<boolean>;
/** Refusals the account page can explain; everything else stays generic. */
export class BillingConflict extends Error {}
// Sandbox objects created before paid Hosted keep their marker; live uses its own.
function marker(config:BillingConfig) {return config.livemode?"hosted-live-v1":"owner-sandbox-v1";}
function metadata(config:BillingConfig,subject:string) {return {saiph_billing:marker(config),saiph_subject_ref:subjectReference(subject),saiph_account:config.accountId};}
function validMetadata(value:Stripe.Metadata|null|undefined,config:BillingConfig,subject:string) {
  const expected=metadata(config,subject);
  return value?.saiph_billing===expected.saiph_billing && value?.saiph_subject_ref===expected.saiph_subject_ref && value?.saiph_account===expected.saiph_account;
}
function assertCustomer(customer:Stripe.Customer|Stripe.DeletedCustomer,config:BillingConfig,subject:string) {
  if (customer.deleted || customer.livemode!==config.livemode || !validMetadata(customer.metadata,config,subject)) throw new Error("Customer binding rejected");
}
export function createStripe(config:BillingConfig) {return new Stripe(config.secretKey,{maxNetworkRetries:2,timeout:10000,telemetry:false});}
export async function verifyPrice(stripe:Stripe,config:BillingConfig,plan:Plan) {
  const price=await stripe.prices.retrieve(plan.priceId,{expand:["product"]});
  const product=typeof price.product==="string"?await stripe.products.retrieve(price.product):price.product;
  if (price.id!==plan.priceId || price.livemode!==config.livemode || !price.active || price.currency!=="eur" || price.unit_amount!==plan.amount
    || price.type!=="recurring" || price.recurring?.interval!==plan.interval || price.recurring.interval_count!==1
    || product.id!==config.productId || product.deleted || product.livemode!==config.livemode || !product.active) throw new Error("Price rejected");
}
async function assertBinding(stripe:Stripe,config:BillingConfig,mapping:Mapping) {
  assertCustomer(await stripe.customers.retrieve(mapping.customerId),config,mapping.subject);
}
/** Shown above Stripe's pay button (owner request, 15 October 2026). */
export const BETA_CHECKOUT_NOTICE="Saiph Hosted is a beta service: expect bugs, missing features and occasional downtime, and features may change. "
  +"You can withdraw within 14 days of subscribing for a full refund from your account page.";
export async function checkout(stripe:Stripe,store:BillingStore,config:BillingConfig,subject:string,planKey:PlanKey) {
  const plan=config.plans[planKey];
  await verifyPrice(stripe,config,plan);
  await store.getOrCreateCustomer(subject,async()=>{
    const customer=await stripe.customers.create({metadata:metadata(config,subject)},{idempotencyKey:customerIdempotency(config.accountId,subject)});
    assertCustomer(customer,config,subject);return customer.id;
  });
  return store.withCustomer(subject,async(mapping)=>{
    await assertBinding(stripe,config,mapping);
    // Serialize provider inspection and create under the persistent customer lock.
    const subscriptions=await stripe.subscriptions.list({customer:mapping.customerId,status:"all",limit:100});
    if (subscriptions.has_more) throw new Error("Subscription reconciliation required");
    if (subscriptions.data.some(s=>!["canceled","incomplete_expired"].includes(s.status))) throw new BillingConflict("Existing subscription must be managed in portal");
    const sessions=await stripe.checkout.sessions.list({customer:mapping.customerId,status:"open",limit:100});
    if (sessions.has_more) throw new Error("Checkout reconciliation required");
    const open=sessions.data.filter(s=>s.mode==="subscription");
    if (open.length>1) throw new Error("Checkout reconciliation required");
    if (open.length===1) {
      const session=open[0];
      if (session.livemode!==config.livemode || resourceId(session.customer,"cus")!==mapping.customerId || !validMetadata(session.metadata,config,subject)) throw new Error("Checkout binding rejected");
      const items=await stripe.checkout.sessions.listLineItems(session.id,{limit:2,expand:["data.price.product"]});
      if (items.has_more || items.data.length!==1 || items.data[0].quantity!==1 || !planForPrice(config,items.data[0].price?.id)
        || items.data[0].price?.livemode!==config.livemode || resourceId(items.data[0].price.product,"prod")!==config.productId) throw new Error("Checkout price binding rejected");
      if (items.data[0].price.id===plan.priceId) return stripeUrl(session.url,"checkout");
      // The other plan was chosen: close the unfinished session before opening a new one.
      await stripe.checkout.sessions.expire(session.id);
    }
    const session=await stripe.checkout.sessions.create({mode:"subscription",customer:mapping.customerId,
      line_items:[{price:plan.priceId,quantity:1}],allowed_payment_method_types:["card"],
      metadata:metadata(config,subject),subscription_data:{metadata:metadata(config,subject)},
      custom_text:{submit:{message:BETA_CHECKOUT_NOTICE}},
      ...(config.livemode?{consent_collection:{terms_of_service:"required" as const}}:{}),
      ...(config.automaticTax?{automatic_tax:{enabled:true},customer_update:{address:"auto" as const},billing_address_collection:"required" as const}:{}),
      success_url:config.origin+"/account?checkout=returned",cancel_url:config.origin+"/account?checkout=cancelled"},
      {idempotencyKey:"saiph-checkout-v3-"+subjectReference(config.accountId+":"+mapping.customerId+":"+plan.priceId+":"+Math.floor(Date.now()/1800000))});
    if (session.livemode!==config.livemode || resourceId(session.customer,"cus")!==mapping.customerId || !validMetadata(session.metadata,config,subject)) throw new Error("Checkout binding rejected");
    return stripeUrl(session.url,"checkout");
  });
}
export async function portal(stripe:Stripe,store:BillingStore,config:BillingConfig,subject:string) {
  const mapping=await store.findCustomer(subject); if (!mapping) throw new BillingConflict("Customer unavailable");
  await assertBinding(stripe,config,mapping);
  const session=await stripe.billingPortal.sessions.create({customer:mapping.customerId,configuration:config.portalId,return_url:config.origin+"/account"});
  if (session.customer!==mapping.customerId || session.configuration!==config.portalId && resourceId(session.configuration,"bpc")!==config.portalId) throw new Error("Portal binding rejected");
  return stripeUrl(session.url,"portal");
}
type Descriptor={kind:"subscription";event:StoredEvent;subscriptionId:string}|{kind:"dispute";event:Omit<StoredEvent,"customerId">;disputeId:string};
export function eventDescriptor(event:Stripe.Event,config:BillingConfig):Descriptor|null {
  if (event.api_version!==Stripe.API_VERSION || event.livemode!==config.livemode || event.account && event.account!==config.accountId || !resourceId(event.id,"evt") || !Number.isSafeInteger(event.created) || event.created<0) throw new Error("Event rejected");
  const object=event.data.object as unknown as Record<string,unknown>;
  if (disputeEvents.has(event.type)) {
    if (object.livemode!==config.livemode) throw new Error("Event rejected");
    const disputeId=resourceId(object.id,"dp") ?? resourceId(object.id,"du"); if (!disputeId) throw new Error("Event rejected");
    return {kind:"dispute",event:{eventId:event.id,type:event.type,created:event.created,livemode:config.livemode},disputeId};
  }
  if (!subscriptionEvents.has(event.type)) return null;
  if (object.livemode!==config.livemode) throw new Error("Event rejected");
  const customerId=resourceId(object.customer,"cus"); if (!customerId) throw new Error("Event customer rejected");
  let subscriptionId:string|null=null;
  if (event.type.startsWith("customer.subscription.")) subscriptionId=resourceId(object.id,"sub");
  else if (event.type.startsWith("checkout.session.")) {
    if (object.mode!=="subscription") return null;
    subscriptionId=resourceId(object.subscription,"sub");
  } else {
    const parent=object.parent as {subscription_details?:{subscription?:unknown}}|undefined;
    subscriptionId=resourceId(parent?.subscription_details?.subscription ?? object.subscription,"sub");
  }
  if (!subscriptionId) return null; // failed/uncompleted Checkout may not have a Subscription.
  return {kind:"subscription",event:{eventId:event.id,type:event.type,created:event.created,customerId,livemode:config.livemode},subscriptionId};
}
function checkMapping(config:BillingConfig,mapping:Mapping,customerId:string) {
  if ((!config.livemode && mapping.subject!==config.ownerSubject) || mapping.customerId!==customerId) throw new Error("Customer binding rejected");
}
/** Current dispute status and its customer, fetched from Stripe (never the event payload). */
async function currentDispute(stripe:Stripe,config:BillingConfig,disputeId:string):Promise<DisputeSnapshot> {
  const dispute=await stripe.disputes.retrieve(disputeId,{expand:["charge"]});
  const charge=dispute.charge as Stripe.Charge|string;
  const customerId=typeof charge==="string"?null:resourceId(charge.customer,"cus");
  if (dispute.livemode!==config.livemode || !customerId || typeof charge==="string" || charge.livemode!==config.livemode) throw new Error("Dispute rejected");
  return {disputeId:dispute.id,customerId,status:dispute.status,livemode:config.livemode};
}
export function grantPolicy(config:BillingConfig) {
  return {issuer:config.grant.issuer,livemode:config.livemode,ownerOnly:config.livemode?null:config.ownerSubject};
}
/** Apply one verified event, then deliver the affected grants. Throws if any
 * grant could not be delivered, so the webhook answers 503 and Stripe retries. */
export async function processWebhook(stripe:Stripe,store:BillingStore,config:BillingConfig,event:Stripe.Event,push:GrantPush) {
  const descriptor=eventDescriptor(event,config);if (!descriptor) return {outcome:"ignored"};
  let customerId:string;let result:unknown;
  if (descriptor.kind==="dispute") {
    customerId=(await currentDispute(stripe,config,descriptor.disputeId)).customerId;
    result=await store.applyDisputeEvent({...descriptor.event,customerId},async(mapping)=>{
      checkMapping(config,mapping,customerId);
      await assertBinding(stripe,config,mapping);
      const dispute=await currentDispute(stripe,config,descriptor.disputeId);
      if (dispute.customerId!==customerId) throw new Error("Dispute binding rejected");
      return dispute;
    });
  } else {
    customerId=descriptor.event.customerId;
    result=await store.applyEvent(descriptor.event,async(mapping)=>{
      // Fetch current provider state after acquiring the database customer lock.
      // Event payloads and redirect queries never determine subscription state.
      checkMapping(config,mapping,customerId);
      await assertBinding(stripe,config,mapping);
      const sub=await stripe.subscriptions.retrieve(descriptor.subscriptionId,{expand:["items.data.price.product"]});
      const item=sub.items.data[0];
      if (sub.livemode!==config.livemode || resourceId(sub.customer,"cus")!==mapping.customerId || !validMetadata(sub.metadata,config,mapping.subject)
        || sub.items.has_more || sub.items.data.length!==1 || item.quantity!==1 || !planForPrice(config,item.price.id)
        || item.price.livemode!==config.livemode || resourceId(item.price.product,"prod")!==config.productId) throw new Error("Subscription binding rejected");
      return {subscriptionId:sub.id,customerId:mapping.customerId,priceId:item.price.id,status:sub.status,
        currentPeriodEnd:item.current_period_end ?? null,cancelAtPeriodEnd:sub.cancel_at_period_end,cancelAt:sub.cancel_at ?? null,canceledAt:sub.canceled_at,endedAt:sub.ended_at,livemode:config.livemode};
    });
  }
  const delivery=await syncGrants(store,grantPolicy(config),push,{customerId});
  if (delivery.failed) throw new Error("Hosted grant delivery pending");
  return result;
}
/** EU right of withdrawal: 14 days from the start of the contract (docs/PAID_HOSTED.md). */
export const WITHDRAWAL_SECONDS=14*86400;
/** Per-charge idempotency prefix: a repeated withdrawal never refunds twice. */
const WITHDRAWAL_REFUND_PREFIX="saiph-withdrawal-v1-";
export class WithdrawalUnavailable extends Error {}
export type WithdrawalStatus=
  {state:"none"}|
  {state:"eligible";subscriptionId:string;startedAt:number;deadline:number;refund:number;currency:string}|
  {state:"expired";deadline:number}|
  {state:"withdrawn";at:number;refunded:number;currency:string};
async function withdrawalFacts(stripe:Stripe,config:BillingConfig,mapping:Mapping,now:number):Promise<{status:WithdrawalStatus;charges:Stripe.Charge[]}> {
  await assertBinding(stripe,config,mapping);
  const subscriptions=await stripe.subscriptions.list({customer:mapping.customerId,status:"all",limit:100});
  if (subscriptions.has_more) throw new Error("Subscription reconciliation required");
  const latest=subscriptions.data.filter(s=>s.livemode===config.livemode && validMetadata(s.metadata,config,mapping.subject))
    .sort((a,b)=>b.created-a.created)[0];
  if (!latest) return {status:{state:"none"},charges:[]};
  const deadline=latest.start_date+WITHDRAWAL_SECONDS;
  const listed=await stripe.charges.list({customer:mapping.customerId,created:{gte:latest.start_date},limit:100});
  if (listed.has_more) throw new Error("Charge reconciliation required");
  const charges=listed.data.filter(c=>c.livemode===config.livemode && c.paid && c.status==="succeeded");
  const currency=charges[0]?.currency ?? "eur";
  const withdrawnAt=Number(latest.metadata?.saiph_withdrawal_at);
  if (Number.isSafeInteger(withdrawnAt) && withdrawnAt>0)
    return {status:{state:"withdrawn",at:withdrawnAt,refunded:charges.reduce((sum,c)=>sum+c.amount_refunded,0),currency},charges};
  if (["canceled","incomplete_expired"].includes(latest.status)) return {status:{state:"none"},charges:[]};
  if (now>=deadline) return {status:{state:"expired",deadline},charges:[]};
  const refundable=charges.filter(c=>!c.refunded);
  return {status:{state:"eligible",subscriptionId:latest.id,startedAt:latest.start_date,deadline,
    refund:refundable.reduce((sum,c)=>sum+(c.amount-c.amount_refunded),0),currency},charges:refundable};
}
/** What the withdrawal page shows. Reads Stripe; changes nothing. */
export async function withdrawalStatus(stripe:Stripe,store:BillingStore,config:BillingConfig,subject:string,now=Math.floor(Date.now()/1000)) {
  const mapping=await store.findCustomer(subject);
  return mapping ? (await withdrawalFacts(stripe,config,mapping,now)).status : {state:"none"} as WithdrawalStatus;
}
/**
 * Withdraw within 14 days: mark, end the subscription now and refund every
 * charge since it started in full (owner policy: no deduction for use).
 * Hosted access ends through the resulting signed webhook, as for any
 * cancellation. Repeat-safe: refunds use per-charge idempotency keys.
 */
export async function withdraw(stripe:Stripe,store:BillingStore,config:BillingConfig,subject:string,now=Math.floor(Date.now()/1000)) {
  return store.withCustomer(subject,async(mapping)=>{
    const {status,charges}=await withdrawalFacts(stripe,config,mapping,now);
    if (status.state!=="eligible") throw new WithdrawalUnavailable("No contract to withdraw from");
    await stripe.subscriptions.update(status.subscriptionId,{metadata:{saiph_withdrawal_at:String(now)}});
    await stripe.subscriptions.cancel(status.subscriptionId,{invoice_now:false,prorate:false,
      cancellation_details:{comment:"Withdrawal within 14 days (EU right of withdrawal)"}});
    for (const charge of charges) {
      await stripe.refunds.create({charge:charge.id,reason:"requested_by_customer",metadata:{saiph_withdrawal:"1"}},
        {idempotencyKey:WITHDRAWAL_REFUND_PREFIX+charge.id});
    }
    return {at:now,refunded:status.refund,currency:status.currency};
  });
}
