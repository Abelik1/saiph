import test from "node:test";
import assert from "node:assert/strict";
import { createNeonPool, validateNeonUrl } from "../lib/billing/connection.mjs";

const valid = "postgresql://synthetic:synthetic@ep-synthetic-pooler.eu-west-2.aws.neon.tech/neondb?sslmode=require";

test("Neon URL validation requires TLS, credentials and correct provider without exposing input", () => {
  assert.equal(validateNeonUrl(valid), valid);
  for (const url of [
    undefined, "", "malformed", "postgresql://synthetic:synthetic@localhost/db?sslmode=require",
    valid.replace("?sslmode=require", ""), valid.replace("synthetic:synthetic@", ""),
    valid.replace("sslmode=require", "sslmode=disable"), valid.replace("neon.tech", "neon.tech.evil.test"),
  ]) {
    assert.throws(() => validateNeonUrl(url), (error) => {
      assert.ok(!error.message.includes("synthetic"));
      return true;
    });
  }
  assert.throws(() => validateNeonUrl(valid, { unpooled: true }));
  assert.equal(validateNeonUrl(valid.replace("-pooler.", "."), { unpooled: true }), valid.replace("-pooler.", "."));
});

test("request scoped Neon pool is lazy and can be closed without connecting", async () => {
  const pool = createNeonPool(valid);
  assert.equal(pool.totalCount, 0);
  await pool.end();
  assert.throws(() => createNeonPool(undefined));
});
