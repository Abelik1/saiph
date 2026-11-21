// SPDX-License-Identifier: AGPL-3.0-or-later
const fs = require("node:fs"), path = require("node:path");
module.exports = async ({ page, expect, session }) => {
  if (session.shell !== "electron" || !session.show || session.mode !== "isolated") throw new Error("Visible isolated Electron required.");
  const directory = path.dirname(session.profile), errors = [], latency = [];
  let id = Date.now();
  page.on("pageerror", error => errors.push(error.message));
  const timeOrigin = await page.evaluate(() => performance.timeOrigin);
  for (let i = 0; i < 180; i++) {
    if (i % 6 === 0) {
      fs.writeFileSync(path.join(directory, "window-request.json"), JSON.stringify({ nonce: session.nonce, id: ++id,
        action: "bounds", bounds: { x: 50 + i % 3 * 40, y: 50 + i % 2 * 30, width: i % 12 ? 1180 : 1280, height: i % 12 ? 800 : 900 } }));
      await expect.poll(() => { try { return JSON.parse(fs.readFileSync(path.join(directory, "window-state.json"))).id; } catch { return 0; } }).toBe(id);
    }
    const name = ["Phone", "Cloud", "Settings"][i % 3], start = Date.now();
    await page.getByRole("navigation", { name: "Main navigation" }).getByRole("button", { name, exact: true }).click();
    await expect(page.getByRole("main", { name: `${name} content` })).toBeVisible();
    latency.push(Date.now() - start);
    if (name === "Phone") await page.getByRole("tab", { name: i % 2 ? "Photos" : "Messages", exact: true }).click();
    await page.mouse.wheel(0, i % 2 ? 400 : -400);
    await page.waitForTimeout(400);
  }
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(timeOrigin);
  expect(errors).toEqual([]);
  latency.sort((a,b) => a-b);
  const result = { cycles: 180, resizeMoveCycles: 30, rendererReloads: 0, pageErrors: errors,
    navigationMilliseconds: { median: latency[Math.floor(latency.length / 2)], p95: latency[Math.floor(latency.length * .95)] },
    limit: "Synthetic native UI stress; OS-frame evidence is recorded separately. No physical devices or live accounts." };
  fs.writeFileSync(path.join(directory, "evidence/electron-stress-results.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
};
