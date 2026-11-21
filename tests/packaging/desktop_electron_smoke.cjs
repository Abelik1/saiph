// SPDX-License-Identifier: AGPL-3.0-or-later
const fs = require("node:fs");
const path = require("node:path");

module.exports = async ({ page, expect, session, browser }) => {
  if (session.shell !== "electron" || session.mode !== "isolated") throw new Error("Isolated Electron session required.");
  const output = path.join(path.dirname(session.profile), "evidence");
  fs.mkdirSync(output, { recursive: true });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
  const isolated = await page.evaluate(() => ({ require: typeof window.require, process: typeof window.process,
    qt: typeof window.qt, version: window.saiphDesktop.version }));
  expect(isolated).toEqual({ require: "undefined", process: "undefined", qt: "undefined", version: 1 });
  const unsupported = await page.evaluate(() => window.saiphDesktop.request("hosted.approve", { confirmed: true }));
  expect(unsupported.ok).toBe(false);
  expect(unsupported.error).toContain("disabled in isolated sessions");
  // Validate DOM session ownership using the real controller, not a mocked browser.
  const wrong = path.join(path.dirname(session.profile), "wrong-session.json");
  fs.writeFileSync(wrong, JSON.stringify({ ...session, nonce: "f".repeat(48) }));
  try { await expect(require("../../scripts/desktop-ui.cjs").connectDesktop(wrong)).rejects.toThrow("belongs to another window"); }
  finally { fs.unlinkSync(wrong); }
  const navigation = page.getByRole("navigation", { name: "Main navigation" });
  await navigation.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByLabel("Computer name", { exact: true }).fill("Electron test Ω");
  await page.getByRole("button", { name: "Save this computer", exact: true }).click();
  await expect(page.getByText("Computer preferences saved.", { exact: true })).toBeVisible();
  expect(JSON.parse(fs.readFileSync(path.join(session.profile, "settings.json"), "utf8")).machine.name).toBe("Electron test Ω");
  await page.screenshot({ path: path.join(output, "electron-settings.png") });
  for (const name of ["Cloud", "Phone", "Settings", "Phone"]) {
    await navigation.getByRole("button", { name, exact: true }).click();
    await expect(page.getByRole("main", { name: `${name} content` })).toBeVisible();
  }
  if (session.fixture === "phone") {
    await page.getByRole("tab", { name: "Photos", exact: true }).click();
    await page.screenshot({ path: path.join(output, "electron-photos.png") });
    await page.getByRole("tab", { name: "Apps", exact: true }).click();
    await page.getByRole("tab", { name: "Messages", exact: true }).click();
    const picture = await page.evaluate(() => window.saiphDesktop.request("phone.photo.view", { device_id: "electron-test-phone", photo_id: "1" }));
    expect(picture.ok).toBe(true);
    expect(picture.result.url).toMatch(/^saiph-media:\/\/[a-f0-9]+\/image$/);
    expect(picture.result.width).toBe(640);
    expect(await page.evaluate(async url => { const image = new Image(); image.src = url; await image.decode(); return image.naturalWidth; }, picture.result.url)).toBe(640);
    const copy = await page.evaluate(() => window.saiphDesktop.request("phone.photo.copy", { device_id: "electron-test-phone", photo_id: "1" }));
    expect(copy.result.copied).toBe(true); // Isolated native memory clipboard only.
    fs.writeFileSync(path.join(path.dirname(session.profile), "native-fixtures.json"), JSON.stringify({ nonce: session.nonce, "dialog.open": path.join(session.profile, "Synthetic original.jpg") }));
    const selection = await page.evaluate(() => window.saiphDesktop.request("dialog.file", {}));
    expect(selection.result.path).toBe(path.join(session.profile, "Synthetic original.jpg"));
    fs.writeFileSync(path.join(path.dirname(session.profile), "service-control.json"), JSON.stringify({ nonce: session.nonce, action: "test.frame" }));
    await expect.poll(() => browser.contexts().flatMap(context => context.pages()).find(candidate => candidate.url().endsWith("/screen.html"))?.url()).toContain("screen.html");
    const viewer = browser.contexts().flatMap(context => context.pages()).find(candidate => candidate.url().endsWith("/screen.html"));
    await expect.poll(() => viewer.getByAltText("Live phone screen").evaluate(image => image.naturalWidth)).toBe(360);
    await viewer.getByRole("button", { name: "Home", exact: true }).click();
    await expect(viewer.getByText("Control on", { exact: true })).toBeVisible();
    expect(await viewer.evaluate(() => window.saiphDesktop.request("settings.save", { close_to_tray: true }).then(() => false, () => true))).toBe(true);
    await viewer.getByRole("button", { name: "Rotate view", exact: true }).click();
    await viewer.screenshot({ path: path.join(output, "electron-phone-screen.png") });
    await viewer.getByRole("button", { name: "Stop sharing", exact: true }).click();
    await expect.poll(() => viewer.isClosed()).toBe(true);
  }
  // Browser screenshots prove frontend continuity, not absence of OS-presented corruption.
  const timeOrigin = await page.evaluate(() => performance.timeOrigin);
  await page.waitForTimeout(1500);
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(timeOrigin);
  await page.reload();
  await expect(navigation).toBeVisible();
  await navigation.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByLabel("Computer name", { exact: true })).toHaveValue("Electron test Ω");
  expect(errors).toEqual([]);
  const result = { passed: true, shell: "electron", realPythonState: true, nativeBridgeSave: true,
    sandboxIsolation: isolated, reloadRetainsSettings: true, liveActionRefusedInIsolation: true,
    mismatchedSessionRefused: true, pageErrors: errors, visible: session.show,
    limitation: "Synthetic profile only; no physical devices, live account, installed upgrade or full GPU flicker acceptance." };
  fs.writeFileSync(path.join(output, "electron-results.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
};
