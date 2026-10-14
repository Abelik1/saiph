// SPDX-License-Identifier: AGPL-3.0-or-later
import type {Entitlement} from "../../lib/billing/entitlement.mjs";
import type {BillingView} from "../../lib/billing/view";

const standingText: Record<Entitlement["state"], string> = {
  none: "No subscription yet", active: "Active", ending: "Active, cancellation scheduled",
  payment_failed: "Payment failed: Stripe is retrying your card",
  pending: "Awaiting payment confirmation", paused: "Paused",
  renewal_unconfirmed: "Renewal not yet confirmed", disputed: "Suspended while a payment dispute is open", ended: "Ended",
};
const day = (seconds: number) => new Intl.DateTimeFormat("en-IE", {day: "numeric", month: "long", year: "numeric", timeZone: "UTC"})
  .format(new Date(seconds * 1000));

/** Subscribe, manage and current billing standing. The checkout return only
 * changes the wording here; access comes from the signed webhook alone. */
export default function SubscriptionCard({view, notice}: {view: BillingView | "unavailable"; notice: "returned" | "cancelled" | null}) {
  const test = view !== "unavailable" && view.mode === "owner-sandbox";
  return <section className="card billing-card" aria-labelledby="subscription-title">
    <div className="card-topline">
      <p className="eyebrow">Saiph Hosted subscription</p>
      {test && <span className="badge">Test mode</span>}
    </div>
    {notice === "returned" && <div className="notice" role="status">
      <strong>Thanks. Stripe is confirming your payment.</strong>
      <p>Access appears on this page once Stripe confirms it, usually within a minute. <a href="/account">Reload to check</a>.</p>
    </div>}
    {notice === "cancelled" && <div className="notice" role="status">
      <strong>Checkout was closed.</strong><p>Nothing was charged. You can subscribe whenever you like.</p>
    </div>}
    {view === "unavailable" ? <p role="status">Subscription details are temporarily unavailable. Please try again shortly.</p> : <div className="billing-grid">
      <div>
        <h2 id="subscription-title">Use Saiph anywhere, no server of your own.</h2>
        <p>Your subscription keeps your computers and phone connected through Saiph Hosted. Your content stays end-to-end encrypted.</p>
        <p className="fine">{test ? "Test mode: use Stripe test card details only. No real money is charged." : "Cancel any time in Manage billing; access continues to the end of the paid period."}</p>
      </div>
      <div className="billing-state">
        <h3>{standingText[view.standing.state]}{view.standing.entitled && view.standing.until !== null ? ` until ${day(view.standing.until)}` : ""}</h3>
        {view.subscriptions.length > 0 && <ul className="subscription-list">
          {view.subscriptions.map((subscription, index) => <li key={index}>
            <strong>{subscription.label}</strong>{subscription.period ? <span>{subscription.period}</span> : null}
          </li>)}
        </ul>}
        <div className="billing-actions">
          {view.canSubscribe && <>
            <form method="post" action="/api/billing/checkout">
              <input type="hidden" name="plan" value="monthly" />
              <button type="submit">€3.99 / month <span aria-hidden="true">↗</span></button>
            </form>
            <form method="post" action="/api/billing/checkout">
              <input type="hidden" name="plan" value="yearly" />
              <button type="submit">€36 / year, save 25% <span aria-hidden="true">↗</span></button>
            </form>
          </>}
          {view.hasCustomer && <form method="post" action="/api/billing/portal">
            <button className="secondary" type="submit">Manage billing</button>
          </form>}
        </div>
      </div>
    </div>}
    <div className="card-footnote">
      Paying gives your account Hosted access. Devices are still approved on your own computer, and signing in never unlocks your content.
    </div>
  </section>;
}
