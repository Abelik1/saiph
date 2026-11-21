// SPDX-License-Identifier: AGPL-3.0-or-later
import fs from "node:fs/promises";
import path from "node:path";

export const CSP = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
  + "img-src 'self' data: blob: saiph-frame: saiph-media:; font-src 'self' data:; connect-src 'self'; "
  + "object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'";

const types: Record<string, string> = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
  ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".ico": "image/x-icon",
  ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf",
};

/** Only packaged dashboard assets, including protection against symlink escapes. */
export async function readAsset(root: string, raw: string, method: string): Promise<Response> {
  const headers = { "Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store" };
  try {
    const url = new URL(raw);
    if (method !== "GET" || url.protocol !== "saiph-app:" || url.host !== "desktop"
      || url.username || url.password || url.search || url.hash) return new Response(null, { status: 403, headers });
    const name = decodeURIComponent(url.pathname);
    if (name.includes("\\") || name.includes("\0")) return new Response(null, { status: 403, headers });
    const canonicalRoot = await fs.realpath(root);
    const file = await fs.realpath(path.resolve(canonicalRoot, "." + name));
    const relative = path.relative(canonicalRoot, file);
    const mime = types[path.extname(file)];
    if (!relative || relative.startsWith("..") || path.isAbsolute(relative) || !mime
      || (path.extname(file) === ".html" && !["index.html", "screen.html"].includes(relative))) return new Response(null, { status: 403, headers });
    let data = await fs.readFile(file);
    // Qt keeps its bundled WebChannel loader; Electron uses the sandboxed preload.
    if (relative === "index.html") data = Buffer.from(data.toString("utf8")
      .replace('<script src="qrc:///qtwebchannel/qwebchannel.js"></script>', ""));
    return new Response(new Uint8Array(data), { headers: { ...headers, "Content-Type": mime } });
  } catch {
    return new Response(null, { status: 404, headers });
  }
}
