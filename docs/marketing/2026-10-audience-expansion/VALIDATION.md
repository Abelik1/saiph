# Audience expansion validation

Windows, 19 October 2026. Marketing assets only; no product implementation changed.

## Final checks

- Rendered from local HTML/SVG/JavaScript in a fresh isolated headless Chromium context, using the existing Playwright dependency and local FFmpeg. No browser installation, generative image/video service or remote render API was used.
- Final command: `node docs/marketing/2026-10-audience-expansion/render.cjs`. The renderer uses the existing Chromium executable or an explicit `--browser` path.
- **54 layout cases passed**: sixteen portrait/square stills, eight carousel cards and six sampled times in each of five vertical animations. Checks cover headline/subtitle fit, artwork frame versus copy/footer overlap, and conservative vertical text bounds. Larger artwork uses more of the canvas while the headline and qualifiers remain in the text band.
- **Five final MP4s** verified by FFprobe: H.264/yuv420p, 1080 x 1920 at 30 fps. Three are 12 seconds / 360 frames each; two are 8 seconds / 240 frames each. All five decoded completely to null output with FFmpeg without errors. They have no audio tracks.
- **Two GIFs** verified at 540 x 960, 10 fps, 8 seconds each. They derive from the final everyday-link and cursor-journey videos.
- **24 PNG artwork files** passed size checks: sixteen stills (eight 1080 x 1350 and eight 1080 x 1080) plus eight 1080 x 1350 carousel cards.
- **24 editable SVGs** parsed as XML and contain their own illustrations and logo geometry, without remote images or font resources. UTF-8 checks passed for the authored punctuation and labels.
- The review passed overflow and filter checks at **1440 x 1000** and **390 x 844**. Motion, static and all-concept buttons showed five, three and eight cards respectively. All **70 local review references** resolve to exported files.
- Existing v3 review navigation into the new audience gallery passed on desktop and mobile, including filters and overflow. All four updated main-review locations resolve their 52 local references.
- Social headline/short-caption checks passed for all eight concepts. Search copy has **24 headlines of at most 30 characters** and **12 descriptions of at most 90 characters**, with recorded character counts checked against the actual text.
- Inspected the eight-concept contact sheet, creator and before/after artwork, and an actual encoded creator frame after the final enlargement. This is representative frame inspection and complete video decoding, not acceptance on every social platform.
- JavaScript syntax, source whitespace and `git diff --check` passed. The repository's limited reviewed-token scanner passed when run explicitly on campaign source files. This is not a credentials/history audit.

## Corrections during production

Preflight caught subtitle crowding in the square study artwork and an oversized creator illustration reaching the footer. The square heading was reduced and device compositions adjusted. The illustration viewport is explicitly clipped, with its intended frame used for page-layout checks. Review inspection also caught a punctuation encoding error introduced during a source rewrite; UTF-8 labels were corrected before final exports. Vertical device artwork was enlarged after the first successful render, and all final media/layout checks above were repeated for that revision.

## Scope and limits

All notes, alerts, links, screens and the landscape image are synthetic illustrations. They are not captured device sessions, measured transfers, customer results or testimonials. Recording scripts remain unrecorded. No physical phone, owner app, account, service, signing identity or advertising account was operated. No ads were uploaded, published or scheduled.

Existing beta/platform qualifiers and the creator Cloud-file and Deskflow/self-hosting requirements remain visible. The release record was checked; no currently disabled trial offer is advertised. These checks do not establish physical feature acceptance, security review, signed release status or platform approval. No product tests were rerun for this marketing-only work.
