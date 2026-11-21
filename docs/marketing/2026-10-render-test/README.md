# Renderer test: one ad in three.js and Blender

Draft for owner review, 27 October 2026. Nothing is published or scheduled.

One 10-second vertical ad and one 4:5 still, built twice from the same source to
decide whether the campaign needs Blender's realism or whether three.js is enough.

**Story.** "Shot on your phone." A photo leaves an Android phone along a lit
string, Saiph's wave identity, while the string field below ripples. "Already on
your PC." It lands in the first tile of the real desktop Photos screen
(`docs/images/readme/desktop-photos.png`, synthetic demo data). End card: Saiph,
"Your devices. Connected.", Android · Windows · Linux, 14 days free · usesaiph.com.

Claim check: the desktop Photos tab lists recent phone photos, so "Already on
your PC" describes a shipped feature. The phone screen is a generic gallery
mock-up, not Saiph's Android UI, and the devices are generic, with no Apple imagery.

## What is shared and what differs

| Shared by both | three.js only | Blender only |
| --- | --- | --- |
| `scene.json`: devices, camera path, timing, colours | WebGL in headless Chrome | Cycles path tracing on the GPU (OptiX) |
| `motion.js` / `blender/motion.py`: identical motion maths | Bloom and depth of field as screen passes | Real depth of field, motion blur, glossy screen glass |
| `assets/`: screen textures and backdrop | Environment-map reflections only | Strings and bead reflect in the screens |
| `overlay.html`: the type layer composited over both | | Compositor bloom |

## Reproduce

From the repository root, with `npm install` run in this folder (three.js), the
frontend's Playwright, FFmpeg and Blender 5.1:

```bash
node docs/marketing/2026-10-render-test/render.cjs --out build/render-test --step assets
node docs/marketing/2026-10-render-test/render.cjs --out build/render-test --step three
"C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" -b --factory-startup -P docs/marketing/2026-10-render-test/blender/scene.py -- --out build/render-test --format story --samples 64
"C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" -b --factory-startup -P docs/marketing/2026-10-render-test/blender/scene.py -- --out build/render-test --format still --samples 128
node docs/marketing/2026-10-render-test/render.cjs --out build/render-test --step overlay
node docs/marketing/2026-10-render-test/render.cjs --out build/render-test --step composite
node docs/marketing/2026-10-render-test/render.cjs --out build/render-test --step compare
```

`--frames 138` or `--frames 0-60` renders part of the story for quick checks.
Everything runs headless; no window opens.
