// SPDX-License-Identifier: AGPL-3.0-or-later
// Built account routes with synthetic configuration; no provider/API requests.
import {spawn} from "node:child_process";
import {once} from "node:events";
import {generateKeyPairSync,randomBytes} from "node:crypto";
import assert from "node:assert/strict";
import {fileURLToPath} from "node:url";
import {setTimeout as delay} from "node:timers/promises";
import {localRequest} from "./local-http.mjs";

const origin="https://account.saiph.test",base="http://127.0.0.1:3213";
const mode=process.env.SAIPH_TRIAL_HTTP_MODE==="development"?"dev":"start";
const child=spawn(process.execPath,[fileURLToPath(new URL("../node_modules/next/dist/bin/next",import.meta.url)),mode,"--hostname","127.0.0.1","--port","3213",...(mode==="dev"?["--webpack"]:[])],{
  cwd:fileURLToPath(new URL("../",import.meta.url)),windowsHide:true,stdio:["ignore","pipe","pipe"],env:{...process.env,
    NODE_ENV:mode==="dev"?"development":"production",NEXT_TELEMETRY_DISABLED:"1",AUTH0_DOMAIN:"synthetic.us.auth0.com",AUTH0_CLIENT_ID:"synthetic_client",
    AUTH0_CLIENT_SECRET:"synthetic_not_real",AUTH0_SECRET:randomBytes(32).toString("hex"),APP_BASE_URL:origin,SAIPH_OWNER_SUBJECT:"synthetic|owner",
    SAIPH_BILLING_MODE:"owner-sandbox",STRIPE_EXPECTED_ACCOUNT_ID:"acct_synthetic",STRIPE_PRODUCT_ID:"prod_synthetic",
    STRIPE_PRICE_ID:"price_monthly",STRIPE_YEARLY_PRICE_ID:"price_yearly",STRIPE_PORTAL_CONFIGURATION_ID:"bpc_synthetic",
    STRIPE_SECRET_KEY:"rk_test_synthetic123",STRIPE_WEBHOOK_SECRET:"whsec_synthetic123",DATABASE_URL:"synthetic-not-a-database-url",
    SAIPH_HOSTED_API_URL:"https://api.saiph.test",SAIPH_BILLING_GRANT_KEY_ID:"trial-smoke",
    SAIPH_BILLING_GRANT_KEY:generateKeyPairSync("ed25519").privateKey.export({format:"der",type:"pkcs8"}).toString("base64url"),
    SAIPH_TRIAL_SECRET:randomBytes(32).toString("base64url"),SAIPH_TRIAL_DAYS:"30"}});
let logs="";child.stdout.on("data",c=>logs+=c);child.stderr.on("data",c=>logs+=c);
const request=(path,options={})=>localRequest(base+path,{...options,headers:{host:"account.saiph.test",...options.headers}});
try {
  let ready=false;
  for(let i=0;i<50;i++){if(child.exitCode!==null)break;try{if((await request("/trial")).status===200){ready=true;break;}}catch{}await delay(100);}
  assert(ready,"Trial server did not become ready: "+logs);
  const page=await request("/trial"),html=await page.text();
  assert.equal(page.status,200);
  assert.match(html,/Try Saiph Cloud free for 14 days/);
  assert.match(html,/Required at Stripe Checkout/);
  assert.match(html,/€9\.99 \/ month/);
  assert.match(html,/billed automatically unless you cancel/);
  assert.match(html,/reminder before billing begins/);
  assert.match(html,/href="\/trial\/start"/);
  assert.doesNotMatch(html,/No card needed|€0|Cloud pauses until you subscribe/);
  assert.match(page.headers.get("cache-control"),/no-store/);
  const cancelled=await request("/trial?checkout=cancelled");
  assert.match(await cancelled.text(),/Your trial has not started/);
  const malformed=await request("/trial/start?days=365");assert.equal(malformed.status,400);
  const anonymous=await request("/api/billing/trial",{method:"POST",body:"trial=start",headers:{origin,"content-type":"application/x-www-form-urlencoded"}});
  assert.equal(anonymous.status,307,"anonymous trial action still requires sign-in");
  console.log("Card-trial HTTP checks passed ("+mode+"): 14-day offer despite legacy 30-day config, card/price/cancel/reminder disclosures, fixed sign-in, no-store, cancelled checkout, forged query and anonymous POST.");
} finally {child.kill();await Promise.race([once(child,"exit"),delay(3000)]);}
