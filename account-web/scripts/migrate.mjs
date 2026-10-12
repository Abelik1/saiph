import { createNeonPool } from "../lib/billing/connection.mjs";
import { loadMigrations, runMigrations } from "../lib/billing/migrate.mjs";

const args = process.argv.slice(2);
try {
  if (args.length !== 1 || !["--plan", "--apply-reviewed"].includes(args[0])) {
    throw new Error("Use --plan or --apply-reviewed");
  }
  const migrations = await loadMigrations();
  if (args[0] === "--plan") {
    // Local verification only: does not load env files or connect to a database.
    console.log(JSON.stringify(migrations.map(({ version, file, sha256 }) => ({ version, file, sha256 })), null, 2));
  } else {
    // Supply the protected UNPOOLED value through the process environment.
    // No dotenv loading, argument secrets, automatic startup migration or raw errors.
    const pool = createNeonPool(process.env.DATABASE_URL_UNPOOLED, { unpooled: true });
    try {
      const applied = await runMigrations(pool, migrations);
      console.log(JSON.stringify({ appliedVersions: applied, verifiedVersions: migrations.map(({ version }) => version) }));
    } finally {
      await pool.end();
    }
  }
} catch {
  console.error("Billing migration failed; verify reviewed checksums and protected database configuration.");
  process.exitCode = 1;
}
