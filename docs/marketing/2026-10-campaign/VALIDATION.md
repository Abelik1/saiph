# Campaign v6 export validation

Windows, 19 October 2026. This record covers marketing assets only.

## Final checks

- Completed a fresh isolated Chromium preflight, then a complete v6 export using Playwright frame capture and local FFmpeg encoding. No generative video service was used.
- Final render command: `node docs/marketing/2026-10-campaign/render.cjs --out build/marketing-campaign-20261019-v6 --browser <existing Chromium executable>`.
- FFprobe verified **10 ad MP4 files**, all H.264/yuv420p at **30 fps**: six 1080 x 1920 vertical masters, two 1920 x 1080 landscape masters, and two 1080 x 1920 vertical quick cuts. Main stories run 32 seconds; quick cuts run exactly 16 seconds / 480 frames. Supporting ads run 15, 12, 12 and 6 seconds.
- An additional eight-second 540 x 960 H.264/yuv420p preview shows the revised curtain over the first two story beats.
- FFmpeg decoded all ten ad MP4s and the preview to null output without errors.
- FFprobe verified the full-story GIF at **540 x 960**, **10 fps**, **32 seconds**.
- **59 layout cases** passed across stills, carousel frames and video scenes, covering headline fit, illustration and footer bounds, screen-content overflow, and conservative vertical text safe areas.
- **43 four-stage curtain checks** passed across all video scenes and formats: headline visible with dim graphics; horizontal seam visible while oscillating; headline gone with illustration partially clipped during opening; illustration fully revealed with the curtain gone. Each scene uses its own timing offsets.
- The full stories and GIF use **0.7 seconds of oscillation followed by a 1.05-second opening**. Both curtain edges part vertically from a horizontal seam. The illustration clip and visible strings share the same geometry, with smooth acceleration and deceleration. Quick cuts run the entire story at double speed, including transitions.
- Inspected portrait oscillation and opening snapshots, a landscape opening, and an actual encoded GIF opening frame. The final video also supplied the short motion preview. This is visual frame inspection and full decoding, not playback acceptance on every target platform.
- PNG dimensions passed for **17 artwork images**: thirteen stills and four carousel frames. Six video-poster thumbnails and two 2000 x 720 storyboards were exported.
- The review rendered at 1440 x 1000 and 390 x 844. Mobile overflow check passed. All 52 local review references resolve to exported files.
- JavaScript syntax checks passed for `device-art.js`, `wave-art.js` and `render.cjs`. Source whitespace and `git diff --check` passed.
- The repository's reviewed-token scanner passed when called explicitly on campaign source files. This is a limited identifier-token check, not a credentials or history audit.

## Revision scope

The v6 curtain replaces the v5 fast lateral wave sweep. Feature action now starts during the opening, so it remains visible after the devices are unveiled. Earlier exports do not establish acceptance of this revision; the v6 files were freshly rendered and decoded.

The films use synthetic illustrations styled with the landing page's existing device CSS. Background contours adapt the app's current static wave field; motion is added for the advertisements. They do not show a physical device run or measured transfer speed. Real clipboard, mirroring and file-transfer films remain recording scripts.

No product implementation, owner app, physical device, account, live service, signing identity or advertising account was operated. No campaign was published or scheduled. Product unit tests were not rerun for this marketing-only change. These checks do not establish product acceptance, independent security review, signing or ad-platform approval. Existing feature qualifiers remain in place.

Videos are silent. No recorded voice or music licence is included. Platform upload acceptance and placement overlays require checking for the selected placement.
