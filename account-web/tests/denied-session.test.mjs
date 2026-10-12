// SPDX-License-Identifier: AGPL-3.0-or-later
import {test} from "node:test";
import assert from "node:assert/strict";
import {NextResponse} from "next/server.js";
import {expireDeniedSessionCookies} from "../lib/denied-session.mjs";
import {accountCookieName} from "../lib/policy.mjs";
const sdk = new URL("./cookies.js", import.meta.resolve("@auth0/nextjs-auth0/server"));
const {setChunkedCookie, RequestCookies} = await import(sdk.href);
for (const size of [100, 5000]) test(`denied callback clears actual SDK cookie format (${size} bytes)`, () => {
 const response=new NextResponse("Access denied",{status:403});
 setChunkedCookie(accountCookieName,"x".repeat(size),{secure:true,httpOnly:true,path:"/",sameSite:"lax"},new RequestCookies(new Headers()),response.cookies);
 const names=response.cookies.getAll().filter(c=>c.value).map(c=>c.name);
 assert.ok(names.length >= (size>3500 ? 2 : 1));
 response.cookies.set("unrelated","keep");
 expireDeniedSessionCookies(response);
 for(const name of names){const cookie=response.cookies.get(name);assert.equal(cookie.value,"");assert.equal(cookie.expires.getTime(),0);assert.equal(cookie.secure,true);assert.equal(cookie.httpOnly,true);assert.equal(cookie.sameSite,"lax");assert.equal(cookie.path,"/");assert.equal(cookie.domain,undefined)}
 assert.equal(response.cookies.get("unrelated").value,"keep");
});
