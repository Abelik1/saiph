# Saiph Cloud ads: strategy and three test sets

Draft for owner review, 28 October 2026 (round 2: feature groups, sound,
reworked A and C). Nothing is published or scheduled. Renderer: Blender (decided after `docs/marketing/2026-10-render-test`).

## 1. What we sell, to whom, and why they'd care

**Offer.** Saiph Cloud: 14 days free, then €9.99/month (card required, cancel
before the trial ends). Destination: usesaiph.com → Start your free trial.

**Who.** People who sit at a Windows or Linux computer most of the day with an
Android phone next to it. Three slices worth separate creative:

| Slice | Their situation | What moves them |
| --- | --- | --- |
| Desk workers and students | The phone buzzes, they pick it up, 10 minutes vanish; sign-in codes and links live on the wrong device | Fewer interruptions, faster small tasks |
| Ecosystem-envious Android users | They've watched iPhone + Mac owners copy and paste across devices and think that's a reason to switch | Getting that without buying new hardware |
| Windows/Linux enthusiasts | Tried Phone Link or KDE Connect, found gaps (Linux, reliability, clipboard) | It works on their setup, and they control it |

**The insight the current ads miss.** "Send a file" is a feature. What people
pay for is **not having to pick up the phone while working**. The phone
becomes part of the computer. Each ad should show the moment a hand
*would* reach for the phone, and doesn't.

**Single-minded proposition:** *Your phone, on your PC.*

## 2. What we can show (claims check)

Only what Saiph Cloud does today. Sources: README feature table,
`docs/PHONE_LINK_PARITY.md`, `docs/RELEASE_STATUS.md`.

| Moment | On Cloud | Evidence | Use as |
| --- | --- | --- | --- |
| Copy on phone → Ctrl+V on PC, and back | Yes, text and images | Physically verified Windows/Android, both ways | **Hero** |
| Phone notification appears on PC, dismiss it there | Yes | Built; physical checks passed | Hero |
| Sign-in code arrives as a notification on the PC | Yes (the notification shows its text) | Cloud notifications | Hero, as "the code is already on your screen" |
| **Copy code** button on a code notification | **Self-hosted only** today: Cloud notifications skip the code detector (`hosted_runtime.py` vs `phone.py`) | Source check 28 Oct | Do not show in Cloud ads until Cloud has it |
| Reply to a text from the keyboard | Beta | Built, physical acceptance pending | Supporting, labelled beta |
| See a call, decline from the PC (audio stays on phone) | Beta | Same | Supporting, labelled beta |
| Send a photo/file either way | Yes, ≤19.9 MB via Cloud | Built | Supporting |
| Ring phone, Do Not Disturb sync, media pauses on calls | Beta / built | User guide | Optional bumpers |
| Screen mirroring: the phone's screen in a window, controlled from the PC | Yes, over USB or the same Wi-Fi (wireless or USB debugging) | Phone Link parity table, item J | Hero in Set A, with the USB/Wi-Fi note |
| Phone camera as the PC's webcam | Yes, over USB or the same Wi-Fi | README feature table | Hero in Set A, with the USB/Wi-Fi note |
| Ready-to-paste photo, Handoff, folder sync, keyboard/mouse sharing | **Not on Cloud** | Parity table | **Do not show** in Cloud ads |

Rules carried over from `docs/POSITIONING.md`: no Apple logos, product shapes
or imagery suggesting affiliation; Apple names only in factual comparison; the
owner's origin line is the only quote we may attribute.

## 3. The three sets

Every set uses the same offer and destination, the same end card, the same
voice and the Saiph wave world as the brand thread. Each set owns **one group
of features**, so a winning set tells us which group people care about, and
each set is cut into **one short video per feature**, so the cuts rank
individual features inside the group.

| Set | Group | Features shown | Angle |
| --- | --- | --- | --- |
| A | Phone on your PC | Sign-in codes and notifications, texts (beta), calls (beta), screen mirroring, phone camera as webcam | Breadth: everything the phone asks for, handled on the PC while the phone sits untouched |
| B | Clipboard & photos | Phone → PC paste, PC → phone paste, pictures in the clipboard | Depth: one action, shown so clearly it needs no explanation |
| C | Pain point | Clipboard from the phone, codes from the phone | Frustration: the workarounds people do every day, then the wall breaks |

