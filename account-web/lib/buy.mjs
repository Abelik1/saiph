// SPDX-License-Identifier: AGPL-3.0-or-later
// The two paths from usesaiph.com (docs/LANDING_CONVERSION.md):
//   Start your free trial: /trial → sign-in (Google or email) → /trial → Stripe card checkout.
//   Buy now: /buy/<plan> → sign-in (Google or email) → back to /buy/<plan> → Stripe Checkout.
// Only these exact return paths (and /account/delete) survive sign-in; anything
// else goes to /account.

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

/** The account deletion page the Android app opens (app/account/delete). */
export const DELETE_PAGE = "/account/delete";

/**
 * Whether a return target is exactly this site's deletion page, with no query.
 * @param {unknown} value @param {string} appBaseUrl
 */
export function isDeleteTarget(value, appBaseUrl) {
  if (typeof value !== "string" || value.length > 200) return false;
  let url;
  try { url = new URL(value, appBaseUrl); } catch { return false; }
  return url.origin === new URL(appBaseUrl).origin && !url.username && !url.password && !url.hash
    && url.pathname === DELETE_PAGE && url.search === "";
}

/**
 * Where a completed sign-in goes: straight back to the chosen plan, marked so
 * the page can count the sign-in once; back to the deletion page, which must
 * not pass through the account overview and its plans; or the account page.
 * @param {unknown} returnTo @param {string} appBaseUrl
 */
export function afterSignIn(returnTo, appBaseUrl) {
  if (isDeleteTarget(returnTo, appBaseUrl)) return new URL(DELETE_PAGE, appBaseUrl);
  const target = parseBuyTarget(returnTo, appBaseUrl);
  if (!target) return new URL("/account", appBaseUrl);
  const url = new URL(target.plan === "trial" ? "/trial" : buyPath(target.plan, target.offer), appBaseUrl);
  url.searchParams.set("signed_in", "1");
  return url;
}
