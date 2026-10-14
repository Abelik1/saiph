// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";
export default function AccountError({ reset }: { reset: () => void }) {
  return (
    <section className="state">
      <p className="eyebrow">Your account</p>
      <h1>We couldn&rsquo;t load your account.</h1>
      <p className="lede" role="alert">
        Account details are temporarily unavailable. Please try again.
      </p>
      <div className="actions">
        <button onClick={() => reset()}>Try again</button>
        <a className="button ghost" href="/">
          Back to account home
        </a>
      </div>
    </section>
  );
}
