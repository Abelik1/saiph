// SPDX-License-Identifier: AGPL-3.0-or-later
import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { PythonService } from "./service.cjs";

test("failed service spawn rejects startup and remains safe to stop", async () => {
  const service = new PythonService();
  await assert.rejects(service.start(path.resolve("missing-test-interpreter"), process.cwd(), "missing-session"), /could not start/);
  await service.stop();
  await assert.rejects(service.call("state", {}), /unavailable/);
});
