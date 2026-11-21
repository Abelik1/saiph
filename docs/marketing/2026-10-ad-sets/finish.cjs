// Finishes the ad sets: composites the caption layer over each Blender render into
// the 9:16 hero MP4 with its soundtrack (sound.cjs), cuts one short video per
// feature ("cuts" in sets/<set>.json), composites the 4:5 and 1:1 stills, and
// writes a review page grouped by what each set tests.
//
//   node docs/marketing/2026-10-ad-sets/finish.cjs --root build/ad-sets [--sets a,b,c]
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : fallback; };
const root = path.resolve(arg('--root', 'build/ad-sets'));
const sets = arg('--sets', 'a,b,c').split(',');
const here = __dirname;
const run = (args) => {
  const r = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', ...args], { encoding: 'utf8', windowsHide: true });
  if (r.status !== 0) throw new Error(r.stderr);
};
const out = path.join(root, 'final');
fs.mkdirSync(out, { recursive: true });
const drafts = [];
const story = (f) => /^\d{4}\.png$/.test(f);

for (const s of sets) {
  const spec = JSON.parse(fs.readFileSync(path.join(here, 'sets', `${s}.json`), 'utf8'));
  const total = Math.round(spec.duration * 30);
  const frames = path.join(root, s, 'render', 'story');
  // A draft (render-draft/story, rendered with --scale 50) picks up where the full frames stop.
  const draft = path.join(root, s, 'render-draft', 'story');
  const full = fs.existsSync(frames) ? fs.readdirSync(frames).filter(story).length : 0;
  const drafted = full < total && fs.existsSync(path.join(draft, `${String(full).padStart(4, '0')}.png`));
  const mix = path.join(root, s, 'mix.wav');
  const sound = fs.existsSync(mix);
  if (full || drafted) {
    const hero = path.join(out, `${s}-hero-9x16.mp4`);
    const pieces = [];
    const inputs = [];
    if (full) { inputs.push('-framerate', '30', '-i', path.join(frames, '%04d.png')); pieces.push(`[${pieces.length}]setsar=1[p${pieces.length}]`); }
    if (drafted) { inputs.push('-framerate', '30', '-start_number', String(full), '-i', path.join(draft, '%04d.png')); pieces.push(`[${pieces.length}]scale=1080:1920:flags=lanczos,setsar=1[p${pieces.length}]`); }
    const n = pieces.length;
    inputs.push('-framerate', '30', '-i', path.join(root, s, 'overlay', '%04d.png'));
    if (sound) inputs.push('-i', mix);
    const graph = [...pieces, `${pieces.map((_, i) => `[p${i}]`).join('')}concat=n=${n}:v=1:a=0[v]`, `[v][${n}]overlay=format=auto,format=yuv420p[out]`].join(';');
    run([...inputs, '-filter_complex', graph, '-map', '[out]', ...(sound ? ['-map', `${n + 1}:a`, '-c:a', 'aac', '-b:a', '192k'] : []),
      '-frames:v', String(total), '-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-movflags', '+faststart', hero]);
    if (drafted) drafts.push(s.toUpperCase()), console.log(`${s}: frames ${full} on are a half-size draft`);
    // Feature cut-downs: [start, end] pieces of the hero, joined, so each tests one feature.
    for (const cut of spec.cuts || []) {
      const v = cut.parts.map(([a, b], i) => `[0:v]trim=${a}:${b},setpts=PTS-STARTPTS[v${i}]`);
      const a = sound ? cut.parts.map(([x, y], i) => `[0:a]atrim=${x}:${y},asetpts=PTS-STARTPTS,afade=t=in:d=0.04,afade=t=out:st=${(y - x - 0.06).toFixed(2)}:d=0.06[a${i}]`) : [];
      const joins = cut.parts.map((_, i) => `[v${i}]${sound ? `[a${i}]` : ''}`).join('');
      run(['-i', hero, '-filter_complex', [...v, ...a, `${joins}concat=n=${cut.parts.length}:v=1:a=${sound ? 1 : 0}[cv]${sound ? '[ca]' : ''}`, '[cv]format=yuv420p[ov]'].join(';'),
        '-map', '[ov]', ...(sound ? ['-map', '[ca]', '-c:a', 'aac', '-b:a', '192k'] : []), '-c:v', 'libx264', '-crf', '17', '-movflags', '+faststart', path.join(out, `${s}-${cut.id}-9x16.mp4`)]);
    }
    console.log(`${s}: hero and ${(spec.cuts || []).length} cuts${sound ? ' with sound' : ', silent'}`);
  } else console.log(`${s}: no story frames yet`);
  for (const [format, still] of Object.entries(spec.stills)) {
    const names = [`still-${still.time}.png`, `still-${Number(still.time).toFixed(1)}.png`];
    const render = ['render', 'render-draft'].flatMap((d) => names.map((n) => path.join(root, s, d, format, n))).find((p) => fs.existsSync(p));
    const layer = path.join(root, s, 'overlay-stills', `${format}.png`);
    if (render && fs.existsSync(layer)) {
      run(['-i', render, '-i', layer, '-filter_complex', '[0][1]overlay', path.join(out, `${s}-${format === 'portrait' ? '4x5' : '1x1'}.png`)]);
      console.log(`${s}: ${format} still`);
    }
  }
}

