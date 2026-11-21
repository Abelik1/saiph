# Saiph: eight ways in

Audience expansion, 19 October 2026. Adds to the existing ecosystem stories. English, Android with Windows/Linux. Draft assets only; nothing published or scheduled.

## What changes

Lead with an everyday situation people recognise, then show one useful connection. Technical buyers still get specific material, but operating-system comparisons no longer carry the whole campaign. These are eight distinct concepts, rather than eight text swaps over the same animation.

| Audience | Need and opening hook | Creative treatment | Finished assets |
| --- | --- | --- | --- |
| Students and learners | Notes on a phone, a draft on a computer. “Your notes have places to be.” | Three-panel comic, panels enter in sequence | 12s motion, portrait/square stills, study carousel |
| Creators and hobby photographers | A phone photo needs to reach the next edit. “Shot on your phone. Ready for the edit.” | Reverse zoom from a large illustrated photo into a phone-to-computer composition | 12s motion, portrait/square stills |
| Writers, freelancers and personal desk users | A reminder can appear on the screen already in use. “Stay with your screen.” | A notification moves into a desktop scene | 12s motion, portrait/square stills |
| Everyday phone/PC users | Emailing oneself a link. “Still emailing yourself links?” | An email detour beside a direct clipboard route | 8s motion, GIF loop, portrait/square stills |
| Mixed Windows/Linux desk users | Two computers share input. “Two computers. One set of hands.” | Cursor journey between two computers, with the integration labelled | 8s motion, GIF loop, portrait/square stills |
| Home-server enthusiasts | Running the connection oneself. “Your desk. Your own Hub.” | Blueprint topology with a phone, computer and server | Portrait/square stills |
| Newcomers | Basic compatibility. “Android. PC. Yes, together.” | Device constellation and plain-language FAQ cards | Portrait/square stills, first-look carousel |
| People who like their current setup | Connect devices already owned. “Love your devices? Keep them.” | Bold device poster | Portrait/square stills |

The creator image is an original vector landscape illustration, not a photograph or customer portfolio. All interface content is synthetic. The motion treatments deliberately differ: comic sequencing, reverse zoom, notification travel, split-screen emphasis and a cursor journey. They retain cyan/violet waves, dark device shells and the original Saiph mark. Light paper treatments give study and newcomer artwork a different feed presence. Existing main-campaign wave-curtain transitions remain available in the earlier stories.

## Copy and format handoffs

- `copy.csv` has eight social ad concepts, audience/format labels, primary copy, short captions, alternate hooks in the review, feature scope, source grounding and a falsifiable test hypothesis.
- `search-copy.csv` has three intent groups: cross-device clipboard, phone photo transfer, and Android/Linux connection. Each has eight independent headlines and four descriptions. Headline and description lengths are checked against Google's 30/90-character limits. This is editorial copy, not an Ads Editor import or a live campaign.
- `RECORDING-SCRIPTS.md` has three 15–20-second scripts for real phone/computer demos, with shot timings and alternate openings. These require recording; illustrations are not substituted for genuine product footage.
- `results-template.csv` provides one blank tracking row per concept; no results or performance figures are prefilled.
- Static PNGs are 1080 x 1350 and 1080 x 1080. Matching SVGs are standalone and editable. Motion MP4s are 1080 x 1920 at 30 fps. Two GIF loops are 540 x 960 at 10 fps. The two four-card carousels are 1080 x 1350.

## Feature guardrails

The main proposition stays within Android, Windows and Linux. No iPhone, Mac, Chromebook, universal hardware support, shared team workspace, remote access, productivity measurement, customer endorsement or device replacement claim is implied.

Creator material describes sending a photo to a computer, not an automatic edit/import into creative software. The Cloud relay limit of 19.9 MB is visible in that concept; larger same-network direct transfers are documented in the product sources. Study material does not promise a student discount or a free hosted plan. Notifications require Android notification access. Keyboard/mouse sharing requires separately installed Deskflow and a self-hosted Hub/private network. Self-hosted posters explicitly state the server/network requirement. No new encryption or security-superiority claims are added.

The current README and release status take precedence over older positioning drafts where feature availability has changed. Text/call beta and local webcam remain in the existing campaign; this expansion concentrates on the core workflows and clearly qualified self-hosted integration.

## Suggested first test

Start with the everyday-link loop, creator photo story and newcomer compatibility card. This is a hypothesis about approachable entry points, not evidence of audience demand or predicted performance. Test the student comic and desk-notification ad as separate audience/placement experiments. Keep homelab and Deskflow creative together with the relevant self-hosting destination and requirement; do not use them to imply those features are included in the hosted plan.

Within each test, change one factor at a time: hold audience, destination, offer and placement constant when comparing creative. Use the same attribution window and conversion event. Compare landing-page visit rate for the general concepts, completed-view rate for matched motion concepts, and self-hosting-guide click rate for the advanced concepts. Each creative's CSV/review specifies its comparator and expected direction. Cross-audience results alone do not establish that one design is better.

Inspect actual release readiness, landing-page consistency and placement previews before any upload. The current source still identifies beta features and pending physical acceptance. This work does not publish, set budgets, install tracking or connect an ad account.

**Facts:** product feature/platform scope is grounded in repository documents; these files are finished creative drafts. **Hypotheses:** the audience/need pairings and expected test outcomes. **MISSING:** campaign performance, customer interviews/reviews, geographic scope, spend limits, conversion instrumentation and acquisition targets. No audience sizes, ROAS, CPA or performance claims have been invented.

## Reproduce the artwork

From this repository, use `node docs/marketing/2026-10-audience-expansion/render.cjs`. The renderer uses the existing frontend Playwright dependency, an already installed Chromium executable and local FFmpeg/FFprobe. Pass `--browser C:/path/to/chrome.exe` if needed. `--preflight` exports and checks layouts without encoding; `--resume` can reuse complete MP4s only when the visual sources match; `--review-only` refreshes documents and the gallery. It uses an isolated headless browser and loopback asset server, and does not launch the product app or operate a phone.
