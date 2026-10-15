# Mobile design system

These are the layout, typography and interaction rules for Saiph mobile
applications. They preserve the deep-night palette, cyan-to-violet actions and
string background described in the [desktop design system](DESKTOP_DESIGN_SYSTEM.md).
The Android setup and Hosted screens are the reference implementation. Apply
these rules to new mobile screens and when updating older screens.

## Screen structure

- Give each screen one clear purpose. Daily use leads with useful actions and
  current state. Account management, sharing permissions, connection controls
  and device details belong in Settings, reachable from the header.
- When connecting to the desktop, point to its Phone tab and the connection
  screen shown there. Use the same scan-and-approve flow for first setup and
  additional phones; do not require searching through account settings.
- Keep Back, the screen title and Settings in predictable header positions.
  The header stays visible while the page scrolls. Header Back and the system
  back gesture must lead to the same place.
- Group related content on one card beneath a sentence-case section heading.
  Keep descriptions, state and actions with the feature they describe.
- Keep frequent actions easy to reach. A fixed action dock stays above system
  navigation and must not cover content. The self-hosted home screen uses this
  for Photo, Sketch, Remote and Hotspot.
- Preserve scroll position when refreshing the same screen. Start a different
  screen at its top. Long lists and larger text must remain scrollable.

## Typography

Use a small semantic type scale rather than a different size for each subtitle,
explanation or control. Android sizes are in `sp`, so they follow the owner's
text-size settings; other platforms must use their native text scaling.

| Role | Android size | Use |
| --- | --- | --- |
| Screen title | 26 sp, bold | Header and introductory heading |
| Section or card title | 18 sp, bold | Group headings and card titles |
| Body and control label | 16 sp | Descriptions, fields, buttons and switches |
| Metadata | 14 sp | Short status, timestamps and secondary identifiers |

Use the system sans-serif family, regular body text and medium button labels.
Feature-row labels may use bold body text. Body line spacing is approximately
1.2 times the font height. Mark headings semantically for assistive technology.
Use sentence case for headings and buttons. Reserve compact captions or eyebrows
for short incidental labels; instructions and permission explanations use body
text. Never shrink text to make a layout fit.

## Copy and feature rows

- Start with a short title and one useful sentence. Explain what the person can
  do and what happens next. Keep implementation details in device details or
  advanced settings unless they affect the person's decision.
- Split separate capabilities into separate rows with a decorative icon, a
  short label and a concise description. Texts and calls get a Texts row and a
  Calls row instead of a paragraph describing both.
- Keep important scope and consequences visible: which approved devices can
  act, whether a feature is enabled, missing permissions, and where call audio
  plays. Do not hide information needed to give informed consent.
- Put longer privacy explanations, uncommon limitations and alternate manual
  setup methods behind clearly labelled disclosures. Expand them in place and
  expose their expanded or collapsed state to assistive technology.
- Use clear empty states that explain what will appear there. Keep received
  file names separate from a short Save action; give the action a spoken label
  identifying its file.

## Setup choices

Present account and self-hosted routes using the same card structure: a short
title, a comparable amount of explanatory text and one full-width action.
Both routes have a card surface and aligned content. The recommended route may
use the primary gradient; the alternative uses a secondary button. Express
priority through button tone, without giving only one choice a box or filling
one card with extra instructions. Invitation help and advanced configuration sit
outside the choice cards. Show additional setup steps when they become relevant.

Use a wizard for multi-step device connection: show one task at a time, the
current step and a clear next action. Keep Back available between reversible
steps. Returning to an earlier step must clear any device comparison that needs
to be repeated. Finish only after the requested action succeeds; distinguish
approval from the device actually connecting. Keep full security codes and
owner verification intact, with manual alternatives inside the relevant step.

## Actions and spacing

Buttons use sentence case, short action labels and consistent pill shapes.
Primary gradient buttons identify the main action in a visible region;
secondary buttons are other standalone actions, tonal buttons are quieter card
or row actions, and danger buttons identify destructive actions. Icon-only
buttons always have a spoken label. Use switches for ordinary on/off settings;
an action requiring owner verification must keep that verification step.

A single action fills its content width. Multiple actions may share an
equal-width row only when every label fits at the current font scale. Otherwise
stack them at full width. Allow button height to grow with wrapped labels.
Do not truncate an essential action or rely on horizontal scrolling to find it.

Android reference dimensions, in `dp`:

| Element | Value |
| --- | --- |
| Page side inset | 18 |
| Card padding | 20 horizontal, 18 vertical |
| Gap after a card | 12 |
| Gap between action buttons | 8 |
| Space before an action group | 16 |
| Card corner radius | 16 |
| Button minimum height | 52 |
| Icon-button minimum touch area | 48 × 48 |

Use these shared dimensions consistently. Other mobile platforms retain the same
hierarchy and spacing rhythm while meeting native touch-target rules. Respect
status bars, navigation bars and keyboard insets.

## Visual language and implementation

Use shared colour roles and status tones. Keep the existing playful palette,
gradient actions, outlined cards and string field. Equivalent controls share
the same font treatments and button styles. Status remains understandable
through words as well as colour. The mobile string background is static and
built once per size to spare the battery.

The Android implementation lives in
[`Ui.kt`](../android/app/src/main/java/com/orionmini/mobile/Ui.kt): `Palette`,
`UiType`, `heading`, `section`, `cardTitle`, `body`, `card`, `button`, `buttonRow`,
`connectionChoice`, `featureRow`, `disclosure` and `switchRow`. Reuse these
helpers rather than duplicating their styling. Widget and window colours live
in [`colors.xml`](../android/app/src/main/res/values/colors.xml);
`SaiphPaletteTest` checks that they agree with the shared palette.

Layout changes must preserve pairing, identities, permission opt-in, explicit
device approval and owner verification. Navigation from a locked screen must
not reveal protected content.

## Review

Review changes with synthetic content at ordinary phone sizes, at 320 dp width,
and with text enlarged to twice its usual scale. Check wrapping, touch targets,
long names, empty states, disclosures, scrolling and both Back paths. Essential
copy and controls must remain readable and reachable.

Use isolated profiles and caches. Follow the
[Android contribution guidance](../android/CONTRIBUTING.md) for compilation,
JVM tests and lint. Distinguish native layout renders and automated checks from
emulator and physical-device evidence; current acceptance status lives in
[`RELEASE_STATUS.md`](RELEASE_STATUS.md).
