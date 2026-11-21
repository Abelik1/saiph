# Sources, skills and production notes

Research date: 19 October 2026. These sources ground the first exploration set. No conversion lift, market-size figures, user counts, testimonials or performance benchmarks are asserted.

## Product material inspected

- `AGENTS.md`, `CONTRIBUTING.md`, `docs/TESTING.md`: isolation, synthetic data, compatibility boundaries and accurate validation.
- `docs/POSITIONING.md`: existing message, owner-approved origin quote, landing copy, social variants and trademark guidance. It contains older availability language.
- `README.md`: current product description, Cloud/self-hosted table, platform scope, pricing, roadmap and acceptance limitations.
- `website/index.html`: current landing source and comparison with Apple Continuity and Phone Link. The current README and landing source use Cloud naming and revised pricing; the campaign omits prices.
- `docs/RELEASE_STATUS.md`, `docs/ACCEPTANCE_PENDING.md`: source changes versus recorded physical acceptance. Automated tests do not establish live demonstrations.
- `website/ANALYTICS.md`, `website/assets/analytics.js`: pageview-only boundary and query/fragment removal. No per-ad conversion tracking implied.
- `TRADEMARKS.md`, `website/assets/site.css`, `docs/DESKTOP_DESIGN_SYSTEM.md`: brand identity, existing colours and product design context.
- `website/assets/stage.js`: existing illustrative device animation; not used as real feature footage.
- `docs/images/readme/desktop-photos.png`: existing synthetic app design preview used unchanged in the clearly labelled self-hosted photo-browsing poster. Not a live acceptance capture.
- `website/assets/logo.svg`: original Saiph logo, copied unchanged.

Product source licences and upstream credit boundaries remain unchanged. New repository source carries the app/repository AGPL boundary. No private operations material, owner settings or service identifiers were copied.

## Current competitor references

Opened primary sources on 19 October 2026:

- [Apple: Continuity features and requirements](https://support.apple.com/en-us/108046). Supports discussion of compatibility among supported Apple devices. Does not support saying Apple has no useful cross-device features.
- [Microsoft: Phone Link requirements and setup](https://support.microsoft.com/en-us/windows/apps/phonelink/phone-link-requirements-and-setup). Supports discussion of Windows and phone requirements.
- [Microsoft: Seamlessly transfer content between devices](https://support.microsoft.com/en-us/windows/apps/phonelink/seamlessly-transfer-content-between-your-devices). Supports device-dependent clipboard and transfer comparisons. Recheck exact model/OS conditions if quoting specifics in a public comparison.

The public Saiph website could not be retrieved through the web tool in this session. The pack is grounded in repository content, with live availability/pricing explicitly unverified. No hosting service was operated or changed.

## Downloaded marketing skills

Installed into the user's existing Codex skills directory with the system skill-installer helper. Source: [Corey Haines' Marketing Skills](https://github.com/coreyhaines31/marketingskills), MIT-licensed. Download pinned to commit `365b412152b9542499ca1439426f7fc3cc92bb65`.

| Skill | Intended use |
| --- | --- |
| product-marketing | Reusable product/audience/voice context |
| copywriting | Concrete benefit copy and grounded claims |
| ad-creative | Distinct first-run angles, copy variants and falsifiable tests |
| ads | Later channel, measurement and paid-test planning |
| social | Recorded founder and short-form content |
| video | Programmatic motion production and demo scripts |
| marketing-plan | Available for a later full growth plan |

Applied ad-creative/video guidance to this first-run set and used copywriting principles to retain the existing maker voice. This is fresh concept development from product sources, not the skill's scaled-performance mode requiring winning ads/reviews. No winning ads or customer reviews were fabricated. A full growth-planning skill workflow was not run. A global shared marketing context was not created in the read-protected `.agents` directory; the campaign brief records context and assumptions in the authorized workspace instead.

The system presentation guidance informed the slide-like visual approach. No PowerPoint deck was requested as a specific file format or exported. Actual deliverables are locally encoded videos plus editable HTML/JSON compositions, static images, a carousel, a GIF and scripts. Cartoon phone/laptop shells, wallpapers and screen chrome reuse the existing landing-page CSS. The campaign screen states and transfer animations are synthetic illustrations, labelled in the artwork. All typography, device illustrations and transitions render from local code, with no generative video model or external rendering API.

## Plugin discovery

Marketing plugin search returned Canva, Windsor.ai, Klaviyo, Similarweb and other integrations. None was installed or connected. They are not required for this local campaign pack. Runway also appeared and was not used, consistent with the requested avoidance of a video AI generator.

No account connection, outbound message, ad publication, scheduling, budget change, analytics modification, install on an owner's device or production action was performed.

## Reproduction and validation

See `CAMPAIGN.md` for the render command, dependencies and export formats. The exported `checks/validation.json` records actual encoded sizes, lengths, frame rates and layout checks. Scene PNGs and review screenshots are in `checks/` for visual inspection. The output can be reproduced from the checked-in composition, manifest and renderer, using local browser/FFmpeg dependencies. Font rendering may differ across hosts.

Source/creative checks validate the campaign files only. They are not product acceptance, a source-history audit, ad-platform approval or a security review. No clip with a fabricated device session was produced. The real demo scripts require recording before they can become demonstration ads.

## Revision 3 feature illustrations

The latest README was re-read on 19 October while updating the plots. It now includes Cloud beta notification replies, image clipboard, group/MMS texts and phone controls. The films illustrate the broad workflows without promising unaccepted device results. Scene-specific qualifiers distinguish local webcam setup, call audio on the phone, self-hosted folder sync and the separately installed Deskflow integration. The rejected confrontational Apple headline is removed from active creative. Both master plots now run 32 seconds, with eight feature scenes apiece.

## Wave treatment and separate animation phases

The owner explicitly identified waves as Saiph's theme and requested clean large-headline-to-graphics handoffs. The background contour formula and cyan/light-cyan/violet colour vocabulary follow `frontend/src/workspace/waves.tsx` and `docs/DESKTOP_DESIGN_SYSTEM.md`. The current production `WaveField` is static; campaign motion is an advertising adaptation, not a claim about the app's current background behaviour. New `wave-art.js`/`.css` supply deterministic canvas/SVG waves. No app implementation was changed.

The v6 revision replaces the fast lateral sweep with a horizontal seam: 0.7 seconds of oscillation, followed by a 1.05-second centre-out curtain opening. The illustration clip and visible strings share the same wave geometry. These timings apply to the full stories and GIF; quick cuts run at double speed.
