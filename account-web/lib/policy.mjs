// SPDX-License-Identifier: AGPL-3.0-or-later
/** @param {Record<string, string | undefined>} env */
export function readAuthConfig(env) {
  const required = ["AUTH0_DOMAIN", "AUTH0_CLIENT_ID", "AUTH0_CLIENT_SECRET", "AUTH0_SECRET", "APP_BASE_URL", "SAIPH_OWNER_SUBJECT"];
  const missing = required.filter((name) => !env[name]?.trim());
  if (missing.length) return {ok: false, reason: "missing configuration"};
  const {AUTH0_DOMAIN: domain, AUTH0_CLIENT_ID: clientId, AUTH0_CLIENT_SECRET: clientSecret,
    AUTH0_SECRET: secret, APP_BASE_URL: appBaseUrl, SAIPH_OWNER_SUBJECT: ownerSubject} = env;
  if (!domain || !/^[a-z0-9-]+(?:\.[a-z0-9-]+)*\.auth0\.com$/.test(domain)
      || !secret || !/^[a-fA-F0-9]{64}$/.test(secret)
      || !clientId || !/^[a-zA-Z0-9_-]+$/.test(clientId)
      || !clientSecret || !ownerSubject || !appBaseUrl) return {ok: false, reason: "invalid configuration"};
  try {
    const url = new URL(appBaseUrl);
    if (url.protocol !== "https:" || url.username || url.password
        || url.pathname !== "/" || url.search || url.hash || url.origin !== appBaseUrl
        || (url.port || !url.hostname.includes("."))) {
      return {ok: false, reason: "invalid configuration"};
    }
  } catch { return {ok: false, reason: "invalid configuration"}; }
  return {ok: true, domain, clientId, clientSecret, secret, appBaseUrl, ownerSubject};
}
/** Subject is read from a validated server session, never a browser request.
 * @param {unknown} subject @param {unknown} ownerSubject */
export function isOwner(subject, ownerSubject) {
  return typeof subject === "string" && typeof ownerSubject === "string"
    && ownerSubject.length > 0 && subject === ownerSubject;
}
export const accountCookieName = "__Host-saiph_account";
/** @param {string} name */
export function isAccountCookie(name) {
  return name === accountCookieName || name.startsWith(accountCookieName + "__") || name.startsWith(accountCookieName + ".");
}
