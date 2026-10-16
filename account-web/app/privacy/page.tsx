// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Metadata } from "next";
import Link from "next/link";
export const metadata: Metadata = { title: "Privacy" };
export default function Privacy() {
  return (
    <div className="prose">
      <p className="eyebrow">Development use only · prepared 11 October 2026</p>
      <h1>Account and billing <span className="gradient-text">privacy.</span></h1>
      <p className="lede">How this owner-only account preview handles your information. Public onboarding and paid Cloud remain closed.</p>
      <section className="prose-section">
        <span className="step-number">01</span>
        <div><h2>Controller and current scope</h2>
      <p>Alexander Belik, operating as Abelik1, Ireland, controls Saiph account administration. This portal is restricted to its configured owner. Public registration and paid Cloud are closed. The working public contact and provider retention/transfer details still need confirmation before public onboarding. See <a href="https://usesaiph.com/contact.html">contact status</a>.</p>
      </div>
      </section>
      <section className="prose-section">
        <span className="step-number">02</span>
        <div><h2>Auth0 and essential cookies</h2>
      <p>Auth0 (Okta) handles sign-in and receives identity/login information, network/device metadata and authentication events. Enabled identity connections, tenant region and log retention must be confirmed. The portal requests the openid, profile and email sign-in scopes, but saves only the authenticated subject in its session user profile to check its owner.</p>
      <p>The secure, HTTP-only, host-only, SameSite Lax session cookie is transient, non-rolling and limited to one hour. Sign-in also uses temporary transaction cookies. Auth0 maintains a separate session on its domain. Local sign-out does not erase provider records. Essential authentication is separate from advertising or marketing consent.</p>
      </div>
      </section>
      <section className="prose-section">
        <span className="step-number">03</span>
        <div><h2>Stripe sandbox and billing records</h2>
      <p>Billing handlers accept test-mode Stripe resources only and are disabled unless configured for owner testing. Enter only Stripe test payment details. Stripe Checkout and its billing portal receive payment/billing details directly; this application does not store full card numbers or security codes.</p>
      <p>The billing database stores the Auth0 subject, Stripe account/customer/subscription/price identifiers, status and billing/cancellation dates, creation/observation times, and minimal event receipts for replay protection. Stripe metadata contains a derived account reference, which remains linked personal data. The billing schema does not store full webhook payloads. Login/payment does not approve devices or grant content keys.</p>
      </div>
      </section>
      <section className="prose-section">
        <span className="step-number">04</span>
        <div><h2>Purposes, bases and recipients</h2>
      <p>The proposed bases are requested account/service and billing administration (contract), required financial records (legal obligations), and necessary security, fraud prevention and reconciliation (assessed legitimate interests). These purposes and assessments must be finalized before public use. Account/billing data is not automatically enrolled in launch emails.</p>
      <p>Auth0 supplies identity services, Vercel hosts the portal, Neon supplies the billing database and Stripe processes billing/payments. Stripe acts as processor for some merchant-directed activities and as independent controller for its own purposes. Authorized administrators, necessary advisers and legally entitled authorities may receive relevant records. Actual regions, subprocessors, contracts and international-transfer safeguards must be verified; an EU region alone is not an EU-only processing guarantee.</p>
      </div>
      </section>
      <section className="prose-section">
        <span className="step-number">05</span>
        <div><h2>Retention and deletion</h2>
      <p>No self-service account deletion or automatic billing purge is implemented. The current database protects customer mappings against deletion; a reviewed maintenance process is required before public use. Deleting an Auth0 user does not automatically remove local, Stripe, support or backup records.</p>
      <p>Proposed targets, pending approval and tested procedures: account/profile data within 30 days after closure, security logs after 30 days and resolved routine correspondence after 12 months. Required Irish business tax records generally need six years; the precise records and retention trigger require confirmation. Provider backup windows, event-replay retention and any narrowly scoped legal holds remain to be settled. Cancellation, refund and erasure are distinct operations.</p>
      </div>
      </section>
      <section className="prose-section">
        <span className="step-number">06</span>
        <div><h2>Your choices and rights</h2>
      <p>Where applicable, request access, correction, erasure, restriction or portability, object to legitimate-interests processing or withdraw optional consent. Requests normally require a response within one month; a lawful extension must be explained within that month. Use the verified controller contact once published. You may complain to the <a href="https://www.dataprotection.ie/en/individuals/exercising-your-rights/complaints-handling-investigations-and-enforcement-individuals">Irish Data Protection Commission</a> or your local supervisory authority.</p>
      <p>No analytics or advertising is included in this portal. It does not receive clipboard, message or file content. Cloud content, metadata, retention and security require a separate verified production description; this draft does not claim production readiness.</p>
      <p>Provider information: <a href="https://auth0.com/docs/secure/data-privacy-and-compliance/data-processing">Auth0</a>, <a href="https://vercel.com/legal/privacy-policy">Vercel</a>, <a href="https://neon.com/privacy-policy">Neon</a> and <a href="https://stripe.com/privacy">Stripe</a>. Read the <a href="https://usesaiph.com/account-privacy.html">full account/privacy preparation notice</a> and <a href="https://usesaiph.com/privacy.html">website notice</a>.</p>
    </div>
      </section>
      <Link className="back-link" href="/">← Back to account home</Link>
    </div>
  );
}
