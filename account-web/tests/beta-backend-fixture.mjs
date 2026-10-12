// SPDX-License-Identifier: AGPL-3.0-or-later
// Test-process-only transport fixture. Never imported by application source.
// Exercises the production BFF/session/HTML boundary without external accounts.
import assert from "node:assert/strict";
const actualFetch = globalThis.fetch;
const entitled = new Set();
let usedBy;
globalThis.fetch = async (input, init) => {
  const url = typeof input === "string" || input instanceof URL ? new URL(input) : new URL(input.url);
  if (url.origin !== "https://api.saiph.test") return actualFetch(input, init);
  const request = new Request(input, init);
  const token = request.headers.get("authorization");
  assert.match(token ?? "", /^Bearer synthetic-token-(friend|other)$/);
  assert.equal(request.headers.has("cookie"), false);
  const reply = (body, status=200) => Response.json(body, {status});
  if (url.pathname === "/v1/beta/access" && request.method === "GET")
    return reply(entitled.has(token) ? {entitled:true,until:2000000000} : {entitled:false,until:null});
  if (url.pathname === "/v1/beta/download" && request.method === "POST") {
    assert.deepEqual(await request.json(), {artifact:"windows"});
    return entitled.has(token) ? reply({ticket:"a".repeat(43)}) : reply({},403);
  }
  assert.equal(url.pathname, "/v1/beta/redeem");assert.equal(request.method, "POST");
  const body = await request.json();assert.deepEqual(Object.keys(body), ["code"]);
  if (body.code !== "SAIPH-" + "a".repeat(32) || usedBy && usedBy !== token) return reply({},403);
  usedBy = token;entitled.add(token);
  return reply({entitled:true,until:2000000000});
};
