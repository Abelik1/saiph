// SPDX-License-Identifier: AGPL-3.0-or-later
import type {Metadata} from "next";
import {headers} from "next/headers";
import {redirect} from "next/navigation";
import {getAuth0} from "../../lib/auth";
import {canUseAccount} from "../../lib/beta-policy.mjs";
import {billingView} from "../../lib/billing/view";
import {maySubscribe, readBillingConfig} from "../../lib/billing/policy";
import {readTrialConfig} from "../../lib/billing/trial.mjs";
import {countStep} from "../../lib/funnel";
import {readConsent, readGaConfig} from "../../lib/ga.mjs";
import {GoogleMark, Icon, Mark} from "../ui";
import {GA_SCRIPT, HANDOFF_SCRIPT} from "../funnel-scripts";
export const dynamic = "force-dynamic";
export const metadata: Metadata = {title: "Start your free trial"};

type Props = {searchParams: Promise<Record<string, string | string[] | undefined>>};
const json = (value: unknown) => JSON.stringify(value).replace(/</g, "\\u003c");
const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;

/** Start your free trial from usesaiph.com: one sign-in button, then the trial
 * starts with no further click (docs/LANDING_CONVERSION.md). Anyone who cannot
 * start one (already used, subscribed, trials full or off) sees the account
 * page, which explains why and offers the plans. */
export default async function Trial({searchParams}: Props) {
  const query = await searchParams;
  const auth0 = getAuth0();
  const billing = readBillingConfig(process.env);
  const trial = readTrialConfig(process.env);
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
      <p className="eyebrow">{signedIn ? "Starting your trial" : "Free trial · Sign in"}</p>
      <h1 id="trial-title">{signedIn ? "Starting your free trial." : "Try Saiph Cloud free."}</h1>
      <dl className="order" aria-label="Your free trial">
        <div><dt>Saiph Cloud free trial</dt><dd><strong>{days}</strong></dd></div>
        <div><dt>Today</dt><dd>€0. No card needed.</dd></div>
        <div><dt>Afterwards</dt><dd>Cloud pauses until you subscribe. Nothing is charged automatically.</dd></div>
      </dl>
      {signedIn ? <form id="handoff-form" method="post" action="/api/billing/trial">
        <input type="hidden" name="trial" value="start" />
        <button className="block" type="submit"><Icon name="key" />Start free trial</button>
      </form> : <a className="google-button" href="/trial/start"><GoogleMark /> Continue with Google</a>}
      <p className="fine after">{signedIn
        ? "Next: install Saiph on your computer and phone from your account page and sign in there with this same account."
        : "Your trial belongs to the Google account you choose. No password, no card, nothing else to fill in."}</p>
      <p className="fine">One free trial per person. By continuing you agree to the <a href="https://usesaiph.com/terms.html#trial">Cloud terms</a>. <a href="/privacy">Privacy</a>{!signedIn && <> · <a href="/buy/monthly">Buy now instead</a></>}</p>
    </div>
    {analytics && <script id="buy-analytics" type="application/json" nonce={nonce} dangerouslySetInnerHTML={{__html: json(analytics)}} />}
    {analytics && <script nonce={nonce} dangerouslySetInnerHTML={{__html: GA_SCRIPT}} />}
    {signedIn && <script nonce={nonce} dangerouslySetInnerHTML={{__html: HANDOFF_SCRIPT}} />}
  </section>;
}
