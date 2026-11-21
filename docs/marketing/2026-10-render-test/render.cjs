// Renders the comparison: screen assets, three.js frames, the shared type layer,
// MP4/still composites and a side-by-side review page. Blender frames come from
// blender/scene.py; run that between `three` and `composite`.
//
//   node docs/marketing/2026-10-render-test/render.cjs --out build/render-test --step assets|three|overlay|composite|compare
//
// Headless and offscreen: a loopback-only file server and a fresh browser context.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { spawnSync } = require('node:child_process');
const { chromium } = require('../../../frontend/node_modules/playwright');

const here = __dirname;
const docs = path.resolve(here, '../..');
const spec = JSON.parse(fs.readFileSync(path.join(here, 'scene.json'), 'utf8'));
const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : fallback; };
const out = path.resolve(arg('--out', 'build/render-test'));
const step = arg('--step', 'assets');
const only = arg('--frames'); // e.g. "0-299" or "138"
const frameCount = Math.round(spec.duration * spec.fps);
const frames = (() => {
  if (!only) return [...Array(frameCount).keys()];
  const [a, b] = only.split('-').map(Number);
  return [...Array((b ?? a) - a + 1).keys()].map((k) => a + k);
})();
const pad = (n) => String(n).padStart(4, '0');
const mkdir = (p) => fs.mkdirSync(p, { recursive: true });
const run = (exe, args) => {
  const r = spawnSync(exe, args, { encoding: 'utf8', windowsHide: true, maxBuffer: 1 << 26 });
  if (r.status !== 0) throw new Error(`${exe} failed: ${r.stderr || r.error}`);
  return r.stdout;
};

