// SPDX-License-Identifier: AGPL-3.0-or-later
import Stripe from "stripe";
import {acceptedEvents,customerIdempotency,resourceId,stripeUrl,subjectReference,type BillingConfig} from "./policy.ts";
export type Mapping={subject:string;customerId:string};
export type Snapshot={subscriptionId:string;customerId:string;priceId:string;status:string;currentPeriodEnd:number|null;cancelAtPeriodEnd:boolean;cancelAt:number|null;canceledAt:number|null;endedAt:number|null;livemode:false};
export type StoredEvent={eventId:string;type:string;created:number;customerId:string;livemode:false};
export type BillingStore={getOrCreateCustomer(subject:string,create:()=>Promise<string>):Promise<Mapping>;
  findCustomer(subject:string):Promise<Mapping|null>;
  withCustomer<T>(subject:string,callback:(mapping:Mapping)=>Promise<T>):Promise<T>;
  applyEvent(event:StoredEvent,loadSnapshot:(mapping:Mapping)=>Promise<Snapshot>):Promise<unknown>};
const marker="owner-sandbox-v1";
function metadata(config:BillingConfig,subject:string) {return {saiph_billing:marker,saiph_subject_ref:subjectReference(subject),saiph_account:config.accountId};}
function validMetadata(value:Stripe.Metadata|null|undefined,config:BillingConfig,subject:string) {
  const expected=metadata(config,subject);
  return value?.saiph_billing===expected.saiph_billing && value?.saiph_subject_ref===expected.saiph_subject_ref && value?.saiph_account===expected.saiph_account;
}
function assertCustomer(customer:Stripe.Customer|Stripe.DeletedCustomer,config:BillingConfig,subject:string) {
  if (customer.deleted || customer.livemode!==false || !validMetadata(customer.metadata,config,subject)) throw new Error("Customer binding rejected");
}
export function createStripe(config:BillingConfig) {return new Stripe(config.secretKey,{maxNetworkRetries:2,timeout:10000,telemetry:false});}
export async function verifyPrice(stripe:Stripe,config:BillingConfig) {
  const price=await stripe.prices.retrieve(config.priceId,{expand:["product"]});
  const product=typeof price.product==="string"?await stripe.products.retrieve(price.product):price.product;
  if (price.id!==config.priceId || price.livemode!==false || !price.active || price.currency!=="eur" || price.unit_amount!==100
    || price.type!=="recurring" || price.recurring?.interval!=="month" || price.recurring.interval_count!==1
    || product.id!==config.productId || product.deleted || product.livemode!==false || !product.active) throw new Error("Sandbox price rejected");
}
async function assertBinding(stripe:Stripe,config:BillingConfig,mapping:Mapping) {
  assertCustomer(await stripe.customers.retrieve(mapping.customerId),config,mapping.subject);
}
export async function checkout(stripe:Stripe,store:BillingStore,config:BillingConfig,subject:string) {
  await verifyPrice(stripe,config);
  await store.getOrCreateCustomer(subject,async()=>{
    const customer=await stripe.customers.create({metadata:metadata(config,subject)},{idempotencyKey:customerIdempotency(config.accountId,subject)});
    assertCustomer(customer,config,subject);return customer.id;
  });
  return store.withCustomer(subject,async(mapping)=>{
    await assertBinding(stripe,config,mapping);
    // Serialize provider inspection and create under the persistent customer lock.
    const subscriptions=await stripe.subscriptions.list({customer:mapping.customerId,status:"all",limit:100});
    if (subscriptions.has_more || subscriptions.data.some(s=>!["canceled","incomplete_expired"].includes(s.status))) throw new Error("Existing subscription must be managed in portal");
    const sessions=await stripe.checkout.sessions.list({customer:mapping.customerId,status:"open",limit:100});
    if (sessions.has_more) throw new Error("Checkout reconciliation required");
    const open=sessions.data.filter(s=>s.mode==="subscription");
    if (open.length>1) throw new Error("Checkout reconciliation required");
    if (open.length===1) {
      const session=open[0];
      if (session.livemode!==false || resourceId(session.customer,"cus")!==mapping.customerId || !validMetadata(session.metadata,config,subject)) throw new Error("Checkout binding rejected");
      const items=await stripe.checkout.sessions.listLineItems(session.id,{limit:2,expand:["data.price.product"]});
      if (items.has_more || items.data.length!==1 || items.data[0].quantity!==1 || items.data[0].price?.id!==config.priceId
        || items.data[0].price.livemode!==false || resourceId(items.data[0].price.product,"prod")!==config.productId) throw new Error("Checkout price binding rejected");
      return stripeUrl(session.url,"checkout");
    }
    const session=await stripe.checkout.sessions.create({mode:"subscription",customer:mapping.customerId,
      line_items:[{price:config.priceId,quantity:1}],allowed_payment_method_types:["card"],
      metadata:metadata(config,subject),subscription_data:{metadata:metadata(config,subject)},
      success_url:config.origin+"/account?checkout=returned",cancel_url:config.origin+"/account?checkout=cancelled"},
      {idempotencyKey:"saiph-checkout-v1-"+subjectReference(config.accountId+":"+mapping.customerId+":"+Math.floor(Date.now()/1800000))});
    if (session.livemode!==false || resourceId(session.customer,"cus")!==mapping.customerId || !validMetadata(session.metadata,config,subject)) throw new Error("Checkout binding rejected");
    return stripeUrl(session.url,"checkout");
  });
}
export async function portal(stripe:Stripe,store:BillingStore,config:BillingConfig,subject:string) {
  const mapping=await store.findCustomer(subject); if (!mapping) throw new Error("Customer unavailable");
  await assertBinding(stripe,config,mapping);
  const session=await stripe.billingPortal.sessions.create({customer:mapping.customerId,configuration:config.portalId,return_url:config.origin+"/account"});
  if (session.customer!==mapping.customerId || session.configuration!==config.portalId && resourceId(session.configuration,"bpc")!==config.portalId) throw new Error("Portal binding rejected");
  return stripeUrl(session.url,"portal");
}
export function eventDescriptor(event:Stripe.Event,config:BillingConfig):{event:StoredEvent;subscriptionId:string}|null {
  if (event.api_version!==Stripe.API_VERSION || event.livemode!==false || event.account && event.account!==config.accountId || !resourceId(event.id,"evt") || !Number.isSafeInteger(event.created) || event.created<0) throw new Error("Event rejected");
  if (!acceptedEvents.has(event.type)) return null;
  const object=event.data.object as unknown as Record<string,unknown>;
  if (object.livemode!==false) throw new Error("Event rejected");
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
  return {event:{eventId:event.id,type:event.type,created:event.created,customerId,livemode:false},subscriptionId};
}
export async function processWebhook(stripe:Stripe,store:BillingStore,config:BillingConfig,event:Stripe.Event) {
  const descriptor=eventDescriptor(event,config);if (!descriptor) return {outcome:"ignored"};
  return store.applyEvent(descriptor.event,async(mapping)=>{
    // Fetch current provider state after acquiring the database customer lock.
    // Event payloads and redirect queries never determine subscription state.
    if (mapping.subject!==config.ownerSubject || mapping.customerId!==descriptor.event.customerId) throw new Error("Customer binding rejected");
    await assertBinding(stripe,config,mapping);
    const sub=await stripe.subscriptions.retrieve(descriptor.subscriptionId,{expand:["items.data.price.product"]});
    if (sub.livemode!==false || resourceId(sub.customer,"cus")!==mapping.customerId || !validMetadata(sub.metadata,config,mapping.subject)
      || sub.items.has_more || sub.items.data.length!==1 || sub.items.data[0].quantity!==1 || sub.items.data[0].price.id!==config.priceId
      || sub.items.data[0].price.livemode!==false || resourceId(sub.items.data[0].price.product,"prod")!==config.productId) throw new Error("Subscription binding rejected");
    const item=sub.items.data[0];
    return {subscriptionId:sub.id,customerId:mapping.customerId,priceId:config.priceId,status:sub.status,
      currentPeriodEnd:item.current_period_end ?? null,cancelAtPeriodEnd:sub.cancel_at_period_end,cancelAt:sub.cancel_at ?? null,canceledAt:sub.canceled_at,endedAt:sub.ended_at,livemode:false};
  });
}
