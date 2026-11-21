# Page-CRO review — Saiph landing page, 27 October 2026

**Mechanical audit: 69/100.** Ran the installed Page-CRO `conversion_audit.py` on `website/index.html` before the manual framework pass. This is a static signal score, not a conversion rate, sales forecast or reason to add elements. The manual review supports preserving the compact page and making targeted offer/friction improvements.

## Context and scope

- Page type: product landing page for Saiph Cloud, with a secondary direct-purchase path.
- Primary audience: Android users with Windows/Linux computers. The owner confirmed **social posts or ads** as the main traffic source. Exact creatives, audience targeting, spend and device split were not supplied; mobile cold traffic is a review assumption, not a measured audience breakdown.
- Primary immediate outcome: **completed free-trial starts per landing visit**, segmented to the relevant social/ad campaign. Secondary outcomes: paid customers and revenue per landing visit after the 30-day trial, assessed with the existing 45-day window. Button clicks alone are not the success measure.
- Design constraints: one prominent Start your free trial action, Buy now secondary, the owner's product demonstration retained, no setup guide or extra marketing sections added without a conversion rationale.
- Evidence: current source/local generated page and the anonymous live homepage at 390×844 and 1440×844; live `/trial` and `/buy/monthly` at mobile size. All live entries returned HTTP 200. No sign-in, trial activation, payment, owner account or live device operation.
- No funnel totals or campaign performance were available in this review. Existing analytics documentation describes the funnel but does not prove deployment, collection or current drop-off. No conversion lift or winning variant is claimed.

## Mechanical score interpretation

| Signal | Score | What it means here |
| --- | ---: | --- |
| CTA | 100 | Script counts 8 buttons and 3 CTA-style links. Seven buttons are demo tabs; the eighth is the footer cookie-settings control. The links include the skip link, trial action and Buy now. This is not 11 competing sales actions. |
| Social proof | 0 | No detected testimonials/customer logos. No verified endorsements were supplied; this is not an instruction to manufacture proof or add a testimonial section. |
| Trust | 100 | Encryption, refund and privacy keywords exist. Keyword detection does not verify security or legal claims. |
| Forms | 60 | Script deducts points because there is no form; its 2 fields are monthly/yearly radio choices. The intentional button-to-Google journey should not be replaced with a form to improve the score. |
| Mobile | 100 | Script checks only the viewport meta tag. Separate rendered checks confirmed no horizontal overflow at the tested sizes. |

The 31-point deduction comprises 25 points for missing detected social proof and 6 for no on-page form. Its CTA formula rewards larger CTA counts, and its above-fold estimate uses element order (including the skip link), not rendered screen position. Keep these limitations visible when comparing future runs.

## Manual review: seven framework dimensions

| Dimension | Finding | Priority |
| --- | --- | --- |
| Value proposition | Platform connection is understandable, but the illustrated Cloud folder feature can imply that paid Saiph Cloud includes storage/folder sync. The README says Cloud folders are self-hosted only. | P1: correct offer scope |
| Headline | “Your Android phone, on your PC” is compact and broad. Feature-specific social ads may need a more specific first demo/headline, depending on the actual ad. No evidence establishes a better general headline yet. | Preserve control; test message match |
| CTA | One visible primary trial action, already above the fold. Buy now has lower emphasis and sends the chosen plan to the account site. Live trial/buy entries each expose one clear Google action. | Strong foundation |
| Hierarchy | Hero and trial action are easy to scan. The mobile consent prompt overlaps the illustrated proof. Subscription pricing begins below the first viewport after the demo. | P2: overlap; pricing is a test hypothesis |
| Trust/proof | No-card trial, privacy/refund links and the account site's explicit no-autocharge explanation provide reassurance. The animation is an illustration, not evidence of measured reliability or actual customer use. | Retain; no fabricated endorsements |
| Objections | Compatibility is visible in the local revised subhead. Live homepage still says “Nothing to set up”; the local “no server to run” correction is more precise. The live trial page clearly explains the trial pauses without automatic charging. | P2: wording consistency |
| Friction | No landing form and a direct handoff to `/trial` or `/buy/<plan>`. The anonymous entry pages load successfully; provider completion was not tested. Actual funnel data is needed to locate abandonment. | Check funnel before major path changes |

