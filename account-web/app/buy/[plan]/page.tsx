// SPDX-License-Identifier: AGPL-3.0-or-later
import type {Metadata} from "next";
import {headers} from "next/headers";
import {notFound, redirect} from "next/navigation";
import {getAuth0} from "../../../lib/auth";
import {canUseAccount} from "../../../lib/beta-policy.mjs";
import {billingView} from "../../../lib/billing/view";
import {maySubscribe, planFor, readBillingConfig} from "../../../lib/billing/policy";
import {euros, resolveOffer} from "../../../lib/billing/price-test.mjs";
import {buyPath, isPlan, offerValue} from "../../../lib/buy.mjs";
import {countStep} from "../../../lib/funnel";
import {readConsent, readGaConfig} from "../../../lib/ga.mjs";
import {GoogleMark, Icon, Mark, Notice} from "../../ui";
import {GA_SCRIPT, HANDOFF_SCRIPT} from "../../funnel-scripts";
export const dynamic = "force-dynamic";
export const metadata: Metadata = {title: "Buy Saiph Cloud"};

type Props = {params: Promise<{plan: string}>; searchParams: Promise<Record<string, string | string[] | undefined>>};
const one = (value: string | string[] | undefined) => typeof value === "string" ? value : undefined;
const json = (value: unknown) => JSON.stringify(value).replace(/</g, "\\u003c");

/** Buy now from usesaiph.com lands here: the order, then one sign-in button.
 * After sign-in it hands straight over to Stripe Checkout (docs/LANDING_CONVERSION.md). */
export default async function Buy({params, searchParams}: Props) {
  const {plan} = await params;
  if (!isPlan(plan)) notFound();
  const query = await searchParams;
  const auth0 = getAuth0();
  const billing = readBillingConfig(process.env);
  if (!auth0 || !billing) return <section className="state">
    <p className="eyebrow">Saiph Cloud</p>
    <h1>Subscriptions are not open yet.</h1>
    <p className="lede">Please try again soon.</p>
    <div className="actions"><a className="button" href="https://usesaiph.com">Back to usesaiph.com</a></div>
  </section>;
  // The same variant decides the price shown here and the price Stripe charges.
  const {test, variant} = resolveOffer(billing.priceTest, offerValue(one(query.offer)));
  const chosen = planFor(billing, plan, variant);
  const offer = test ? variant : null;
  const price = euros(chosen.amount);
  const period = plan === "yearly" ? "year" : "month";
  const other = plan === "yearly" ? "monthly" : "yearly";
  const request = await headers();
  const nonce = request.get("x-nonce") ?? undefined;
  const ga = readGaConfig(process.env);
  const consent = readConsent(request.get("cookie"));
  const session = await auth0.getSession();
  const signedIn = Boolean(session);
  if (session) {
    // Anyone who cannot check out (already subscribed, not allowed, billing
    // unavailable) sees the account page, which explains why.
    if (!canUseAccount(session.user.sub, process.env.SAIPH_OWNER_SUBJECT, process.env, session.user.mfa)
      || !maySubscribe(billing, session.user.sub)) redirect("/account");
    const view = await billingView(session.user.sub, session.user.trialKey);
    if (!view || view === "unavailable" || !view.canSubscribe) redirect("/account");
  } else {
    await countStep("signin_view", plan, test, variant);
  }
  const analytics = ga && consent.granted ? {id: ga.measurementId,
    // GA4's recommended "login" marks step 4; "session" means already signed in.
    event: signedIn ? "login" : "signin_view",
    params: {...(signedIn ? {method: one(query.signed_in) === "1" ? "google" : "session"} : {}), plan,
      ...(test ? {price_test: test, price_variant: variant} : {})}} : null;
  return <section className="buy-page" aria-labelledby="buy-title">
    <div className="card featured buy-card">
      <Mark id="buy" size={40} />
      <p className="eyebrow">{signedIn ? "Step 2 of 2 · Payment" : "Step 1 of 2 · Sign in"}</p>
      <h1 id="buy-title">{signedIn ? "Taking you to secure payment." : "Sign in to buy Saiph Cloud."}</h1>
      <dl className="order" aria-label="Your order">
        <div><dt>Saiph Cloud, {plan}</dt><dd><strong>{price}</strong> / {period}</dd></div>
        <div><dt>Today</dt><dd>{price}, then every {period}. No VAT is added.</dd></div>
      </dl>
      {signedIn ? <form id="handoff-form" method="post" action="/api/billing/checkout">
        <input type="hidden" name="plan" value={plan} />
        {offer && <input type="hidden" name="offer" value={offer} />}
        <button className="block" type="submit"><Icon name="card" />Continue to payment</button>
      </form> : <a className="google-button" href={buyPath(plan, offer).replace(/^\/buy\/(monthly|yearly)/, "/buy/$1/start")}>
        <GoogleMark /> Continue with Google
      </a>}
      <p className="fine after">{signedIn
        ? "Stripe's payment page shows the price again before you pay. Cancel any time; you can withdraw within 14 days for a full refund."
        : "Your subscription belongs to the Google account you choose, so your devices can use it. Next is Stripe's secure payment page. No password, nothing else to fill in."}</p>
      {!signedIn && <p className="fine">
        <a href={buyPath(other, offer)}>Switch to {other} instead</a> · <a href="https://usesaiph.com/terms.html">Terms</a> · <a href="/privacy">Privacy</a>
      </p>}
      {test && <Notice tone="neutral" title="We are testing prices.">This is the price you will pay, and it stays the same for you.</Notice>}
    </div>
    {analytics && <script id="buy-analytics" type="application/json" nonce={nonce} dangerouslySetInnerHTML={{__html: json(analytics)}} />}
    {analytics && <script nonce={nonce} dangerouslySetInnerHTML={{__html: GA_SCRIPT}} />}
    {signedIn && <script nonce={nonce} dangerouslySetInnerHTML={{__html: HANDOFF_SCRIPT}} />}
  </section>;
}
