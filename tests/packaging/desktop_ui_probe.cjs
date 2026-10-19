// SPDX-License-Identifier: AGPL-3.0-or-later
const {
  chromium,
  expect,
} = require("../../frontend/node_modules/@playwright/test");
(async () => {
  const browser = await chromium.connectOverCDP(
    `http://127.0.0.1:${process.env.ORION_UI_DEBUG_PORT || 9467}`,
    { noDefaults: true },
  );
  const page = browser.contexts()[0].pages()[0];
  await page.reload();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const out =
    process.env.ORION_UI_SCREENSHOTS ||
    require("path").resolve(
      __dirname,
      "../../test-artifacts/desktop-ui-review",
    );
  require("fs").mkdirSync(out, { recursive: true });
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Phone", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Phone", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Photos", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Open Study 15.jpg" }),
  ).toBeVisible();
  await page.screenshot({ path: out + "/photos.png" });
  const frame = await page.locator(".app-footer").boundingBox();
  await page
    .locator(".app-scroll")
    .evaluate((el) => (el.scrollTop = el.scrollHeight));
  expect(await page.locator(".app-footer").boundingBox()).toEqual(frame);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollHeight === innerHeight,
    ),
  ).toBe(true);
  const savedScroll = await page
    .locator(".app-scroll")
    .evaluate((el) => el.scrollTop);
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  await nav.getByRole("button", { name: "Cloud", exact: true }).click();
  await nav.getByRole("button", { name: "Phone", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Photos", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  expect(await page.locator(".app-scroll").evaluate((el) => el.scrollTop)).toBe(
    savedScroll,
  );
  await page.locator(".app-scroll").evaluate((el) => (el.scrollTop = 0));
  await page
    .getByRole("button", { name: "Open Study 15.jpg" })
    .click({ button: "right" });
  await expect(page.getByRole("menu", { name: "Photo actions" })).toBeVisible();
  await page.screenshot({ path: out + "/photo-menu.png" });
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Open Study 15.jpg" }).click();
  const viewer = page.getByRole("dialog", { name: "Study 15.jpg" });
  await expect(viewer.getByRole("status")).toHaveText("Original quality");
  const img = viewer.getByRole("img");
  const dimensions = await img.evaluate((el) => ({
    width: el.naturalWidth,
    height: el.naturalHeight,
  }));
  expect(dimensions).toEqual({ width: 900, height: 1500 });
  await viewer.getByRole("button", { name: "Photo details" }).click();
  await expect(viewer.getByText("900 × 1500")).toBeVisible();
  await page.screenshot({ path: out + "/photo-viewer.png" });
  await viewer.getByRole("button", { name: "Copy image" }).click();
  await expect(
    viewer.getByRole("button", { name: "Copied original" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Open Study 15.jpg" }),
  ).toBeFocused();
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Settings" })
    .click();
  await expect(page.getByRole("tab", { name: "General" })).toBeVisible();
  const cards = await page
    .locator(".settings-content .card:visible")
    .evaluateAll((nodes) =>
      nodes.map((node) => node.getBoundingClientRect().width),
    );
  expect(Math.max(...cards) - Math.min(...cards)).toBeLessThan(2);
  await page.getByLabel("Computer name", { exact: true }).fill("Studio draft");
  await nav.getByRole("button", { name: "Cloud", exact: true }).click();
  await page.getByRole("button", { name: "Cloud settings" }).click();
  await expect(page.getByRole("tab", { name: "Connections" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.getByRole("tab", { name: "General" }).click();
  await expect(page.getByLabel("Computer name", { exact: true })).toHaveValue(
    "Studio draft",
  );
  await expect(page.locator(".settings-unsaved:visible")).toContainText(
    "Unsaved changes",
  );
  await page.screenshot({ path: out + "/settings.png" });
  await page.getByRole("tab", { name: "Connections" }).click();
  // Connections lays its preferences out as visible switch rows, like Settings → Phone.
  await expect(page.getByRole("switch", { name: "Share clipboard" })).toBeVisible();
  await expect(
    page.locator(".settings-content details:not([data-slot=disclosure])"),
  ).toHaveCount(0);
  await page
    .getByLabel("Cloud folder", { exact: true })
    .fill("/tmp/synthetic-cloud-draft");
  await page.getByRole("tab", { name: "Devices" }).click();
  await expect(page.getByLabel("Linux loopback device")).toBeVisible();
  await expect(page.getByLabel("OBS profile", { exact: true })).toHaveCount(0);
  await page.screenshot({ path: out + "/devices.png" });
  await page.getByRole("tab", { name: "Connections" }).click();
  await expect(page.getByLabel("Cloud folder", { exact: true })).toHaveValue(
    "/tmp/synthetic-cloud-draft",
  );
  await expect(page.getByLabel("Quiet hours end")).toHaveAttribute(
    "type",
    "time",
  );
  await expect(page.getByLabel("Focus timezone")).toHaveAttribute("list", /.+/);
  await page.screenshot({ path: out + "/connections.png" });
  expect(errors).toEqual([]);
  console.log(
    JSON.stringify({
      passed: true,
      dimensions,
      footer: frame,
      screenshots: out,
    }),
  );
  process.exit(0);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
