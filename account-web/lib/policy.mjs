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
/** The default sign-in. Fixing the connection here sends people straight to
 * Google's account chooser instead of the Auth0 login page; the proxy refuses
 * login queries, so callers cannot pick a connection, scope or audience.
 * @param {{audience: string} | null} beta */
export function loginParameters(beta) {
  return {scope: "openid profile email", connection: "google-oauth2", ...(beta ? {audience: beta.audience} : {})};
}
/** Auth0's email-and-password connection: sign up, sign in, email verification
 * and password reset all happen on Auth0's page, so Saiph never sees a password. */
export const EMAIL_CONNECTION = "Username-Password-Authentication";
/** The sign-in method a start route was asked for. "google" with no `with`,
 * "email" for exactly `with=email`; null (refuse) for any other value or any
 * key the route does not read itself.
 * @param {URLSearchParams} query @param {string[]} [own] keys the route reads */
export function signInMethod(query, own = []) {
  const keys = [...query.keys()];
  if (keys.some(key => key !== "with" && !own.includes(key)) || new Set(keys).size !== keys.length) return null;
  const value = query.get("with");
  return value === null ? "google" : value === "email" ? "email" : null;
}
/** Only the connection changes; scope and audience stay those of loginParameters.
 * `prompt=login` always shows the email form, even after a Google sign-in.
 * @param {"google" | "email"} method */
export function methodParameters(method) {
  return method === "email" ? {connection: EMAIL_CONNECTION, prompt: "login"} : {};
}
/** The email start link for a start route path that may already have a query.
 * @param {string} start */
export function emailStart(start) {
  return start + (start.includes("?") ? "&" : "?") + "with=email";
}
export const accountCookieName = "__Host-saiph_account";
/** @param {string} name */
export function isAccountCookie(name) {
  return name === accountCookieName || name.startsWith(accountCookieName + "__") || name.startsWith(accountCookieName + ".");
}
