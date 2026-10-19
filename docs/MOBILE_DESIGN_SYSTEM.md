# Mobile design system

These are the layout, typography and interaction rules for Saiph mobile
applications. They preserve the deep-night palette, cyan-to-violet actions and
string background described in the [desktop design system](DESKTOP_DESIGN_SYSTEM.md).
The Android setup and Hosted screens are the reference implementation. Apply
these rules to new mobile screens and when updating older screens.

## Screen structure

- Give each screen one clear purpose. Daily use leads with useful actions and
  current state. Show permission actions beside their features. Account
  management, detailed permission settings, connection controls and device
  details belong in Settings, reachable from the header.
- When connecting to the desktop, point to its Phone tab and the connection
  screen shown there. Use the same scan-and-approve flow for first setup and
  additional phones; do not require searching through account settings.
- Keep Back, the screen title and Settings in predictable header positions.
  The header stays visible while the page scrolls. Header Back and the system
  back gesture must lead to the same place.
- Every secondary screen, including separate activities such as Phone camera,
  Remote, Sketch, Photo, Send with Saiph and Update, uses the main page's
  header: a Back arrow in the top start corner, then the title. Never end a
  screen with a **Close**, **Back** or **Cancel** button at the bottom to leave
  it; leaving is the arrow's job. A Cancel stays only where it abandons a
  decision in progress, such as a security-code comparison.
- Group related content on one card beneath a sentence-case section heading.
  Keep descriptions, state and actions with the feature they describe.
- Keep frequent actions easy to reach. A fixed action dock stays above system
  navigation and must not cover content. The self-hosted home screen uses this
  for Photo, Sketch, Remote and Hotspot.
- Both home screens start with a quick-actions strip (`quickActions` in
  `Ui.kt`): equal icon tiles with a short label for the features people start,
  currently **Use as webcam**, **Share screen** and **Send a file**. Keep it to
  three or four tiles; a feature in the strip does not get a second card with
  the same button further down.
- Feature on/off on the home screen is a switch row (title and one-line summary
  on the left, the switch on the right), never a pair of Allow / Turn off or
  Stop sharing buttons. Turning a switch on still runs owner verification and
  Android's permission request; it stays off until they succeed. A missing
  Android access after it is on is one short warning and one compact action.
- Keep home copy to a title and one short summary per feature. Details (what
  each part does, who can use it) go behind a **Learn more** disclosure or in
  Settings.
