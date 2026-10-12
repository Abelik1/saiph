// SPDX-License-Identifier: AGPL-3.0-or-later
import Link from "next/link";
import { getAuth0 } from "../lib/auth";
import {readBetaConfig} from "../lib/beta-policy.mjs";
export const dynamic = "force-dynamic";

export default function Home() {
  const configured = Boolean(getAuth0());
  const beta = readBetaConfig(process.env) !== null;
  return (
    <>
      <section className="welcome-grid" aria-labelledby="welcome-title">
        <div className="welcome-copy">
          <p className="eyebrow">
            <span className="status-dot" aria-hidden="true" /> Saiph account
            preview
          </p>
          <h1 id="welcome-title">
            A little closer.
            <br />
            <em>A little more yours.</em>
          </h1>
          <p className="lede">
            {beta ? "Connect your computer and Android phone through Saiph. Your invitation provides beta access without payment or running a server."
              : "One place for your Saiph account and subscription. Built around the same idea as Saiph: keeping you in control."}
          </p>
          <p className="welcome-note">
            {beta ? "Invited to the friends beta? Sign in and enter your invitation code."
              : "This preview is open to the owner while account onboarding is being prepared."}
          </p>
          <div className="welcome-links">
            <a href="https://usesaiph.com">
              Explore Saiph <span aria-hidden="true">↗</span>
            </a>
            <Link href="/privacy">How your account data is used</Link>
            {beta && <Link href="/setup">Beta setup guide</Link>}
          </div>
        </div>
        <section className="card sign-in-card" aria-labelledby="sign-in-title">
          <div className="card-topline">
            <span className="eyebrow">Your account</span>
            <span className="badge">{beta ? "Friends beta" : "Owner access"}</span>
          </div>
          <div className="account-symbol" aria-hidden="true">
            <svg
              viewBox="0 0 40 40"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            >
              <circle cx="20" cy="14" r="6" />
              <path d="M8 32c0-7 5-11 12-11s12 4 12 11" />
            </svg>
          </div>
          <h2 id="sign-in-title">Welcome back.</h2>
          <p>
            {beta ? "Sign in to activate your beta access. No paid subscription is required."
              : "Sign in to view your account and check the progress of your test subscription."}
          </p>
          {configured ? (
            <a className="button full-width" href="/auth/login">
              Sign in with Auth0 <span aria-hidden="true">→</span>
            </a>
          ) : (
            <div className="notice" role="status">
              <strong>Sign-in is being set up</strong>
              <p>
                Account access will be available once configuration is complete.
              </p>
            </div>
          )}
          <p className="fine sign-in-detail">
            {beta ? "Your invitation code activates account access. You will approve your devices after installing the apps."
              : "Only the owner can access this preview. Signing in does not approve a device or activate Hosted."}
          </p>
          <div className="card-footnote">
            <span className="status-dot" aria-hidden="true" /> No live payments
            in this preview
          </div>
        </section>
      </section>
      <section className="next-section" aria-labelledby="separate-steps">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Made clear from the start</p>
            <h2 id="separate-steps">
              Your account is one part of the picture.
            </h2>
          </div>
          <span className="fine">{beta ? "Invited beta access" : "Hosted is a design preview"}</span>
        </div>
        <ol className="step-grid">
          <li>
            <span className="step-number">01</span>
            <h3>Sign in</h3>
            <p>
              Access your account through Auth0. Your session stays separate
              from device pairing.
            </p>
            <span className="step-state">{beta ? "Sign in with your own account" : "Owner preview"}</span>
          </li>
          <li>
            <span className="step-number">02</span>
            <h3>Approve your devices</h3>
            <p>
              Device approval is a separate step. An account session alone
              cannot unlock message content.
            </p>
            <span className="step-state muted-state">Separate approval</span>
          </li>
          <li>
            <span className="step-number">03</span>
            <h3>{beta ? "Activate your invitation" : "Hosted, when it’s ready"}</h3>
            <p>
              {beta ? "Enter your beta code on the account page, then install Saiph on your computer and phone."
                : "Hosted access is still being prepared. Any subscription testing here uses Stripe test mode."}
            </p>
            <span className="step-state muted-state">{beta ? "No payment required" : "Coming later"}</span>
          </li>
        </ol>
      </section>
    </>
  );
}
