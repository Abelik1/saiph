// SPDX-License-Identifier: AGPL-3.0-or-later
import "server-only";
import { Auth0Client } from "@auth0/nextjs-auth0/server";
import { NextResponse } from "next/server";
import { accountCookieName, loginParameters, readAuthConfig } from "./policy.mjs";
import {canUseAccount, completedSecondFactor, readBetaConfig, secondFactorRequired} from "./beta-policy.mjs";
import {readTrialConfig, trialEmailKey} from "./billing/trial.mjs";
import {readBillingConfig} from "./billing/policy";
import {resolveOffer} from "./billing/price-test.mjs";
import {afterSignIn, parseBuyTarget} from "./buy.mjs";
import {countStep} from "./funnel";
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
      authorizationParameters: loginParameters(beta),
      enableAccessTokenEndpoint: false, enableConnectAccountEndpoint: false,
      enableTelemetry: false, signInReturnToPath: "/account",
      session: {rolling: false, absoluteDuration: 3600, inactivityDuration: 1800,
        cookie: {name: accountCookieName, secure: true, sameSite: "lax", path: "/", transient: true}},
      transactionCookie: {sameSite: "lax", secure: true},
      async onCallback(error, context, session) {
        if (error) return new NextResponse("Sign-in could not be completed. Please start again.", {status: 400});
        if (secondFactorRequired(process.env) && !completedSecondFactor(session?.user)) {
          return new NextResponse("Two-step verification is required. Turn it on when Saiph asks during sign-in, then sign in again.", {status: 403});
        }
        if (!canUseAccount(session?.user.sub, config.ownerSubject, process.env, completedSecondFactor(session?.user))) {
          return new NextResponse("This development account site is restricted to its owner.", {status: 403});
        }
        // Always the configured origin: /account, or the exact /buy/<plan> page the
        // sign-in started from, so a buyer goes straight on to Stripe Checkout.
        const destination = afterSignIn(context.returnTo, config.appBaseUrl);
        const bought = parseBuyTarget(context.returnTo, config.appBaseUrl);
        if (bought) {
          const {test, variant} = resolveOffer(readBillingConfig(process.env)?.priceTest ?? null, bought.offer);
          await countStep("signin_done", bought.plan, test, variant);
        }
        return NextResponse.redirect(destination);
      },
      async beforeSessionSaved(session) {
        // No profile, email or access token is exposed through a browser API.
        // Only whether this sign-in used a second factor is kept, and for the
        // one-trial-per-person rule a keyed hash of the verified email (never the
        // address itself; lib/billing/trial.mjs).
        const trialKey = trialEmailKey(session.user, readTrialConfig(process.env));
        return {...session, user: {sub: session.user.sub, mfa: completedSecondFactor(session.user), ...(trialKey ? {trialKey} : {})}};
      }
    });
  }
  return instance;
}
