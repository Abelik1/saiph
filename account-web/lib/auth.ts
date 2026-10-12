// SPDX-License-Identifier: AGPL-3.0-or-later
import "server-only";
import { Auth0Client } from "@auth0/nextjs-auth0/server";
import { NextResponse } from "next/server";
import { accountCookieName, readAuthConfig } from "./policy.mjs";
import {canUseAccount, readBetaConfig} from "./beta-policy.mjs";
let instance: Auth0Client | undefined;
export function getAuth0() {
  const config = readAuthConfig(process.env);
  if (!config.ok || !config.appBaseUrl || !config.ownerSubject) return null;
  const beta = readBetaConfig(process.env);
  if (process.env.SAIPH_ACCOUNT_MODE === "friends-beta" && !beta) return null;
  if (!instance) {
    instance = new Auth0Client({
      domain: config.domain, clientId: config.clientId, clientSecret: config.clientSecret,
      secret: config.secret, appBaseUrl: config.appBaseUrl,
      authorizationParameters: {scope: "openid profile email", ...(beta ? {audience:beta.audience} : {})},
      enableAccessTokenEndpoint: false, enableConnectAccountEndpoint: false,
      enableTelemetry: false, signInReturnToPath: "/account",
      session: {rolling: false, absoluteDuration: 3600, inactivityDuration: 1800,
        cookie: {name: accountCookieName, secure: true, sameSite: "lax", path: "/", transient: true}},
      transactionCookie: {sameSite: "lax", secure: true},
      async onCallback(error, _context, session) {
        if (error) return new NextResponse("Sign-in could not be completed. Please start again.", {status: 400});
        if (!canUseAccount(session?.user.sub, config.ownerSubject, process.env)) {
          return new NextResponse("This development account site is restricted to its owner.", {status: 403});
        }
        // Always use the configured origin and destination, ignoring caller returnTo.
        return NextResponse.redirect(new URL("/account", config.appBaseUrl));
      },
      async beforeSessionSaved(session) {
        // No profile, email or access token is exposed through a browser API.
        return {...session, user: {sub: session.user.sub}};
      }
    });
  }
  return instance;
}
