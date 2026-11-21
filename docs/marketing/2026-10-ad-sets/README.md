# Saiph Cloud ad sets (October 2026)

Three test sets for Saiph Cloud, built in Blender with real Saiph screens.
Draft for owner review; nothing is published or scheduled. Add `--scale 50
--samples 16` to a Blender command for a quick half-size draft.

- [STRATEGY.md](STRATEGY.md): proposition, claims check, the three sets, test design
- [AUDIENCE.md](AUDIENCE.md): markets, ages, platform shares, rough costs, first test

| Set | Group (what it tests) | Hero | One cut per feature | Stills |
| --- | --- | --- | --- | --- |
| A | Phone on your PC: codes, texts, calls, screen mirroring, camera as webcam | 26 s | code, text, call, mirror, camera | 4:5, 1:1 |
| B | Clipboard & photos: phone → PC, PC → phone, pictures | 12 s | clipboard, back, photos | 4:5, 1:1 |
| C | Pain point: the daily workarounds, then the glass between the devices shatters | 17.5 s | rituals, paste, code | 4:5, 1:1 |

Every video has a voiceover, sound effects and music from ElevenLabs
(`sound.cjs`); captions stay burned in for sound-off viewing. The names under
each video on the review page are the ad names to use in Ads Manager (see
[STRATEGY.md](STRATEGY.md#5-the-test)).

## How it's made

1. **Real UI.** `capture-ui.cjs` photographs the desktop app's design preview
   (`frontend/preview.html?cloud=1`, synthetic data) at 1280 x 800, 1.5x scale,
   including real typing in the message box and the incoming-call banner.
   `?cloud=1` drops what Saiph Cloud doesn't have yet (Copy code, Hub suggestions).
2. **Screens over time.** `screens/*.html` place those captures with generic
   stand-ins (a bank sign-in, mail, a document, Android surfaces). `render-screen.cjs`
   renders each to a PNG sequence that Blender plays on the device screens.
3. **Blender.** `blender/kit.py` holds the shared pieces: real-size phone and
   laptop, backlit keyboard, walnut desk, light strings, camera, bloom, render
   loop. `blender/set_a.py`, `set_b.py` and `set_c.py` build each set. Set C's
   pane is a Voronoi fracture with scripted slow-motion physics, so every render
   is identical.
4. **Captions.** `overlay.html` reads `sets/<set>.json` (captions, end card,
   stills, ad copy) and renders a transparent layer inside the Reels/TikTok safe area.
5. **Sound.** `sound.cjs` reads the `audio` block of `sets/<set>.json` (voice
   lines with start times, sound effects, a music prompt), generates each clip
   with the ElevenLabs API, caches it under `build/ad-sets/audio-cache`, and
   mixes `build/ad-sets/<set>/mix.wav`. It warns when a line overlaps the next
   or runs past the end. The key comes from `ELEVENLABS_API_KEY`; never commit it.
6. **Finish.** `finish.cjs` composites picture, captions and sound, cuts one
   video per feature (`cuts`), builds the stills and a review page.

## Reproduce

Start the frontend dev server (port 5199), then from the repository root:

```bash
node docs/marketing/2026-10-ad-sets/capture-ui.cjs --out build/ad-sets/ui
node docs/marketing/2026-10-ad-sets/render-screen.cjs --page screens/a-phone.html --out build/ad-sets/a/phone --width 900 --height 1970 --duration 26
node docs/marketing/2026-10-ad-sets/render-screen.cjs --page screens/a-laptop.html --out build/ad-sets/a/laptop --duration 26
node docs/marketing/2026-10-ad-sets/render-screen.cjs --page screens/b-phone.html --out build/ad-sets/b/phone --width 900 --height 1970 --duration 12
node docs/marketing/2026-10-ad-sets/render-screen.cjs --page screens/b-laptop.html --out build/ad-sets/b/laptop --duration 12
node docs/marketing/2026-10-ad-sets/render-screen.cjs --page screens/c-laptop.html --out build/ad-sets/c/laptop --duration 17.5
node docs/marketing/2026-10-ad-sets/render-screen.cjs --page screens/c-phone.html --out build/ad-sets/c/phone --width 900 --height 1970 --duration 17.5
node docs/marketing/2026-10-ad-sets/render-screen.cjs --page "screens/c-phone.html?far=1" --out build/ad-sets/c/phone-far --width 900 --height 1970 --duration 1 --frames 0-0
"C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" -b --factory-startup -P docs/marketing/2026-10-ad-sets/blender/set_a.py -- --format story
"C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" -b --factory-startup -P docs/marketing/2026-10-ad-sets/blender/set_a.py -- --format portrait --time 16.9 --samples 128
node docs/marketing/2026-10-ad-sets/render-screen.cjs --page "overlay.html?set=a&w=1080&h=1920" --out build/ad-sets/a/overlay --width 1080 --height 1920 --duration 26 --transparent
ELEVENLABS_API_KEY=... node docs/marketing/2026-10-ad-sets/sound.cjs --root build/ad-sets
node docs/marketing/2026-10-ad-sets/finish.cjs --root build/ad-sets
```

Sets B and C follow the same pattern (see the usage line at the top of each
script); still times are in `sets/<set>.json`. A full 9:16 hero takes about
25–35 minutes on an RTX 3060 Ti at 64 samples when rendered alone.
