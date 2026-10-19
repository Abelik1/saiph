// SPDX-License-Identifier: AGPL-3.0-or-later
// The two paths from usesaiph.com (docs/LANDING_CONVERSION.md):
//   Start your free trial: /trial → Google sign-in → back to /trial → trial starts.
//   Buy now: /buy/<plan> → Google sign-in → back to /buy/<plan> → Stripe Checkout.
// Only these exact return paths survive sign-in; anything else goes to /account.

export const BUY_PLANS = /** @type {const} */ (["monthly", "yearly"]);
const OFFER = /^[a-d]$/;

/** @param {unknown} plan @returns {plan is "monthly"|"yearly"} */
export function isPlan(plan) {
  return plan === "monthly" || plan === "yearly";
}

/** @param {unknown} offer @returns {string | null} */
export function offerValue(offer) {
  return typeof offer === "string" && OFFER.test(offer) ? offer : null;
}

/** "/buy/monthly" or "/buy/yearly?offer=b". @param {"monthly"|"yearly"} plan @param {string | null} offer */
export function buyPath(plan, offer) {
  return "/buy/" + plan + (offer ? "?offer=" + offer : "");
}

/**
 * Parse a return target, accepting only this site's /trial (no query) or
 * /buy/<plan> with at most an offer query. Absolute URLs must be this origin.
 * @param {unknown} value @param {string} appBaseUrl
 * @returns {{plan: "monthly"|"yearly"|"trial", offer: string | null} | null}
 */
export function parseBuyTarget(value, appBaseUrl) {
  if (typeof value !== "string" || value.length > 200) return null;
  let url;
  try { url = new URL(value, appBaseUrl); } catch { return null; }
  if (url.origin !== new URL(appBaseUrl).origin || url.username || url.password || url.hash) return null;
  if (url.pathname === "/trial") return url.search === "" ? { plan: "trial", offer: null } : null;
  const match = /^\/buy\/(monthly|yearly)$/.exec(url.pathname);
  if (!match) return null;
  const keys = [...url.searchParams.keys()];
  if (keys.some((key) => key !== "offer") || keys.length > 1) return null;
  const offer = url.searchParams.get("offer");
  if (offer !== null && !OFFER.test(offer)) return null;
  return { plan: /** @type {"monthly"|"yearly"} */ (match[1]), offer };
}

/**
 * Where a completed sign-in goes: straight back to the chosen plan, marked so
 * the page can count the sign-in once, or the account page as before.
 * @param {unknown} returnTo @param {string} appBaseUrl
 */
export function afterSignIn(returnTo, appBaseUrl) {
  const target = parseBuyTarget(returnTo, appBaseUrl);
  if (!target) return new URL("/account", appBaseUrl);
  const url = new URL(target.plan === "trial" ? "/trial" : buyPath(target.plan, target.offer), appBaseUrl);
  url.searchParams.set("signed_in", "1");
  return url;
}
