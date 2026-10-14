// SPDX-License-Identifier: AGPL-3.0-or-later
import "server-only";
import {getAuth0} from "./auth";
import {readBetaConfig} from "./beta-policy.mjs";
import {checkedAccess,checkedHostedAccess,type HostedAccess} from "./beta-http.mjs";

type Path = "/v1/beta/access"|"/v1/beta/redeem"|"/v1/beta/download"|"/v1/billing/access";
async function call(path: Path, payload?:Record<string,string>) {
  const config = readBetaConfig(process.env), auth0 = getAuth0();
  if (!config || !auth0) throw new Error("Beta access unavailable");
  const {token} = await auth0.getAccessToken();
  const response = await fetch(config.origin + path, {
    method: payload === undefined ? "GET" : "POST", redirect:"error", cache:"no-store",
    signal:AbortSignal.timeout(8000), headers:{Authorization:"Bearer " + token, "Content-Type":"application/json"},
    ...(payload === undefined ? {} : {body:JSON.stringify(payload)}),
  });
  if (response.status !== 200 || response.headers.get("content-type")?.split(";")[0] !== "application/json")
    throw new Error("Beta access unavailable");
  const reader = response.body?.getReader();
  if (!reader) throw new Error("Beta access unavailable");
  const chunks:Buffer[] = []; let length = 0;
  try {
    while (true) {
      const part = await reader.read(); if (part.done) break;
      length += part.value.byteLength;
      if (length > 4096) { await reader.cancel(); throw new Error("Beta access unavailable"); }
      chunks.push(Buffer.from(part.value));
    }
  } finally { reader.releaseLock(); }
  return JSON.parse(Buffer.concat(chunks).toString("utf8")) as unknown;
}

export async function betaCall(path: "/v1/beta/access"|"/v1/beta/redeem", code?:string) {
  return checkedAccess(await call(path, code === undefined ? undefined : {code}));
}

/** Hosted access with its source (beta, paid, admin). A service release without
 * /v1/billing/access still answers the beta status, with the source unknown. */
export async function hostedAccess(): Promise<HostedAccess | (ReturnType<typeof checkedAccess> & {kinds: null})> {
  try { return checkedHostedAccess(await call("/v1/billing/access")); }
  catch { return {...await betaCall("/v1/beta/access"), kinds: null}; }
}

export async function betaDownload(artifact:string) {
  const value = await call("/v1/beta/download", {artifact});
  if (!value || typeof value !== "object" || Object.keys(value).join(",") !== "ticket"
    || !("ticket" in value) || typeof value.ticket !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(value.ticket))
    throw new Error("Download unavailable");
  return readBetaConfig(process.env)!.origin + "/v1/download/" + value.ticket;
}
