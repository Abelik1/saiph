// SPDX-License-Identifier: AGPL-3.0-or-later
import { NextRequest, NextResponse } from "next/server";
import { getAuth0 } from "./lib/auth";
import {canUseAccount} from "./lib/beta-policy.mjs";
import { webhookPath } from "./lib/billing/policy";
import { expireDeniedSessionCookies } from "./lib/denied-session.mjs";
import {readAuthConfig} from "./lib/policy.mjs";
import {canonicalDestination, contentSecurityPolicy, responseReferrerPolicy} from "./lib/security.mjs";
import {randomBytes} from "node:crypto";
export async function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname;
  const nonce = randomBytes(18).toString("base64");
  const csp = contentSecurityPolicy(nonce, process.env.NODE_ENV === "development");
  const responseHeaders = {"Cache-Control": "private, no-store", "Referrer-Policy": responseReferrerPolicy(path), "Content-Security-Policy": csp};
  function secure(response: NextResponse) {
    for (const [name, value] of Object.entries(responseHeaders)) response.headers.set(name, value);
    if (response.headers.get("x-middleware-next") === "1") {
      // Next reads the request policy to nonce its framework and hydration scripts.
      // Preserve request-cookie overrides emitted by the Auth0 SDK.
      const overrides = new Set((response.headers.get("x-middleware-override-headers") || "").split(",").filter(Boolean));
      for (const [name, value] of [["content-security-policy", csp], ["x-nonce", nonce]]) {
        overrides.add(name);
        response.headers.set("x-middleware-request-" + name, value);
      }
      // When there were no overrides, Next also needs the original request headers.
      for (const [name, value] of request.headers) {
        if (!overrides.has(name)) response.headers.set("x-middleware-request-" + name, value);
        overrides.add(name);
      }
      response.headers.set("x-middleware-override-headers", [...overrides].join(","));
    }
    return response;
  }
  const authConfig = readAuthConfig(process.env);
  if (authConfig.ok && authConfig.appBaseUrl && process.env.VERCEL_ENV !== "preview") {
    // A self-hosted Next server can keep its bind address in request.url.
    // Use HTTP Host, never caller-supplied forwarded-host headers, for aliases.
    const requested = new URL(request.url);
    const destination = canonicalDestination(requested, authConfig.appBaseUrl, request.method,
      request.headers.get("host") || requested.host);
    if (destination) return destination.location
      ? secure(NextResponse.redirect(destination.location, destination.status))
      : new NextResponse("Use the account website address to submit this request.", {status: destination.status, headers: responseHeaders});
  }
  // Only this exact receiver bypasses browser sessions. It verifies the raw-body
  // Stripe signature itself; Vercel Deployment Protection remains unchanged.
  if (path === webhookPath) return secure(NextResponse.next());
  const allowedAuthRoutes = ["/auth/login", "/auth/logout", "/auth/callback"];
  if (path.startsWith("/auth/") && !allowedAuthRoutes.includes(path)) {
    return new NextResponse("Not found", {status: 404, headers: responseHeaders});
  }
  const auth0 = getAuth0();
  if (!auth0) {
    if (path === "/" || path === "/privacy" || path === "/setup") return secure(NextResponse.next());
    return new NextResponse("Account setup is pending. Please try again after configuration.", {status: 503, headers: responseHeaders});
  }
  // Prevent login-query overrides of audience, scopes, connections or return URL.
  if (["/auth/login", "/auth/logout"].includes(path) && request.nextUrl.search) {
    return new NextResponse("Start sign-in or sign-out using the account page links.", {status: 400, headers: responseHeaders});
  }
  try {
    const response = await auth0.middleware(request);
    // The SDK writes a session after onCallback even for a denied callback.
    // Expire every session chunk on error so a non-owner keeps no app session.
    if (path === "/auth/callback" && response.status >= 400) {
      expireDeniedSessionCookies(response);
    }
    if (path === "/account" || path.startsWith("/account/") || path.startsWith("/api/")) {
      const session = await auth0.getSession(request);
      if (!session) return secure(NextResponse.redirect(new URL("/auth/login", process.env.APP_BASE_URL)));
      if (!canUseAccount(session.user.sub, process.env.SAIPH_OWNER_SUBJECT, process.env, session.user.mfa)) {
        return new NextResponse("Access denied", {status: 403, headers: responseHeaders});
      }
    }
    return secure(response);
  } catch {
    // Never serialize SDK errors, callback codes, tokens or subject identifiers.
    return new NextResponse("Account service is temporarily unavailable.", {status: 503, headers: responseHeaders});
  }
}
export const config = {matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"]};
