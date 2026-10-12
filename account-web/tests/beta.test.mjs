// SPDX-License-Identifier: AGPL-3.0-or-later
import {test} from "node:test";
import assert from "node:assert/strict";
import {readBetaConfig,canUseAccount} from "../lib/beta-policy.mjs";
import {checkedAccess,redeemBeta} from "../lib/beta-http.mjs";
const env = {SAIPH_ACCOUNT_MODE:"friends-beta", SAIPH_HOSTED_API_URL:"https://api.saiph.test",
  SAIPH_HOSTED_API_AUDIENCE:"https://api.saiph.test/identifier", APP_BASE_URL:"https://account.saiph.test"};
const code = "SAIPH-" + "a".repeat(32);
function request({method="POST",origin=env.APP_BASE_URL,type="application/x-www-form-urlencoded",body="code="+code,query="",site="same-origin"}={}) {
  return new Request(env.APP_BASE_URL+"/api/beta/redeem"+query, {method,
    headers:{origin,"content-type":type,"sec-fetch-site":site}, ...(method==="GET"?{}:{body})});
}
function dependencies(overrides={}) {
  return {env,getSession:async()=>({user:{sub:"synthetic|friend"}}),
    call:async(path,value)=>{assert.equal(path,"/v1/beta/redeem");assert.equal(value,code);return {entitled:true,until:2000000000};},...overrides};
}
test("beta is explicit and incomplete or unsafe service configuration fails closed",()=>{
  assert.ok(readBetaConfig(env));
  for (const key of ["SAIPH_ACCOUNT_MODE","SAIPH_HOSTED_API_URL","SAIPH_HOSTED_API_AUDIENCE"]) {
    const candidate={...env};delete candidate[key];assert.equal(readBetaConfig(candidate),null);
  }
  for(const url of ["http://api.saiph.test","https://api.saiph.test/","https://api.saiph.test/path","https://user:pass@api.saiph.test","https://api.saiph.test?token=x","https://api.saiph.test:444"]) {
    assert.equal(readBetaConfig({...env,SAIPH_HOSTED_API_URL:url}),null,url);
  }
  assert.equal(canUseAccount("synthetic|friend","synthetic|owner",{}),false);
  assert.equal(canUseAccount("synthetic|owner","synthetic|owner",{}),true);
  assert.equal(canUseAccount("synthetic|friend","synthetic|owner",env),true);
  for(const subject of [null,"","x".repeat(257),"with space",{sub:"synthetic|friend"}])
    assert.equal(canUseAccount(subject,"synthetic|owner",env),false);
});
test("access status accepts only the narrow consistent server response",()=>{
  assert.deepEqual(checkedAccess({entitled:false,until:null}),{entitled:false,until:null});
  for(const value of [null,[],{entitled:true,until:null},{entitled:false,until:2000000000},
    {entitled:true,until:"2000000000"},{entitled:true,until:NaN},{entitled:true,until:1.1},
    {entitled:true,until:2000000000,token:"hidden"}]) assert.throws(()=>checkedAccess(value));
});
test("successful code submission uses server session and fixed redirect without echoing code",async()=>{
  const response=await redeemBeta(request(),dependencies());
  assert.equal(response.status,303);assert.equal(response.headers.get("location"),env.APP_BASE_URL+"/account");
  assert.match(response.headers.get("cache-control"),/no-store/);
  assert.equal((await response.text()).includes(code),false);
});
test("redemption rejects CSRF, identity overrides, duplicate fields, JSON and oversized input before backend call",async()=>{
  let calls=0;
  const deps=dependencies({call:async()=>{calls++;throw Error("must not call");}});
  for(const options of [{origin:"https://evil.test"},{site:"cross-site"},{query:"?returnTo=https://evil.test"},
    {type:"application/json",body:JSON.stringify({code})},{body:"code="+code+"&subject=other"},
    {body:"code="+code+"&code="+code},{body:"code="+"a".repeat(2000)},{body:"code=invalid"}]) {
    const response=await redeemBeta(request(options),deps);assert.ok([400,403].includes(response.status));
  }
  assert.equal(calls,0);
});
test("missing login and disabled configuration never call backend",async()=>{
  const call=async()=>{throw Error("must not call");};
  assert.equal((await redeemBeta(request(),dependencies({getSession:async()=>null,call}))).status,401);
  assert.equal((await redeemBeta(request(),dependencies({env:{},call}))).status,503);
  assert.equal((await redeemBeta(request({method:"GET"}),dependencies({call}))).status,405);
});
test("backend denial or malformed status produces generic failure with no secret leakage",async()=>{
  for(const call of [async()=>{throw Error(code+" bearer-secret");},async()=>({entitled:false,until:null}),
    async()=>({entitled:true,until:null})]) {
    const response=await redeemBeta(request(),dependencies({call}));assert.equal(response.status,403);
    const body=await response.text();assert.equal(body.includes(code),false);assert.equal(body.includes("bearer-secret"),false);
  }
});
