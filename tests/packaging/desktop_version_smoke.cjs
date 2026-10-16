// SPDX-License-Identifier: AGPL-3.0-or-later
const fs = require("node:fs");
const path = require("node:path");
module.exports = async ({page, expect, session}) => {
  if (session.mode !== "isolated") throw Error("Fresh isolated profile required");
  const version = page.getByLabel("Installed Saiph version", {exact:true});
  await expect(version).toHaveText(/^Saiph \d+\.\d+\.\d+[-\w.]*$/);
  const box = await version.boundingBox();
  const viewport = page.viewportSize() || await page.evaluate(() => ({width:innerWidth, height:innerHeight}));
  expect(box.x).toBeGreaterThan(viewport.width / 2);
  expect(box.y).toBeGreaterThan(viewport.height - 80);
  expect(await page.locator("body").innerText()).not.toContain("Saiph Hosted");
  const directory = path.join(path.dirname(session.profile), "evidence");
  fs.mkdirSync(directory, {recursive:true});
  await page.screenshot({path:path.join(directory,"installed-version.png")});
};
