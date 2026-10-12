// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";
export default function AccountError({ reset }: { reset: () => void }) {
  return (
    <section className="error-state">
      <p className="eyebrow">Account overview</p>
      <h1>
        We couldn’t load
        <br />
        <em>your account.</em>
      </h1>
      <p className="lede" role="alert">
        Account details are temporarily unavailable. Please try again.
      </p>
      <div className="actions">
        <button onClick={() => reset()}>Try again</button>
        <a className="button secondary" href="/">
          Back to account home
        </a>
      </div>
    </section>
  );
}