What differentiates Saiph and is shown: Android to **Windows and Linux** (end
card on every ad), clipboard **both ways with pictures** (B), the phone's
**screen and camera** on the PC (A). No competitor is named.

### Set A: "Never pick up your phone" (26 s)

The phone stands on its stand beside the laptop, in view, and is never
touched. Every beat is shown twice: the phone buzzes, then the laptop handles
it, then we see the result land back on the phone. A pulse runs along the
Saiph string each time something crosses. The pill **"Never pick up your
phone"** stays on screen throughout.

| Time | Caption | What happens |
| --- | --- | --- |
| 0–4.7 s | Sign-in code? It's already on your PC. | Phone buzzes with a Northbank code; on the PC the same text arrives as a Saiph notification; typed in, signed in |
| 4.7–10 s | A text? Reply from your keyboard. / Sent from your phone. | Phone buzzes with Ada's text; reply typed in Saiph's real Messages tab; the reply appears under the text on the phone |
| 10–14.6 s | A call? Decline it here. | Phone rings; Saiph's call banner; Decline clicked; the phone shows "Call declined" and goes quiet |
| 14.6–19.4 s | Your phone's screen, in a window. | Mirror screen clicked; the phone's own screen opens in a window; it's unlocked, Parcels opened and scrolled from the PC, and the phone on the stand does the same |
| 19.4–23.4 s | Its camera is your webcam. | Webcam clicked; the phone shows the camera-in-use badge; a video call shows the phone's camera |
| 23.4–26 s | Your phone, on your PC. | End card |

Notes on screen: "Texts and calls are in beta on Saiph Cloud" (texts, calls) and
"Screen and camera work over USB or the same Wi-Fi" (mirror, camera).

**The webcam picture is a drawn stick figure** waving at the camera (the
owner's call: it needn't be photorealistic, and a drawing can't be mistaken for
a real customer).

### Set B: "Ctrl+V" (12 s)

*Why they'd want it: the single most useful thing, shown so clearly it
needs no explanation.*

A satisfying, almost ASMR loop of one action. Macro Blender close-ups: a
fingertip long-presses text on the phone → **Copy**; hard cut to a realistic
keycap macro, **Ctrl**, **V**; the same text appears in the laptop's document
in one frame. Then the reverse (copy on PC, paste on phone), then an image.
Each paste lands on a pluck; the voice only speaks at the end.

| Time | Caption | Picture |
| --- | --- | --- |
| 0–2 s | Copy on your phone. | Macro on phone, text selection handles, Copy |
| 2–4 s | Ctrl+V on your PC. | Keycap macro, depth of field, text pops into the doc |
| 4–7 s | And back. | Copy a link on the PC → paste into the phone's message box |
| 7–9.6 s | Photos too. | Copy an image on the phone → paste into a slide |
| 9.7–12 s | Copy here. Paste there. | End card |

Optional: the same script shot on real devices by the owner. Real footage is
the strongest proof for this claim, and a render can't stand in for it.

### Set C: "Enough." (17.5 s)

*Why they'd want it: everyone has a small daily ritual of moving things between
their own phone and computer the hard way, and it's quietly maddening.*

| Time | Caption | Picture |
| --- | --- | --- |
| 0–1.8 s | Emailed yourself a link. Again. | An inbox of emails from you, to you, subject "link" |
| 1.8–4.6 s | Walked across the room for a sign-in code. | The camera gets up and crosses a real room (rug, lamp, plant, bookcase) to the phone buzzing on a shelf, the code on its lock screen |
| 4.6–6.2 s | Typed it out by hand. | A long address typed letter by letter; one typo |
| 6.2–8.5 s | Copy on your phone. | The phone, now on the desk, copies an address |
| 8.5–11.8 s | Enough. | The copy's pulse runs along the Saiph string, hits the pane of glass between phone and laptop, and the glass shatters in 3 s of slow motion while the camera pushes through the shards |
| 11.8–13.4 s | Ctrl+V on your PC. | The address pasted into a document |
| 13.4–15.6 s | Codes, texts, your whole phone. | The phone buzzes with a new code; a pulse carries it to the PC, where the notification is headed "From your phone · Pixel 8"; typed in, signed in |
| 15.6–17.5 s | Your phone, on your PC. | End card |

