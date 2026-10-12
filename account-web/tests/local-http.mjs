// SPDX-License-Identifier: AGPL-3.0-or-later
import {request} from "node:http";

// Node fetch replaces Host with the connection address. These tests need to
// exercise virtual-host routing while connecting only to an isolated loopback server.
export function localRequest(url, {method = "GET", headers = {}, body} = {}) {
  const target = new URL(url);
  if (target.protocol !== "http:" || target.hostname !== "127.0.0.1") throw new Error("Loopback HTTP only");
  return new Promise((resolve, reject) => {
    const req = request(target, {method, headers, signal: AbortSignal.timeout(10000)}, res => {
      const chunks = [];
      res.on("data", chunk => chunks.push(chunk));
      res.on("error", reject);
      res.on("end", () => {
        const responseHeaders = new Headers();
        for (let i = 0; i < res.rawHeaders.length; i += 2) responseHeaders.append(res.rawHeaders[i], res.rawHeaders[i + 1]);
        resolve(new Response([204, 205, 304].includes(res.statusCode) ? null : Buffer.concat(chunks),
          {status: res.statusCode, headers: responseHeaders}));
      });
    });
    req.on("error", reject);
    req.end(body);
  });
}
