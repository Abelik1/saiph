# Saiph: Your devices. Connected.

Campaign draft v6, 19 October 2026. English, Android with Windows/Linux, independent-maker tone. Nothing published or scheduled.

## Creative direction

The idea is the convenience people associate with a connected ecosystem, on the devices they already own. The lead hook is **Apple-style convenience? With your Android and PC.** It asks about a familiar benefit and immediately states the supported platforms.

The owner's revision calls for illustrated devices matching the landing page, less empty space and static text, and two plots whose graphics change to demonstrate the feature range. The earlier confrontational Apple hook is removed from the active creative, scripts and copy CSV.

The two master ads run 32 seconds each, with eight four-second scenes. Each also has a 16-second vertical quick cut, retaining all eight scenes at two seconds per scene. Each scene changes the screen content and action. Device entrances, continuous camera push/pull, parallax, animated typing, travelling content packets, call rings, photo reveals and a cursor crossing computers provide motion. One compact headline introduces each beat. Large phone, laptop and second-computer illustrations carry the explanation.

Device shells, wallpapers, windows and screen chrome reuse `website/assets/site.css`. The campaign adds deterministic synthetic screen states. These are labelled illustrated feature previews, not live product footage or measured transfer-speed demonstrations. No generative video service is used.

## Wave identity and scene rhythm

The owner identifies Saiph with waves, matching the app's string-field backgrounds. The campaign uses the cyan, light-cyan and violet palette and contour geometry from `frontend/src/workspace/waves.tsx`. The current app field is static; the advertising treatment adds timed drift, plucks, flowing device connections and horizontal wave curtains. An animated wave underline links the wordmark to that identity. Static exports use the same wave shapes in a frozen pose.

Every video beat has separate headline and feature phases. After the headline, horizontal strings oscillate across the middle for 0.7 seconds as the text fades toward the seam. The strings then part upward and downward over 1.05 seconds, revealing the enlarged illustrations through a matching wave-shaped opening. Smooth acceleration and deceleration soften the movement. This 1.75-second curtain replaces the previous 0.55-second sideways sweep. There is no persistent marketing headline beside every feature. Only the small brand/destination and relevant feature qualifiers remain. The call to action returns on the closing beat.

Feature-specific staging changes the composition: clipboard emphasizes the source phone, notifications foreground the laptop, photo sharing enlarges the phone, controls place the phone on the opposite side, and folder/keyboard scenes replace it with another computer. Moving image/document packets follow the wave connections. This avoids a repeated pair of fixed devices with only their text changing.

The full-story beats run four seconds each, allowing about 0.85 seconds for the headline, 1.75 seconds for the oscillation and curtain opening, and the remaining time for the feature action. The action begins during the opening and continues after it. The 16-second versions compress the same story. The renderer checks the headline, oscillating seam, partial opening and completed graphics reveal for every video scene. The full stories and GIF preserve the slower timing; the 16-second quick cuts play the entire composition at double speed.

## Plot A: That ecosystem feeling

| Time | Story beat | Picture and action |
| --- | --- | --- |
| 0–4s | Apple-style convenience? | Android phone and PC enter as a connected pair. |
| 4–8s | Copy here. Paste there. | Highlight text on Android, move a clipboard packet, type the same text on the laptop. |
| 8–12s | Your phone alerts. On your computer. | A reminder travels from phone to a computer notification. |
| 12–16s | From your camera to your computer. | A photo appears on Android and opens on the laptop. |
| 16–20s | Send it back. Keep going. | A PDF travels in the opposite direction, from computer to Android. |
| 20–24s | Your number. A real keyboard. | An incoming text and a reply appear on the computer and phone. |
| 24–28s | A call comes in. You choose. | The phone rings and the computer presents answer/decline controls. |
| 28–32s | Your devices. Connected. | Return to the connected pair and the Saiph destination. |

Text and call scenes retain beta/permissions qualifiers. The call scene explicitly says audio stays on the phone. This is an illustration of feature scope, not a claim of a completed physical acceptance run.

## Plot B: A day across your devices

| Time | Story beat | Picture and action |
| --- | --- | --- |
| 0–4s | One day. Your devices. | Establish the Android and Windows/Linux desk. |
| 4–8s | 09:00, your reminder | The phone reminder arrives on the computer. |
| 8–12s | 10:00, the video call | A matching cartoon camera view appears on phone and computer. |
| 12–16s | 12:30, phone controls | Show ringer, media, Do Not Disturb and a find-phone action. |
| 16–20s | 14:00, your next computer | Replace the phone with another computer and show a document in the synced folder. |
| 20–24s | 16:00, two computers | A cursor crosses computers while one keyboard stays in view. |
| 24–28s | 18:00, your own setup | Show the self-hosted Hub and its devices. |
| 28–32s | Keep your day moving | Return to Saiph and the supported platforms. |

