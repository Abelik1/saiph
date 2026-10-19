// SPDX-License-Identifier: AGPL-3.0-or-later
import type {TrialView} from "../../lib/billing/view";
import {CARRY_MIN_SECONDS} from "../../lib/billing/trial.mjs";
import {Icon} from "../ui";

const day = (seconds: number) => new Intl.DateTimeFormat("en-IE", {day: "numeric", month: "long", year: "numeric", timeZone: "UTC"})
  .format(new Date(seconds * 1000));
const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;
const refusals = {
  used: ["A free trial was already used", "This email address has already had a free trial. Subscribe below to use Saiph Cloud."],
  full: ["Free trial places are taken", "All free trial places have been taken for now. You can still subscribe below."],
  sign_in_again: ["Check your free trial", "Sign out and sign in again to see whether you can start a free trial."],
};

/** Free trial offer and countdown, from the stored trial row only (lib/billing/trial.mjs). */
export default function TrialCard({trial, now = Math.floor(Date.now() / 1000)}: {trial: TrialView; now?: number}) {
  if (trial.state === "off" || trial.state === "subscribed") return null;
  if (trial.state === "active" && trial.endsAt !== null) {
    const carried = trial.endsAt >= now + CARRY_MIN_SECONDS;
    return <section className="card featured" aria-labelledby="trial-title">
      <div className="card-head">
        <div><p className="eyebrow">Free trial</p><h2 id="trial-title">{plural(trial.daysLeft ?? 0, "day")} left</h2></div>
        <span className="pill good">Trial active</span>
      </div>
      <p>Your free trial of Saiph Cloud ends on {day(trial.endsAt)} (UTC).
        {carried ? " Subscribe any time below: you will not be charged until your trial ends." : " Subscribe below to keep Cloud running after it ends."}</p>
      <p className="fine">When the trial ends, Cloud pauses until you subscribe. Your account, approved devices and encrypted data are kept.</p>
    </section>;
  }
  if (trial.state === "ended" && trial.endsAt !== null) return <section className="card featured" aria-labelledby="trial-title">
    <div className="card-head">
      <div><p className="eyebrow">Free trial</p><h2 id="trial-title">Your free trial has ended</h2></div>
      <span className="pill warn">Subscribe to continue</span>
    </div>
    <p>Your trial ended on {day(trial.endsAt)} (UTC). Saiph Cloud is paused for this account until you subscribe below.</p>
    <p className="fine">Nothing was deleted: your account, approved devices and encrypted data are kept, and your devices reconnect once you subscribe.</p>
  </section>;
  if (trial.state === "available") return <section className="card featured string-edge" aria-labelledby="trial-title">
    <div className="card-head">
      <div><p className="eyebrow">Free trial</p><h2 id="trial-title">Try Saiph Cloud free for {plural(trial.days, "day")}</h2></div>
      <span className="pill info plain">No card needed</span>
    </div>
    <p>Connect your computer and phone through Saiph Cloud straight away. When the trial ends, Cloud pauses until you subscribe; nothing is deleted and nothing is charged automatically.</p>
    <form method="post" action="/api/billing/trial">
      <input type="hidden" name="trial" value="start" />
      <button className="block" type="submit">Start free trial</button>
    </form>
    <p className="fine after">One free trial per person. By starting it you agree to the <a href="https://usesaiph.com/terms.html">Cloud terms</a>.</p>
  </section>;
  if (trial.state !== "used" && trial.state !== "full" && trial.state !== "sign_in_again") return null;
  const [title, body] = refusals[trial.state];
  return <section className="card" aria-labelledby="trial-title">
    <p className="eyebrow">Free trial</p>
    <h2 id="trial-title">{title}</h2>
    <p>{body}</p>
    {trial.state === "sign_in_again" && <div className="actions"><a className="button ghost small" href="/auth/logout"><Icon name="key" />Sign out</a></div>}
  </section>;
}
