// SPDX-License-Identifier: AGPL-3.0-or-later
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { windowsVersions } = require("../../scripts/package-electron.cjs");
test("Windows fixed fields preserve the build while display strings retain a dotted prerelease", () => {
  assert.deepEqual(windowsVersions("0.1.0-beta.41-electron.1", "41"), { product: "0.1.0", file: "0.1.0.41", display: "0.1.0-beta.41-electron.1" });
});
test("Windows packaging refuses malformed or overflowing version fields", () => {
  for (const [version, build] of [["1.2.3", "65536"], ["65536.2.3", "1"], ["1.2.3", "-1"], ["1.2.3", "NaN"], ["bad", "1"]]) assert.throws(() => windowsVersions(version, build));
});
