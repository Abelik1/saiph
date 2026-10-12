// SPDX-License-Identifier: AGPL-3.0-or-later
// Runs the actual production build with synthetic encrypted SDK cookies.
// No provider account, login, keys or external requests are used.
import Stripe from "stripe";
import {spawn} from "node:child_process";
import {once} from "node:events";
import assert from "node:assert/strict";
import {randomBytes} from "node:crypto";
import {setTimeout as delay} from "node:timers/promises";
import {fileURLToPath} from "node:url";
import {accountCookieName, isAccountCookie} from "../lib/policy.mjs";
import {localRequest} from "./local-http.mjs";
const sdk = new URL("./cookies.js", import.meta.resolve("@auth0/nextjs-auth0/server"));
const {encrypt, setChunkedCookie, RequestCookies, ResponseCookies} = await import(sdk.href);
const cwd = fileURLToPath(new URL("../", import.meta.url));
const secret = randomBytes(32).toString("hex");
const base = "http://127.0.0.1:3211";
const child = spawn(process.execPath, [fileURLToPath(new URL("../node_modules/next/dist/bin/next", import.meta.url)), "start", "--hostname", "127.0.0.1", "--port", "3211"], {cwd, env: {...process.env, NODE_ENV:"production", NEXT_TELEMETRY_DISABLED:"1", AUTH0_DOMAIN:"synthetic.us.auth0.com", AUTH0_CLIENT_ID:"synthetic_client", AUTH0_CLIENT_SECRET:"synthetic_not_real", AUTH0_SECRET:secret, APP_BASE_URL:"https://account.saiph.test", SAIPH_OWNER_SUBJECT:"synthetic|owner",SAIPH_BILLING_MODE:"owner-sandbox",STRIPE_EXPECTED_ACCOUNT_ID:"acct_synthetic",STRIPE_PRODUCT_ID:"prod_synthetic",STRIPE_PRICE_ID:"price_synthetic",STRIPE_PORTAL_CONFIGURATION_ID:"bpc_synthetic",STRIPE_SECRET_KEY:"rk_test_synthetic123",STRIPE_WEBHOOK_SECRET:"whsec_synthetic123",DATABASE_URL:"synthetic-not-a-database-url"}, stdio:["ignore","pipe","pipe"]});
let logs = "";child.stdout.on("data", c => logs += c);child.stderr.on("data", c => logs += c);
const checks = [];
async function request(path, cookie, method="GET", headers={}, body=undefined) {
 return localRequest(base + path, {method,body,headers:{host:"account.saiph.test",...headers,...(cookie?{cookie}:{})}});
}
async function sessionCookie(subject, expired=false, padding=0) {
 const now=Math.floor(Date.now()/1000);
 const session={user:{sub:subject, padding:"x".repeat(padding)},tokenSet:{accessToken:"synthetic_token_must_not_serialize",expiresAt:now+3600},internal:{sid:"synthetic_sid",createdAt:now}};
 const value=await encrypt(session,secret,expired ? now-120 : now+3600);
 const response=new ResponseCookies(new Headers());
 setChunkedCookie(accountCookieName,value,{secure:true,httpOnly:true,path:"/",sameSite:"lax"},new RequestCookies(new Headers()),response);
 const chunks=response.getAll().filter(c=>c.value);
 assert.ok(chunks.every(c=>isAccountCookie(c.name)));
 return chunks.map(c=>`${c.name}=${c.value}`).join("; ");
}
try {
 let ready=false, startupStatus;
 for(let i=0;i<50;i++){if(child.exitCode !== null)break;try{const r=await request("/");startupStatus=r.status;if(r.status===200){ready=true;break}}catch{}await delay(100)}
 assert.ok(ready,"Production server did not become ready: "+startupStatus+"\n"+logs);
 for(const [label,cookie,status] of [
  ["owner",await sessionCookie("synthetic|owner"),200],
  ["other owner",await sessionCookie("synthetic|other"),403],
  ["chunked other owner",await sessionCookie("synthetic|other",false,4000),403],
  ["expired",await sessionCookie("synthetic|owner",true),307],
  ["tampered",accountCookieName+"=invalid",307],
  ["absent",undefined,307]
 ]) {
  const r=await request("/account",cookie);assert.equal(r.status,status,label);
  const body=await r.text();assert.equal(body.includes("synthetic_token_must_not_serialize"),false);
  assert.equal(body.includes("synthetic|owner"),false);
  assert.match(r.headers.get("cache-control"),/no-store/);
  if(status===307)assert.equal(r.headers.get("location"),"https://account.saiph.test/auth/login");
  if(label==="owner")assert.match(body,/Auth0 session active/);
  checks.push({case:label,status:r.status});
 }
 for(const [path,status] of [["/auth/profile",404],["/auth/access-token",404],["/auth/login?scope=offline_access",400],["/auth/logout?returnTo=https://evil.test",400],["/auth/callback?code=synthetic&state=invalid",400]]) {
  const r=await request(path);assert.equal(r.status,status,path);checks.push({case:path,status:r.status});
 }
 const ownerCookie=await sessionCookie("synthetic|owner");
 const otherCookie=await sessionCookie("synthetic|other");
 // Checkout return parameters are feedback only, never payment evidence.
 for (const [query,expected] of [["returned","You’re back from test checkout."],["cancelled","Test checkout was closed."]]) {
  const r=await request("/account?checkout="+query,ownerCookie);
  assert.equal(r.status,200);
  const html=await r.text();
  assert.ok(html.includes(expected));
  assert.match(html,/Stripe test setup pending/);
  assert.equal(html.includes("Test subscription active"),false);
  assert.equal(html.includes('action="/api/billing/checkout"'),false);
  checks.push({case:"checkout "+query+" does not grant payment status or enable unavailable billing",status:200});
 }
 const injected=await request("/account?checkout="+encodeURIComponent("<script>synthetic_injection</script>"),ownerCookie);
 assert.equal(injected.status,200);
 assert.equal((await injected.text()).includes("<script>synthetic_injection</script>"),false);
 checks.push({case:"unrecognized checkout query cannot inject executable markup",status:200});
 for(const path of ["/api/billing/checkout","/api/billing/portal"]) {
  for(const [label,cookie,status,headers] of [["absent",undefined,307,{}],["non-owner",otherCookie,403,{origin:"https://account.saiph.test"}],["owner missing origin",ownerCookie,403,{}],["owner wrong origin",ownerCookie,403,{origin:"https://evil.test"}]]) {
   const r=await request(path,cookie,"POST",headers);assert.equal(r.status,status,path+" "+label);assert.match(r.headers.get("cache-control"),/no-store/);checks.push({case:path+" "+label,status:r.status});
  }
 }
 // Exact webhook bypasses browser auth and independently rejects bad signatures.
 for(const [path,status] of [["/api/stripe/webhook",400],["/api/stripe/webhook-other",307]]) {
  const r=await request(path,undefined,"POST",{"content-type":"application/json","stripe-signature":"t=1,v1=invalid"},"{}");assert.equal(r.status,status,path);assert.match(r.headers.get("cache-control"),/no-store/);checks.push({case:path+" unauthenticated invalid signature",status:r.status});
 }
 const sdkStripe=new Stripe("rk_test_synthetic123");
 const payload=JSON.stringify({id:"evt_synthetic",object:"event",api_version:Stripe.API_VERSION,created:Math.floor(Date.now()/1000),livemode:false,type:"customer.subscription.updated",data:{object:{id:"sub_synthetic",object:"subscription",customer:"cus_synthetic",livemode:false}}});
 const signature=sdkStripe.webhooks.generateTestHeaderString({payload,secret:"whsec_synthetic123"});
 const unavailableDb=await request("/api/stripe/webhook",undefined,"POST",{"content-type":"application/json","stripe-signature":signature},payload);
 assert.equal(unavailableDb.status,503);assert.match(unavailableDb.headers.get("cache-control"),/no-store/);assert.equal((await unavailableDb.text()).includes("DATABASE_URL"),false);checks.push({case:"signed webhook missing durable store fails without acknowledgement",status:503});
 const methodResponse=await request("/api/billing/checkout",ownerCookie);assert.equal(methodResponse.status,405);checks.push({case:"checkout GET",status:405});
 console.log(JSON.stringify({checks,scope:"Actual Next.js production HTTP + official SDK encrypted synthetic sessions; no real provider login"},null,2));
} finally {
 child.kill();await Promise.race([once(child,"exit"),delay(3000)]);
}
