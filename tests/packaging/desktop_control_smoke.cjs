// SPDX-License-Identifier: AGPL-3.0-or-later
// Run with desktop-ui.cjs run --script tests/packaging/desktop_control_smoke.cjs.
const fs = require("node:fs");
const path = require("node:path");

module.exports = async ({ page, expect, session }) => {
  if (session.mode !== "isolated") throw new Error("Smoke flow requires an isolated test profile.");
  const output = path.join(path.dirname(session.profile), "evidence");
  fs.mkdirSync(output, { recursive: true });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  // A stale/reused debug port must never let a controller drive another window.
  const wrongSession = path.join(output, "wrong-session.json");
  fs.writeFileSync(wrongSession, JSON.stringify({ ...session, nonce: session.nonce === "b".repeat(48) ? "a".repeat(48) : "b".repeat(48) }));
  try {
    await expect(require("../../scripts/desktop-ui.cjs").connectDesktop(wrongSession)).rejects.toThrow("belongs to another window");
  } finally { fs.unlinkSync(wrongSession); }
  await expect(page.getByRole("heading", { name: "Connect your phone", exact: true })).toBeVisible();
  const navigation = page.getByRole("navigation", { name: "Main navigation" });
  await navigation.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("tab", { name: "Connections", exact: true }).click();
  await expect(page.getByRole("tab", { name: "Connections", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "General", exact: true }).click();
  await page.getByLabel("Computer name", { exact: true }).fill("Automated test desktop");
  await page.getByRole("button", { name: "Save this computer", exact: true }).click();
  await expect(page.getByText("Computer preferences saved.", { exact: true })).toBeVisible();
  // Verify the native QWebChannel/bridge saved the profile, beyond a DOM assertion.
  const saved = JSON.parse(fs.readFileSync(path.join(session.profile, "settings.json"), "utf8"));
  expect(saved.machine.name).toBe("Automated test desktop");
  await page.screenshot({ path: path.join(output, "settings-saved.png") });
  await page.getByRole("button", { name: "Connect a phone", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Connect your phone", exact: true })).toBeVisible();
  const ownHub = page.getByRole("button", { name: "Use my own Hub instead", exact: true });
  if (await ownHub.count()) await ownHub.click();
  await expect(page.getByRole("button", { name: "Open server invitation", exact: true })).toBeVisible();
  const account = page.getByRole("button", { name: "Use a Saiph account instead", exact: true });
  if (await account.count()) {
    await account.click();
    await expect(page.getByRole("heading", { name: "Phone connection", exact: true })).toBeVisible();
  }
  await page.screenshot({ path: path.join(output, "phone-wizard.png") });
  expect(errors).toEqual([]);
  const result = { passed: true, nativeQt: true, nativeBridgeSave: true, tabs: true,
    formEntry: true, phoneSetupNavigation: true, mismatchedSessionRefused: true, pageErrors: errors, mode: session.mode,
    limits: "No live account, physical phone or owner-verification acceptance." };
  fs.writeFileSync(path.join(output, "results.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
};