Webcam uses local USB/Wi-Fi and needs desktop camera setup. Phone controls are beta. Folder sync requires a self-hosted Hub. Keyboard/mouse sharing requires that private-network setup plus separately installed Deskflow. The Hub scene explains that free self-hosting requires the owner's server and private network. Each condition appears on the relevant scene.

## Supporting creative

| Asset | Duration | Role |
| --- | --- | --- |
| 03, The email to yourself | 15s | Photo/file sharing pain point, changing photo and document scenes |
| 04, Linux deserves this too | 12s | Linux-specific identity, clipboard and notification scenes |
| 05, Your own Hub | 12s | Self-hosting, folder sync and Deskflow scenes |
| 06, Six seconds of Saiph | 6s | Clipboard action followed by the connected-device close |

Every concept has portrait and square static artwork. The pack also includes a four-frame clipboard carousel, a loop of Plot B, a static poster using the existing synthetic app design preview, and copy variants in `copy.csv`. The real clipboard zoom-out, optional mirroring reveal, founder story and photo-transfer films remain recording scripts.

## Product scope and evidence

The current README describes Saiph Cloud and self-hosted modes for Android, Windows 10/11 x64 and Linux x86_64. It lists clipboard, notifications, photos/files, texts, call controls, local webcam/microphone, phone controls, self-hosted folder sync and Deskflow integration. Feature coverage in this pair follows those categories; installer updates are not a separate story scene.

The README changed during campaign work. It now lists Cloud at EUR 9.99 monthly / EUR 89.99 yearly and additional beta parity features. The ads remain price-free. Device/OS permissions and physical acceptance limitations still apply. The campaign makes no iPhone/Mac support claim and no independent-audit or computer-call-audio claim. No owner device, account or private operations material was used.

The origin quote remains source material in `docs/POSITIONING.md`, but the revised ads do not use it. They also do not promise superiority over every Apple/Microsoft feature. Current Apple/Microsoft documentation is linked in `SOURCES.md`; comparative wording remains about the ecosystem idea and supported devices.

## Recommended first test

Compare Plot A and Plot B in the same audience and placement. A asks whether ecosystem convenience attracts attention; B asks whether the day-in-the-life structure makes the use cases clearer. Compare completion rate, outbound clicks per impression and the questions people ask. These are hypotheses, not measured results.

Use the shorter feature-specific cuts after learning which demonstrations people understand. Record the real clipboard reveal as the next proof asset, keeping the phone and computer visible together through the transfer. Do not use cartoon animation as acceptance evidence.

Budget, selected geography/platform and historical conversion performance are MISSING. No spend is authorized or initiated by this pack. For an eventual paid pilot, choose a fixed total loss limit and an end date before launching. Keep the platform, audience and offer consistent when comparing narratives.

The website analytics source removes queries/fragments and does not provide account, checkout or activation events. Platform creative IDs and aggregate impressions/views/clicks can be logged in `results-template.csv`; a UTM field alone does not establish subscription attribution. No tracking boundary was changed. Customer acquisition cost and retained activation remain unmeasured.

## Editable source and reproduction

- `campaign.json`: copy, scene timing, feature kind, direction and scene-specific qualifier.
- `motion.html`: text composition and deterministic timeline.
- `device-art.js`: synthetic screen states, device camera motion and animated feature actions.
- `device-art.css`: graphic layout and campaign presentation.
- `wave-art.js` and `wave-art.css`: deterministic string-field backgrounds, device wave paths, wave-shaped reveals and horizontal curtain transitions.
- `render.cjs`: isolated browser screenshots, local encoding and validation. It extracts the website's device styles to exported `assets/landing-devices.css`.

From the repository root, with existing frontend Playwright dependencies, Chromium and FFmpeg/FFprobe available:

```powershell
node docs/marketing/2026-10-campaign/render.cjs --out build/marketing-campaign-20261019-v6 --browser C:/path/to/chrome.exe
```

The renderer does not install a browser or operate the product app. It starts a loopback-only asset server and a fresh headless browser context. The output contains six vertical master MP4s, two landscape master MP4s, two vertical quick-cut MP4s, thirteen static images, four carousel frames, six video-poster thumbnails, a GIF, a contact sheet, two full storyboards, the review page, copy CSV and documents. Vertical video is 1080 x 1920, landscape is 1920 x 1080, H.264/yuv420p at 30 fps. Portrait images are 1080 x 1350 and square images are 1080 x 1080. The GIF is 540 x 960 at 10 fps.

`--preflight` checks every scene and exports scene snapshots without encoding. `--resume` reuses completed exports only when the composition, device artwork and manifest still match the previous run. `--stills-only` produces artwork and the review shell; full video links require the full render. The CSV is an editorial handoff, not a platform-specific bulk-import file. Important copy and feature qualifiers stay in the conservative vertical text safe area. Check the chosen platform's current overlays before publication.

Facts: source material describes the named feature categories and their mode/permission limits. Hypotheses: the two narratives may appeal to different motivations. Missing: physical acceptance, current public destination verification, platform upload acceptance and performance data.
