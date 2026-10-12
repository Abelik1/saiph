// SPDX-License-Identifier: AGPL-3.0-or-later
// Actual Next production HTTP and SDK cookies; synthetic backend transport only.
import {spawn} from "node:child_process";
import {once} from "node:events";
import assert from "node:assert/strict";
import {randomBytes} from "node:crypto";
import {setTimeout as delay} from "node:timers/promises";
import {fileURLToPath} from "node:url";
import {accountCookieName} from "../lib/policy.mjs";
import {localRequest} from "./local-http.mjs";
const sdk = new URL("./cookies.js", import.meta.resolve("@auth0/nextjs-auth0/server"));
const {encrypt,setChunkedCookie,RequestCookies,ResponseCookies} = await import(sdk.href);
const secret = randomBytes(32).toString("hex"), code="SAIPH-"+"a".repeat(32);
const origin="https://account.saiph.test", base="http://127.0.0.1:3212";
const child = spawn(process.execPath, ["--import",new URL("./beta-backend-fixture.mjs",import.meta.url).href,
  fileURLToPath(new URL("../node_modules/next/dist/bin/next",import.meta.url)),"start","--hostname","127.0.0.1","--port","3212"],
  {cwd:fileURLToPath(new URL("../",import.meta.url)),env:{...process.env,NODE_ENV:"production",NEXT_TELEMETRY_DISABLED:"1",
    AUTH0_DOMAIN:"synthetic.us.auth0.com",AUTH0_CLIENT_ID:"synthetic_web",AUTH0_CLIENT_SECRET:"synthetic-not-real",
    AUTH0_SECRET:secret,APP_BASE_URL:origin,SAIPH_OWNER_SUBJECT:"synthetic|owner",SAIPH_ACCOUNT_MODE:"friends-beta",
    SAIPH_HOSTED_API_URL:"https://api.saiph.test",SAIPH_HOSTED_API_AUDIENCE:"https://api.synthetic.invalid",SAIPH_BILLING_MODE:"disabled"},
    stdio:["ignore","pipe","pipe"]});
