// SPDX-License-Identifier: AGPL-3.0-or-later
// Ed25519-signed grant pushes to the Hosted service. The website holds the
// private key; the service holds only the public key (docs/PAID_HOSTED.md).
import { createPrivateKey, sign } from "node:crypto";

export const GRANT_CONTEXT = "saiph-billing-grant-v1.";
export const GRANT_PATH = "/v1/billing/grant";

/** @typedef {{issuer: string, subject: string, grant: string, until: number, sequence: number, livemode: boolean}} GrantValue */
/** @typedef {{origin: string, keyId: string, key: import("node:crypto").KeyObject}} GrantTarget */

/** Parse a base64url PKCS#8 DER Ed25519 private key; throws without echoing it.
 * @param {unknown} encoded */
export function grantKey(encoded) {
  try {
    if (typeof encoded !== "string" || !/^[A-Za-z0-9_-]{40,200}$/.test(encoded)) throw new Error();
    const key = createPrivateKey({ key: Buffer.from(encoded, "base64url"), format: "der", type: "pkcs8" });
    if (key.asymmetricKeyType !== "ed25519") throw new Error();
    return key;
  } catch {
    throw new Error("Invalid billing grant key");
  }
}

/** Fixed field order; the service rejects missing or extra fields.
 * @param {{keyId: string, key: import("node:crypto").KeyObject}} signer
 * @param {GrantValue} value
 * @param {number} now Unix seconds
 */
export function signedGrant(signer, value, now) {
  const body = JSON.stringify({ issuer: value.issuer, subject: value.subject, grant: value.grant,
    until: value.until, sequence: value.sequence, livemode: value.livemode });
  const t = String(now);
  const signature = sign(null, Buffer.from(GRANT_CONTEXT + t + "." + body), signer.key).toString("base64url");
  return { body, header: `t=${t},k=${signer.keyId},v1=${signature}` };
}

/** POST one grant. Resolves with whether the service applied it (false: it already
 * had this or a newer sequence). Throws on any other outcome, without details.
 * @param {GrantTarget} target
 * @param {GrantValue} value
 * @param {{fetchImpl?: typeof fetch, now?: number}} [options]
 */
export async function pushGrant(target, value, { fetchImpl = fetch, now = Math.floor(Date.now() / 1000) } = {}) {
  const { body, header } = signedGrant(target, value, now);
  const response = await fetchImpl(target.origin + GRANT_PATH, {
    method: "POST", redirect: "error", cache: "no-store", signal: AbortSignal.timeout(8000),
    headers: { "Content-Type": "application/json", "Saiph-Billing-Signature": header }, body,
  });
  const text = response.status === 200 && response.headers.get("content-type")?.split(";")[0] === "application/json"
    ? await response.text() : null;
  if (text === null || text.length > 256) throw new Error("Hosted grant push failed");
  let result;
  try { result = JSON.parse(text); } catch { throw new Error("Hosted grant push failed"); }
  if (!result || typeof result !== "object" || Object.keys(result).join(",") !== "applied" || typeof result.applied !== "boolean") {
    throw new Error("Hosted grant push failed");
  }
  return result.applied;
}
