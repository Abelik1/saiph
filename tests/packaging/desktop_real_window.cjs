// SPDX-License-Identifier: AGPL-3.0-or-later
// Asks the display server, not the page: renderer screenshots pass even when no window exists.
const { execFileSync } = require("node:child_process");

module.exports = function assertRealWindow(session) {
  if (process.platform !== "linux") return "not-linux";
  if (process.env.ORION_MINI_ELECTRON_PLATFORM === "wayland") return "native-wayland";
  const run = (tool, args) => execFileSync(tool, args, { encoding: "utf8", timeout: 15000 });
  const windows = run("xwininfo", ["-root", "-tree"]).split("\n")
    .map(line => line.match(/^\s*(0x[0-9a-f]+) "Saiph": \("saiph-desktop"/i)).filter(Boolean)
    .filter(match => run("xprop", ["-id", match[1], "_NET_WM_PID"]).trim().endsWith(`= ${session.pid}`));
  if (!windows.length) throw new Error("This Saiph has no window on the display server.");
  if (!windows.some(match => run("xwininfo", ["-id", match[1]]).includes("Map State: IsViewable"))) throw new Error("This Saiph's window is not on screen.");
  return "viewable";
};
