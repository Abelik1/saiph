// SPDX-License-Identifier: AGPL-3.0-or-later
const labels = {
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
 */
export function subscriptionSummary(snapshot) {
  const label = Object.hasOwn(labels, snapshot.status)
    ? labels[/** @type {keyof typeof labels} */ (snapshot.status)]
    : "Status unavailable";
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
    period = `${snapshot.cancelAtPeriodEnd ? "Scheduled to end" : "Current test period ends"} ${date} (UTC)`;
  }
  return { label, period };
}
