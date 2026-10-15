// SPDX-License-Identifier: AGPL-3.0-or-later
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { readSession } = require("../../scripts/desktop-ui.cjs");

test("only ready loopback sessions can be controlled", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "saiph-ui-session-"));
  const file = path.join(directory, "session.json");
  const valid = { schema: 1, status: "ready", pid: 1234, nonce: "a".repeat(48),
    endpoint: "http://127.0.0.1:9467", dashboard: "file:///synthetic/index.html", mode: "isolated" };
  try {
    fs.writeFileSync(file, JSON.stringify(valid));
    assert.equal(readSession(file).endpoint, valid.endpoint);
    for (const change of [{ endpoint: "http://192.0.2.10:9467" }, { endpoint: "http://127.0.0.1:9467@evil.invalid" },
      { endpoint: "http://user:password@127.0.0.1:9467" }, { status: "stopped" }, { nonce: "" },
      { dashboard: "https://example.invalid/" }, { mode: "owner" }]) {
      fs.writeFileSync(file, JSON.stringify({ ...valid, ...change }));
      assert.throws(() => readSession(file));
    }
  } finally {
    fs.unlinkSync(file);
    fs.rmdirSync(directory);
  }
});
