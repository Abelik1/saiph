// SPDX-License-Identifier: AGPL-3.0-or-later
/** @param {Record<string,string|undefined>} env */
export function readBetaConfig(env) {
  if (env.SAIPH_ACCOUNT_MODE !== "friends-beta") return null;
  const origin = env.SAIPH_HOSTED_API_URL;
  const audience = env.SAIPH_HOSTED_API_AUDIENCE;
  try {
    if (!origin || !audience) return null;
    const url = new URL(origin), api = new URL(audience);
    if (url.protocol !== "https:" || url.origin !== origin || url.username || url.password
      || url.port || !url.hostname.includes(".") || url.pathname !== "/" || url.search || url.hash
      || api.protocol !== "https:" || api.username || api.password || api.search || api.hash) return null;
    return {origin, audience};
  } catch { return null; }
}

/** A validated session can reach code entry; this does not grant Hosted access.
 * @param {unknown} subject @param {unknown} owner @param {Record<string,string|undefined>} env */
export function canUseAccount(subject, owner, env) {
  return typeof subject === "string" && /^[\x21-\x7e]{1,256}$/.test(subject)
    && (subject === owner || readBetaConfig(env) !== null);
}
