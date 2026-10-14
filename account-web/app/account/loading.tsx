// SPDX-License-Identifier: AGPL-3.0-or-later
export default function Loading() {
  return (
    <section className="state" aria-busy="true" aria-labelledby="loading-title">
      <svg className="loader" viewBox="0 0 120 30" aria-hidden="true">
        <path d="M2 15Q31 3 60 15T118 15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        <path d="M2 15Q31 25 60 15T118 15" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
      </svg>
      <h1 id="loading-title">Loading your account.</h1>
      <p className="lede" role="status">
        Checking your session and subscription details…
      </p>
    </section>
  );
}
