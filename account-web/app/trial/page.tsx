// SPDX-License-Identifier: AGPL-3.0-or-later
import type {Metadata} from "next";
import {headers} from "next/headers";
import {redirect} from "next/navigation";
import {getAuth0} from "../../lib/auth";
import {canUseAccount} from "../../lib/beta-policy.mjs";
import {billingView} from "../../lib/billing/view";
import {maySubscribe, readBillingConfig} from "../../lib/billing/policy";
import {readCardTrialConfig} from "../../lib/billing/trial.mjs";
import {countStep} from "../../lib/funnel";
import {readConsent, readGaConfig} from "../../lib/ga.mjs";
import {GoogleMark, Icon, Mark, Notice} from "../ui";
import {GA_SCRIPT, HANDOFF_SCRIPT} from "../funnel-scripts";
export const dynamic = "force-dynamic";
export const metadata: Metadata = {title: "Start your free trial"};

type Props = {searchParams: Promise<Record<string, string | string[] | undefined>>};
const json = (value: unknown) => JSON.stringify(value).replace(/</g, "\\u003c");
const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;

/** Start your free trial from usesaiph.com: Google sign-in, then Stripe's
 * card-required trial checkout. Anyone who cannot
 * start one (already used, subscribed, trials full or off) sees the account
 * page, which explains why and offers the plans. */
export default async function Trial({searchParams}: Props) {
  const query = await searchParams;
  const auth0 = getAuth0();
  const billing = readBillingConfig(process.env);
  const trial = readCardTrialConfig(process.env);
  if (!auth0 || !billing || !trial) return <section className="buy-page" aria-labelledby="trial-title">
    <div className="card buy-card">
      <Mark id="trial" size={40} />
      <p className="eyebrow">Saiph Cloud</p>
      <h1 id="trial-title">Free trials are not available right now.</h1>
      <p className="lede">You can still subscribe, and withdraw within 14 days for a full refund.</p>
      <div className="actions"><a className="button" href="/buy/monthly">Monthly, €9.99</a><a className="button secondary" href="/buy/yearly">Yearly, €89.99</a></div>
    </div>
  </section>;
  const request = await headers();
  const nonce = request.get("x-nonce") ?? undefined;
  const ga = readGaConfig(process.env);
  const consent = readConsent(request.get("cookie"));
  const session = await auth0.getSession();
  const signedIn = Boolean(session);
  if (session) {
    if (!canUseAccount(session.user.sub, process.env.SAIPH_OWNER_SUBJECT, process.env, session.user.mfa)
      || !maySubscribe(billing, session.user.sub)) redirect("/account");
    const view = await billingView(session.user.sub, session.user.trialKey);
    // Only an available trial is started here; every other state is explained on /account.
    if (!view || view === "unavailable" || view.trial.state !== "available") redirect("/account");
  } else {
    await countStep("signin_view", "trial", null, "a");
  }
  const days = plural(trial.days, "day");
  const analytics = ga && consent.granted ? {id: ga.measurementId, event: signedIn ? "login" : "signin_view",
    params: {plan: "trial", ...(signedIn ? {method: query.signed_in === "1" ? "google" : "session"} : {})}} : null;
  return <section className="buy-page" aria-labelledby="trial-title">
    <div className="card featured buy-card">
      <Mark id="trial" size={40} />
      <p className="eyebrow">{signedIn ? "Step 2 of 2 · Card details" : "Step 1 of 2 · Sign in"}</p>
      <h1 id="trial-title">{signedIn ? "Continue to your free trial." : "Try Saiph Cloud free for 14 days."}</h1>
      <dl className="order" aria-label="Your free trial">
        <div><dt>Saiph Cloud free trial</dt><dd><strong>{days}</strong></dd></div>
        <div><dt>Card details</dt><dd>Required at Stripe Checkout. No subscription charge during your trial.</dd></div>
        <div><dt>After 14 days</dt><dd><strong>€9.99 / month</strong>, billed automatically unless you cancel before your trial ends. No VAT is added.</dd></div>
      </dl>
      {query.checkout === "cancelled" && <Notice tone="neutral" title="Checkout was cancelled.">Your trial has not started. You can try again below.</Notice>}
      {signedIn ? <form id="handoff-form" method="post" action="/api/billing/trial">
        <input type="hidden" name="trial" value="start" />
        <button className="block" type="submit"><Icon name="card" />Continue to Stripe</button>
      </form> : <a className="google-button" href="/trial/start"><GoogleMark /> Continue with Google</a>}
      <p className="fine after">{signedIn
        ? "Your trial starts after you complete Stripe Checkout. Then install Saiph on your computer and phone and use this same account."
        : "Your trial belongs to the Google account you choose. Next, add your card on Stripe's secure checkout page."}</p>
      <p className="fine">Cancel any time in <strong>Manage billing</strong> on your account page. Cancel before the trial ends to avoid the first charge. We will email a reminder before billing begins.</p>
      <p className="fine">One free trial per person. Review the <a href="https://usesaiph.com/terms.html#trial">Cloud terms</a> before confirming your subscription in Stripe. <a href="/privacy">Privacy</a>{!signedIn && <> · <a href="/buy/monthly">Buy now instead</a></>}</p>
    </div>
    {analytics && <script id="buy-analytics" type="application/json" nonce={nonce} dangerouslySetInnerHTML={{__html: json(analytics)}} />}
    {analytics && <script nonce={nonce} dangerouslySetInnerHTML={{__html: GA_SCRIPT}} />}
    {signedIn && <script nonce={nonce} dangerouslySetInnerHTML={{__html: HANDOFF_SCRIPT}} />}
  </section>;
}