- A request that needs the owner immediately, such as **Find phone**, opens its
  own full-screen page with one very large action, over the lock screen when
  needed, and keeps an ongoing notification with the same action. Swiping the
  notification away does not cancel the request; it comes back until the
  request ends. The page shows only what the request needs (here, the asking
  computer's name) and never opens the rest of Saiph while the phone is locked.
  Ending the request from any place (the page, the notification, a hardware
  key, the computer or its time limit) ends it everywhere and tells the
  computers, so the desktop's action returns to its idle label.
- Preserve scroll position when refreshing the same screen. Start a different
  screen at its top. Long lists and larger text must remain scrollable.

## Hierarchy

The eye must find the screen's purpose before its controls. Titles clearly
outrank buttons: screen title (26 sp bold) > section heading (18 sp bold) >
item or row title (16 sp bold) > explanation (16 sp or 14 sp muted) > controls.
Avoid walls of large, equal-weight, full-width buttons: one primary action per
visible region, other actions as compact content-width buttons, switches for
on/off and link rows (chevron or outward arrow) for navigation. If a page needs
more than two or three full-width buttons, it is probably several items or
pages.

## Single-action screens

When a screen has essentially one main action (scan a code, start the camera,
allow a permission), show what happens around that tap as picture instructions,
like assembly instructions: two to four numbered pictograms, each with one
short line, ending with the result the person gets. Put the main action in the
dock. Pictures are flat, still and drawn from the palette; every step's words
carry the same instruction for assistive technology. Examples in the app:

| Screen | Steps |
| --- | --- |
| Phone camera, before scanning | 1 open Saiph → Phone → Webcam on the computer · 2 scan the code · 3 confirm it's you · 4 the computer receives the camera |
| Sharing setup: photos | 1 confirm it's you · 2 choose which photos Android allows · 3 computers show them |
| Sharing setup: notifications | 1 turn on notification access in Android Settings · 2 notifications appear on computers |
| Sharing setup: texts and calls | 1 confirm it's you · 2 allow texts, calls and contacts · 3 use them on the computer; audio stays on the phone |
| Request from a computer (sheet) | the request's picture · title naming the computer · Allow, then the page verifies it's you |

| Update | 1 download from your Saiph account or Hub · 2 Saiph checks it's the published, signed build · 3 Android asks you to confirm; Saiph restarts updated |
| Update: allow installs | 1 turn on Allow from this source in Android settings · 2 come back; Android asks to confirm · 3 Saiph restarts updated |

The larger `SetupArtwork` scenes stay for setup screens that introduce Saiph
(welcome, scan, approve, Hub); use step pictures where the order of what
happens matters more than the mood.

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
  setup methods behind clearly labelled disclosures. A disclosure is a quiet
  text row with a chevron, not a button, so it never reads as one more action;
  it still fills its row with a 48 dp target. Expand it in place and expose
  its expanded or collapsed state to assistive technology.
- Lists that update by themselves, such as received files, redraw when their
  contents change instead of offering a Refresh button.
- Call the service "Saiph account" in copy for people ("Sign in to Saiph",
  "Remove this phone from your account"). "Hosted" stays in technical places
  only, such as custom service fields and identifiers.
- Use clear empty states that explain what will appear there. Keep received
  file names separate from a short Save action; give the action a spoken label
  identifying its file.

## Setup choices

Use one welcome screen for first install. Lead with a large device illustration,
a short headline and one sentence. Offer **Subscribe** as the primary action,
**Continue with Google** as a secondary action for existing accounts and
**Self-host instead** as a quiet text action. Do not put another sign-in page
behind it or require a second sign-in tap before opening the browser. Keep
plan prices and checkout on the website instead of duplicating them in the APK.
An account already signed in uses **Continue setup**, which resumes its current
step without another browser round trip.

Keep welcome and scanning actions in a dock above system navigation, with
scrollable content above. Lead Scan with an illustration of the desktop's Phone
tab and its QR, one short instruction, **Scan QR code**, and a **Paste a code
instead** disclosure. Use Account → Scan → Approve progress. Put subscription,
connection and Hub illustrations in shared `SetupArtwork`; motion runs only while
the view is visible and respects disabled system animations. The drawings are
decorative, never real pairing codes; screen titles and instructions convey the
same task without relying on animation.

The self-hosted screen has a header Back arrow and a clearly labelled
**Back to Saiph** text action with an arrow. Header Back and system Back take
the same route to the welcome screen, without adding another choice page.
Leaving an unfinished invitation cancels its pending setup; an in-flight pairing
must finish before changing routes. Switching an unpaired phone to a Hub stops
its account service first. Existing paired phones keep their identity and
approved-device controls. Until approval, the Scan screen also offers
**Use a different account**.

Google is the direct normal sign-in route for the bundled Auth0 deployment;
Auth0 still issues the same Saiph tokens through AppAuth with state and PKCE.
Keep **Other sign-in options** available for existing accounts that used email or
another provider, and preserve custom non-Auth0 issuers. A matching email alone
does not establish that two provider accounts have the same identity. Remember
the provider only after accepting a current grant, and reuse it when an approved
phone needs to sign in again; legacy profiles keep their original provider picker. Google
connection enablement and consent-screen branding belong to the private service
configuration, not mobile UI source. See Auth0's
[direct-provider routing](https://support.auth0.com/center/s/article/How-to-skip-the-universal-login-page-and-redirect-to-the-upstream-identity-provider-immediately)
and [Google connection and branding guide](https://auth0.com/docs/authenticate/identity-providers/social-identity-providers/google).

Show a security code the owner must compare on its own themed screen or card:
grouped monospace text on a field surface (`securityCode` in `Ui.kt`), the same
explanation of what the comparison checks, a Cancel action and one explicit
"Every group matches" action that still goes through owner verification. Do
not put the code in a system dialog message.

Use a wizard for multi-step device connection: show one task at a time, the
current step and a clear next action. Keep Back available between reversible
steps. Returning to an earlier step must clear any device comparison that needs
to be repeated. Finish only after the requested action succeeds; distinguish
approval from the device actually connecting. Keep full security codes and
owner verification intact, with manual alternatives inside the relevant step.

## Settings

Settings is a short list of categories, not one long page. The top level has a
search field, then one row per category with an icon, its title and a one-line
summary naming what it holds. Each row opens the category's own page, titled
with the category name, with the header Back arrow returning to the list.
Search filters by item titles, other words for the same item and category
names as the person types; choosing a result opens its page, scrolls to the
item and marks it briefly. A blank search shows the category list again.

Categories, in this fixed order (a category with nothing for the current
connection type is hidden):

| Category | Cloud items | Self-hosted items |
| --- | --- | --- |
| Account & devices | Subscription · Sign in and out · Your own Hub · This phone · Remove this phone | Saiph account · Hub and device |
| Connection | Sync · Background activity | Saiph is on · Tailscale and VPN · Permissions and background |
| Notifications | Phone notifications · Saiph alerts | Do Not Disturb sync · Shared sleep plan |
| Messages & calls | Texts and calls | — |
| Photos & files | Photo gallery | Backups |
| Clipboard | Clipboard sharing | Clipboard sharing |
| Camera & screen | Phone as webcam · Camera access | — |
| Status & controls | (reserved: phone status, quick actions, audio player) | — |
| Privacy & security | App lock · Security activity · Usage statistics · Privacy policy and terms | App lock · Usage statistics |
| About & help | Version | Version and updates |

New settings go into these categories rather than new top-level pages: feature
on/off switches go with their feature (Notifications, Messages & calls, Photos &
files, Camera & screen for phone screen and apps), sync over mobile data under
Connection, phone status, quick actions, the audio player and wallpaper under
Status & controls, and help links under About & help.

A category page holds items. Each item has a 16 sp bold title, a short muted
explanation and compact controls: a switch for on/off (on the title line), a
link row for another screen or Android's own settings (chevron for in-app
pages, outward arrow for Android or web pages), or a content-width button for
an action. Destructive actions keep the danger tone and their confirmation.
Turning on a switch that needs owner verification or Android access leaves it
off until that succeeds, then the page redraws. An item that needs an
approved, syncing phone stays listed and says when it becomes available, so a
search never lands on nothing. Start a new card under a section heading only
when a page has genuinely separate groups.

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
`connectionChoice`, `setupLink`, `setupProgress`, `featureRow`, `disclosure`, `securityCode` and `switchRow`. Reuse these
helpers rather than duplicating their styling. Further shared pieces:

- [`ScreenFrame`](../android/app/src/main/java/com/orionmini/mobile/ScreenFrame.kt):
  the header (Back arrow and title), scrolling or fixed content, the strings
  behind and `dockActions`, for a screen in its own activity. `HostedActivity`
  and `OrionActivity` keep their own equivalent `shell`/`title` frames.
- [`stepGuide`, `Step` and `StepPicture`](../android/app/src/main/java/com/orionmini/mobile/StepGuide.kt):
  numbered picture instructions for single-action screens. Add a pictogram to
  `StepPicture` when none fits; keep it flat and on the 64-unit grid.
- [`SettingsCatalog`](../android/app/src/main/java/com/orionmini/mobile/SettingsCatalog.kt):
  the categories, each connection type's items with their search keywords,
  `search`, `categories` and `summary`. It has no Android dependencies;
  `SettingsCatalogTest` covers search.
- [`SettingsPages.kt`](../android/app/src/main/java/com/orionmini/mobile/SettingsPages.kt):
  `settingsHome` (search and category list), `SettingsPage` (`item`,
  `switchItem`, `linkItem`, `section`, `reveal`), `settingsRow`,
  `settingsList`, `settingSwitch`, `settingsSearch`, `compactButton`,
  `compactActions` and `SettingsIcons`.

To add a setting, add an `Entry` (id, category, title, keywords) to
`SettingsCatalog.CLOUD` or `SELF_HOSTED`, then draw it with the same id on that
category's page in `HostedActivity.hostedSettings` or `OrionActivity.settings`. Widget and window colours live
in [`colors.xml`](../android/app/src/main/res/values/colors.xml);
`SaiphPaletteTest` checks that they agree with the shared palette.
The welcome, QR, approval and Hub artwork lives in `SetupArtwork.kt`; its vector
paths and paints are reused between frames.

Layout changes must preserve pairing, identities, permission opt-in, explicit
device approval and owner verification. Navigation from a locked screen must
not reveal protected content.

## Requests from a computer and live state

A computer asking for the camera or the phone screen is a single decision, so it
gets one sheet (`RequestPrompts.kt`) while Saiph is open: an illustration in a
tonal circle (the camera, or Saiph's mark for the screen), the title "<computer>
wants to use your camera" / "<computer> wants to show your screen", one line on
what happens next, then **Allow** (primary) and **Not now**. It rises from the
bottom with the raised surface and strong outline, is protected like every Saiph
window, and never starts anything: Allow opens the page that verifies the owner.
Outside Saiph the same request is a heads-up notification with Allow. Both go
away together when the request is answered anywhere, cancelled or expires.

Live capture is the one place the app uses solid red (`Live.RED`, white text):
the camera page while it streams and the phone screen page while sharing carry a
red **● LIVE** banner at the top of their content, and their ongoing
notifications use a red accent with Stop. Do not use that red for ordinary
errors (they keep `Palette.BAD` on a surface) or for photos, text or calls,
which are not live.

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

## Connection state and policy

Account sign-in, local identity creation, pending approval and verified connection
are distinct states. Never open daily use because a device ID was saved or a
status string changed. Keep comparison visible until its action completes;
serialize actions, disable duplicate taps and show readable inline retry errors.
Preserve partial identities and offer explicit recovery without replacing keys.

At the top level, do not show an in-app Back arrow that exits the app. Show it
only for nested screens, such as Settings or code comparison. Android system Back
retains normal platform behavior. Once approved, launch daily use. Subscription,
account and Hub switching belong in Settings. Returning from Settings returns to
the current task. Keep a complete security-code comparison and native owner check.

Show linked privacy and applicable Cloud terms on first use, with explicit
acknowledgment. Put detailed privacy and feature limits in that linked policy.
Keep short permission context next to its opt-in; policy acknowledgment never
enables texts, calls, permissions or anonymous usage sharing.

Offer sharing setup automatically after device approval: photos, notifications,
then texts and calls. Give each step one named Allow action and a Not now route.
Keep those controls visible beside the same features in daily use. Never grant
permissions or enable sharing merely because setup was opened. Keep owner
verification before enabling photos or texts/calls.

Permission buttons must always give a visible result. Use Android's current
runtime permission flow, reselect permitted photos when supported, and open app
settings when access is already granted or Android cannot ask again. Recheck
permission state after returning; do not redraw underneath a permission prompt.
Use specific labels such as Allow photo gallery and Allow texts and calls.

Keep sign-in across normal app restarts with a protected rotating session.
Connection retries and temporary offline states must not look like sign-out or
erase device approval. Gallery previews should fill their viewer while the
original loads, preserve aspect ratio, and keep the same frame after loading.

Use **Cloud** and **Self-hosted** for connection choices. Keep technical Hosted
identifiers, protocol names and saved settings unchanged. A failed local setup
gets an explicit Restart setup action that preserves earlier key/trust files and
account sign-in; it never silently repairs or resets an established checkpoint.

Camera sessions use a short-lived code from the computer and a visible Start
camera action on the phone. Native owner verification and Android camera access
remain explicit. The camera screen stays visible with Stop; leaving it ends
capture. Keep third-party implementation names out of this normal flow. Never
request microphone access as part of camera setup or resume capture implicitly.
