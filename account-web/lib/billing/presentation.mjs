// SPDX-License-Identifier: AGPL-3.0-or-later
const labels = {
  incomplete: "Checkout incomplete",
  incomplete_expired: "Checkout expired",
  trialing: "Trial",
  active: "Subscription active",
  past_due: "Payment overdue",
  canceled: "Subscription canceled",
  unpaid: "Payment unpaid",
  paused: "Subscription paused",
};
const testLabels = {
  incomplete: "Checkout incomplete",
  incomplete_expired: "Checkout expired",
  trialing: "Test trial",
  active: "Test subscription active",
  past_due: "Test payment overdue",
  canceled: "Test subscription canceled",
  unpaid: "Test payment unpaid",
  paused: "Test subscription paused",
};

/** Only fixed labels and validated dates leave the server-side billing display.
 * @param {{status: string, currentPeriodEnd: number | null, cancelAtPeriodEnd: boolean}} snapshot
 * @param {{test?: boolean, plan?: "monthly" | "yearly" | null}} [options] sandbox labels by default
 */
export function subscriptionSummary(snapshot, { test = true, plan = null } = {}) {
  const table = test ? testLabels : labels;
  const base = Object.hasOwn(table, snapshot.status)
    ? table[/** @type {keyof typeof table} */ (snapshot.status)]
    : "Status unavailable";
  const label = plan === "monthly" ? base + " (monthly)" : plan === "yearly" ? base + " (yearly)" : base;
  const terminal =
    snapshot.status === "canceled" || snapshot.status === "incomplete_expired";
  const seconds = snapshot.currentPeriodEnd;
  let period = "";
  if (
    !terminal &&
    typeof seconds === "number" &&
    Number.isSafeInteger(seconds) &&
    seconds > 0 &&
    seconds <= 253402300799
  ) {
    const date = new Intl.DateTimeFormat("en-IE", {
      day: "numeric",
      month: "short",
      year: "numeric",
      timeZone: "UTC",
    }).format(new Date(seconds * 1000));
    period = `${snapshot.cancelAtPeriodEnd ? "Scheduled to end" : test ? "Current test period ends" : "Renews"} ${date} (UTC)`;
  }
  return { label, period };
}
