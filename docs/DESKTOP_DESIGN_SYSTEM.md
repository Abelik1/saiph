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
