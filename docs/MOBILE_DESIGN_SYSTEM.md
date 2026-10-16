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
helpers rather than duplicating their styling. Widget and window colours live
in [`colors.xml`](../android/app/src/main/res/values/colors.xml);
`SaiphPaletteTest` checks that they agree with the shared palette.
The welcome, QR, approval and Hub artwork lives in `SetupArtwork.kt`; its vector
paths and paints are reused between frames.

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

## Connection state and policy

Account sign-in, local identity creation, pending approval and verified connection
are distinct states. Never open daily use because a device ID was saved or a
status string changed. Keep comparison visible until its action completes;
serialize actions, disable duplicate taps and show readable inline retry errors.
Preserve partial identities and offer explicit recovery without replacing keys.

Once signed in, Back exits setup; once approved, launch daily use. Subscription,
account and Hub switching belong in Settings. Returning from Settings returns to
the current task. Keep a complete security-code comparison and native owner check.

Show linked privacy and applicable Hosted terms on first use, with explicit
acknowledgment. Put detailed privacy and feature limits in that linked policy.
Keep short permission context next to its opt-in; policy acknowledgment never
enables texts, calls, permissions or anonymous usage sharing.
