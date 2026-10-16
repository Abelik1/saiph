// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getAuth0 } from "../../../lib/auth";
import { canUseAccount } from "../../../lib/beta-policy.mjs";
import { withBillingStore } from "../../../lib/billing/db";
import { maySubscribe, readBillingConfig } from "../../../lib/billing/policy";
import { createStripe, withdrawalStatus, type WithdrawalStatus } from "../../../lib/billing/service";
import { Notice } from "../../ui";
import { SignOut } from "../parts";
export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Withdraw from contract" };

const when = (seconds: number, time = false) => new Intl.DateTimeFormat("en-IE", {
  day: "numeric", month: "long", year: "numeric", timeZone: "UTC",
  ...(time ? { hour: "2-digit", minute: "2-digit" } : {}),
}).format(new Date(seconds * 1000)) + (time ? " UTC" : "");
const money = (cents: number, currency: string) =>
  new Intl.NumberFormat("en-IE", { style: "currency", currency: currency.toUpperCase() }).format(cents / 100);

/**
 * EU right of withdrawal (14 days): a clearly labelled page reachable from the
 * account page, then one "Confirm withdrawal" button. Status is read from
 * Stripe on every visit; the ?done query only changes the heading.
 */
export default async function Withdraw({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const auth0 = getAuth0();
  const session = auth0 ? await auth0.getSession() : null;
  if (!auth0 || !session) redirect("/auth/login");
  if (!canUseAccount(session.user.sub, process.env.SAIPH_OWNER_SUBJECT, process.env, session.user.mfa)) redirect("/account");
  const config = readBillingConfig(process.env);
  let status: WithdrawalStatus | "unavailable" = { state: "none" };
  if (config && maySubscribe(config, session.user.sub)) {
    const subject = session.user.sub;
    try { status = await withBillingStore(config, (store) => withdrawalStatus(createStripe(config), store, config, subject)); }
    catch { status = "unavailable"; }
  }
  const { done } = await searchParams;
  return <>
    <div className="page-head">
      <div>
        <p className="eyebrow">Saiph Hosted subscription</p>
        <h1>{status !== "unavailable" && status.state === "withdrawn" ? (status.complete ? "Withdrawal received." : "Withdrawal received, still processing.") : "Withdraw from contract."}</h1>
        <p className="lede">Within 14 days of subscribing you can withdraw without giving a reason and get a full refund.</p>
      </div>
      <SignOut />
    </div>
    {status === "unavailable" ? <Notice tone="warn" title="We couldn't check your subscription just now.">
      Please try again shortly, or write to support@usesaiph.com and we will process your withdrawal.
    </Notice> : status.state === "withdrawn" && !status.complete ? <section className="card" aria-labelledby="withdraw-title">
      <h2 id="withdraw-title">We have your withdrawal, but it isn't finished yet.</h2>
      <dl className="facts">
        <div><dt>Received</dt><dd>{when(status.at, true)}</dd></div>
        <div><dt>Refunded so far</dt><dd>{money(status.refunded, status.currency)}</dd></div>
        <div><dt>Still to refund</dt><dd>{money(status.outstanding, status.currency)}</dd></div>
      </dl>
      <p>Part of the cancellation or refund could not be completed just now. Your withdrawal still counts from the time above. Press the button to finish it, or write to support@usesaiph.com and we will.</p>
      <form method="post" action="/api/billing/withdraw" className="actions">
        <input type="hidden" name="confirm" value="withdraw" />
        <button type="submit">Finish withdrawal</button>
      </form>
    </section> : status.state === "withdrawn" ? <section className="card" aria-labelledby="withdraw-title">
      <h2 id="withdraw-title">{done ? "Your withdrawal is confirmed." : "You have withdrawn from this subscription."}</h2>
      <dl className="facts">
        <div><dt>Received</dt><dd>{when(status.at, true)}</dd></div>
        <div><dt>Refunded</dt><dd>{money(status.refunded, status.currency)} to your original payment method</dd></div>
        <div><dt>Hosted access</dt><dd>Ended</dd></div>
      </dl>
      <p className="fine">Refunds usually reach your card within 5–10 business days. Keep this page or Stripe's refund email as your confirmation. Your devices and their data on your own computers are not affected.</p>
    </section> : status.state === "eligible" ? <section className="card" aria-labelledby="withdraw-title">
      <h2 id="withdraw-title">Withdraw from your Saiph Hosted subscription</h2>
      <dl className="facts">
        <div><dt>Subscribed</dt><dd>{when(status.startedAt)}</dd></div>
        <div><dt>You can withdraw until</dt><dd>{when(status.deadline, true)}</dd></div>
        <div><dt>Refund</dt><dd>{money(status.refund, status.currency)}, in full</dd></div>
      </dl>
      <p>Confirming ends your subscription and your Hosted access straight away, and refunds everything you paid for it to your original payment method. You can subscribe again later.</p>
      <form method="post" action="/api/billing/withdraw" className="actions">
        <input type="hidden" name="confirm" value="withdraw" />
        <button type="submit">Confirm withdrawal</button>
        <a className="button ghost" href="/account">Keep my subscription</a>
      </form>
    </section> : status.state === "expired" ? <section className="card">
      <h2>The 14-day withdrawal period has ended.</h2>
      <p>It ended on {when(status.deadline, true)}. You can still stop future renewals at any time with Manage billing on your account page; access continues to the end of the period you paid for.</p>
      <div className="actions"><a className="button" href="/account">Back to your account</a></div>
    </section> : <section className="card">
      <h2>There is no subscription to withdraw from.</h2>
      <p>This account has no Saiph Hosted subscription within its first 14 days.</p>
      <div className="actions"><a className="button" href="/account">Back to your account</a></div>
    </section>}
  </>;
}
