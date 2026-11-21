// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getAuth0 } from "../../../lib/auth";
import { isOwner } from "../../../lib/billing/admin";
import { withBillingStore } from "../../../lib/billing/db";
import { DELETION_DAYS } from "../../../lib/billing/deletion";
import { readBillingConfig } from "../../../lib/billing/policy";
import { readTrialConfig } from "../../../lib/billing/trial.mjs";
import { Notice } from "../../ui";
import { SignOut } from "../parts";
export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Admin" };

const day = (seconds: number) => new Intl.DateTimeFormat("en-IE", {
  day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC",
}).format(new Date(seconds * 1000)) + " UTC";
const stamp = (value: string | string[] | undefined) =>
  typeof value === "string" && /^\d{1,12}$/.test(value) ? Number(value) : null;

/** What the last lookup or extension found. Only dates and counts come back in the URL, never the address. */
function Result({ query }: { query: Record<string, string | string[] | undefined> }) {
  const until = stamp(query.until), from = stamp(query.from), started = stamp(query.started), max = stamp(query.max);
  const now = Math.floor(Date.now() / 1000);
  switch (query.result) {
    case "found": return until && started ? <Notice tone="info" title={until > now ? "Trial running." : "Trial ended."}>
      Started {day(started)}; {until > now ? "ends" : "ended"} {day(until)}.</Notice> : null;
    case "extended": return until ? <Notice tone="info" title="Trial extended.">
      {from ? <>It was ending {day(from)}. </> : null}It now ends {day(until)}, and Saiph Cloud already knows.</Notice> : null;
    case "extended_pending": return until ? <Notice tone="warn" title="Trial extended; delivery pending.">
      It now ends {day(until)}. Saiph Cloud could not be told just now; the daily refresh delivers it automatically.</Notice> : null;
    case "too_long": return <Notice tone="warn" title="That is more than 30 days ahead.">
      {until ? <>The trial ends {day(until)}. </> : null}A trial can end at most 30 days from now{max !== null ? <>, so you can add up to {max} {max === 1 ? "day" : "days"} today</> : null}.</Notice>;
    case "not_found": return <Notice tone="warn" title="No trial for that address.">
      Nobody has started a free trial with that email address. They need to sign in and press Start free trial first.</Notice>;
    case "invalid_email": return <Notice tone="warn" title="That is not an email address." />;
    case "invalid_days": return <Notice tone="warn" title="Choose 1 to 30 days." />;
    case "migration": return <Notice tone="warn" title="Database update needed.">
      Run the reviewed migration (version 5) in Neon before extending trials.</Notice>;
    default: return null;
  }
}

type PendingDeletion = { subject: string; issuer: string; requestedAt: number; subscriptionRenews: boolean };

/** What marking a deletion request done found. The URL never names who. */
function DeletionResult({ result }: { result: string | string[] | undefined }) {
  switch (result) {
    case "done": return <Notice tone="info" title="Deletion request marked done." />;
    case "not_found": return <Notice tone="warn" title="That request was not pending.">It may already have been marked done.</Notice>;
    case "migration": return <Notice tone="warn" title="Database update needed.">
      Run the reviewed migration (version 8) in Neon before handling deletion requests.</Notice>;
    default: return null;
  }
}

/** Pending account deletion requests from /account/delete, oldest first. */
function Deletions({ pending }: { pending: PendingDeletion[] | "migration" | "unavailable" }) {
  const now = Math.floor(Date.now() / 1000);
  return <section className="card after" aria-labelledby="deletion-admin-title">
    <h2 id="deletion-admin-title">Account deletion requests</h2>
    <p>Delete the Auth0 user, the Saiph Cloud account with its devices and content, and billing records not needed for tax, within {DELETION_DAYS} days of the request. Then mark it done.</p>
    {pending === "migration" ? <Notice tone="warn" title="Database update needed.">Run the reviewed migration (version 8) in Neon to receive deletion requests.</Notice>
      : pending === "unavailable" ? <Notice tone="warn" title="Requests could not be read just now." />
      : pending.length === 0 ? <p className="fine after">No pending requests.</p>
      : <ul className="subscription-list">
        {pending.map((item) => {
          const due = item.requestedAt + DELETION_DAYS * 86400;
          return <li key={item.subject}>
            <div>
              <strong>{item.subject}</strong>
              <span className="fine"> · {item.issuer} · requested {day(item.requestedAt)} · due {day(due)}{due < now ? " (overdue)" : ""}</span>
              {item.subscriptionRenews && <span className="pill warn">Subscription still renews</span>}
            </div>
            <form method="post" action="/api/admin/deletion">
              <input type="hidden" name="action" value="done" />
              <input type="hidden" name="subject" value={item.subject} />
              <button className="ghost small" type="submit">Mark done</button>
            </form>
          </li>;
        })}
      </ul>}
  </section>;
}

/**
 * Owner-only admin page. Find a person's free trial by the email address they
 * signed in with, and extend it; list account deletion requests and mark them
 * done. Everyone else is sent back to their account.
 */
export default async function Admin({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const auth0 = getAuth0();
  const session = auth0 ? await auth0.getSession() : null;
  if (!auth0 || !session) redirect("/auth/login");
  const config = readBillingConfig(process.env);
  if (!config || !isOwner(config, process.env, session)) redirect("/account");
  const trials = readTrialConfig(process.env);
  const query = await searchParams;
  const pending: PendingDeletion[] | "migration" | "unavailable" = await withBillingStore(config, (store) => store.pendingDeletions())
    .catch((error: { code?: unknown }) => error?.code === "MIGRATION_PENDING" ? "migration" : "unavailable");
  return <>
    <div className="page-head">
      <div>
        <p className="eyebrow">Owner</p>
        <h1>Admin.</h1>
        <p className="lede">Look up or extend a person&apos;s free trial, and handle account deletion requests.{trials ? <> New trials last {trials.days} days.</> : <> Free trials are off.</>}</p>
      </div>
      <SignOut />
    </div>
    <Result query={query} />
    <DeletionResult result={query.deletion} />
    <section className="card" aria-labelledby="trial-admin-title">
      <h2 id="trial-admin-title">Free trial</h2>
      <p>Use the email address the person signs in with. Days are added to the current end, or from today if the trial has ended. A trial can end at most 30 days from now.</p>
      <form className="code-form" method="post" action="/api/admin/trial">
        <label htmlFor="trial-email">Email address</label>
        <div className="code-row">
          <input id="trial-email" name="email" type="email" required autoComplete="off" spellCheck={false} maxLength={320} />
        </div>
        <label htmlFor="trial-days">Days to add</label>
        <div className="code-row">
          <input id="trial-days" name="days" type="number" min={1} max={30} defaultValue={7} inputMode="numeric" />
          <button type="submit" name="action" value="extend">Extend trial</button>
          <button className="ghost" type="submit" name="action" value="lookup" formNoValidate>Look up</button>
        </div>
      </form>
    </section>
    <Deletions pending={pending} />
  </>;
}
