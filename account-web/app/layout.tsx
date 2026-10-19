// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Metadata } from "next";
import Link from "next/link";
import { readBetaConfig } from "../lib/beta-policy.mjs";
import { readBillingConfig } from "../lib/billing/policy";
import { Mark } from "./ui";
import "./site.css";
// Per-request CSP nonces also cover the privacy and not-found pages.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: {
    default: "Saiph account",
    template: "%s · Saiph account",
  },
  description: "Your Saiph account, beta access and Cloud subscription.",
  robots: { index: false, follow: false },
};

export default function Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const beta = readBetaConfig(process.env) !== null;
  // Live payments: no "Development" badge on the page people pay from.
  const live = readBillingConfig(process.env)?.livemode === true;
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <header className="site-header">
          <div>
            <Link className="brand" href="/" aria-label="Saiph account home">
              <Mark id="brand" />
              Saiph <span className="brand-section">Account</span>
            </Link>
            <nav className="site-nav" aria-label="Main navigation">
              <Link href="/account">Account</Link>
              {beta && <Link href="/setup">Setup<span className="hide-sm">&nbsp;guide</span></Link>}
              <Link className="hide-sm" href="/privacy">Privacy</Link>
              {!live && <span className="pill warn" title="Development site: no real payments"><span>Dev<span className="hide-sm">elopment</span></span></span>}
            </nav>
          </div>
        </header>
        <main id="main" tabIndex={-1}>
          {children}
        </main>
        <footer className="site-footer">
          <div>
            <span>Saiph · Your devices. Your control.</span>
            <nav aria-label="Footer">
              <a href="https://usesaiph.com">usesaiph.com</a>
              <Link href="/privacy">Privacy</Link>
              <a href="https://usesaiph.com/terms.html">{live ? "Cloud terms" : "Cloud terms (draft)"}</a>
              <a href="https://usesaiph.com/refunds.html">{live ? "Refunds" : "Refunds (draft)"}</a>
              <a href="https://usesaiph.com/contact.html">Contact</a>
              <a href="https://usesaiph.com/privacy.html#cookies">Cookie settings</a>
            </nav>
          </div>
        </footer>
      </body>
    </html>
  );
}