## Quick Wins (Implement Now)

These were recommendations from the initial audit. The follow-up implementation
below records the completed local fixes separately from the remaining hypotheses.

1. **P1: Correct the Cloud-folder demo's offer scope.** The homepage tab is “Cloud”; its scene labels the file-manager window “Saiph Cloud” and says “Optional Cloud.” `README.md:80–87` says folder sync is self-hosted only and hosted Cloud stores no files. Remove this self-host-only scene from the paid landing-page rotation, or clearly identify the existing scene as self-hosted. Preserve the demonstration of the paid product's other features. **Rationale:** a buyer should understand what the subscription includes. **Effort:** small copy/scene change with mobile checks. **Success:** correct feature comprehension; monitor activated trials and subsequent paid conversion, not merely clicks.
2. **P2: Carry the existing factual hero correction into the next reviewed release.** The live subhead is “End-to-end encrypted. Nothing to set up.” Local source already says “For Windows and Linux. End-to-end encrypted, with no server to run.” Keep the short factual reassurance; leave actual pairing instructions in the apps/account guide. **Rationale:** reduce the gap between the offer and first use without adding a section. **Effort:** already prepared locally; release remains a separate operation. **Success:** platform comprehension and fewer setup-expectation complaints; conversion effect unknown.
3. **P2: Prevent the cookie prompt from obscuring the product proof on mobile.** At 390×844 on the live site, the prompt occupies y≈704–832, overlapping the demo at y≈503–957. The primary trial CTA remains clear at y≈292–355. Adjust the prompt placement/reserved space so it does not cover the demonstration; retain equally usable Accept/Decline controls and existing consent behavior. **Rationale:** visitors should be able to understand the product while making the cookie choice. **Effort:** small responsive-layout change, checked with the prompt open and dismissed. **Success:** completed trials per visit, with consent behavior intact; do not optimize acceptance rate.

## High-Impact Changes (Prioritize)

1. **Match the first proof to the social post/ad.** A clipboard ad should land on a clipboard demonstration; a photo-transfer ad on photo transfer. The current first scene is Notifications, and the campaign drafts cover several different motivations. Retain one landing page and its primary trial CTA; selecting the relevant existing scene can provide message match without another destination or section. **Effort:** roughly 0.5–1 day for a constrained campaign/scene mapping and regression checks, depending on campaign setup. **Success metric:** completed trials per landing visit within the same campaign/audience, followed by paying customers per visit. **Evidence limit:** actual currently running creatives were not supplied, so this is a prioritized hypothesis rather than an established mismatch for every ad.
2. **Use the existing funnel to choose the next optimization.** Compare landing→trial click, trial page→sign-in completion, and sign-in→actual trial start. Keep purchase→paid conversion separate from trial starts and use the 45-day follow-up. Read aggregate reports through the authorized operations workflow; do not copy account-level data or production configuration into this repository. **Effort:** small if collection is already deployed; otherwise first verify instrumentation. **Success metric:** trustworthy step totals and an identified drop-off, then an improvement in completed outcomes. **Evidence limit:** current counts, sample sizes and collection state were not inspected.

## Test Ideas

Run one hypothesis at a time within comparable social/ad traffic. Keep the audience, creative, price and attribution window fixed for a layout/copy comparison. Choose a sample-size/analysis rule before launch; do not declare a winner from a small early lead.

| Hypothesis | Control | Variant | Primary measure / guardrail | Priority |
| --- | --- | --- | --- | --- |
| Visitors from a specific feature ad respond better to matching first proof | Notifications starts first | The existing scene matching that ad starts first | Completed trial starts / campaign landing visit; paid conversion after trial | High |
| Visible future cost attracts better-qualified trials | Price cards after demo | Bring the existing price choice earlier, or test a compact price disclosure in existing copy space; retain the demo and CTA hierarchy | Paying customers / landing visit at 45 days; trial starts as a secondary measure | Medium |
| Concrete task language matches a particular ad better | Current general headline | A matching clipboard or notification headline in the same space | Completed trials / same-campaign visit; paid conversion guardrail | Medium |
| Extra reassurance reduces trial hesitation | “Free for 30 days, no card needed” | “30 days free. No card or automatic charges.” in the same support-line position | Completed trials / landing visit; check mobile wrapping | Lower |

