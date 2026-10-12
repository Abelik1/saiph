// SPDX-License-Identifier: AGPL-3.0-or-later
import {readBetaConfig} from "./beta-policy.mjs";
/** @param {Request} request
 * @param {{env:Record<string,string|undefined>,getSession:()=>Promise<{user:{sub?:string}}|null>,
 * download:(artifact:string)=>Promise<string>}} deps */
export async function downloadBeta(request, deps) {
  const headers = {"Cache-Control":"private, no-store", "Referrer-Policy":"no-referrer"};
  /** @param {number} status @param {string} text */
  const reply = (status,text) => new Response(text,{status,headers});
  const config = readBetaConfig(deps.env);
  if (!config) return reply(503,"Downloads unavailable.");
  if (request.method !== "POST") return reply(405,"Method not allowed.");
  if (request.headers.get("origin") !== deps.env.APP_BASE_URL || new URL(request.url).search
    || request.headers.get("sec-fetch-site") && request.headers.get("sec-fetch-site") !== "same-origin"
    || request.headers.get("content-type")?.split(";")[0] !== "application/x-www-form-urlencoded")
    return reply(403,"Request rejected.");
  try {
    const session = await deps.getSession();
    if (!session?.user.sub) return reply(401,"Sign in required.");
    const reader = request.body?.getReader();
    if (!reader) return reply(400,"Choose a download.");
    const chunks = []; let length = 0;
    try {
      while (true) {
        const part = await reader.read(); if (part.done) break;
        length += part.value.byteLength;
        if (length > 256) { await reader.cancel(); return reply(400,"Request rejected."); }
        chunks.push(Buffer.from(part.value));
      }
    } finally { reader.releaseLock(); }
    const fields = [...new URLSearchParams(Buffer.concat(chunks).toString("utf8")).entries()];
    if (fields.length !== 1 || fields[0][0] !== "artifact"
      || !["windows","linux","android","desktop_source","android_source","notices","checksums","qt_sources_windows","qt_sources_linux"].includes(fields[0][1]))
      return reply(400,"Choose a download.");
    const location = await deps.download(fields[0][1]);
    if (!location.startsWith(config.origin + "/v1/download/") || !/^[A-Za-z0-9_-]{43}$/.test(location.slice((config.origin + "/v1/download/").length)))
      throw new Error("Invalid download location");
    return new Response(null,{status:303,headers:{...headers,Location:location}});
  } catch { return reply(403,"Download unavailable. Check your beta access and try again shortly."); }
}
