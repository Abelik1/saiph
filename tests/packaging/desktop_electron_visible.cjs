// SPDX-License-Identifier: AGPL-3.0-or-later
// A short visible native-window check. Full OS frame capture remains a release gate.
const fs = require("node:fs");
const path = require("node:path");

module.exports = async connection => {
  const { page, expect, session } = connection;
  if (session.shell !== "electron" || !session.show || session.mode !== "isolated") throw new Error("Visible isolated Electron session required.");
  await require("./desktop_electron_smoke.cjs")(connection);
  const realWindow = require("./desktop_real_window.cjs")(session);
  const directory = path.dirname(session.profile);
  let id = Date.now();
  const control = async (action, bounds) => {
    const request = { nonce: session.nonce, id: ++id, action, ...(bounds ? { bounds } : {}) };
    fs.writeFileSync(path.join(directory, "window-request.tmp"), JSON.stringify(request));
    fs.renameSync(path.join(directory, "window-request.tmp"), path.join(directory, "window-request.json"));
    await expect.poll(() => {
      try { return JSON.parse(fs.readFileSync(path.join(directory, "window-state.json"), "utf8")).id; }
      catch { return 0; }
    }).toBe(id);
  };
  const navigation = page.getByRole("navigation", { name: "Main navigation" });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  {
    for (let i = 0; i < 30; i++) {
      await control("bounds", { x: 50 + (i % 4) * 45,
        y: 50 + (i % 3) * 25, width: i % 2 ? 1180 : 1280, height: i % 2 ? 800 : 900 });
      const name = ["Phone", "Cloud", "Settings"][i % 3];
      await navigation.getByRole("button", { name, exact: true }).click();
      await expect(page.getByRole("main", { name: `${name} content` })).toBeVisible();
      await page.mouse.wheel(0, i % 2 ? 400 : -400);
      await page.waitForTimeout(150);
    }
    for (const action of ["maximize", "restore", "minimize", "restore"]) {
      await control(action);
      await page.waitForTimeout(300);
    }
    await control("bounds", { x: 50, y: 50, width: 1280, height: 900 });
    await expect(navigation).toBeVisible();
    expect(errors).toEqual([]);
    const output = path.join(path.dirname(session.profile), "evidence");
    await page.screenshot({ path: path.join(output, "electron-visible.png") });
    fs.writeFileSync(path.join(output, "electron-visible-results.json"), JSON.stringify({ passed: true,
      shell: "electron", realWindow, normalGPUSettings: true, moveResizeTabCycles: 30, maximizeRestoreMinimize: true,
      pageErrors: errors, limitation: "Short visible smoke test; browser screenshots do not prove OS presentation is free of corruption." }, null, 2));
  }
};
