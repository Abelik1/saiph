// Renders an HTML screen timeline (window.setTime(t)) to a PNG sequence for Blender.
//
//   node docs/marketing/2026-10-ad-sets/render-screen.cjs --page screens/a-laptop.html --out build/ad-sets/a/laptop \
//        --width 1920 --height 1200 --duration 15 [--fps 30] [--frames 0-449] [--transparent]
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('../../../frontend/node_modules/playwright');

const repo = path.resolve(__dirname, '../../..');
const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : fallback; };
const page = arg('--page'), out = path.resolve(arg('--out')), fps = Number(arg('--fps', 30));
const width = Number(arg('--width', 1920)), height = Number(arg('--height', 1200)), duration = Number(arg('--duration', 15));
const total = Math.round(duration * fps);
const [a, b] = (arg('--frames') || `0-${total - 1}`).split('-').map(Number);
const types = { '.html': 'text/html', '.js': 'text/javascript', '.png': 'image/png', '.svg': 'image/svg+xml', '.json': 'application/json' };

(async () => {
  fs.mkdirSync(out, { recursive: true });
  const server = http.createServer((req, res) => {
    const file = path.join(repo, decodeURIComponent(new URL(req.url, 'http://x').pathname));
    if (!file.startsWith(repo) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'content-type': types[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const browser = await chromium.launch({ headless: true });
  try {
    const tab = await browser.newPage({ viewport: { width, height } });
    tab.on('pageerror', (e) => console.error('page error:', e.message));
    await tab.goto(`http://127.0.0.1:${server.address().port}/docs/marketing/2026-10-ad-sets/${page}`);
    await tab.evaluate(() => window.ready);
    for (let n = a; n <= (b ?? a); n++) {
      await tab.evaluate((t) => window.setTime(t), n / fps);
      await tab.screenshot({ path: path.join(out, `${String(n).padStart(4, '0')}.png`), omitBackground: process.argv.includes('--transparent') });
    }
    console.log(`${page}: frames ${a}-${b ?? a} to ${out}`);
  } finally { await browser.close(); server.close(); }
})().catch((e) => { console.error(e); process.exit(1); });
