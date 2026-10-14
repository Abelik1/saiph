// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getAuth0 } from "../../lib/auth";
import { billingView } from "../../lib/billing/view";
import {canUseAccount, readBetaConfig} from "../../lib/beta-policy.mjs";
import BetaAccount from "./BetaAccount";
import SubscriptionCard from "./SubscriptionCard";
export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Overview" };

type Props = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};
export default async function Account({ searchParams }: Props) {
  const auth0 = getAuth0();
  if (!auth0)
    return (
      <>
        <p className="eyebrow">Your account</p>
        <h1>Setup pending.</h1>
        <p className="lede">
          Account configuration is incomplete. Please return once sign-in is
          ready.
        </p>
        <a className="button" href="/">
          Back to account home
        </a>
      </>
    );
  const session = await auth0.getSession();
  if (!session) redirect("/auth/login");
  if (!canUseAccount(session.user.sub, process.env.SAIPH_OWNER_SUBJECT, process.env, session.user.mfa))
    return (
      <>
        <h1>Access denied.</h1>
        <p>This portal is restricted to its owner.</p>
      </>
    );
  // Billing standing comes only from webhook-stored rows (lib/billing/view.ts).
  const billing = await billingView(session.user.sub);
  // The checkout return is a display hint only; it never reaches billing state.
  const { checkout } = await searchParams;
  const notice = checkout === "returned" ? "returned" : checkout === "cancelled" ? "cancelled" : null;
  if (readBetaConfig(process.env)) return <BetaAccount billing={billing} notice={notice} />;
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Account overview</p>
          <h1>
            Your account,
            <br />
            <em>at a glance.</em>
          </h1>
          <p className="lede">Welcome to your owner preview.</p>
        </div>
        <a className="button secondary" href="/auth/logout">
          Sign out <span aria-hidden="true">↗</span>
        </a>
      </div>
      <div className="status-grid" aria-label="Account status">
        <section className="status-tile">
          <p className="eyebrow">Account</p>
          <h2>
            <span className="status-dot" aria-hidden="true" /> Signed in
          </h2>
          <p>Auth0 session active</p>
        </section>
        <section className="status-tile">
          <p className="eyebrow">Devices</p>
          <h2>Separate approval</h2>
          <p>Signing in does not pair your devices.</p>
        </section>
        <section className="status-tile">
          <p className="eyebrow">Hosted</p>
          <h2>Preview</h2>
          <p>Hosted access is managed by the Hosted service.</p>
        </section>
      </div>
      {billing ? <SubscriptionCard view={billing} notice={notice} /> : (
        <section className="card billing-card" aria-labelledby="subscription-title">
          <h2 id="subscription-title">Subscriptions are not available yet.</h2>
          <p>Subscriptions open when billing configuration and storage are ready.</p>
        </section>
      )}
      <section className="account-note">
        <h2>Your devices stay in your hands.</h2>
        <p>
          Your account session and device approval are separate. Signing in does
          not unlock message content.
        </p>
      </section>
    </>
  );
}
