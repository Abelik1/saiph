// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Metadata } from "next";
import { getAuth0 } from "../../../lib/auth";
import { canUseAccount } from "../../../lib/beta-policy.mjs";
import { withBillingStore } from "../../../lib/billing/db";
import { DELETION_DAYS } from "../../../lib/billing/deletion";
import { readBillingConfig } from "../../../lib/billing/policy";
import { Icon, Notice } from "../../ui";
export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Delete your account" };

type Status = {
  request: { state: "pending" | "done"; requestedAt: number; completedAt: number | null } | null;
  subscriptionRenews: boolean;
};
const day = (seconds: number) => new Intl.DateTimeFormat("en-IE", {
  day: "numeric", month: "long", year: "numeric", timeZone: "UTC",
}).format(new Date(seconds * 1000));
const SUPPORT = "support@usesaiph.com";

/** Cancelling is separate from deleting; said without a link, because the account page shows plans. */
function CancelFirst() {
  return <Notice tone="warn" title="Cancel your subscription first.">
    Your Saiph Cloud subscription is still set to renew. Deleting your account does not cancel it. Sign in to your Saiph
    account page on the web, choose Manage billing and cancel it, so you are not charged again.
  </Notice>;
}

function RequestForm({ renews }: { renews: boolean }) {
  return <section className="card" aria-labelledby="request-title">
    <h2 id="request-title">Request deletion</h2>
    <p>We delete your account and its data within {DELETION_DAYS} days. This cannot be undone: your devices are removed from your account, and your encrypted content on Saiph Cloud is gone for good.</p>
    {renews && <p><strong>We will still record your request</strong>, but please cancel your subscription in Manage billing first.</p>}
    <form method="post" action="/api/account/delete" className="actions">
      <input type="hidden" name="confirm" value="delete" />
      <button type="submit">Request deletion</button>
    </form>
  </section>;
}

/**
 * Public page for Google Play's account deletion requirement, opened from the
 * Android app's settings. It explains what is deleted to anyone; a signed-in
 * person can file the request. No navigation, and no links to plans, prices or
 * purchases (the layout draws this page without the site menus).
 */
export default async function DeleteAccount({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const auth0 = getAuth0();
  const session = auth0 ? await auth0.getSession() : null;
  const subject = session?.user.sub;
  const allowed = typeof subject === "string"
    && canUseAccount(subject, process.env.SAIPH_OWNER_SUBJECT, process.env, session?.user.mfa);
  const config = readBillingConfig(process.env);
  let status: Status | "unavailable" | null = null;
  if (allowed && config) {
    try { status = await withBillingStore(config, (store) => store.deletionStatus(subject)) as Status; }
    catch { status = "unavailable"; }
  }
  const { requested } = await searchParams;
  const pending = status && status !== "unavailable" && status.request?.state === "pending" ? status.request : null;
  const done = status && status !== "unavailable" && status.request?.state === "done" ? status.request : null;
  const renews = Boolean(status && status !== "unavailable" && status.subscriptionRenews);

  return <>
    <div className="page-head">
      <div>
        <p className="eyebrow">Saiph account</p>
        <h1>{pending ? (requested ? "Deletion requested." : "Your deletion request is in.") : "Delete your Saiph account."}</h1>
        <p className="lede">Ask us to delete your Saiph account and the data the Saiph service keeps about you. We finish within {DELETION_DAYS} days of your request.</p>
      </div>
    </div>

    {pending && <Notice title={"Request received " + day(pending.requestedAt) + "."}>
      We will delete your account and its data by {day(pending.requestedAt + DELETION_DAYS * 86400)}. There is nothing else you need to do{renews ? " except cancel your subscription" : ""}. To withdraw the request, email {SUPPORT}.
    </Notice>}
    {renews && <CancelFirst />}

    <div className="stack after">
      <section className="card" aria-labelledby="what-title">
        <h2 id="what-title">What gets deleted</h2>
        <ul className="aside-list">
          <li><Icon name="key" /><span><strong>Your sign-in.</strong> The Saiph login (held by our sign-in provider, Auth0) for the Google account you use with Saiph.</span></li>
          <li><Icon name="devices" /><span><strong>Your Saiph Cloud account.</strong> Its device records and approvals, and the encrypted content your devices stored on the service.</span></li>
          <li><Icon name="card" /><span><strong>Billing records</strong>, except those tax law requires us to keep. Those are kept only as long as the law requires (generally six years in Ireland) and then deleted. Stripe keeps its own payment records under its own policy.</span></li>
        </ul>
        <p className="fine after">Data on your own phone and computers stays there until you remove it or uninstall Saiph. A self-hosted Hub you run yourself is yours to delete.</p>
      </section>

      <section className="card" aria-labelledby="before-title">
        <h2 id="before-title">Before you ask</h2>
        <ul className="aside-list">
          <li><Icon name="info" /><span><strong>Cancel any subscription first.</strong> Deleting your account does not cancel a Saiph Cloud subscription. Cancel it in Manage billing on your Saiph account page on the web.</span></li>
          <li><Icon name="check" /><span><strong>Within {DELETION_DAYS} days.</strong> We delete your account and data within {DELETION_DAYS} days of your request. This page shows when your request was received.</span></li>
        </ul>
      </section>

      {!auth0 || !config ? <section className="card">
        <h2>Requests by email</h2>
        <p>Online requests are not available on this site yet. Email {SUPPORT} from the address you sign in with, and we will delete your account within {DELETION_DAYS} days.</p>
      </section> : !session ? <section className="card" aria-labelledby="signin-title">
        <h2 id="signin-title">Sign in to request deletion</h2>
        <p>Sign in with the Google account you use for Saiph, so we know which account to delete. You come straight back here.</p>
        <div className="actions"><a className="button" href="/account/delete/sign-in">Sign in to continue</a></div>
        <p className="fine after">Cannot sign in? Email {SUPPORT} from the address you sign in with.</p>
      </section> : !allowed ? <section className="card">
        <h2>Requests by email</h2>
        <p>This sign-in cannot use the request form. Email {SUPPORT} from the address you sign in with, and we will delete your account within {DELETION_DAYS} days.</p>
      </section> : status === "unavailable" ? <Notice tone="warn" title="We could not check your account just now.">
        Please try again shortly, or email {SUPPORT} from the address you sign in with.
      </Notice> : pending ? null : <>
        {done && <Notice tone="neutral" title={"An earlier request was completed " + day(done.completedAt ?? done.requestedAt) + "."}>
          If you have used Saiph again since then, you can ask again below.
        </Notice>}
        <RequestForm renews={renews} />
      </>}
    </div>
  </>;
}
