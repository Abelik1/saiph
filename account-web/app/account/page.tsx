// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getAuth0 } from "../../lib/auth";
import { withBillingStore } from "../../lib/billing/db";
import { readBillingConfig } from "../../lib/billing/policy";
import { deriveEntitlement, type Entitlement } from "../../lib/billing/entitlement.mjs";
import { subscriptionSummary } from "../../lib/billing/presentation.mjs";
import {canUseAccount, readBetaConfig} from "../../lib/beta-policy.mjs";
import BetaAccount from "./BetaAccount";
export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Overview" };

const standingText: Record<Entitlement["state"], string> = {
  none: "No subscription observed", active: "Active", ending: "Active, cancellation scheduled",
  payment_failed: "Payment failed: renewal suspended", pending: "Awaiting payment confirmation",
  paused: "Paused", renewal_unconfirmed: "Renewal not yet confirmed", ended: "Ended",
};

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
  if (readBetaConfig(process.env)) return <BetaAccount />;
  const billing = readBillingConfig(process.env);
  let sandboxConfigured = false;
  let hasCustomer = false;
  let standing: Entitlement | null = null;
  let subscriptions: ReturnType<typeof subscriptionSummary>[] = [];
  if (billing) {
    try {
      const observed = await withBillingStore(
        billing.accountId,
        async (store) => {
          const customer = await store.findCustomer(billing.ownerSubject);
          const snapshots = customer
            ? await store.listSubscriptions(billing.ownerSubject)
            : [];
          return {
            hasCustomer: Boolean(customer),
            subscriptions: snapshots.map(subscriptionSummary),
            standing: deriveEntitlement(snapshots, Math.floor(Date.now() / 1000)),
          };
        },
      );
      hasCustomer = observed.hasCustomer;
      standing = observed.standing;
      subscriptions = observed.subscriptions;
      sandboxConfigured = true;
    } catch {
      /* Keep unavailable storage and provider details private. */
    }
  }
  const { checkout } = await searchParams;
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
      {checkout === "returned" ? (
        <div className="notice" role="status">
          <strong>You’re back from test checkout.</strong>
          <p>
            Returning does not confirm payment. Subscription details below
            reflect stored billing updates.
          </p>
        </div>
      ) : checkout === "cancelled" ? (
        <div className="notice" role="status">
          <strong>Test checkout was closed.</strong>
          <p>
            Your subscription status is shown below. You can try checkout again
            when it is available.
          </p>
        </div>
      ) : null}
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
          <h2>Design preview</h2>
          <p>Hosted access has not been granted.</p>
        </section>
      </div>
      <section
        className="card billing-card"
        aria-labelledby="subscription-title"
      >
        <div className="card-topline">
          <p className="eyebrow">Subscription</p>
          <span className="badge">Test mode</span>
        </div>
        <div className="billing-grid">
          <div>
            <h2 id="subscription-title">A safe place to try things.</h2>
            <p>
              Test the subscription flow before Hosted opens. No live payment is
              collected here.
            </p>
            <div className="test-price">
              €1 <span>/ month · test subscription</span>
            </div>
            <p className="fine">Use test payment details only.</p>
          </div>
          <div className="billing-state">
            <h3>
              {sandboxConfigured
                ? "Owner sandbox testing"
                : "Stripe test setup pending"}
            </h3>
            {sandboxConfigured ? (
              <>
                {standing && <p role="status">Sandbox billing: {standingText[standing.state]}{standing.entitled && standing.until !== null ? ` until ${new Date(standing.until * 1000).toISOString().slice(0, 10)}` : ""}</p>}
                {subscriptions.length ? (
                  <ul className="subscription-list">
                    {subscriptions.map((subscription, index) => (
                      <li key={index}>
                        <strong>{subscription.label}</strong>
                        {subscription.period ? (
                          <span>{subscription.period}</span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>No test subscription update has been recorded yet.</p>
                )}
                <div className="billing-actions">
                  <form method="post" action="/api/billing/checkout">
                    <button type="submit">
                      Open test checkout <span aria-hidden="true">↗</span>
                    </button>
                  </form>
                  {hasCustomer ? (
                    <form method="post" action="/api/billing/portal">
                      <button className="secondary" type="submit">
                        Manage test subscription
                      </button>
                    </form>
                  ) : (
                    <p className="fine">
                      Subscription management becomes available after a test
                      customer is created.
                    </p>
                  )}
                </div>
              </>
            ) : (
              <>
                <p>
                  Subscription testing will be available when billing
                  configuration and storage are ready.
                </p>
                <button disabled>Test subscription unavailable</button>
              </>
            )}
          </div>
        </div>
        <div className="card-footnote">
          Test billing does not activate Hosted or approve devices. Paid launch
          awaits product acceptance and independent review.
        </div>
      </section>
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
