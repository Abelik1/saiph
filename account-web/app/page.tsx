// SPDX-License-Identifier: AGPL-3.0-or-later
import Link from "next/link";
import { getAuth0 } from "../lib/auth";
import {readBetaConfig} from "../lib/beta-policy.mjs";
import { GoogleMark, Icon, Mark, Notice, Strings } from "./ui";
export const dynamic = "force-dynamic";

export default function Home() {
  const configured = Boolean(getAuth0());
  const beta = readBetaConfig(process.env) !== null;
  return (
    <>
      <section className="hero" aria-labelledby="welcome-title">
        <div className="hero-copy">
          <p className="eyebrow">{beta ? "Saiph beta access" : "Saiph account preview"}</p>
          <h1 id="welcome-title">
            Your devices,
            <br />
            <span className="gradient-text">working together.</span>
          </h1>
          <p className="lede">
            {beta ? "Sign in to activate your beta access, download the apps and connect your computer and Android phone. Saiph hosts the connection, so there is no server to run."
              : "One place for your Saiph account and Hosted subscription, built around the same idea as Saiph: you stay in control."}
          </p>
          <div className="hero-links">
            <a href="https://usesaiph.com">What is Saiph? <Icon name="external" /></a>
            {beta && <Link href="/setup">Read the setup guide</Link>}
            <Link href="/privacy">How your account data is used</Link>
          </div>
        </div>
        <section className="card sign-in featured string-edge" aria-labelledby="sign-in-title">
          <Mark id="sign-in" size={44} />
          <h2 id="sign-in-title">Sign in</h2>
          <p>
            {beta ? "Have an invitation code? Sign in first, then enter it on your account page. No payment is needed for beta access."
              : "Sign in to view your account and your test subscription. This preview is open to its owner only."}
          </p>
          {configured ? (
            <a className="google-button" href="/auth/login">
              <GoogleMark /> Continue with Google
            </a>
          ) : (
            <Notice tone="neutral" title="Sign-in is being set up">
              Account access opens once configuration is complete.
            </Notice>
          )}
          <p className="fine">
            Signing in never approves a device or unlocks your content. You approve each device yourself, on your own computer.
          </p>
        </section>
        <Strings />
      </section>
      <section aria-labelledby="how-title">
        <div className="section-title">
          <h2 id="how-title">How it works</h2>
          <span className="fine">{beta ? "Invite-only beta" : "Hosted is a design preview"}</span>
        </div>
        <ol className="steps">
          <li>
            <h3>Sign in</h3>
            <p>Use your own account. Your session stays separate from device pairing.</p>
          </li>
          <li>
            <h3>{beta ? "Activate beta access" : "Choose a plan"}</h3>
            <p>
              {beta ? "Enter your invitation code on your account page. It gives you access without a subscription."
                : "Hosted access is still being prepared. Any subscription here uses Stripe test mode."}
            </p>
          </li>
          <li>
            <h3>Connect your devices</h3>
            <p>Install Saiph on your computer and phone, then approve the phone from your computer. Content stays end-to-end encrypted.</p>
          </li>
        </ol>
      </section>
    </>
  );
}
