// SPDX-License-Identifier: AGPL-3.0-or-later
import {test} from "node:test";
import assert from "node:assert/strict";
import {readAuthConfig, isOwner, isAccountCookie} from "../lib/policy.mjs";
const env = {NODE_ENV: "production", AUTH0_DOMAIN: "synthetic.us.auth0.com", AUTH0_CLIENT_ID: "synthetic_web_client", AUTH0_CLIENT_SECRET: "synthetic-secret-not-real", AUTH0_SECRET: "ab".repeat(32), APP_BASE_URL: "https://account.dev.saiph.test", SAIPH_OWNER_SUBJECT: "synthetic|owner"};
test("missing owner and provider secrets fail closed without values in errors", () => {
  for (const key of Object.keys(env).filter(k => k !== "NODE_ENV")) {
    const candidate = {...env}; delete candidate[key];
    const result = readAuthConfig(candidate);
    assert.equal(result.ok, false);
    assert.equal(JSON.stringify(result).includes("synthetic-secret"), false);
  }
});
test("production rejects insecure and ambiguous callback origins", () => {
  for (const APP_BASE_URL of ["http://localhost:3000", "http://account.dev.saiph.test", "https://user:pass@account.dev.saiph.test", "https://account.dev.saiph.test/path", "https://account.dev.saiph.test/", "https://account.dev.saiph.test?redirect=evil", "https://account.dev.saiph.test#fragment", "https://account.dev.saiph.test:444"]) {
    assert.equal(readAuthConfig({...env, APP_BASE_URL}).ok, false, APP_BASE_URL);
  }
  assert.equal(readAuthConfig(env).ok, true);
});
test("rejects malformed issuer and encryption secret", () => {
  for (const AUTH0_DOMAIN of ["https://synthetic.us.auth0.com", "synthetic.us.auth0.com/", "synthetic.us.auth0.com.evil.test"]) assert.equal(readAuthConfig({...env, AUTH0_DOMAIN}).ok, false);
  assert.equal(readAuthConfig({...env, AUTH0_SECRET: "short"}).ok, false);
});
test("ownership uses exact validated subject, with no email or client fallbacks", () => {
  assert.equal(isOwner("synthetic|owner", env.SAIPH_OWNER_SUBJECT), true);
  for (const subject of [undefined, null, "", "synthetic|other", "SYNTHETIC|owner", {sub: "synthetic|owner"}]) assert.equal(isOwner(subject, env.SAIPH_OWNER_SUBJECT), false);
  assert.equal(isOwner("", ""), false);
});
test("denied callbacks identify all chunked session cookies without clearing unrelated cookies", () => {
  for (const name of ["__Host-saiph_account", "__Host-saiph_account.0", "__Host-saiph_account.1", "__Host-saiph_account__0", "__Host-saiph_account__1"]) assert.equal(isAccountCookie(name), true);
  for (const name of ["other", "__Host-saiph_account_backup", "__Host-personal_cv"]) assert.equal(isAccountCookie(name), false);
});
