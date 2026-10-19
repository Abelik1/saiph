// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getAuth0 } from "../../lib/auth";
import { billingView } from "../../lib/billing/view";
import {canUseAccount, readBetaConfig} from "../../lib/beta-policy.mjs";
import BetaAccount from "./BetaAccount";
import SubscriptionCard from "./SubscriptionCard";
import {CheckoutNotice, SignOut} from "./parts";
import {Icon} from "../ui";
export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Overview" };

type Props = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};
export default async function Account({ searchParams }: Props) {
  const auth0 = getAuth0();
  if (!auth0)
    return (
      <section className="state">
        <p className="eyebrow">Your account</p>
        <h1>Setup pending.</h1>
        <p className="lede">
          Account configuration is incomplete. Please return once sign-in is
          ready.
        </p>
        <div className="actions"><a className="button" href="/">Back to account home</a></div>
      </section>
    );
  const session = await auth0.getSession();
  if (!session) redirect("/auth/login");
  if (!canUseAccount(session.user.sub, process.env.SAIPH_OWNER_SUBJECT, process.env, session.user.mfa))
    return (
      <section className="state">
        <h1>Access denied.</h1>
        <p className="lede">This portal is restricted to its owner.</p>
        <div className="actions"><SignOut /></div>
      </section>
    );
  // Billing standing comes only from webhook-stored rows (lib/billing/view.ts).
  const billing = await billingView(session.user.sub, session.user.trialKey);
  // The checkout return is a display hint only; it never reaches billing state.
  const { checkout, trial } = await searchParams;
  const notice = checkout === "returned" ? "returned" : checkout === "cancelled" ? "cancelled" : trial === "started" ? "trial" : null;
  if (readBetaConfig(process.env)) return <BetaAccount billing={billing} notice={notice} />;
  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">Account overview</p>
          <h1>Your account, <span className="gradient-text">at a glance.</span></h1>
          <p className="lede">Welcome to your owner preview.</p>
        </div>
        <SignOut />
      </div>
      {billing && <CheckoutNotice notice={notice} />}
      <dl className="facts overview" aria-label="Account status">
        <div><dt>Account</dt><dd><span className="pill good">Signed in</span><span className="fine">Auth0 session active</span></dd></div>
        <div><dt>Devices</dt><dd>Separate approval<span className="fine">Signing in does not pair your devices.</span></dd></div>
        <div><dt>Cloud</dt><dd>Preview<span className="fine">Cloud access is managed by the Cloud service.</span></dd></div>
      </dl>
      <div className="after">
        {billing ? <SubscriptionCard view={billing} /> : (
          <section className="card" aria-labelledby="subscription-title">
            <p className="eyebrow">Saiph Cloud subscription</p>
            <h2 id="subscription-title">Subscriptions are not available yet.</h2>
            <p>Subscriptions open when billing configuration and storage are ready.</p>
          </section>
        )}
      </div>
      <p className="fine after with-icon"><Icon name="lock" />Your account session and device approval are separate. Signing in does not unlock message content.</p>
    </>
  );
}
