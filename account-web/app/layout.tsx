// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Metadata } from "next";
import Link from "next/link";
import "./site.css";
// Per-request CSP nonces also cover the privacy and not-found pages.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: {
    default: "Saiph account · Development",
    template: "%s · Saiph account",
  },
  description: "Your Saiph account and development beta access.",
  robots: { index: false, follow: false },
};

export default function Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <header className="site-header">
          <Link className="brand" href="/" aria-label="Saiph account home">
            <svg viewBox="0 0 32 32" aria-hidden="true">
              <path
                d="M16 2 20 12 30 16 20 20 16 30 12 20 2 16 12 12Z"
                fill="currentColor"
              />
              <circle cx="16" cy="16" r="3" fill="#0a0e13" />
            </svg>
            Saiph<span className="brand-divider">/</span>
            <span className="brand-section">Account</span>
          </Link>
          <nav aria-label="Main navigation">
            <Link href="/account">Overview</Link>
            <Link href="/privacy">Privacy</Link>
            <span className="badge">Development</span>
          </nav>
        </header>
        <main id="main" tabIndex={-1}>
          {children}
        </main>
        <footer className="site-footer">
          <span>
            Saiph <span aria-hidden="true">·</span> Your devices. Your control.
          </span>
          <div>
            <a href="https://usesaiph.com">
              About Saiph <span aria-hidden="true">↗</span>
            </a>
            <Link href="/privacy">Privacy information</Link>
            <a href="https://usesaiph.com/terms.html">Hosted terms (draft)</a>
            <a href="https://usesaiph.com/refunds.html">Refunds and cancellation (draft)</a>
            <a href="https://usesaiph.com/contact.html">Contact status</a>
          </div>
        </footer>
      </body>
    </html>
  );
}
