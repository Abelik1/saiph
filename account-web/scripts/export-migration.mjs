import { writeFile } from "node:fs/promises";
import { exportMigrationSql, loadMigrations } from "../lib/billing/migrate.mjs";
const migrations = await loadMigrations();
const target = new URL("../migrations/reviewed-migration.sql", import.meta.url);
await writeFile(target, exportMigrationSql(migrations));
console.log("Reviewed SQL editor transaction exported; versions: " + migrations.map(({version}) => version).join(","));