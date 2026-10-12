// SPDX-License-Identifier: AGPL-3.0-or-later
export default function Loading() {
  return (
    <section
      className="loading-state"
      aria-busy="true"
      aria-labelledby="loading-title"
    >
      <p className="eyebrow">Account overview</p>
      <h1 id="loading-title">Loading your account.</h1>
      <p className="lede" role="status">
        Checking your session and subscription details…
      </p>
      <div className="status-grid" aria-hidden="true">
        <div className="status-tile skeleton" />
        <div className="status-tile skeleton" />
        <div className="status-tile skeleton" />
      </div>
    </section>
  );
}
