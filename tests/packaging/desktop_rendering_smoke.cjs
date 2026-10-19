// SPDX-License-Identifier: AGPL-3.0-or-later
// Run with desktop-ui.cjs against a fresh isolated Qt session.
const fs = require('node:fs');
const path = require('node:path');

module.exports = async ({ page, expect, session }) => {
  if (session.mode !== 'isolated') throw Error('Isolated session required');
  const out = path.join(path.dirname(session.profile), 'evidence');
  fs.mkdirSync(out, { recursive: true });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const nav = page.getByRole('navigation', { name: 'Main navigation' });
  await expect(nav).toBeVisible();
  // These surfaces sit above a continuously redrawn canvas. Backdrop blur
  // makes Qt WebEngine repeatedly composite them and can flicker on Windows.
  for (const name of ['Phone', 'Cloud', 'Settings']) {
    await nav.getByRole('button', { name, exact: true }).click();
    const surfaces = await page.locator('.link-header, .app-footer').evaluateAll(elements =>
      elements.map(element => ({
        surface: element.tagName,
        backdrop: getComputedStyle(element).backdropFilter,
      })),
    );
    expect(surfaces).toHaveLength(2);
    for (const surface of surfaces) expect(surface.backdrop, surface.surface).toBe('none');
  }
  // Keep the actual native one-second refresh running: it must not replace
  // the shell or its background canvas when the desktop is sitting idle.
  const shell = await page.locator('.link-shell').elementHandle();
  const canvas = await page.locator('.wave-field canvas').elementHandle();
  const origin = await page.evaluate(() => performance.timeOrigin);
  await page.waitForTimeout(3200);
  expect(await shell.evaluate(element => element.isConnected)).toBe(true);
  expect(await canvas.evaluate(element => element.isConnected)).toBe(true);
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(origin);
  expect(errors).toEqual([]);
  await page.screenshot({ path: path.join(out, 'idle-rendering.png') });
  fs.writeFileSync(path.join(out, 'rendering-results.json'), JSON.stringify({
    passed: true, nativeQt: true, backdropBlur: false, idleShellRetained: true,
    pageErrors: errors, liveAccounts: false,
    limitation: 'The default harness disables GPU; this does not establish visible GPU flicker acceptance.',
  }, null, 2));
};
