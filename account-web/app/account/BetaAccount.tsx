// SPDX-License-Identifier: AGPL-3.0-or-later
import {hostedAccess} from "../../lib/beta";
import type {BillingView} from "../../lib/billing/view";
import {CheckoutNotice, SignOut} from "./parts";
import SubscriptionCard from "./SubscriptionCard";
import Link from "next/link";
import {Icon, type IconName} from "../ui";

type Access = {entitled: boolean; until: number | null; kinds: ("admin" | "beta" | "paid" | "trial")[] | null};
type Props = {billing: BillingView | "unavailable" | null; notice: "returned" | "cancelled" | "trial" | null};

export default async function BetaAccount(props: Props) {
  const access = await hostedAccess().catch(() => null);
  return <BetaAccountView access={access} {...props} />;
}

const installers: [string, string, string, IconName][] = [
  ["windows", "Windows", "Installer for Windows 10 and 11", "windows"],
  ["linux", "Linux", "Desktop app for Linux", "linux"],
  ["android", "Android", "APK for Android phones", "android"],
];
const extras: [string, string][] = [
  ["desktop_source", "Desktop source"], ["android_source", "Android source"], ["notices", "Licences and notices"],
  ["qt_sources_windows", "Qt and PySide sources (Windows)"], ["qt_sources_linux", "Qt and PySide sources (Linux)"], ["checksums", "Checksums"],
];
const day = (seconds: number) => new Intl.DateTimeFormat("en-IE", {day: "numeric", month: "long", year: "numeric", timeZone: "UTC"})
  .format(new Date(seconds * 1000));

export function BetaAccountView({access, billing, notice}: Props & {access: Access | null}) {
  const paid = access?.kinds?.includes("paid") ?? false;
  const trial = !paid && (access?.kinds?.includes("trial") ?? false) && !(access?.kinds?.includes("beta") ?? false);
  const source = access?.kinds == null ? null : paid && access.kinds.length > 1 ? "Subscription and invitation"
    : paid ? "Subscription" : trial ? "Free trial" : "Beta invitation";
  const offerTrial = billing !== null && billing !== "unavailable" && billing.trial.state === "available";
  const firebase = process.env.SAIPH_ANDROID_BETA_URL;
  return <>
    <div className="page-head">
      <div>
        <p className="eyebrow">Your Saiph account</p>
        <h1>{access?.entitled ? (paid || trial ? "Welcome to Saiph Cloud." : "Welcome to the beta.") : billing ? "Get Saiph Cloud." : "Activate your beta access."}</h1>
        <p className="lede">Use this same account on your computer and phone.{access?.entitled ? "" : billing ? (offerTrial ? " Start your free trial, subscribe, or enter an invitation code." : " Subscribe, or enter an invitation code.") : " Your invitation gives you access without a subscription."}</p>
      </div>
      <SignOut />
    </div>
    {billing && <CheckoutNotice notice={notice} />}
    {access === null && <div className="notice warn" role="status"><Icon name="info" />
      <div><strong>Access status is temporarily unavailable.</strong><p>Try again shortly.</p></div></div>}
    {access?.entitled ? <>
      <div className="split">
        <section className="card featured string-edge" aria-labelledby="beta-access-title">
          <div className="card-head">
            <div><p className="eyebrow">Saiph Cloud</p><h2 id="beta-access-title">Cloud access active</h2></div>
            <span className="pill good">Active</span>
          </div>
          <dl className="facts">
            <div><dt>Active until</dt><dd>{day(access.until!)}</dd></div>
            {source && <div><dt>Through</dt><dd>{source}</dd></div>}
          </dl>
          {!paid && !trial && <p className="fine after">Beta access needs no payment.</p>}
        </section>
        <NextSteps />
      </div>
      <section className="card after" aria-labelledby="downloads-title">
        <h2 id="downloads-title">Download Saiph</h2>
        <p>Install the beta builds from here: they already include the connection settings. These are development builds.</p>
        <div className="downloads">
          {installers.map(([value, label, detail, icon]) =>
            <form key={value} method="post" action="/api/beta/download">
              <input type="hidden" name="artifact" value={value} />
              <button className="download" type="submit"><Icon name={icon} />{label}<span>{detail}</span></button>
            </form>)}
        </div>
        {firebase && /^https:\/\/appdistribution\.firebase\.dev\/i\/[A-Za-z0-9]{8,64}$/.test(firebase)
          && <p className="fine after">Prefer automatic updates on Android? <a href={firebase} rel="noreferrer">Join the Android beta in Firebase</a>.</p>}
        <div className="card-foot"><Icon name="info" /><span>Windows installers don&rsquo;t have a trusted publisher signature yet. Check the checksum before installing.</span></div>
        <details className="more">
          <summary>Source code, licences and checksums</summary>
          <div className="link-list">
            {extras.map(([value, label]) => <form key={value} method="post" action="/api/beta/download">
              <input type="hidden" name="artifact" value={value} /><button className="ghost small" type="submit">{label}</button>
            </form>)}
          </div>
        </details>
      </section>
    </> : <div className="split">
      <section className="card featured" aria-labelledby="beta-code-title">
        <div className="card-head">
          <div><p className="eyebrow">Beta access</p><h2 id="beta-code-title">Enter your invitation code</h2></div>
          <span className="pill">Not active</span>
        </div>
        <p>Your invitation contains a code that starts with SAIPH-. It activates Cloud access for this account; no payment is needed.</p>
        <form className="code-form" method="post" action="/api/beta/redeem">
          <label htmlFor="beta-code">Invitation code</label>
          <div className="code-row">
            <input id="beta-code" name="code" type="password" required autoComplete="off" spellCheck={false} placeholder="SAIPH-…"
              minLength={38} maxLength={38} pattern="SAIPH-[A-Za-z0-9_\-]{32}" aria-describedby="beta-code-help" />
            <button type="submit">Activate beta access</button>
          </div>
          <p id="beta-code-help" className="fine">Use it with your own account.</p>
        </form>
      </section>
      <NextSteps />
    </div>}
    {billing && <div className="after"><SubscriptionCard view={billing} /></div>}
  </>;
}

function NextSteps() {
  return <aside className="card" aria-labelledby="next-title">
    <h2 id="next-title">Setting up</h2>
    <ul className="aside-list">
      <li><Icon name="devices" /><span>You need a Windows or Linux computer and an Android phone.</span></li>
      <li><Icon name="key" /><span>Sign in with this account on both, then approve the phone from your computer.</span></li>
      <li><Icon name="lock" /><span>Signing in never approves a device or unlocks encrypted content.</span></li>
    </ul>
    <div className="actions"><Link className="button secondary block" href="/setup"><Icon name="book" />Open the setup guide</Link></div>
  </aside>;
}
