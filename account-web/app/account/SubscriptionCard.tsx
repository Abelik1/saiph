// SPDX-License-Identifier: AGPL-3.0-or-later
import type {Entitlement} from "../../lib/billing/entitlement.mjs";
import type {BillingView} from "../../lib/billing/view";
import {Icon, Notice} from "../ui";

const standingText: Record<Entitlement["state"], string> = {
  none: "No subscription yet", active: "Active", ending: "Active, cancellation scheduled",
  payment_failed: "Payment failed: Stripe is retrying your card",
  pending: "Awaiting payment confirmation", paused: "Paused",
  renewal_unconfirmed: "Renewal not yet confirmed", disputed: "Suspended while a payment dispute is open", ended: "Ended",
};
const standingTone: Record<Entitlement["state"], string> = {
  none: "", active: "good", ending: "warn", payment_failed: "bad", pending: "warn",
  paused: "warn", renewal_unconfirmed: "warn", disputed: "bad", ended: "",
};
const day = (seconds: number) => new Intl.DateTimeFormat("en-IE", {day: "numeric", month: "long", year: "numeric", timeZone: "UTC"})
  .format(new Date(seconds * 1000));

/** Subscribe, manage and current billing standing, from webhook-stored rows only.
 * The checkout return notice is shown by the page, never derived here. */
export default function SubscriptionCard({view}: {view: BillingView | "unavailable"}) {
  const test = view !== "unavailable" && view.mode === "owner-sandbox";
  return <section className="card" aria-labelledby="subscription-title">
    <div className="card-head">
      <div>
        <p className="eyebrow">Saiph Hosted subscription</p>
        <h2 id="subscription-title">Use Saiph anywhere, with no server of your own.</h2>
      </div>
      {test && <span className="pill warn">Test mode</span>}
    </div>
    {view === "unavailable" ? <p role="status">Subscription details are temporarily unavailable. Please try again shortly.</p> : <>
      <p>Your subscription keeps your computers and phone connected through Saiph Hosted. Your content stays end-to-end encrypted.</p>
      <Notice tone="warn" title="Saiph Hosted is in beta.">
        Expect bugs, missing features and occasional downtime, and features may change as we build it. You can withdraw within 14 days of subscribing for a full refund.
      </Notice>
      {view.standing.state !== "none" && <dl className="facts">
        <div><dt>Status</dt><dd><span className={"pill " + standingTone[view.standing.state]}>{standingText[view.standing.state]}</span></dd></div>
        {view.standing.entitled && view.standing.until !== null && <div><dt>Access until</dt><dd>{day(view.standing.until)}</dd></div>}
      </dl>}
      {view.subscriptions.length > 0 && <ul className="subscription-list">
        {view.subscriptions.map((subscription, index) => <li key={index}>
          <strong>{subscription.label}</strong>{subscription.period ? <span>{subscription.period}</span> : null}
        </li>)}
      </ul>}
      {view.canSubscribe && <div className="plans">
        <div className="plan">
          <h3>Monthly</h3>
          <p className="price">€9.99 <span>/ month</span></p>
          <p>Cancel any time.</p>
          <form method="post" action="/api/billing/checkout">
            <input type="hidden" name="plan" value="monthly" />
            <button className="secondary block" type="submit">Choose monthly</button>
          </form>
        </div>
        <div className="plan recommended">
          <span className="pill info plain">Save about 25%</span>
          <h3>Yearly</h3>
          <p className="price">€89.99 <span>/ year</span></p>
          <p>Works out at about €7.50 a month.</p>
          <form method="post" action="/api/billing/checkout">
            <input type="hidden" name="plan" value="yearly" />
            <button className="block" type="submit">Choose yearly</button>
          </form>
        </div>
      </div>}
      {view.hasCustomer && <div className="actions">
        <form method="post" action="/api/billing/portal">
          <button className="ghost" type="submit"><Icon name="card" />Manage billing</button>
        </form>
        <span className="fine">Change plan, update your card or cancel, in Stripe.</span>
      </div>}
      {view.hasCustomer && <p className="fine"><a href="/account/withdraw">Withdraw from contract here</a>: within 14 days of subscribing, with a full refund.</p>}
      <p className="fine after">{test ? "Test mode: use Stripe test card details only. No real money is charged." : "Cancel any time in Manage billing; access continues to the end of the paid period."}</p>
    </>}
    <div className="card-foot"><Icon name="lock" /><span>Paying gives your account Hosted access. You still approve devices on your own computer, and signing in never unlocks your content.</span></div>
  </section>;
}
