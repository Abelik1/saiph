// SPDX-License-Identifier: AGPL-3.0-or-later
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { readAsset } from "./assets.cjs";
import { validateCall } from "./contract.cjs";
import { applyWindowControl } from "./window-control.cjs";

test("serves only the chosen local app origin and contained assets with CSP", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "saiph-electron-assets-"));
  try {
    const root = path.join(directory, "dashboard");
    await fs.mkdir(root);
    await fs.writeFile(path.join(root, "index.html"), '<script src="qrc:///qtwebchannel/qwebchannel.js"></script><p>Saiph</p>');
    await fs.writeFile(path.join(directory, "private.js"), "private");
    const page = await readAsset(root, "saiph-app://desktop/index.html", "GET");
    assert.equal(page.status, 200);
    assert.match(page.headers.get("Content-Security-Policy")!, /script-src 'self'/);
    assert.equal(await page.text(), "<p>Saiph</p>");
    for (const [url, method] of [["saiph-app://desktop/index.html", "POST"], ["saiph-app://other/index.html", "GET"],
      ["file:///index.html", "GET"], ["saiph-app://desktop/%2f..%2fprivate.js", "GET"],
      ["saiph-app://desktop/%5c..%5cprivate.js", "GET"]]) {
      assert.notEqual((await readAsset(root, url, method)).status, 200);
    }
  } finally { await fs.rm(directory, { recursive: true, force: true }); }
});

test("native window controls require the owning test nonce and bounded geometry", () => {
  for (const request of [{ nonce: "wrong", id: 1, action: "maximize" },
    { nonce: "test", id: 1, action: "quit-owner-app" },
    { nonce: "test", id: 1, action: "bounds", bounds: { x: 0, y: 0, width: 1, height: 1 } }]) {
    assert.throws(() => applyWindowControl({} as never, request, "test"));
  }
});

test("rejects arbitrary IPC shapes and oversized argument payloads", () => {
  assert.doesNotThrow(() => validateCall("state", {}));
  for (const [method, args] of [["exec shell", {}], ["state", []], ["state", null], ["state", { data: "x".repeat(65537) }]]) {
    assert.throws(() => validateCall(method, args));
  }
});
