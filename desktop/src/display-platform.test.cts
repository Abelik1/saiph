// SPDX-License-Identifier: AGPL-3.0-or-later
import { test } from "node:test";
import assert from "node:assert/strict";
import { missingDisplayPlatform } from "./display-platform.cjs";

const wayland = { DISPLAY: ":0", WAYLAND_DISPLAY: "wayland-0" };

test("a Wayland session restarts on X11 unless the platform is already chosen", () => {
  assert.equal(missingDisplayPlatform("linux", wayland, ["saiph"]), "--ozone-platform=x11");
  assert.equal(missingDisplayPlatform("linux", { DISPLAY: ":0", XDG_SESSION_TYPE: "wayland" }, ["saiph"]), "--ozone-platform=x11");
  assert.equal(missingDisplayPlatform("linux", wayland, ["saiph", "--ozone-platform=x11"]), undefined);
  assert.equal(missingDisplayPlatform("linux", wayland, ["saiph", "--ozone-platform", "wayland"]), undefined);
});

test("an explicit platform choice is honoured", () => {
  assert.equal(missingDisplayPlatform("linux", { ...wayland, ORION_MINI_ELECTRON_PLATFORM: "wayland" }, ["saiph"]), "--ozone-platform=wayland");
});

test("no restart without both display servers or off Linux", () => {
  assert.equal(missingDisplayPlatform("linux", { DISPLAY: ":0" }, ["saiph"]), undefined);
  assert.equal(missingDisplayPlatform("linux", { WAYLAND_DISPLAY: "wayland-0" }, ["saiph"]), undefined);
  assert.equal(missingDisplayPlatform("win32", wayland, ["saiph"]), undefined);
});