// Review page: one section per set, grouped by what it tests, with every cut named the
// way it should be named in Ads Manager so results map back to a set and a feature.
const esc = (x) => String(x).replace(/&/g, '&amp;').replace(/</g, '&lt;');
// Every set with a finished hero, even when this run only rebuilt some of them.
const listed = fs.readdirSync(path.join(here, 'sets')).map((f) => f.replace('.json', '')).filter((s) => fs.existsSync(path.join(out, `${s}-hero-9x16.mp4`)));
const cards = listed.map((s) => {
  const spec = JSON.parse(fs.readFileSync(path.join(here, 'sets', `${s}.json`), 'utf8'));
  const c = spec.copy;
  const cuts = (spec.cuts || []).map((cut) => {
    const secs = cut.parts.reduce((n, [a, b]) => n + b - a, 0).toFixed(1);
    return `<figure><video src="${s}-${cut.id}-9x16.mp4" controls playsinline loop preload="metadata"></video><figcaption><b>${esc(cut.feature)}</b> · ${secs} s<br><code>saiph-${s}-${cut.id}</code></figcaption></figure>`;
  }).join('');
  return `<section><div class="head"><h2>${esc(spec.name)}</h2><span class="group">${esc(spec.group || '')}</span></div>
    <p>${esc(spec.angle || '')}</p><ul class="features">${(spec.features || []).map((f) => `<li>${esc(f)}</li>`).join('')}</ul>
    <div class="row"><figure><video src="${s}-hero-9x16.mp4" controls playsinline loop preload="metadata"></video><figcaption><b>Hero</b> · 9:16 · ${spec.duration} s<br><code>saiph-${s}-hero</code></figcaption></figure>
    <div class="stills"><img src="${s}-4x5.png" alt="${esc(spec.name)} 4:5 still"><img src="${s}-1x1.png" alt="${esc(spec.name)} 1:1 still"><figcaption>4:5 and 1:1 · <code>saiph-${s}-static</code></figcaption></div>
    <dl><dt>Primary text</dt><dd>${esc(c.primary)}</dd><dt>Headline</dt><dd>${esc(c.headline)}</dd><dt>Description</dt><dd>${esc(c.description)}</dd></dl></div>
    <h3>One feature per cut</h3><div class="cuts">${cuts}</div></section>`;
}).join('');
fs.writeFileSync(path.join(out, 'index.html'), `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Saiph ad sets</title><style>
  body{margin:0;background:#06090e;color:#e7edf4;font:16px/1.5 "Segoe UI",system-ui,sans-serif}main{max-width:1500px;margin:auto;padding:36px 24px}
  h1{font-size:38px;margin:0 0 6px;letter-spacing:-.02em}h2{font-size:26px;margin:0}h3{font-size:18px;margin:26px 0 12px;color:#cbd5e1}p{color:#9fb0c3;margin:6px 0}
  section{border-top:1px solid #1c2633;padding:28px 0}.head{display:flex;gap:14px;align-items:center;flex-wrap:wrap}
  .group{padding:4px 12px;border-radius:999px;background:#0e2a33;color:#67e8f9;font-size:14px;font-weight:600}
  .features{display:flex;flex-wrap:wrap;gap:8px;padding:0;margin:10px 0 18px;list-style:none}.features li{padding:3px 10px;border-radius:8px;background:#121b27;color:#cbd5e1;font-size:14px}
  .row{display:grid;grid-template-columns:300px 300px 1fr;gap:24px;align-items:start}.cuts{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:18px}
  video{width:100%;border-radius:12px;background:#0d131b;aspect-ratio:9/16}figure{margin:0}figcaption{color:#9fb0c3;font-size:14px;margin-top:6px}code{color:#a5f3fc;font-size:13px}
  .stills{display:grid;gap:12px}.stills img{width:100%;border-radius:10px}dt{color:#67e8f9;font-size:13px;text-transform:uppercase;letter-spacing:.06em;margin-top:10px}dd{margin:2px 0 0}dl{margin:0}
  @media(max-width:900px){.row{grid-template-columns:1fr 1fr}}</style></head><body><main>
  <h1>Saiph Cloud ad sets</h1><p>Rendered in Blender with real Saiph screens from the design preview (synthetic data). Sound: ElevenLabs voice, effects and music (sound.cjs).
  Each set tests one group; each cut tests one feature. Use the code under each video as the ad name and utm_content.${drafts.length ? ` <b>Draft:</b> set ${drafts.join(', ')} uses quick half-size frames; stills are full quality.` : ''}</p>${cards}</main></body></html>`);
console.log('review page:', path.join(out, 'index.html'));
