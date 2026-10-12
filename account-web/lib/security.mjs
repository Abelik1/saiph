// SPDX-License-Identifier: AGPL-3.0-or-later
/** @param {string} nonce @param {boolean} development */
export function contentSecurityPolicy(nonce, development = false) {
  if (!/^[A-Za-z0-9+/]{22,64}={0,2}$/.test(nonce)) throw new Error("Invalid CSP nonce");
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${development ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:", "font-src 'self'", "connect-src 'self'",
    "object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'",
    // Auth0 and download redirects are top-level navigation, not embedded content.
    // Avoid form-action: hosted Checkout/download POSTs legitimately redirect off-site.
    ...(development ? [] : ["upgrade-insecure-requests"]),
  ].join("; ");
}

/** Only the configured account origin can serve sessions. Never forward callback
 * codes, state, cookies or POST bodies from an alias to the canonical hostname.
 * @param {URL} requested @param {string} canonical @param {string} method
 * @param {string} requestedHost */
export function canonicalDestination(requested, canonical, method, requestedHost = requested.host) {
  const target = new URL(canonical);
  if (requestedHost === target.host) return null;
  if (method !== "GET" && method !== "HEAD") return {status: 421, location: null};
  target.pathname = requested.pathname.startsWith("/auth/") ? "/auth/login" : requested.pathname;
  target.search = requested.pathname.startsWith("/auth/") ? "" : requested.search;
  return {status: 308, location: target.href};
}

/** Keep browser POST Origin checks usable on account forms without sending
 * referrers across origins. Auth routes and API redirects suppress them entirely.
 * @param {string} path */
export function responseReferrerPolicy(path) {
  return path === "/account" || path.startsWith("/account/") ? "same-origin" : "no-referrer";
}