Avoid: naming Apple, Microsoft or Phone Link, "killer", and any claim of beating
another product. The glass is the gap between the viewer's own devices, not a
rival's ecosystem.

## 4. How it's built

- **Real UI, not drawn UI.** The desktop app's states come from the
  synthetic-data design preview (`?cloud=1`) through headless Playwright. The
  phone shows generic Android surfaces. Saiph's own Android screens are
  FLAG_SECURE and stay out.
- **One Blender world.** Desk, keyboard, wave wall and devices are shared in
  `blender/kit.py`; Set C adds a room and a Voronoi-fractured pane.
- **Sound (ElevenLabs).** `sound.cjs` reads the `audio` block in each
  `sets/<set>.json`: timed voice lines (voice Lily, British), sound effects
  and a music bed, generated through the ElevenLabs API, cached, and mixed with
  the music and effects ducked under the voice to −14 LUFS. Set C's script is
  read by `eleven_v3` in one take (`oneTake`), with a single `[sighs]` tag at
  the start, so the voice and mood hold from line to line; the take is cut
  into lines by its character timings. v3 has no speed setting, so `maxPause`
  trims its long pauses and levels each line, and `tempo` speeds them all
  equally to fit. "Enough." is a caption only: said aloud it sounded staged. To change a line, edit
  its text or time and re-run; only changed clips are regenerated. Effects are
  acoustic where they close a video (a felt-piano chord, not a synth sting).
  Captions stay burned in for sound-off viewing.
- **Formats per set.** 9:16 hero, one 9:16 cut per feature, a 4:5 and a 1:1
  still.

## 5. The test

Exploration phase: no performance data exists yet. Markets: Ireland and the
Netherlands first; the UK once UK VAT registration is settled. Android only,
ages 25–44 (see `AUDIENCE.md`).

**Structure in Meta Ads Manager.** One campaign, two ad sets with the same
audience and equal budget:

1. **Groups:** the three heroes (`saiph-a-hero`, `saiph-b-hero`, `saiph-c-hero`).
   Answers: which group of features, or the pain-point angle, sells best.
2. **Features:** the eleven feature cuts (`saiph-a-code`, `saiph-a-text`,
   `saiph-a-call`, `saiph-a-mirror`, `saiph-a-camera`, `saiph-b-clipboard`,
   `saiph-b-back`, `saiph-b-photos`, `saiph-c-rituals`, `saiph-c-paste`,
   `saiph-c-code`). Answers: which single feature people respond to.

Use each name as the ad name and as `utm_content`, with
`utm_campaign=saiph-cloud-test-1`, so a trial start in the funnel reports maps
back to one ad, one set and one feature. Turn off Advantage+ creative
enhancements (music, cropping, text variations) so every ad stays as built.

**Read after ≥1,000 impressions per ad**, then compare:

- 3-second view rate (did the hook stop the thumb?)
- Hold rate to 75% (did the story keep them?)
- Outbound CTR, then trial starts per landing visit (did it sell?)

Falsifiable hypotheses:

1. **A beats B and C on trial starts per landing visit**, because five uses
   justify €9.99 better than one.
2. **C has the highest 3-second view rate of the heroes**, because a named
   frustration stops the thumb faster than a product shot.
3. **Among the cuts, `saiph-a-mirror` and `saiph-a-camera` beat
   `saiph-a-code` on outbound CTR**, because they show something Android users
   don't expect a PC to do.

If C wins on trial starts, frustration becomes the lead angle and A and B are
recut to open with a named ritual. The winning feature cuts become the hooks
of the next round.

**MISSING:** budget and loss limit, confirmation that `utm_content` survives to a
trial start in the funnel reports (`website/ANALYTICS.md`), and any customer
language. Before scaling past this test, collect 5–10 verbatim comments from
beta users. The best hooks come from their words, not ours.
