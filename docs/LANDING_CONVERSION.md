# Landing page conversion: research and design rules (2026-10-19)

The owner's most important early-user feedback was that usesaiph.com is too
complicated: "even the laziest visitor should still be able to sign up". This
note collects published conversion research, turns it into rules for this site,
and records what was built from them. Implementation details for analytics are in
`website/ANALYTICS.md`; billing in `docs/PAID_HOSTED.md`.

Sources were read on 19 October 2026. Where only a secondary summary of a study
was available, that is said next to it.

## 1. What the research says

### Minimal pages, one call to action

- **Every extra choice costs attention.** Removing a landing page's navigation is
  the most-repeated landing test. The best-known case (VWO's Yuppiechef test) went
  from 3% to 6% sign-ups, but it published no sample size or stopping rule, so
  treat it as a direction rather than a measured effect
  ([analysis of the Yuppiechef test](https://atticusli.com/blog/posts/landing-page-navigation-ab-test/);
  [summary of 144 navigation experiments](https://experiments.lazyweb.com/research/what-companies-ab-test-nav-landing-pages)).
  The same reviews warn that stripping everything hurts when visitors still need
  to check trust or understand the offer. So: cut destinations, keep the few
  facts a buyer needs.
- **Show value before asking for anything.** Nielsen Norman Group's
  [Login walls](https://www.nngroup.com/articles/login-walls/) research: people
  leave rather than register when they cannot yet see what they get. Ask for an
  account only at the meaningful action (here: paying), and show the benefit
  first.

### Sign-in

- **Forced account creation loses buyers.** Baymard's abandonment survey lists
  "required to create an account" as the reason for **18%** of US shoppers who
  abandoned a checkout, and "checkout too long or complicated" for **17%**
  ([Baymard, cart abandonment rate, updated September 2025](https://baymard.com/lists/cart-abandonment-rate)).
  Baymard's guidance is to make the quickest path the most prominent option
  ([Make "Guest Checkout" prominent](https://baymard.com/research-articles/make-guest-checkout-prominent))
  and to delay account creation to the end
  ([Delayed account creation](https://baymard.com/research-articles/delayed-account-creation)).
- **Saiph cannot offer a guest purchase.** A subscription must belong to a
  signed-in account, or the payer gets no Cloud access (`docs/PAID_HOSTED.md`;
  Stripe Payment Links are ruled out for that reason). The nearest equivalent is
  social sign-in with no form: one "Continue with Google" button, no password, no
  fields, no e-mail confirmation. Auth0 describes "bring your own identity"
  social login as a way of
  [simplifying authentication without compromising security](https://auth0.com/docs/architecture-scenarios/implementation/b2c/b2c-authentication),
  and recommends its hosted Universal Login
  ([Universal Login](https://dev.auth0.com/docs/authenticate/login/auth0-universal-login)).
  Saiph already skips the Auth0 page and goes straight to Google's account
  chooser (`account-web/lib/policy.mjs`).
- **Explain why sign-in is needed, right where it is asked.** A vendor survey
  found 48% of people had abandoned a sign-up form
  ([AYTM](https://aytm.com/post/social-logins-survey)); the KIT study of social
  sign-up screens found people were poorly informed about what they agreed to
  ([Karegar et al.](https://publikationen.bibliothek.kit.edu/1000083574/14753733)).
  One sentence on the sign-in screen ("your subscription belongs to the account
  you sign in with") answers the question a dialog on the website used to.

### Checkout friction

- **Surprise costs are the top reason people leave**: 40% for extra costs, 12%
  for not seeing the total up front, 19% for not trusting the site with a card
  ([Baymard](https://baymard.com/lists/cart-abandonment-rate)).
- **Stripe's guidance** is to cut steps and fields, show the total early, offer
  wallets and saved details, and label the pay button with what it does
  ([Stripe: checkout screen best practices](https://stripe.com/resources/more/checkout-screen-best-practices);
  [Stripe: how to increase checkout conversion](https://stripe.com/resources/more/how-to-increase-checkout-conversion)).
  Stripe recommends its hosted full-page Checkout, which includes Link and dynamic
  payment methods and a full order summary
  ([Stripe Checkout](https://docs.stripe.com/payments/checkout)). Saiph already
  uses it.

### Buy or start a trial

- Published benchmarks agree on direction but not size. A card-required trial
  converts to paid roughly 2 to 3 times as often as a no-card trial
  (First Page Sage: 48.8% vs 18.2%, via
  [Userpilot](https://userpilot.com/blog/?p=1723); ChartMogul's 2026 report, via
  [Mean CEO](https://blog.mean.ceo/?p=11198), 31.4% vs 8.9%). No-card trials get
  more sign-ups; [Sixteen Ventures](https://sixteenventures.com/saas-free-trial-benchmarks/)
  warns to compare per visitor, not per trial. These are SaaS averages from
  secondary summaries; none is for a consumer utility like Saiph.
- EU law already gives every buyer **14 days to withdraw with a full refund**,
  and Saiph refunds even after use (`website/terms.html`). For a buyer that is a
  money-back guarantee, which removes most of the risk a trial exists to remove.

### Consent for Google Analytics (Ireland)

- The Irish Data Protection Commission's
  [guidance note on cookies](https://www.dataprotection.ie/sites/default/files/uploads/2020-04/Guidance%20note%20on%20cookies%20and%20other%20tracking%20technologies.pdf):
  analytics cookies need consent; implied consent and pre-ticked boxes are not
  valid; nudging towards "accept" is not allowed; withdrawing must be as easy as
  giving consent ([DPC FAQ](https://www.dataprotection.ie/en/faqs/cookies/my-website-or-app-uses-cookies-and-other-tracking-do-i-have-get-consent-users));
  and the [DPC cookie sweep](https://www.dataprotection.ie/sites/default/files/uploads/2020-04/Data%20Protection%20Commission%20cookies%20sweep%20REVISED%2015%20April%202020%20v.01.pdf)
  expects a reject option of equal prominence. The note (pages 8–11) also says
  to ask people to reaffirm a stored consent "no longer than six months" later,
  that consent "may not be 'bundled' for multiple purposes", and that the rules
  apply to any information stored on the device (local storage too), personal
  data or not.
- Google Consent Mode v2 has four signals (`ad_storage`, `analytics_storage`,
  `ad_user_data`, `ad_personalization`); defaults must be set before any tag runs
  ([Google: set up consent mode](https://developers.google.com/tag-platform/security/guides/consent)).
  In **basic** consent mode the Google tag does not load at all until the visitor
  accepts, so nothing (not even a cookieless ping) reaches Google from a visitor
  who declines; **advanced** mode loads the tag and sends cookieless pings while
  denied ([Google: consent mode overview](https://developers.google.com/tag-platform/security/concepts/consent-mode)).
- Server-side events go through the GA4 Measurement Protocol, which takes the
  web `client_id` the tag created and a `consent` object
  ([sending events](https://developers.google.com/analytics/devguides/collection/protocol/ga4/sending-events);
  [reference](https://developers.google.com/analytics/devguides/collection/protocol/ga4/reference)).
  The EU endpoint is `region1.google-analytics.com`.
- Cross-domain measurement keeps one client ID across sites with the `_gl` link
  parameter; for subdomains Google recommends making sure every subdomain uses
  the same cookie domain and listing them to avoid self-referrals
  ([GA4 cross-domain measurement](https://support.google.com/analytics/answer/10071811)).

### Price tests and EU consumer law

- **Clear total price before purchase.** The Consumer Rights Directive requires
  the total price including taxes in pre-contract information (Art. 6(1)(e)) and
  again **directly before** the order, with a button that makes the obligation to
  pay unambiguous (Art. 8(2))
  ([Directive 2011/83/EU](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32011L0083)).
  Stripe Checkout's "Subscribe" button and order summary cover the final step.
- **Personalised prices must be disclosed.** The Omnibus Directive added Art.
  6(1)(ea): say so "where applicable, that the price was personalised on the
  basis of automated decision-making"; recital 45 excludes dynamic pricing that
  involves no personalisation
  ([Directive (EU) 2019/2161](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32019L2161)).
  A random price test is not based on the visitor's data, but the safe course is
  still to be open about it. Consumer groups treat the line as unsettled
  ([BEUC on price personalisation](https://www.beuc.eu/sites/default/files/publications/BEUC-X-2023-097_Price_personalisation.pdf);
  [Euroconsumers on dynamic pricing](https://www.euroconsumers.org/is-dynamic-pricing-legal-definitely-maybe/)).
  The Commission's 2021 guidance flags price changes **after the purchase process
  has begun** as a concern (summarised by
  [Euroconsumers](https://www.euroconsumers.org/wp-content/uploads/2024/11/Dynamic-Pricing-Definitely-Maybe.pdf)).
- **Running the test properly.** Kohavi, Tang and Xu's
  [Trustworthy Online Controlled Experiments](https://www.cambridge.org/core/books/trustworthy-online-controlled-experiments/sample-ratio-mismatch-and-other-trustrelated-guardrail-metrics/8DBB0F59AC7729D7BC6B94690DB9CCD5):
  fix the sample size or analysis method before starting (repeatedly checking
  significance, "peeking", is called one of the most common mistakes), and check
  for a sample ratio mismatch (a split that drifts from the planned 50/50 means
  the assignment is broken, and the result can't be trusted).

## 2. Design rules for usesaiph.com

1. **One product on the landing page: Saiph Cloud.** Self-hosting and downloads
   get one quiet text link. Downloads live on `self-host.html` and
   `downloads.html` only.
2. **Say what it is in three lines or fewer**, above the price: what it connects,
   that it's end-to-end encrypted, that there is nothing to set up.
3. **Prices on the first screen, as the total.** Reuse the Cloud page's two-plan
   box. "€9.99 a month" and "€89.99 a year", no VAT added (the trader is not VAT
   registered, `terms.html`), no "from" prices.
4. **One primary button.** While free trials run it is **Start your free
   trial** (30 days, no card), with the price box and a quieter **Buy now** right
   under it; with trials off, **Buy now** is the primary button. The two plan
   cards pick the plan (a radio group); Buy now carries that plan. Monthly is preselected: the smallest
   first payment for a beta product, and no default nudging towards the larger
   one. Yearly keeps its "Save about 25%" label.
5. **Reassurance next to the button, not in a dialog:** sign in with Google, pay
   with Stripe, cancel any time, 14 days to withdraw for a full refund.
6. **Navigation is the logo, Self-host and Account.** The demo animation and the
   comparison table move to the Cloud page (`hosted.html`), one link away.
7. **No pre-sign-in dialog for buying or the trial.** The account site's own sign-in screen
   shows the order (plan and total price) and one "Continue with Google" button,
   with one line on why. The website dialog stays only for the download buttons,
   which are no longer on the landing page.
8. **After sign-in, go straight to Stripe.** No account dashboard in between; the
   chosen plan is carried through sign-in. With JavaScript off, one "Continue to
   payment" button does the same.
9. **Checkout is Stripe's hosted page**, with no added fields. The price shown on
   the website, on the sign-in screen and in Stripe is the same number.
10. **"Start your free trial" first, "Buy now" beside it.** See the decision below.
11. **GA4 only after an explicit "Accept"**: basic consent mode, all four signals
    default to denied, Accept and Decline as identical buttons in one row, a
    "Cookie settings" link in every footer to change the choice, re-ask after six
    months. The banner is small and never blocks the page; on wide screens it
    sits in a corner, clear of the Buy button. Vercel Web
    Analytics (cookie-free) keeps counting for everyone as the baseline.
12. **Price tests are random, sticky and disclosed**: one variant per visitor,
    kept for 90 days; the variant's price shown on the landing page, the sign-in
    screen and in Stripe; never changed after a visitor clicks Buy; existing
    subscribers keep the price they signed up at. Only visitors who accepted
    analytics take part (assigning and remembering a variant stores something on
    the device, which needs consent); everyone else sees the standard price.
    The banner names price testing as part of what "Accept" allows, treating it
    as one measurement purpose. Because the DPC forbids bundling separate
    purposes, the owner should confirm that reading before switching a test on;
    the stricter alternative is a second, separate choice. Plan the sample size
    first, don't stop early, and check the split.

### Decision: "Start your free trial" first, "Buy now" beside it

Updated 19 October 2026, after the owner switched on a **30-day free trial with
no card** (`SAIPH_TRIAL_DAYS=30`). The first version of this page made Buy now the
main button, because card-required conversion to paid is 2 to 3 times higher in
every benchmark found. With a no-card trial live, the research points the other
way for this page's goal ("even the laziest visitor can still sign up"):

- **Least effort wins the first step.** A no-card trial is one Google sign-in and
  nothing else: no plan choice, no card, no price decision. Baymard's top
  abandonment reasons (extra costs, trust with card details, forced accounts)
  mostly disappear when nothing is paid.
- **More people start.** No-card trials produce several times more sign-ups per
  visitor than card-required ones; the lower trial-to-paid rate is the price of
  that (Sixteen Ventures: compare per visitor, not per trial). For a new product
  whose owner wants active users first, starts per visitor is the right measure.
- **Honest and clear.** The button text says what happens; the line under it
  gives the trial length, "no card needed", the price afterwards (€9.99 a month or
  €89.99 a year) and that nothing is charged automatically, which matches the
  trial terms (Cloud pauses until you subscribe).
- **Buyers keep the short path.** The price box and Buy now stay directly under
  the trial button ("Or subscribe now"), so anyone ready to pay goes straight to
  Stripe. Subscribing during a trial keeps the remaining free days (the first
  payment is taken when the trial ends).

The trial path mirrors Buy now: usesaiph.com **Start your free trial** →
account site `/trial` (what you get, one **Continue with Google** button) →
Google → back to `/trial`, which starts the trial with no further click and opens
the account page with the downloads. Someone who already used a trial, already
subscribes, or meets a full cap goes to the account page, which explains why and
offers the plans.

Measure both paths (website/ANALYTICS.md). The next experiment worth running is
trial-first against Buy-first, judged on paying customers per 100 landing visits
after 45 days, not on trial starts alone.

## 3. What was built

| Rule | Where |
| --- | --- |
| 1–6 Simplified landing, trial button, price box, Buy now, no downloads | `website/index.html`, `website/assets/site.css`, `website/assets/site.js`, `website/landing-settings.json` (`hostedTrial`) |
| Trial path: `/trial` sign-in screen, return through Google, automatic trial start, counted | `account-web/app/trial/`, `account-web/lib/buy.mjs`, `account-web/lib/billing/http.ts` (`trialAction` counting only) |
| Demo and comparison moved | `website/hosted.html` |
| 7–9 `/buy/monthly` and `/buy/yearly` sign-in screen, plan carried through Google sign-in, automatic hand-off to Checkout | `account-web/app/buy/[plan]/`, `account-web/lib/auth.ts`, `account-web/lib/buy.mjs` |
| 11 Consent banner, Consent Mode v2, GA4 loader, CSP | `website/assets/consent.js`, `vercel.json`, `account-web/app/buy/[plan]/page.tsx`, `account-web/lib/security.mjs`, `account-web/proxy.ts` |
| Funnel events and server-side checkout/purchase events | `website/assets/consent.js`, `website/assets/site.js`, `account-web/lib/ga.mjs`, `account-web/lib/billing/http.ts`, `account-web/lib/billing/service.ts` |
| Aggregate funnel without GA | `account-web/lib/billing/report.mjs`, `account-web/lib/funnel.ts`, migration `0006_funnel_counts.sql`, Vercel `buy_click` in `website/assets/analytics.js` |
| 12 Price test, off by default | `website/assets/consent.js` (`priceTest` settings), `account-web/lib/billing/price-test.mjs`, `account-web/lib/billing/policy.ts` |
| Trust on the payment path: no "Development" badge or "(draft)" legal links when billing is live | `account-web/app/layout.tsx` |

Tests: `tests/test_website_buy.py` (landing structure, footer and legal links on
every page, CSP, builder validation, consent banner and GA loading in a synthetic
DOM, price-test assignment, Buy links); `account-web/tests/buy-funnel.test.mjs`
(return-path allow-list, price-test configuration, consent cookie parsing,
Measurement Protocol payloads, Checkout with variants and consent, purchase
counting from the signed webhook); new cases in `billing-report.test.mjs`,
`billing-db.test.mjs` (real PostgreSQL) and `http-smoke.mjs` (production Next
server). None of them contacts Google, Stripe, Auth0 or Neon; live Checkout,
GA4 ingestion and the real Google sign-in round trip are not verified by them.

How to read the funnel, the price-test procedure and the owner steps are in
`website/ANALYTICS.md`.
