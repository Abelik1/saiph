// SPDX-License-Identifier: AGPL-3.0-or-later
// Settings → Connections in the real Qt shell: visible sections, switches that persist through
// the native bridge, and a design-system disclosure driven from the keyboard. Run with
// desktop-ui.cjs run --script tests/packaging/desktop_settings_polish.cjs on a fresh isolated session.
const fs = require("node:fs");
const path = require("node:path");

module.exports = async ({ page, expect, session }) => {
  if (session.mode !== "isolated") throw new Error("Isolated session required");
  const out = path.join(path.dirname(session.profile), "evidence");
  fs.mkdirSync(out, { recursive: true });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const settings = () => JSON.parse(fs.readFileSync(path.join(session.profile, "settings.json"), "utf8"));

  await page.getByRole("navigation", { name: "Main navigation" }).getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("tab", { name: "Connections", exact: true }).click();
  for (const name of ["Phone and this computer", "Quiet hours", "Cloud folders"]) {
    const heading = page.getByRole("heading", { name, exact: true });
    await expect(heading).toBeVisible();
    expect(await heading.evaluate((el) => el.closest("details"))).toBe(null);
  }
  await expect(page.locator(".settings-content details:not([data-slot=disclosure])")).toHaveCount(0);
  await page.screenshot({ path: path.join(out, "connections.png"), fullPage: true });

  // A switch saves on its own, through the native bridge into the profile.
  const codes = page.getByRole("switch", { name: "Copy verification codes", exact: true });
  await expect(codes).toHaveAttribute("aria-checked", "false");
  await codes.click();
  await expect.poll(() => settings().link?.auto_copy_codes).toBe(true);
  await expect(codes).toHaveAttribute("aria-checked", "true");
  await codes.click();
  await expect.poll(() => settings().link?.auto_copy_codes).toBe(false);

  // Quiet hours keep their explicit Save.
  await page.getByLabel("Quiet hours end", { exact: true }).fill("08:30");
  await page.getByRole("button", { name: "Save quiet hours", exact: true }).click();
  await expect(page.getByText("Quiet hours saved.", { exact: true })).toBeVisible();
  expect([settings().link.wake_hour, settings().link.wake_minute]).toEqual([8, 30]);

  // The self-hosted Hub stays folded away; it opens and closes from the keyboard.
  const hub = page.locator("summary", { hasText: "Self-hosted Hub" });
  await hub.focus();
  await expect(hub).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("Saiph Hub address")).toBeVisible();
  await page.screenshot({ path: path.join(out, "connections-hub-open.png") });
  await page.keyboard.press("Space");
  await expect(page.getByLabel("Saiph Hub address")).toBeHidden();

  expect(errors).toEqual([]);
  fs.writeFileSync(path.join(out, "settings-polish-results.json"), JSON.stringify({ passed: true, nativeQt: true, visibleSections: true, switchPersists: true, quietHoursPersist: true, disclosureKeyboard: true, liveAccounts: false }, null, 2));
};
