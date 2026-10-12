import { spawnSync } from "node:child_process";
import { randomUUID, randomBytes } from "node:crypto";
import pg from "pg";

const name = "saiph-billing-test-" + randomUUID();
const password = randomBytes(24).toString("hex");
let started = false;

/** @param {string[]} args */
function docker(args) {
  const result = spawnSync("docker", args, { encoding: "utf8", timeout: 30_000 });
  if (result.status !== 0) throw new Error("Isolated PostgreSQL container operation failed");
  return result.stdout.trim();
}
try {
  // Fresh synthetic database, bound to loopback on an automatically selected port.
  // No host mounts, shared networks, persistent volume or production credentials.
  docker(["run", "--detach", "--rm", "--name", name,
    "--label", "saiph.purpose=billing-synthetic-test",
    "--env", "POSTGRES_PASSWORD=" + password, "--env", "POSTGRES_DB=saiph_billing_test",
    "--publish", "127.0.0.1::5432", "postgres:16-alpine"]);
  started = true;
  const port = docker(["port", name, "5432/tcp"]).split(":").at(-1);
  const url = "postgresql://postgres:" + password + "@127.0.0.1:" + port + "/saiph_billing_test";
  for (let attempt = 0; attempt < 30; attempt++) {
    const client = new pg.Client({ connectionString: url, connectionTimeoutMillis: 500 });
    try {
      await client.connect();
      await client.query("SELECT 1");
      break;
    } catch {
      if (attempt === 29) throw new Error("Isolated PostgreSQL did not become ready");
      await new Promise((resolve) => setTimeout(resolve, 200));
    } finally {
      await client.end().catch(() => {});
    }
  }
  const result = spawnSync(process.execPath, ["--test", "--test-concurrency=1", "tests/billing-db.test.mjs", "tests/billing-lifecycle.test.mjs"], {
    env: { ...process.env, SAIPH_BILLING_TEST_DATABASE_URL: url },
    stdio: "inherit",
    timeout: 120_000,
  });
  process.exitCode = result.status ?? 1;
} catch {
  console.error("Billing database tests failed: isolated Docker PostgreSQL is required.");
  process.exitCode = 1;
} finally {
  if (started) {
    try { docker(["stop", "--time", "5", name]); }
    catch { console.error("Could not stop this run's isolated PostgreSQL container: " + name); process.exitCode = 1; }
  }
}
