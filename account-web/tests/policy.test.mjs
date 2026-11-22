// SPDX-License-Identifier: AGPL-3.0-or-later
import {test} from "node:test";
import assert from "node:assert/strict";
import {readAuthConfig, isOwner, isAccountCookie, loginParameters} from "../lib/policy.mjs";
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

test("sign-in goes straight to Google with fixed scopes and only the beta audience added", () => {
  assert.deepEqual(loginParameters(null), {scope: "openid profile email", connection: "google-oauth2"});
  assert.deepEqual(loginParameters({audience: "https://api.saiph.test"}),
    {scope: "openid profile email", connection: "google-oauth2", audience: "https://api.saiph.test"});
});

test("start routes take only with=email, plus the route's own keys, and email changes only the connection", async () => {
  const {signInMethod, methodParameters, emailStart, EMAIL_CONNECTION} = await import("../lib/policy.mjs");
  const q = s => new URLSearchParams(s);
  assert.equal(signInMethod(q("")), "google");
  assert.equal(signInMethod(q("with=email")), "email");
  for (const bad of ["with=google", "with=", "with=EMAIL", "with=email&with=email", "connection=google-oauth2", "with=email&returnTo=https://evil.test", "offer=a"])
    assert.equal(signInMethod(q(bad)), null, bad);
  assert.equal(signInMethod(q("offer=a&with=email"), ["offer"]), "email");
  assert.equal(signInMethod(q("offer=a&offer=b"), ["offer"]), null);
  assert.deepEqual(methodParameters("google"), {});
  assert.deepEqual(methodParameters("email"), {connection: EMAIL_CONNECTION, prompt: "login"});
  assert.equal(EMAIL_CONNECTION, "Username-Password-Authentication");
  assert.equal(emailStart("/trial/start"), "/trial/start?with=email");
  assert.equal(emailStart("/buy/monthly/start?offer=b"), "/buy/monthly/start?offer=b&with=email");
});

test("every sign-in start route reads with= and hands its method to Auth0", async () => {
  const {readFile} = await import("node:fs/promises");
  for (const route of ["../app/sign-in/route.ts", "../app/trial/start/route.ts", "../app/buy/[plan]/start/route.ts", "../app/account/delete/sign-in/route.ts"]) {
    const source = await readFile(new URL(route, import.meta.url), "utf8");
    assert.match(source, /const method = signInMethod\(/, route);
    assert.match(source, /if \(!method\)|!method \|\|/, route);
    assert.match(source, /authorizationParameters: methodParameters\(method\)/, route);
    assert.equal((source.match(/startInteractiveLogin\(/g) || []).length, 1, route);
  }
  for (const [page, href] of [["../app/page.tsx", "/sign-in?with=email"], ["../app/trial/page.tsx", "/trial/start?with=email"], ["../app/buy/[plan]/page.tsx", "emailStart(start)"]]) {
    assert.ok((await readFile(new URL(page, import.meta.url), "utf8")).includes(href), page);
  }
});
