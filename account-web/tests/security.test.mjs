// SPDX-License-Identifier: AGPL-3.0-or-later
import {test} from "node:test";
import assert from "node:assert/strict";
import {canonicalDestination, contentSecurityPolicy, responseReferrerPolicy} from "../lib/security.mjs";
test("alias navigation stays on the fixed account origin and drops auth secrets", () => {
  const canonical="https://account.saiph.test";
  assert.equal(canonicalDestination(new URL(canonical+"/account"),canonical,"GET"),null);
  assert.equal(canonicalDestination(new URL("http://127.0.0.1:3211/account"),canonical,"GET","account.saiph.test"),null);
  assert.equal(canonicalDestination(new URL(canonical),canonical,"GET","account.saiph.test:3211").status,308);
  for(const path of ["/auth/callback?code=secret&state=secret","/auth/logout?returnTo=https://evil.test"]) {
    assert.deepEqual(canonicalDestination(new URL("https://alias.test"+path),canonical,"GET"),{status:308,location:canonical+"/auth/login"});
  }
  assert.deepEqual(canonicalDestination(new URL("https://alias.test//evil.test/path?q=1"),canonical,"GET"),
    {status:308,location:canonical+"//evil.test/path?q=1"});
  for(const method of ["POST","PUT","DELETE"]) assert.deepEqual(canonicalDestination(new URL("https://alias.test/api/beta/redeem"),canonical,method),{status:421,location:null});
});
test("production CSP refuses injected nonces and does not allow arbitrary scripts",()=>{
  const policy=contentSecurityPolicy("a".repeat(24));
  assert.match(policy,/script-src 'self' 'nonce-a+' 'strict-dynamic';/);
  assert.match(policy,/object-src 'none'/);assert.match(policy,/frame-ancestors 'none'/);
  assert.equal(policy.includes("unsafe-eval"),false);
  for(const bad of ["short","a' https://evil.test; ","a".repeat(200)]) assert.throws(()=>contentSecurityPolicy(bad));
});

test("account forms preserve same-origin POST identity without cross-origin referrers", () => {
  for (const path of ["/account", "/account/settings"]) assert.equal(responseReferrerPolicy(path), "same-origin");
  for (const path of ["/", "/setup", "/account-alias", "/auth/login", "/auth/callback", "/auth/logout", "/api/beta/download", "/api/beta/redeem"])
    assert.equal(responseReferrerPolicy(path), "no-referrer");
});
