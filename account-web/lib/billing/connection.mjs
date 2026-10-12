import { Pool } from "@neondatabase/serverless";

/** Validate without echoing a connection string. Production always uses Neon TLS.
 * @param {unknown} value
 * @param {{unpooled?: boolean}} [options]
 */
export function validateNeonUrl(value, { unpooled = false } = {}) {
  if (typeof value !== "string" || !value) throw new Error("Billing database is not configured");
  let url;
  try { url = new URL(value); } catch { throw new Error("Invalid billing database configuration"); }
  if (!["postgres:", "postgresql:"].includes(url.protocol) ||
      !url.hostname.endsWith(".neon.tech") ||
      !["require", "verify-ca", "verify-full"].includes(url.searchParams.get("sslmode") ?? "") ||
      !url.username || !url.password || !url.pathname.slice(1) ||
      (unpooled && url.hostname.includes("-pooler."))) {
    throw new Error("Invalid billing database configuration");
  }
  return value;
}

/** Request-scoped pool; no connection or environment lookup during next build.
 * @param {unknown} connectionString
 * @param {{unpooled?: boolean}} [options]
 */
export function createNeonPool(connectionString, options) {
  const pool = new Pool({
    connectionString: validateNeonUrl(connectionString, options),
    max: 2,
    connectionTimeoutMillis: 10_000,
    idleTimeoutMillis: 1_000,
  });
  // Never emit a raw driver error: it may contain SQL, identifiers or credentials.
  pool.on("error", () => { console.error("Billing database connection interrupted"); });
  return pool;
}