const types = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml' };
function serve() {
  const server = http.createServer((req, res) => {
    const file = path.join(docs, decodeURIComponent(new URL(req.url, 'http://x').pathname));
    if (!file.startsWith(docs) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'content-type': types[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

async function withBrowser(fn) {
  const server = await serve();
  const base = `http://127.0.0.1:${server.address().port}/marketing/2026-10-render-test/`;
  const browser = await chromium.launch({ headless: true, executablePath: arg('--browser'),
    args: ['--no-first-run', '--ignore-gpu-blocklist', '--enable-gpu', '--use-angle=d3d11', '--enable-unsafe-swiftshader'] });
  try { return await fn(browser, base); } finally { await browser.close(); server.close(); }
}

// Screen textures: the photo, a generic Android viewer around it, and the real
// desktop Photos screen with that photo's tile emptied for the "before" state.
async function assets() {
  const dir = path.join(here, 'assets');
  mkdir(dir);
  await withBrowser(async (browser, base) => {
    const page = await browser.newPage();
    await page.goto(base + 'scene.json');
    const shot = async (name, w, h, html) => {
      await page.setViewportSize({ width: w, height: h });
      await page.setContent(`<!doctype html><html><body style="margin:0;background:transparent">${html}</body></html>`);
      await page.waitForTimeout(150);
      await page.screenshot({ path: path.join(dir, name), omitBackground: true });
    };
    const photo = `<div style="position:absolute;inset:0;background:linear-gradient(135deg,#a63c2e 0%,#c2754a 40%,#d9b468 75%,#e3d684 100%)"><div style="position:absolute;left:18%;top:20%;width:26%;height:26%;border-radius:50%;background:#bff3f1;box-shadow:0 0 60px #fff8"></div><div style="position:absolute;left:0;right:0;bottom:0;height:34%;background:linear-gradient(180deg,transparent,#5a1f1a99)"></div></div>`;
    await shot('photo.png', 1024, 1024, `<div style="position:relative;width:1024px;height:1024px;border-radius:28px;overflow:hidden">${photo}</div>`);
    const icon = (d) => `<svg viewBox="0 0 24 24" width="54" height="54" fill="none" stroke="#e8eaed" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
    await shot('phone-screen.png', 852, 1884, `<div style="position:relative;width:852px;height:1884px;border-radius:64px;overflow:hidden;background:#000;font-family:Roboto,'Segoe UI',sans-serif;color:#e8eaed">
      <div style="display:flex;justify-content:space-between;padding:34px 52px 0;font-size:34px;font-weight:500"><span>10:24</span><span>▾ ▴ ▮ 76%</span></div>
      <div style="display:flex;align-items:center;gap:30px;padding:56px 44px 0;font-size:36px">${icon('<path d="M15 18l-6-6 6-6"/>')}<span style="flex:1">Today · 10:21</span>${icon('<circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/>')}</div>
      <div style="position:absolute;left:0;right:0;top:470px;height:852px">${photo}</div>
      <div style="position:absolute;left:0;right:0;bottom:120px;display:flex;justify-content:space-around">
        ${icon('<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4"/>')}
        ${icon('<path d="M12 20h9M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/>')}
        ${icon('<path d="M20.8 4.6a5.5 5.5 0 00-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 00-7.8 7.8l1 1.1L12 21l7.8-7.5 1-1.1a5.5 5.5 0 000-7.8z"/>')}
        ${icon('<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>')}</div>
      <div style="position:absolute;left:50%;bottom:34px;width:220px;height:8px;margin-left:-110px;border-radius:4px;background:#e8eaed"></div></div>`);
    await shot('backdrop.png', 1600, 1000, `<div style="width:1600px;height:1000px;background:radial-gradient(520px 380px at 30% 34%,#0f4a5c 0%,transparent 100%),radial-gradient(620px 420px at 74% 30%,#2a2160 0%,transparent 100%),#04070c"></div>`);
    const screen = fs.readFileSync(path.resolve(here, spec.laptop.screen)).toString('base64');
    await shot('laptop-before.png', 2160, 1350, `<div style="position:relative;width:2160px;height:1350px"><img src="data:image/png;base64,${screen}" style="display:block">
      <div style="position:absolute;left:556px;top:452px;width:300px;height:348px;background:#091123"></div></div>`);
  });
  console.log('assets written to', dir);
}

async function three() {
  for (const [name, f] of [['story', spec.formats.story], ['still', spec.formats.still]]) {
    if (name === 'still' && only) continue;
    const dir = path.join(out, 'three', name);
    mkdir(dir);
    await withBrowser(async (browser, base) => {
      const page = await browser.newPage({ viewport: { width: f.width, height: f.height } });
      page.on('pageerror', (e) => console.error('page error:', e.message));
      await page.goto(`${base}threejs/index.html?format=${name}`);
      await page.waitForFunction(() => window.ready === true, null, { timeout: 120000 });
      console.log('webgl:', await page.evaluate(() => {
        const gl = document.querySelector('canvas').getContext('webgl2'); const ext = gl.getExtension('WEBGL_debug_renderer_info');
        return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : 'unknown'; }));
      const list = name === 'still' ? [Math.round(f.time * spec.fps)] : frames;
      const started = Date.now();
      for (const n of list) {
        await page.evaluate((t) => window.renderAt(t), n / spec.fps);
        await page.locator('canvas').screenshot({ path: path.join(dir, name === 'still' ? 'still.png' : `${pad(n)}.png`) });
      }
      const seconds = (Date.now() - started) / 1000;
      fs.writeFileSync(path.join(dir, 'timing.json'), JSON.stringify({ frames: list.length, seconds, perFrame: seconds / list.length }, null, 2));
      console.log(`three ${name}: ${list.length} frames in ${seconds.toFixed(1)} s`);
    });
  }
}

async function overlay() {
  await withBrowser(async (browser, base) => {
    for (const [name, f] of [['story', spec.formats.story], ['still', spec.formats.still]]) {
      const dir = path.join(out, 'overlay', name);
      mkdir(dir);
      const page = await browser.newPage({ viewport: { width: f.width, height: f.height } });
      await page.goto(`${base}overlay.html?w=${f.width}&h=${f.height}${name === 'still' ? '&still=1' : ''}`);
      await page.waitForFunction(() => window.ready === true);
      const list = name === 'still' ? [0] : [...Array(frameCount).keys()];
      for (const n of list) {
        await page.evaluate((t) => window.setTime(t), n / spec.fps);
        await page.screenshot({ path: path.join(dir, name === 'still' ? 'still.png' : `${pad(n)}.png`), omitBackground: true });
      }
    }
  });
  console.log('overlay frames written');
}

function composite() {
  for (const engine of ['three', 'blender']) {
    const story = path.join(out, engine, 'story');
    if (!fs.existsSync(path.join(story, '0000.png'))) { console.log(`skip ${engine}: no frames`); continue; }
    const mp4 = path.join(out, `${engine}-story.mp4`);
    run('ffmpeg', ['-y', '-loglevel', 'error', '-framerate', String(spec.fps), '-i', path.join(story, '%04d.png'),
      '-framerate', String(spec.fps), '-i', path.join(out, 'overlay', 'story', '%04d.png'),
      '-filter_complex', '[0][1]overlay=format=auto,format=yuv420p', '-c:v', 'libx264', '-preset', 'slow', '-crf', '16', '-movflags', '+faststart', mp4]);
    const still = path.join(out, engine, 'still', 'still.png');
    if (fs.existsSync(still)) run('ffmpeg', ['-y', '-loglevel', 'error', '-i', still, '-i', path.join(out, 'overlay', 'still', 'still.png'),
      '-filter_complex', '[0][1]overlay', path.join(out, `${engine}-still.png`)]);
    for (const t of [1.0, 4.6, 6.6, 9.6]) run('ffmpeg', ['-y', '-loglevel', 'error', '-ss', String(t), '-i', mp4, '-frames:v', '1', path.join(out, `${engine}-frame-${t}.png`)]);
    console.log('composited', engine);
  }
  // Side by side, labelled, at half size: the quickest way to compare.
  const pair = ['three', 'blender'].map((e) => path.join(out, `${e}-story.mp4`));
  if (pair.every((p) => fs.existsSync(p))) {
    const font = 'C\\:/Windows/Fonts/segoeuib.ttf';
    const label = (text) => `drawtext=fontfile='${font}':text='${text}':x=(w-tw)/2:y=h-th-28:fontsize=30:fontcolor=white:box=1:boxcolor=0x04070cb0:boxborderw=12`;
    run('ffmpeg', ['-y', '-loglevel', 'error', '-i', pair[0], '-i', pair[1], '-filter_complex',
      `[0]scale=540:960,${label('three.js')},pad=560:960:0:0:0x04070c[a];[1]scale=540:960,${label('Blender Cycles')}[b];[a][b]hstack,format=yuv420p`,
      '-c:v', 'libx264', '-crf', '20', '-movflags', '+faststart', path.join(out, 'side-by-side.mp4')]);
    console.log('side-by-side written');
  }
}

function compare() {
  const timing = (engine, name) => { try { return JSON.parse(fs.readFileSync(path.join(out, engine, name, 'timing.json'), 'utf8')); } catch { return null; } };
  const row = (engine, label) => {
    const t = timing(engine, 'story');
    const time = t ? `${t.frames} frames in ${(t.seconds / 60).toFixed(1)} min (${t.perFrame.toFixed(2)} s per frame)` : 'not rendered';
    return `<section><h2>${label}</h2><p>${time}</p><div class="pair"><video src="${engine}-story.mp4" controls loop muted playsinline></video><img src="${engine}-still.png" alt="${label} still"></div>
      <div class="frames">${[1.0, 4.6, 6.6, 9.6].map((s) => `<img src="${engine}-frame-${s}.png" alt="${label} at ${s} s">`).join('')}</div></section>`;
  };
  fs.writeFileSync(path.join(out, 'index.html'), `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Saiph render test</title><style>
    body{margin:0;background:#06090e;color:#e7edf4;font:16px/1.5 "Segoe UI",system-ui,sans-serif}main{max-width:1400px;margin:auto;padding:40px 24px}
    h1{font-size:40px;letter-spacing:-.02em;margin:0 0 8px}p{color:#9fb0c3}.pair{display:grid;grid-template-columns:360px 1fr;gap:24px;align-items:start}
    video,img{width:100%;display:block;border-radius:10px;background:#0d131b}.pair img{max-width:620px}.frames{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:16px}
    section{padding:28px 0;border-top:1px solid #1c2633}</style></head><body><main><h1>One ad, two renderers</h1>
    <p>Same scene file, camera path, screens and type layer. Only the 3D renderer differs.</p>
    <section><h2>Side by side</h2><video src="side-by-side.mp4" controls loop muted playsinline style="max-width:760px"></video></section>
    ${row('three', 'three.js (WebGL, headless Chrome)')}${row('blender', 'Blender 5.1 (Cycles, RTX 3060 Ti)')}</main></body></html>`);
  console.log('review page:', path.join(out, 'index.html'));
}

(async () => {
  if (step === 'assets') await assets();
  else if (step === 'three') await three();
  else if (step === 'overlay') await overlay();
  else if (step === 'composite') composite();
  else if (step === 'compare') compare();
  else throw new Error(`unknown step ${step}`);
})().catch((e) => { console.error(e); process.exit(1); });
