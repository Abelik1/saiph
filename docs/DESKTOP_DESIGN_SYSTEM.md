# Desktop design system

How the desktop app (`frontend/`) is styled. It is built on [shadcn/ui](https://ui.shadcn.com)
components over Radix primitives and Tailwind v4, using the same structure as the Inhabis
design system (colour families, then shadcn-named roles, then components), in Saiph's own
deep-night, cyan and violet palette. `frontend/src/design-system/design-tokens.test.ts`
enforces the colour rules in `npm run test:unit`.

Preview any change on synthetic data with `npm --prefix frontend run dev` and open
`/preview.html` (`frontend/src/preview/`). It runs the real app shell against a fake client;
nothing in it comes from a real profile, and it is not part of the production build.

## Layers

| Layer | File | Holds |
|---|---|---|
| Families | `src/design-system/families.css` | Hue and saturation knobs (night, cyan, sky, violet, amber) and type stacks. Read only by the role file. |
| Roles | `src/design-system/tokens.css` | Every colour, shadow, radius and easing the app uses, named by job: `--primary`, `--muted-foreground`, `--status-off-surface`. |
| Tailwind | `src/index.css` (`@theme inline`) | Exposes the roles as classes: `bg-card`, `text-muted-foreground`, `border-border`, `rounded-field`. |
| Motifs | `src/design-system/motifs.css` | The string squiggle, the disclosure chevron and the motion they use. |
| Components | `src/components/ui/*` | shadcn components: Button, Badge, Card, Tabs, Select, DropdownMenu, Dialog, Popover, Switch, ToggleGroup, Disclosure, Input/Textarea, Field/Label, Item, Tooltip, Separator/Skeleton. |

A role is written from a family, for example
`hsl(var(--hue-cyan) calc(var(--sat-cyan) * 86%) 53%)`, so turning a family knob moves every
role built on it. Status colours (on, warning, off, destructive) are stated outright, because
they must not drift with the brand. Saiph is dark only.

## Rules

1. **No colour outside a token file.** No hex, `rgb()`, `hsl()` with a number, `white` or
   `black` in a stylesheet or component, and no Tailwind palette classes such as
   `bg-slate-800` or `text-white`. Read a role. If none fits, add one to `tokens.css` named for
   its job (`--attention-surface`, not `--light-orange`).
2. **Components never read a family.** `var(--hue-*)` appears only in `tokens.css`.
3. **Transparency goes through `color-mix()`** or Tailwind's `/alpha` on a role
   (`bg-card/90`), not a second token per alpha.
4. **One component per job.** Use the components before writing a variant:
   - Buttons: `default` is the one main action in a view (the string gradient); `secondary`
     for other standalone actions; `tonal` for quiet actions inside a card or row (a soft
     pill, never bare text); `ghost` for icon-only buttons, always with an `aria-label`;
     `destructive` for stop and remove; `link` only inside a sentence. Sizes `default`,
     `sm`, `icon`, `icon-sm`. Buttons default to `type="button"`; a submit button says
     `type="submit"`.
   - A choice from a list is a `Select`. Places are `Tabs`. One of a few visible options is a
     `ToggleGroup`. On/off is a `Switch`. Extra detail is a `Disclosure`. Options that belong to
     one control open beside it in a `Popover`. A choice that scopes a whole page (which device)
     is a `DropdownMenu` on the page heading. A focused, interruptible task (adding a device) is a
     `Dialog`.
   - One `default` (gradient) button per visible region: the region's main action. Actions on a
     row are `tonal`. A button's error appears below its row of buttons, never between them.
   - Every list row is an `Item` (media, title, description, actions).
   - A status is a `Badge` with a tone: `good`, `warn`, `bad`, `attention`, `quiet`.
5. **No blur over the strings.** The wave field redraws continuously; `backdrop-filter` over
   it re-blurs every frame. Surfaces are slightly see-through (`bg-card/90`) instead.
6. **Motion uses transform and opacity only,** so the compositor runs it without repainting,
   and every animation stops under `prefers-reduced-motion`.

## Page layout

The Phone page is the model for the others:

- **A bar for the thing the page is about.** The device name is the heading and, with more than one
  device, the switcher. Device-wide actions sit on the right of that bar: Find phone, Mirror
  screen, Webcam, Microphone, Add a device, and a gear for device settings.
- **A rail for what changes on its own.** Quick controls (sound, now playing, Do Not Disturb)
  above notifications, which scroll inside their card so they are always on screen. Saiph Hub's
  suggestions lead the notifications list.
- **A main card that fills the window.** Each tab opens with a heading and its main action on the
  right. Messages keep the reply field pinned at the bottom.
- **Live state in plain sight.** While the phone's camera or microphone captures, a card at the top
  of the rail says so. An incoming call shows a bar under the header on every page.
- **Keyboard.** Ctrl+1 to Ctrl+5 open the phone tabs, Ctrl+N starts a message, Enter sends and
  Shift+Enter adds a line, Esc closes a composer, popover or dialog.

## Connection and setup

The **Phone** tab is the home for connecting a phone, including on first launch.
An empty Phone page shows connection setup instead of empty feature panels.
Settings offers a **Connect a phone** shortcut to that same flow. The longer
setup guide is optional, under Settings → General, for feature choices, tools
and privacy preferences.

- Use a wizard with one task per screen and a visible Account → Computer → Scan
  → Approve progress indicator. Sign-in and explicit main-computer setup advance
  when their native state changes. Show the QR automatically on Scan and watch
  for the phone's request there: the wizard moves to Approve by itself when a
  new request appears, with **Continue to approval** as the manual fallback.
  **Back to scanning** clears the previous request and comparison, and requests
  already on the list then wait for an explicit Continue. Move keyboard focus to
  the heading when navigating Scan and Approve, and show completion only after
  approval succeeds. Keep the completion screen until the phone actually
  connects, say so when it does, and leave the Phone page to a Done action.
- Settings → General shows its **Connect a phone** shortcut only while no phone
  is connected; afterwards adding a phone lives in the Phone tab's header. The
  optional guide starts at its feature choices on a connected computer.
- Reuse `HostedPhoneSetup` in `PhoneSetup.tsx` for Phone, the add-phone dialog
  and the optional guide. Keep account settings focused on managing the account.
- Describe fingerprints as **security codes** in the normal flow. Label the
  computer's code and the device's code distinctly. Explain that signing in finds
  the account while comparing codes checks the device keys. Show every group;
  never silently confirm a match or shorten the code used for approval.
- Keep manual copying and pasting in labelled disclosures next to the relevant
  step. They are fallbacks when scanning or request discovery is unavailable,
  including on older services. Connection details and device-management data
  belong in expandable settings sections; errors and consent stay visible.
- Keep a QR within the active connection view. Closing it or leaving that view
  drops the displayed code and ignores late responses. Server expiry and owner
  verification remain authoritative. Inspecting a different request clears its
  confirmation; a late inspection must not replace the current request.
- Self-hosted Hub invitations are an explicit alternative. Preserve their
  existing approval and pairing flow. Optional tools and usage-sharing prompts
  must not interrupt a new user's account connection.

Android instructions point to this Phone flow rather than sending people through
account settings. These layout rules preserve the current beta's computer and
phone trust confirmations; changing the trust protocol needs separate review.

## The strings

Saiph's visual language is a field of strings that ripple like plucked guitar strings
(`src/workspace/waves.tsx`). The background field, the loader, the step progress, the brand
mark and the selected-tab underline all share it, and all read `--wave-1` (cyan),
`--wave-2` (light cyan), `--wave-3` (violet) and `--wave-star`.

- `WaveField` draws the background at 30 fps while it only drifts, and at full rate while a
  pluck or a gather is moving. Each string's gradient is made once per resize, ripples are
  skipped for strings and points they cannot reach, and the canvas is capped at 1.5x pixel
  ratio.
- `pluck(x, y)` sends a ripple; `useGather(ref, active)` curls the strings around an element
  while it works (every `Action` does this while pending).
- The `wave-underline` class marks the current tab or navigation item.

## Android

The [mobile design system](MOBILE_DESIGN_SYSTEM.md) defines the layout, typography,
copy, setup-choice and accessibility rules for mobile applications. Use it when
building or updating a phone screen; the Android setup and Hosted screens are its
reference implementation.

The phone app (`android/app/src/main/java/com/orionmini/mobile/Ui.kt`) uses the same roles in
`Palette`, with the same values in `res/values/colors.xml` for the widgets and the window theme.
`SaiphPaletteTest` fails if the two drift, or if a widget states a colour instead of reading one.

- **Buttons** are pills with the same jobs: the gradient `primary` for a screen's one main action,
  `Tone.SECONDARY` for standalone actions, `Tone.TONAL` for actions on a card or row, and
  `Tone.DANGER` for retiring or removing. Icon-only buttons (`iconButton`) always carry a label.
- **Status** is a `badge` (Online, Paused, Reconnecting, Ready), **settings** are `switchRow`s in
  cards, and every group of controls sits on a `card` under a `section` label.
- **Layout.** A header with Back (on inner screens), the title, and status and Settings on the
  right. On the home screen, Photo, Sketch, Remote and Hotspot sit in a dock fixed at the bottom,
  so a long inbox never pushes them out of reach. Devices come before the inbox, and recent
  decisions show three until asked for more. The Hosted daily screen leads with Files and
  photos and Texts and calls. Account, permissions, connection controls and device details
  live under Settings, reachable from the header.
- **The strings** are a static `StringField` behind every screen, built once per size and never
  animated, to spare the battery.

## Cascade

`src/index.css` declares `@layer theme, base, legacy, components, utilities`. The older page
stylesheets (`workspace.css`, `link.css`, `waves.css`, `PhoneTabs.css`, `PhotoGallery.css`,
`SettingsLayout.css`) are imported into `legacy`, below Tailwind, so a design-system
component always wins. Their global element rules skip anything with a `data-slot`
attribute, which every component in `src/components/ui` sets. Nothing may be imported
unlayered: unlayered CSS beats every layer.

The legacy files still contain colour literals. The token test holds each to its current
count, which may only go down; lower it when you move rules onto roles.

## State of the migration

| Area | State |
|---|---|
| App shell (header, navigation, footer) | Built from the system |
| Phone page: device bar, quick controls, webcam and microphone, notifications with undo, Hub suggestions, Add a device dialog | Built from the system |
| Phone tabs: Messages, Calls, Share (files and handoff), Apps | Built from the system |
| Phone tabs: Photos (grid, viewer, context menu) | Legacy CSS on roles; menu items share one style |
| Your week | Built from the system, in Settings → General |
| `Action`, `Empty`, `SettingsShortcut` in `ui.tsx` and `Navigation.tsx` | Built from the system; older `className` looks map onto Button variants |
| Settings, Cloud, setup guide, Workspace add-on pages | Legacy CSS on roles; buttons and fields restyled through the legacy global rules |

Next steps: rebuild Settings and the setup guide from the components, then Cloud, then
retire each legacy stylesheet as its count reaches zero.

Use **Saiph Cloud** and **Self-hosted** for connection choices and people-facing
service labels. Preserve the existing Hosted protocol, command and settings names.

## Galleries and device preferences

Photo tiles contain the image only. Keep the filename in the viewer and details.
Place the actions menu over the image's top-right corner, visible on hover,
keyboard focus and touch screens. Preserve accessible names and the context menu.
Keep preview and original in the same fitted frame while loading; actual-size
zoom is a separate action.

Connections leads with the Cloud account and approved devices, then the same
layout as Settings → Phone: open sections (**Phone and this computer**, **Quiet
hours**, **Cloud folders**) of `SwitchRow`s (`workspace/SettingRow.tsx`) that save
as soon as they change. Never hide preferences behind a disclosure; a text field
(quiet-hours times, the Cloud folder path) keeps its own Save button. Keep
self-hosted pairing and advanced fields in labelled disclosures: an unpaired Hub is
a single closed **Self-hosted Hub** disclosure at the end, and a paired one is a
card with **Pair with a different Hub** folded. Lists inside a disclosure (Recent
device changes) are `Item` rows, newest first, with a count in the summary's
`meta` slot and relative times. No bare `<details>` or native `<select>` in
Settings: use `Disclosure` and `Select`.

### Phone notifications

`workspace/PhoneNotifications.tsx` draws every phone notification, for Saiph Hub
and Saiph Cloud alike: a card with the app's tile, its name and a relative time
("Just now", "2 min ago", "3 h ago", "Yesterday", then the date; the full time is
the tooltip), the title, the text clamped to three lines with **Show more**, the
notification's own actions, and Open and Dismiss as labelled icon buttons
(`Dismiss <title>`). Several notifications from one app share one header with the
tile, a count and **Clear**. An empty list shows an icon, a title and what to do.
The newest Saiph Cloud notification is previewed with the same card in Settings →
Connections → Saiph Cloud.

Phones do not send app icons yet, so the tile is the app's initials on one of five
tints (`--app-tint-1` to `--app-tint-5` in `tokens.css`), chosen by a stable hash of
the package (or the app name, which is all Saiph Cloud sends). Adding real icons is
a protocol change across both transports and is not part of this pass: the Hub's
`notification.upsert` model forbids unknown fields and the desktop's Cloud reader
requires an exact key set, so a phone that added an icon field would have every
notification rejected by an older Hub or desktop. The intended design is a separate,
capability-gated event (`app.icon {package, png}`) that the phone sends once per
package, a PNG of at most 48×48 pixels and a few kilobytes, which the desktop checks
(signature, IHDR size, byte limit, package pattern) and caches by package in the
profile; Saiph Cloud first needs the package name it does not send today.
Devices uses the same preference cards, label scale and spacing for camera,
microphone, remote controls and automatic locking. Keep permission consequences
beside the controls that enable them.

Present phone-camera preview and meeting-app webcam use as Saiph features. The
Windows build bundles the Saiph Camera backend; normal setup never asks users to
download or configure another app. Keep the camera QR private and short-lived,
show live video at a useful width, and keep Stop visible. Legacy OBS profiles,
scene fields and installation details belong inside
meeting-app disclosures. Do not start capture when opening or saving preferences.