let logs="";child.stdout.on("data",c=>logs+=c);child.stderr.on("data",c=>logs+=c);
const checks=[];
async function cookie(who) {
  const now=Math.floor(Date.now()/1000);
  const value=await encrypt({user:{sub:"synthetic|"+who},tokenSet:{accessToken:"synthetic-token-"+who,expiresAt:now+3600},
    internal:{sid:"synthetic",createdAt:now}},secret,now+3600);
  const response=new ResponseCookies(new Headers());
  setChunkedCookie(accountCookieName,value,{secure:true,httpOnly:true,path:"/",sameSite:"lax"},new RequestCookies(new Headers()),response);
  return response.getAll().filter(c=>c.value).map(c=>`${c.name}=${c.value}`).join("; ");
}
async function request(path,session,body,headers={}) {
  return localRequest(base+path,{method:body===undefined?"GET":"POST",body,
    headers:{host:"account.saiph.test",...(session?{cookie:session}:{}),...(body===undefined?{}:{origin,"sec-fetch-site":"same-origin","content-type":"application/x-www-form-urlencoded"}),...headers}});
}
async function checkPage(session,active) {
  const response=await request("/account?checkout=returned&entitled=true",session);
  assert.equal(response.status,200);assert.match(response.headers.get("cache-control"),/no-store/);
  assert.equal(response.headers.get("referrer-policy"),"same-origin");
  const html=await response.text();assert.match(html,active?/Beta access active/:/Enter your invitation code/);
  for(const hidden of [code,"synthetic-token-","synthetic|friend",'action="/api/billing/checkout"']) assert.equal(html.includes(hidden),false,hidden);
  assert.equal(html.includes("Beta access active"),active);
}
try {
  let ready=false;let startupStatus;
  for(let i=0;i<60;i++){if(child.exitCode !== null)break;try{startupStatus=(await request("/")).status;if(startupStatus===200){ready=true;break;}}catch{}await delay(100);}
  assert.ok(ready,"Synthetic production server failed to start: "+startupStatus+"\n"+logs);
  const friend=await cookie("friend"),other=await cookie("other");
  const first=await request("/setup"), second=await request("/setup");
  assert.equal(first.status,200);assert.equal(second.status,200);
  assert.equal(first.headers.get("referrer-policy"),"no-referrer");
  const policy=first.headers.get("content-security-policy");
  assert.ok(policy);assert.match(policy,/script-src 'self' 'nonce-[A-Za-z0-9+/]+' 'strict-dynamic'/);
  assert.equal(policy.includes("unsafe-eval"),false);
  assert.notEqual(policy,second.headers.get("content-security-policy"));
  const nonce=policy.match(/'nonce-([^']+)'/)[1], setupHtml=await first.text();
  assert.match(setupHtml,/You do not need a server or Tailscale/);
  for(const script of setupHtml.matchAll(/<script\b([^>]*)>/g)) assert.ok(script[1].includes('nonce="'+nonce+'"'),"Framework script missing the request nonce");
  assert.equal(first.headers.has("x-nonce"),false);
  checks.push("public Hosted guide; unique CSP nonce applied to framework scripts");
  const alias=await request("/account?checkout=returned",undefined,undefined,{host:"old-account.saiph.test"});
  assert.equal(alias.status,308);assert.equal(alias.headers.get("location"),origin+"/account?checkout=returned");
  const callbackAlias=await request("/auth/callback?code=must-not-forward&state=private",undefined,undefined,{host:"old-account.saiph.test"});
  assert.equal(callbackAlias.status,308);assert.equal(callbackAlias.headers.get("location"),origin+"/auth/login");
  const postAlias=await request("/api/beta/redeem",friend,"code="+code,{host:"old-account.saiph.test"});
  assert.equal(postAlias.status,421);assert.equal(postAlias.headers.has("location"),false);
  checks.push("aliases redirect safely; callback secrets and POST bodies are never forwarded");
  await checkPage(friend,false);checks.push("non-owner can enter code; query cannot grant access");
  assert.equal((await request("/api/beta/redeem",friend,"code="+code,{origin:"https://evil.test"})).status,403);
  assert.equal((await request("/api/beta/redeem",friend,"code="+code+"&subject=other")).status,400);
  checks.push("CSRF and identity override rejected");
  const accepted=await request("/api/beta/redeem",friend,"code="+code);
  assert.equal(accepted.status,303);assert.equal(accepted.headers.get("location"),origin+"/account");
  await checkPage(friend,true);await checkPage(other,false);checks.push("redemption updates only signed-in account");
  assert.equal((await request("/api/beta/redeem",other,"code="+code)).status,403);
  checks.push("another account cannot reuse code");
  const download = await request("/api/beta/download",friend,"artifact=windows");
  assert.equal(download.status,303);
  assert.equal(download.headers.get("referrer-policy"),"no-referrer");
  assert.equal(download.headers.get("location"),"https://api.saiph.test/v1/download/"+"a".repeat(43));
  assert.equal((await request("/api/beta/download",other,"artifact=windows")).status,403);
  assert.equal((await request("/api/beta/download",friend,"artifact=windows",{origin:"https://evil.test"})).status,403);
  checks.push("entitled download redirects to a checked short-lived ticket; other account and CSRF denied");
  assert.equal((await request("/api/billing/checkout",friend,"")).status,503);
  assert.equal((await request("/api/beta/redeem",undefined,"code="+code)).status,307);
  assert.equal((await request("/auth/access-token",friend)).status,404);
  checks.push("beta does not enable billing or browser token endpoint; login still required");
  assert.equal(logs.includes(code),false);assert.equal(logs.includes("synthetic-token-friend"),false);
  console.log(JSON.stringify({checks,scope:"Actual production HTTP and official encrypted SDK cookies; backend transport fixture, no provider login"},null,2));
} finally {child.kill();await Promise.race([once(child,"exit"),delay(3000)]);}
