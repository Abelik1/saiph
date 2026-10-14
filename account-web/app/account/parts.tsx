// SPDX-License-Identifier: AGPL-3.0-or-later
import {Notice} from "../ui";

/** Feedback after Stripe Checkout. Wording only: access comes from the signed webhook alone. */
export function CheckoutNotice({notice}: {notice: "returned" | "cancelled" | null}) {
  if (notice === "returned") return <Notice title="Thanks. Stripe is confirming your payment.">
    Access appears here once Stripe confirms it, usually within a minute. <a href="/account">Reload to check</a>.
  </Notice>;
  if (notice === "cancelled") return <Notice tone="neutral" title="Checkout was closed.">
    Nothing was charged. You can subscribe whenever you like.
  </Notice>;
  return null;
}

export function SignOut() {
  return <a className="button ghost small" href="/auth/logout">Sign out</a>;
}
