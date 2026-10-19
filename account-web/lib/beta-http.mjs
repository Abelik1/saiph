// SPDX-License-Identifier: AGPL-3.0-or-later
import {readBetaConfig} from "./beta-policy.mjs";
/** @typedef {{entitled:boolean,until:number|null}} BetaAccess */
/** @param {unknown} value @returns {BetaAccess} */
export function checkedAccess(value) {
  if (!value || typeof value !== "object" || !("entitled" in value) || !("until" in value)
    || Object.keys(value).sort().join(",") !== "entitled,until"
    || typeof value.entitled !== "boolean"
    || (value.until !== null && (!Number.isSafeInteger(value.until) || Number(value.until) <= 0))
    || (value.entitled !== (value.until !== null))) throw new Error("Access response rejected");
  return /** @type {BetaAccess} */ (value);
}

/** @typedef {BetaAccess & {kinds: ("admin"|"beta"|"paid"|"trial")[], trialUntil: number | null}} HostedAccess */
/** /v1/billing/access: the same consistency rules plus which grant kinds apply.
 * A service with free trials adds `trial_until` for accounts that had one.
 * @param {unknown} value @returns {HostedAccess} */
export function checkedHostedAccess(value) {
  const keys = value && typeof value === "object" ? Object.keys(value).sort().join(",") : "";
  if (!value || typeof value !== "object" || !("kinds" in value) || !Array.isArray(value.kinds)
    || (keys !== "entitled,kinds,until" && keys !== "entitled,kinds,trial_until,until")
    || value.kinds.some((kind) => !["admin", "beta", "paid", "trial"].includes(kind))
    || new Set(value.kinds).size !== value.kinds.length
    || (value.kinds.length > 0) !== ("entitled" in value && value.entitled === true)) throw new Error("Access response rejected");
  const {kinds, trial_until: trialUntil = null, ...access} =
    /** @type {{kinds: ("admin"|"beta"|"paid"|"trial")[], trial_until?: unknown, entitled: unknown, until: unknown}} */ (value);
  if (trialUntil !== null && (!Number.isSafeInteger(trialUntil) || Number(trialUntil) <= 0)) throw new Error("Access response rejected");
  return {...checkedAccess(access), kinds, trialUntil: /** @type {number | null} */ (trialUntil)};
}

/** Browser input supplies only a code. Identity comes from the SDK session/token.
 * @param {Request} request
 * @param {{env:Record<string,string|undefined>,getSession:()=>Promise<{user:{sub?:string}}|null>,
 * call:(path:string,code?:string)=>Promise<BetaAccess>}} deps */
export async function redeemBeta(request, deps) {
  const headers = {"Cache-Control":"private, no-store", "Referrer-Policy":"no-referrer"};
  /** @param {number} status @param {string} message */
  const reply = (status, message) => new Response(message, {status, headers});
  const config = readBetaConfig(deps.env);
  if (!config) return reply(503, "Beta access is not configured.");
  if (request.method !== "POST") return reply(405, "Method not allowed.");
  if (request.headers.get("origin") !== deps.env.APP_BASE_URL
    || request.headers.get("sec-fetch-site") && request.headers.get("sec-fetch-site") !== "same-origin"
    || new URL(request.url).search) return reply(403, "Request rejected.");
  if (request.headers.get("content-type")?.split(";")[0] !== "application/x-www-form-urlencoded")
    return reply(400, "Request rejected.");
  try {
    const session = await deps.getSession();
    if (!session || !session.user.sub) return reply(401, "Sign in required.");
    const reader = request.body?.getReader();
    if (!reader) return reply(400, "Enter a beta code.");
    const chunks = []; let length = 0;
    try {
      while (true) {
        const part = await reader.read(); if (part.done) break;
        length += part.value.byteLength;
        if (length > 1024) { await reader.cancel(); return reply(400, "Request rejected."); }
        chunks.push(Buffer.from(part.value));
      }
    } finally { reader.releaseLock(); }
    const form = new URLSearchParams(Buffer.concat(chunks).toString("utf8"));
    const fields = [...form.entries()];
    if (fields.length !== 1 || fields[0][0] !== "code" || !/^SAIPH-[A-Za-z0-9_-]{32}$/.test(fields[0][1]))
      return reply(400, "Enter a valid beta code.");
    const access = checkedAccess(await deps.call("/v1/beta/redeem", fields[0][1]));
    if (!access.entitled) return reply(403, "The beta code was not accepted.");
    return new Response(null, {status:303, headers:{...headers, Location:new URL("/account", deps.env.APP_BASE_URL).href}});
  } catch { return reply(403, "The beta code could not be accepted. Check the code or ask for a new invitation."); }
}
