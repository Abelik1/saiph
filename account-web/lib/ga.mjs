// SPDX-License-Identifier: AGPL-3.0-or-later
// Google Analytics 4 for the buy funnel (website/ANALYTICS.md). Off unless the
// owner sets GA4_MEASUREMENT_ID (and, for server-side events, GA4_API_SECRET).
// Only visitors who pressed Accept on usesaiph.com are measured: that choice is
// the saiph_consent cookie on usesaiph.com, and the GA client ID is the _ga
// cookie the website's tag set there. The account site never asks again.
// No email, account, Stripe or session identifier is ever sent to Google.

const SIX_MONTHS = 182 * 86400;
const MEASUREMENT_ID = /^G-[A-Z0-9]{4,16}$/;
const API_SECRET = /^[A-Za-z0-9_-]{8,64}$/;
// GA's own client ID format: two dot-separated numbers.
const CLIENT_ID = /^[0-9]{1,12}\.[0-9]{9,11}$/;

/** @param {Record<string, string | undefined>} env */
export function readGaConfig(env) {
  const measurementId = env.GA4_MEASUREMENT_ID?.trim() ?? "";
  if (!MEASUREMENT_ID.test(measurementId)) return null;
  const apiSecret = env.GA4_API_SECRET?.trim() ?? "";
  return { measurementId, apiSecret: API_SECRET.test(apiSecret) ? apiSecret : null };
}

/** @param {string | null | undefined} header @param {string} name */
function cookie(header, name) {
  for (const part of (header ?? "").split(";")) {
    const index = part.indexOf("=");
    if (index > 0 && part.slice(0, index).trim() === name) return part.slice(index + 1).trim();
  }
  return null;
}

/**
 * The visitor's analytics choice and GA client ID, from the request cookies.
 * Granted only for an explicit Accept within the last six months.
 * @param {string | null | undefined} cookieHeader @param {number} [now] seconds
 * @returns {{granted: boolean, clientId: string | null}}
 */
export function readConsent(cookieHeader, now = Math.floor(Date.now() / 1000)) {
  const choice = /^v1\.(granted|denied)\.(\d{10})$/.exec(cookie(cookieHeader, "saiph_consent") ?? "");
  const granted = choice !== null && choice[1] === "granted" && now - Number(choice[2]) < SIX_MONTHS && Number(choice[2]) <= now + 300;
  if (!granted) return { granted: false, clientId: null };
  const ga = /^GA1\.[0-9]\.([0-9]{1,12}\.[0-9]{9,11})$/.exec(cookie(cookieHeader, "_ga") ?? "");
  return { granted: true, clientId: ga ? ga[1] : null };
}

/** @param {unknown} value */
export function validClientId(value) {
  return typeof value === "string" && CLIENT_ID.test(value);
}

const EVENTS = new Set(["begin_checkout", "purchase", "trial_start"]);
const PARAMS = new Set(["plan", "price_test", "price_variant", "value", "currency", "transaction_id"]);

/**
 * A Measurement Protocol body with a fixed event list and parameter list.
 * Advertising signals are always denied.
 * @param {string} clientId @param {string} name @param {Record<string, string | number>} params
 */
export function measurementBody(clientId, name, params) {
  if (!validClientId(clientId) || !EVENTS.has(name)) throw new Error("Analytics event rejected");
  /** @type {Record<string, string | number>} */
  const clean = { engagement_time_msec: 1 };
  for (const [key, value] of Object.entries(params)) {
    if (!PARAMS.has(key) || value === undefined || value === null || value === "") continue;
    if (typeof value === "number" ? !Number.isFinite(value) : typeof value !== "string" || !/^[A-Za-z0-9._-]{1,64}$/.test(value)) {
      throw new Error("Analytics event rejected");
    }
    clean[key] = value;
  }
  return { client_id: clientId, non_personalized_ads: true,
    consent: { ad_user_data: "DENIED", ad_personalization: "DENIED" }, events: [{ name, params: clean }] };
}

/**
 * Send one event to Google's EU endpoint. Analytics never blocks or fails a
 * checkout or webhook: errors and slow answers are ignored.
 * @param {{measurementId: string, apiSecret: string | null} | null} config
 * @param {string | null} clientId @param {string} name @param {Record<string, string | number>} params
 * @param {typeof fetch} [fetchImpl]
 */
export async function sendEvent(config, clientId, name, params, fetchImpl = fetch) {
  if (!config?.apiSecret || !validClientId(clientId)) return false;
  try {
    const body = measurementBody(/** @type {string} */ (clientId), name, params);
    const url = "https://region1.google-analytics.com/mp/collect?measurement_id=" + encodeURIComponent(config.measurementId)
      + "&api_secret=" + encodeURIComponent(config.apiSecret);
    const response = await fetchImpl(url, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body), signal: AbortSignal.timeout(2000), redirect: "error" });
    return response.ok;
  } catch {
    return false;
  }
}
