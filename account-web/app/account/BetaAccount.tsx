// SPDX-License-Identifier: AGPL-3.0-or-later
import {hostedAccess} from "../../lib/beta";
import type {BillingView} from "../../lib/billing/view";
import SubscriptionCard from "./SubscriptionCard";
import Link from "next/link";
export default async function BetaAccount({billing, notice}: {billing: BillingView | "unavailable" | null; notice: "returned" | "cancelled" | null}) {
  const access = await hostedAccess().catch(() => null);
  const paid = access?.kinds?.includes("paid") ?? false;
  const source = access?.kinds == null ? "" : paid && access.kinds.length > 1 ? " through your subscription and invitation"
    : paid ? " through your subscription" : " through your beta invitation";
  return <>
    <p className="eyebrow">Your Saiph account</p>
    <h1>{access?.entitled ? (paid ? "Welcome to Saiph Hosted." : "Welcome to the beta.") : billing ? "Get Saiph Hosted." : "Join the friends beta."}</h1>
    <p className="lede">Use the same account on your computer and phone.{billing ? " Subscribe below, or enter a beta invitation code." : " Your beta invitation provides access without a paid subscription."}</p>
    {access?.entitled ? <section className="card" aria-labelledby="beta-access-title">
      <h2 id="beta-access-title">Hosted access active</h2>
      <p>Access is active{source} until {new Date(access.until! * 1000).toISOString().slice(0,10)}.{paid ? "" : " No payment is required."}</p>
      <p>Install the apps below. Turn on Hosted, sign in on both devices, then approve your phone from your computer.</p>
      <p><Link className="button" href="/setup">Follow the setup guide</Link></p>
      <p>Windows installers currently have no trusted publisher signature. These are development beta builds.</p>
      <div className="beta-form">
        {[["windows","Download for Windows"],["linux","Download for Linux"],["android","Download Android APK"],
          ["desktop_source","Desktop source"],["android_source","Android source"],["notices","Licences and notices"],
          ["qt_sources_windows","Windows Qt and PySide sources"],["qt_sources_linux","Linux Qt and PySide sources"],["checksums","Checksums"]].map(([value,label]) =>
          <form key={value} method="post" action="/api/beta/download">
            <input type="hidden" name="artifact" value={value} /><button type="submit">{label}</button>
          </form>)}
      </div>
      {process.env.SAIPH_ANDROID_BETA_URL && /^https:\/\/appdistribution\.firebase\.dev\/i\/[A-Za-z0-9]{8,64}$/.test(process.env.SAIPH_ANDROID_BETA_URL)
        && <p><a href={process.env.SAIPH_ANDROID_BETA_URL} rel="noreferrer">Join the Android beta in Firebase</a></p>}
      <p>Signing in does not approve a device or unlock encrypted content.</p>
    </section> : <section className="card" aria-labelledby="beta-code-title">
      <h2 id="beta-code-title">Enter your invitation code</h2>
      <p><Link href="/setup">What you will need and how setup works</Link></p>
      {access === null && <p role="status">Access status is temporarily unavailable. Try again shortly.</p>}
      <form className="beta-form" method="post" action="/api/beta/redeem">
        <label htmlFor="beta-code">Beta code</label>
        <input id="beta-code" name="code" type="password" required autoComplete="off" spellCheck={false}
          minLength={38} maxLength={38} pattern="SAIPH-[A-Za-z0-9_\-]{32}" aria-describedby="beta-code-help" />
        <p id="beta-code-help" className="fine">Your invitation contains a code starting with SAIPH-. Use it with your own account.</p>
        <button type="submit">Activate beta access</button>
      </form>
    </section>}
    {billing && <SubscriptionCard view={billing} notice={notice} />}
    <p><a className="button secondary" href="/auth/logout">Sign out</a></p>
  </>;
}