The live subscription price starts at y≈997 on 390×844 and y≈986 on 1440×844. The corresponding local positions are y≈1033 and y≈991. This shows price is below the initial viewport; it does not prove that moving it above the owner's demonstration would improve conversion.

## Copy Alternatives

Keep the incumbent as the control. These alternatives replace existing text rather than adding page sections.

| Element | Option | Best use / reason |
| --- | --- | --- |
| Headline A | Your Android phone, on your PC. | Current broad proposition; short and platform-specific. |
| Headline B | Your phone’s texts and notifications, on your PC. | A notification/text-led ad; more concrete benefit without introducing a new product. |
| Headline C | Copy on your phone. Paste on your PC. | A clipboard-led ad; immediately matches that task. Keep Android/Windows/Linux support visible in the existing subhead. |
| CTA A | Start your free trial | Current control; unambiguous action and a clear free offer. |
| CTA B | Try Saiph free for 30 days | A test of putting the duration into the button; verify wrapping and button size. |
| Trial reassurance A | Free for 30 days, no card needed | Current concise reassurance. |
| Trial reassurance B | 30 days free. No card or automatic charges. | Makes the already-true trial behavior explicit; test against the incumbent. |

Do not add testimonial blocks, signup fields, setup steps or duplicate conversion buttons just to raise the mechanical score. The seven feature tabs are demo controls, so their count should not be treated as seven purchase routes.

## Verification and artifacts

- Source audit JSON: `build/cro-review-20261027/source-audit.json`.
- Local renders: `local-{390,1440}-fresh.png` and `local-{390,1440}-declined.png`; local metrics/handoff text: `rendered-evidence.json`.
- Live homepage: `live-home-{390,1440}.png`, rendered HTML and `live-home-evidence.json`.
- Live anonymous entry screenshots: `live-trial-mobile.png`, `live-buy-mobile.png`.
- Both tested local widths have one visible primary trial button and no horizontal overflow/browser page errors. Public homepage and trial/purchase entries returned 200. The external web retrieval tool could not open these URLs; a fresh anonymous browser provided the live evidence instead.
- Temporary review browser contexts and loopback server were closed. Source UI files, paid campaigns, analytics configuration and deployments were not changed by this review. No provider sign-in, payment or customer data was used.

## Follow-up implementation — 27 October 2026 (local, unreleased)

Applied the three concrete quick wins after the owner requested implementation:

- Removed the self-host-only folder-sync tab from both the landing and paid Cloud
  feature page, and removed its unused animation. Six paid-product demonstrations
  remain; the primary trial action, secondary Buy action and pricing are preserved.
- Retained the existing local “For Windows and Linux” / “no server to run” hero
  correction. Publication remains a separate release operation.
- On landing-page viewports below 1000px, the cookie choice reserves space between
  the trial offer and demo. It no longer overlays either. Wider layouts retain
  the corner prompt. Accept and Decline retain identical dimensions and styling;
  consent storage, analytics gating and price-test behavior are unchanged.
- Reopening Cookie settings scrolls the choice into view and focuses its first
  control. Dismissal restores focus to Cookie settings when reopened, or to the
  available primary conversion action for the initial choice, without scrolling
  the visitor to the footer.

Fresh isolated Chrome renders at 320, 390, 768 and 1440 × 844 confirmed no
horizontal overflow, an initially visible trial action, equal consent controls,
no mobile overlap, working dismissal/reopening/persistence, all six demo scenes
and keyboard wraparound, with no browser page errors. The paid Cloud page's six
tabs and cookie controls also passed. Local checked build and website regression
results are recorded in `docs/RELEASE_STATUS.md`. Evidence and screenshots are
under ignored `build/cro-fixes-20261027/`; temporary browsers/server were closed.

Campaign matching, alternative headlines/CTA copy, price placement and funnel
analysis remain recommendations or experiments. No ads, production data, provider
sign-in, trial activation, payment or deployment was operated. No conversion lift
is inferred from these checks.
