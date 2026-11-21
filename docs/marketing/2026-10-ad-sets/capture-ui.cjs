// Captures the real Saiph desktop UI from the design preview (synthetic data) for
// the ad screens. Start the frontend dev server first (port 5199), then:
//
//   node docs/marketing/2026-10-ad-sets/capture-ui.cjs --out build/ad-sets/ui
//
// The UI renders at 1280 x 800 CSS pixels and 1.5x scale, so it stays readable
// when the laptop screen is small in a vertical frame.
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('../../../frontend/node_modules/playwright');

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : fallback; };
const out = path.resolve(arg('--out', 'build/ad-sets/ui'));
const base = arg('--base', 'http://localhost:5199/preview.html');
fs.mkdirSync(out, { recursive: true });

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1.5, reducedMotion: 'reduce' });
  const page = await context.newPage();
  const open = async (query) => {
    await page.goto(`${base}?cloud=1${query}`);
    await page.getByPlaceholder('Message').waitFor();
    await page.waitForTimeout(1200);
  };
  const shot = (name) => page.screenshot({ path: path.join(out, name) });

  // Messages tab, calm.
  await open('');
  await shot('app-messages.png');

  // Typing a reply in the real message box, one frame per character.
  const reply = 'Yes! See you at 7';
  const box = page.getByPlaceholder('Message');
  await box.click();
  await shot('app-reply-00.png');
  for (let i = 1; i <= reply.length; i++) {
    await box.fill(reply.slice(0, i));
    await shot(`app-reply-${String(i).padStart(2, '0')}.png`);
  }

  // An incoming call reaches every page as a banner with Answer and Decline.
  await open('&call=ringing');
  await shot('app-call.png');
  const decline = page.getByRole('button', { name: 'Decline' });
  await decline.hover();
  await shot('app-call-hover.png');
  const box2 = await decline.boundingBox();
  fs.writeFileSync(path.join(out, 'positions.json'), JSON.stringify({
    viewport: { width: 1280, height: 800, scale: 1.5 },
    decline: box2,
    message: await page.getByPlaceholder('Message').boundingBox(),
  }, null, 2));

  await browser.close();
  console.log('captured to', out);
})().catch((e) => { console.error(e); process.exit(1); });
