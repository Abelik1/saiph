# Public website analytics

## Google Analytics 4 and the Buy now funnel (19 October 2026)

The owner asked for Google Analytics. This reverses the earlier "don't add GA4"
recommendation (`docs/USAGE_DATA_RECOMMENDATIONS.md`, section 1); the conditions
that recommendation set (explicit Accept, Consent Mode defaulting to denied,
Vercel kept as the baseline) are how it is built. The research and design rules
are in `docs/LANDING_CONVERSION.md`.

**Off until the owner sets a measurement ID.** With `ga4.measurementId` empty
(the default) there is no banner, no cookie and no Google request. Vercel Web
Analytics (below) keeps working either way, for every visitor, cookie-free.

### How consent works

- `assets/consent.js` runs on every page. With a measurement ID set it shows a
  small banner: "May we use Google Analytics cookies…" with **Accept** and
  **Decline** as identical buttons and a link to `privacy.html#cookies`.
- **Basic Consent Mode v2.** Nothing from Google loads before Accept. After
  Accept the page sets all four signals (`ad_storage`, `analytics_storage`,
  `ad_user_data`, `ad_personalization`) to `denied`, then updates only
  `analytics_storage` to `granted`, then loads `gtag.js`. Google signals and ad
  personalisation are off. Declining loads nothing.
- The choice is a first-party cookie `saiph_consent=v1.<granted|denied>.<time>`
  on `usesaiph.com` (so the account site sees the same choice), kept six months,
  then asked again (DPC guidance). **Cookie settings** in every footer reopens
  the banner; Decline after Accept deletes the `_ga` cookies. GPC or Do Not Track
  counts as Decline.
- GA loads only on `https://usesaiph.com` and `https://www.usesaiph.com`; Vercel
  previews and local builds can show the banner but never contact Google.
- Page addresses sent to GA keep only `utm_source`, `utm_medium`, `utm_campaign`
  and `utm_content`; other query values are removed.
- CSP: the root `vercel.json` now sends a Content-Security-Policy for every page
  except `/android/*` (which keeps its own stricter policy) and `/.well-known/*`:
  scripts from `self` and `https://www.googletagmanager.com`, connections and
  images to `*.google-analytics.com`, `*.analytics.google.com` and
  `*.googletagmanager.com`. The account site adds those hosts only on
  `/buy/monthly`, `/buy/yearly` and `/trial`, and only when `GA4_MEASUREMENT_ID` is set
  (`account-web/lib/security.mjs`).

### The funnel and where each step is recorded

| # | Step | GA4 event | Recorded by | Without GA (aggregate) |
| --- | --- | --- | --- | --- |
| 1 | Landing visit | `page_view` (automatic) | usesaiph.com tag | Vercel pageviews of `/` |
| 2 | Buy now click | `buy_click` with `plan` | usesaiph.com tag | Vercel event `buy_click` with `plan` |
| 3 | Reached the sign-in page | `signin_view` with `plan` | account site `/buy/<plan>` page tag | `billing:report` `signin_view` |
| 4 | Sign-in completed | `login` with `method` (`google` just now, `session` if already signed in) | account site `/buy/<plan>` page tag | `billing:report` `signin_done` (counted in the Auth0 callback) |
| 5 | Stripe Checkout started | `begin_checkout` with `plan`, `currency` | account site **server** (Measurement Protocol) | `billing:report` `checkout_started` |
| 6 | Purchase completed | `purchase` with `plan`, `value`, `currency`, `transaction_id` | account site **server**, from the verified Stripe webhook | `billing:report` `purchase` |

The free-trial path (the landing page's main button while trials run) has its
own steps, with `plan` = `trial`:

| # | Step | GA4 event | Recorded by | Without GA (aggregate) |
| --- | --- | --- | --- | --- |
| 1 | Landing visit | `page_view` | usesaiph.com tag | Vercel pageviews of `/` |
| 2 | Start your free trial click | `trial_click` | usesaiph.com tag | Vercel event `trial_click` |
| 3 | Reached the trial sign-in page | `signin_view` with `plan` = `trial` | account site `/trial` page tag | `billing:report` `funnel.trial.steps.signin_view` |
| 4 | Sign-in completed | `login` with `plan` = `trial` | account site `/trial` page tag | `funnel.trial.steps.signin_done` |
| 5 | Trial started | `trial_start` | account site **server** (Measurement Protocol), once per new trial | `funnel.trial.steps.trial_started` (and `trialsStarted` from the trials table) |

A trial that later becomes a subscription shows up as `begin_checkout` and
`purchase` for the same client ID, and in `billing:report` as `trialConversion`.

Every event also carries `price_test` and `price_variant` while a price test
runs. Server-side events are sent only when the request carries an Accept
cookie, use only Google's client ID from the `_ga` cookie, deny both
advertising signals, go to the EU endpoint (`region1.google-analytics.com`) and
never include an email, name, account subject, Stripe customer, subscription or
session ID. `transaction_id` is a hash of the Checkout session ID, so GA can
de-duplicate without seeing Stripe's ID. For the purchase, the client ID is kept
in the Checkout Session's metadata (`saiph_ga`; never on the customer or the
subscription) because the webhook has no browser cookie. A purchase is counted
when its `checkout.session.completed` event is first applied, so Stripe retries
never count twice. Analytics can never fail a checkout or a webhook: errors and
timeouts (2 s) are ignored.

Cross-domain: `account.dev.usesaiph.com` is a subdomain, and both sites set the
GA cookie on `usesaiph.com`, so the client ID is shared without link
decoration. The tag also lists both domains in `linker` for safety.

### Reading the funnel in GA4 (exploration recipe)

1. In GA4, **Admin → Data display → Custom definitions → Create custom
   dimension** (event scope) for `plan`, `price_test`, `price_variant` and
   `method`. Mark `purchase` as a key event (it usually is by default).
2. **Explore → Funnel exploration.** Set *Open funnel* off and *Show elapsed
   time* on. Steps:
   1. Landing visit: event `page_view` where *Page path* exactly matches `/`
   2. Buy now: event `buy_click`
   3. Sign-in page: event `signin_view` (people already signed in skip it; to
      include them, make the step `signin_view` **or** `login` with `method` =
      `session`)
   4. Signed in: event `login`
   5. Checkout started: event `begin_checkout`
   6. Purchase: event `purchase`

   For the trial path make a second funnel: `page_view` (`/`) → `trial_click`
   → `signin_view` with `plan` = `trial` → `login` with `plan` = `trial` →
   `trial_start`, and optionally → `purchase` with *Open funnel* on and a 45-day
   window to see trials that became paying customers.
3. *Breakdown*: `plan`, or `price_variant` while a test runs. *Segment
   comparisons*: Session source / medium for campaigns.
4. The "abandonment" row under each step is where journeys end. Save the
   exploration as "Buy now funnel".

GA4 only sees visitors who pressed Accept. For whole-population totals use
Vercel (steps 1 and 2) and `npm run billing:report` (steps 3 to 6); the two
together show the same journey without consent bias but not per person.

### Aggregate funnel without GA

`npm run billing:report` (in `account-web`, owner-run with the account site's
environment) now has a `funnel` section from the daily counts in
`saiph_billing.funnel_daily` (migration 0006): totals per step, the percentage
that reached each step from the previous one, and the same per plan and per
price-test variant, plus weekly rows. `funnel.total` is the Buy now path;
`funnel.trial` is the free-trial path (sign-in page, sign-in done, trial
started). Counts under `--min-cell` (default 5) are
shown as `<5`. The table holds only day, step, plan, test and variant: nothing
about who. Until migration 0006 is applied, counting is skipped and `funnel` is
`null`; nothing else changes.

### Price test

Off by default; nothing is switched on by this change.

- **Website** (`landing-settings.json`): `priceTest` =
  `{"enabled": true, "id": "2026-11-price", "variants": {"b": {"monthly": "€7.99", "yearly": "€69.99"}}}`.
  Variant `a` is always the standard price. The builder refuses an enabled test
  without an id, a variant, open subscriptions and an approved privacy notice.
- **Account site** (Vercel, server-only): `SAIPH_PRICE_TEST` maps the same
  variants to Stripe prices and amounts in cents:
  `{"id":"2026-11-price","variants":{"b":{"monthly":{"price":"price_…","amount":799},"yearly":{"price":"price_…","amount":6999}}}}`.
  Checkout verifies the Stripe price's amount, currency and interval against it.
  An invalid value switches the test off (logged by name) and never turns
  billing off. Keep a variant's prices configured for as long as any subscription
  uses them: the webhook only accepts subscriptions on configured prices.
- **Assignment** (`assets/consent.js`): random, once per visitor, kept 90 days.
  Assigning and remembering a variant stores something on the device, so only
  visitors who had already pressed Accept when the price first appeared are
  drawn; a visitor who sees the standard price and then accepts keeps it and is
  marked out of the test, so nobody sees a price change. Campaign links may also
  carry `?offer=b` (no storage); split the ads randomly in the ad platform.
- **Shown before purchase:** the landing box, the account site's sign-in page
  (from the server's own configuration) and Stripe Checkout all show the
  variant's price, with a note that prices are being tested. The Buy link sends
  the variant only if the page could show its prices.
- **Recorded:** `price_test` and `price_variant` on every GA event, and per
  variant in `billing:report`. Checkout Session metadata carries
  `saiph_price_test` and `saiph_variant`.
- **Running it properly:** decide the primary metric (purchases per Buy-page
  visit, or revenue per visitor), the minimum detectable effect and the sample
  size *before* starting; run whole weeks; don't stop early on a good day; check
  the split stays near 50/50 (a sample ratio mismatch means broken assignment);
  only consenting visitors take part, which is fine for comparing variants but
  not for absolute rates.
- **Ending it:** set `enabled` to `false` on the website first (new visitors see
  the standard price), then later remove `SAIPH_PRICE_TEST` only once no
  subscription uses its prices. Existing subscribers keep their price; changing
  it needs 30 days' notice under the Cloud terms.

### Owner steps

1. **Create the GA4 property** (Analytics → Admin → Create property, time zone
   Ireland, currency EUR) and a **Web data stream** for `https://usesaiph.com`.
   In the stream: turn off *Enhanced measurement → Form interactions* and *Site
   search*; under *Configure tag settings → Configure your domains* add
   `usesaiph.com` and `account.dev.usesaiph.com`; under *List unwanted
   referrals* add `account.dev.usesaiph.com`, `checkout.stripe.com` and
   `accounts.google.com`. Admin → Data collection: leave Google signals **off**.
   Admin → Data retention: **2 months** (the privacy notice says so).
   Accept Google's data processing terms (Admin → Account settings).
2. Put the stream's **Measurement ID** (`G-…`) into `website/landing-settings.json`
   `ga4.measurementId`, and into the account site's Vercel environment as
   `GA4_MEASUREMENT_ID`. For server-side checkout and purchase events, create a
   **Measurement Protocol API secret** (stream → Measurement Protocol API
   secrets) and add it to the account site as `GA4_API_SECRET` (server-only;
   never in the website settings or Git). Redeploy both.
3. Apply **migrations 0005 and 0006** to the account database (whole
   `account-web/migrations/reviewed-migration.sql`, receipt shows versions 1–6;
   0005 is the trial extension, 0006 the funnel counts) before or after
   deploying; until then funnel counting is skipped.
4. **Search Console and Bing** (unchanged, see below).
5. **Choosing test prices** is the owner's decision: pick them, create the
   recurring EUR prices on the existing Saiph Cloud product in Stripe (live
   mode), set `SAIPH_PRICE_TEST` on the account site and `priceTest` in the
   website settings with the same numbers, and confirm the legal reading in
   `docs/LANDING_CONVERSION.md` (price testing named under the analytics
   Accept). Nothing here creates prices or starts a test.
6. After deploying, check in the browser: banner appears; Decline loads nothing
   from Google (Network panel); Accept loads `gtag/js` and sends a `page_view`;
   GA4 **DebugView**/Realtime shows `buy_click`, `signin_view`, `login`, and
   after a real purchase `begin_checkout` and `purchase`.


## Vercel Web Analytics (cookie-free baseline)

19 October 2026 update: besides pageviews, the loader now keeps allow-listed
campaign tags and counts five kinds of button press (`buy_click` added with the
Buy now funnel). Both are rebuilt from fixed
lists in `assets/analytics.js`; anything else is dropped.

- **Campaign tags** on pageviews: `utm_source`, `utm_medium` and `utm_campaign`
  only when the value is on the lists in `analytics.js`, and `utm_content` only
  when it looks like an ad ID (`01-ecosystem-convenience`). `utm_term`, other
  parameters and fragments are always removed. To run a new campaign, add its
  `utm_campaign` name (and any new source) to `analytics.js` in a reviewed change
  and tag links like
  `https://usesaiph.com/?utm_source=reddit&utm_medium=paid_social&utm_campaign=2026-10-launch&utm_content=01-ecosystem-convenience`.
- **Custom events** (Vercel Pro): `download_click` with `platform` (`windows`,
  `linux`, `android` for the Firebase beta, `android_apk`, `server`),
  `buy_click` with `plan` (`monthly`, `yearly`), `cloud_click`, `account_click`
  and `github_click`. Each records which public
  page it happened on, never the link target. The `beforeSend` hook returns a
  rebuilt payload for every event, because the provider would otherwise keep its
  original payload.
- **Reading them:** Vercel → saiph-landing → Analytics: the UTM panels and the
  Events panel. The Vercel MCP/API `aggregate_pageviews` / events endpoints give
  the same data.

The privacy notice (`privacy.html#analytics`) describes both. GPC/Do Not Track,
the page allow-list and the referrer checks apply to events too.

**Search (owner step):** add `usesaiph.com` to Google Search Console as a Domain
property (DNS TXT record at the domain's DNS provider), then submit
`https://usesaiph.com/sitemap.xml`. Import the property into Bing Webmaster
Tools. Neither adds a script or cookie to the site.

16 October 2026 update: the owner confirmed enabling Web Analytics in the landing
project dashboard. `landing-settings.json` now opts into public-page analytics
using `/_vercel/insights/script.js`; unconfigured builds still default to off,
and local previews remain excluded by the loader. The existing production bundle
was observed with analytics off and its script route returning 404 before this
source change. A fresh deployment is needed for both the build setting and
Vercel's analytics routes to take effect. Provider acceptance and dashboard
ingestion have not been verified. Keep the current-visit status on the privacy
page rather than in every page footer. The historical preparation notes follow.

Vercel Web Analytics source is ready, **disabled by default**. This change does
not activate the dashboard, change a plan, deploy, approve a privacy notice or
instrument the account/Auth0/Stripe application. Website settings generated by
`build-website.py` contain:

```json
"analytics": {
  "enabled": false,
  "scriptPath": "/_vercel/insights/script.js"
}
```

## Collection boundary

`assets/analytics.js` queues Vercel's documented `beforeSend` hook before loading
the same-origin provider script. Only pageviews of explicitly listed public
HTML pages are accepted. Queries, fragments and unknown event properties are
removed; custom events, identify/group events and private/unknown paths are
dropped. There is no button, email, checkout or account event tracking. No
application cookies or identity calls are added. Global Privacy Control and Do
Not Track disable collection for that visit.

Only the verified public landing origins `https://usesaiph.com` and
`https://www.usesaiph.com` are enabled in source. Localhost, account
hosts, unrelated hosts and per-deployment preview aliases are excluded. Add a
new approved production hostname through a reviewed source change rather than
broadly allowing Vercel preview or account domains.

The provider reads `document.referrer` independently of `beforeSend`. The loader
therefore skips visits with referrer credentials, queries, fragments, non-HTTPS
URLs, unknown same-site paths or external paths beyond `/`. Ordinary external
origin-only referrals and known same-site public pages remain eligible. This
intentionally undercounts some visits. Each public page also sets a
`no-referrer` policy so browser request headers do not forward its full URL to
analytics endpoints or external links. URL stripping is not a claim that Vercel
hosting has never received the original HTTP request.

When enabled, Vercel receives the analytics request, including its network IP
address, and processes request metadata to derive aggregated browser, device
and geographic statistics. Its published privacy documentation describes a
visitor hash discarded after 24 hours; that is not an aggregate-data retention
period or an EU-only processing commitment. Confirm the actual project plan,
retention, processor contract and transfers in the website notice before
activation. Do not infer that cookie-free analytics settles every legal basis
or disclosure requirement.

## Owner dashboard step

Read-only project inspection on 11 October 2026 confirmed the landing project and
its production deployment. Team, project and deployment identifiers are recorded
in the private operations repository. The connected project tool does not expose
analytics enablement or retention. They remain unverified; no dashboard setting
or billing option was changed.

With the owner, open the landing project's Analytics dashboard in Vercel:

1. Verify the team and project; review Web Analytics enablement, the current
   plan, included usage, spending settings and retention. Do not select an
   upgrade or paid add-on merely to finish this checklist.
2. Finalize the website analytics notice, lawful-basis decision, working public
   controller contact, retention and transfer facts. Incorporate the separate
   legal/privacy work before changing privacy status to `approved`. The builder
   and loader reject activation with draft/incomplete privacy settings.
3. Enable **Web Analytics for `saiph-landing` only** when the owner is ready.
   Enabling adds analytics routes after a subsequent deployment; it does not
   enable this source configuration. Leave `saiph-account-dev`, Auth0, Stripe,
   the personal CV apex/www and unrelated projects unchanged.
4. Copy the HTML script path shown for this project. The legacy same-origin path
   is the default above; for Vercel v2's generated path set `scriptPath` to the
   actual `/<unique-path>/script.js`. The builder accepts only same-origin fixed
   script paths, with no credentials, query or arbitrary script URL. Use the
   path actually supplied by Vercel; do not invent one. The loader derives the
   same prefix's `/view` and `/event` endpoints.
5. Set `analytics.enabled` to `true` in the reviewed public deployment settings
   and build a fresh static bundle. Operations must verify the intended project
   before deploying that bundle. Existing `script-src 'self'` and
   `connect-src 'self'` policies suffice; no inline script, third-party script
   origin or broad CSP relaxation is needed. Preserve existing security headers.
6. On the allowed production hostname, use the browser Network panel to confirm
   one script load and a successful pageview request. Inspect the request JSON:
   a visit to `/downloads.html?synthetic=redaction-check#example` must report only
   the origin and `/downloads.html`, without those values. Verify the dashboard
   receives that pageview, then test public navigation. Source tests alone do
   not establish provider acceptance or dashboard ingestion.
7. Verify a sensitive route/unsafe referrer and a browser GPC/DNT preference do
   not load the analytics script. Verify account/checkout requests contain no
   analytics requests. Record the source commit, settings/manifest hashes,
   project/deployment, date and observed Network/dashboard result.

Because previews are excluded, finish ingestion acceptance on the allowed
production hostname after explicit activation. Local tests simulate activation
with synthetic data and never contact analytics ingestion.

## Disable and rollback

Set `analytics.enabled` back to `false`, rebuild and deploy the reviewed bundle
to the landing project. This stops future script loading; it does not delete
previously collected statistics. If required, disable Web Analytics in that
project's dashboard and follow the provider's retention/deletion process. Record
that work separately. A dashboard toggle alone is not evidence that all copies
of earlier data have been erased.

## Validation and primary references

On Windows, Python 3.12 and Node 24, the offline checks were:

```powershell
py -3.12 -m pytest tests/test_website_analytics.py tests/test_website_release.py tests/test_website_downloads.py tests/test_public_release_metadata.py tests/test_release_readiness.py -q -p no:cacheprovider
```

Result: **183 passed, 1 skipped**. The existing directory-symlink check skips
because this Windows environment lacks symlink creation privilege; no analytics
privacy-boundary test was skipped. The tests exercise the
shipped loader in Node with a synthetic DOM, build validation and negative
route/referrer/event cases. They do not substitute for the owner's browser and
dashboard acceptance above.

The checked landing bundle prepared 12 static files with analytics disabled.
`node --check website/assets/analytics.js` and `git diff --check` passed.
The broader `verify-public.py` desktop-suite attempt could not collect six test
modules because this Python environment lacks PySide6, qrcode and tink. No
repository-wide desktop pass is claimed for this website-only change.
Read-only inspection of the current public landing response confirmed
`script-src 'self'` and `connect-src 'self'`; the source adds the stricter
per-page `no-referrer` meta policy before any scripts.

Primary Vercel documentation reviewed 11 October 2026:

- [HTML setup and dashboard activation](https://vercel.com/docs/analytics/quickstart)
- [beforeSend and v2 script/endpoint configuration](https://vercel.com/docs/analytics/package)
- [Sensitive-data redaction](https://vercel.com/docs/analytics/redacting-sensitive-data)
- [Analytics privacy and collected metadata](https://vercel.com/docs/analytics/privacy-policy)
- [Current limits and pricing to review in the dashboard](https://vercel.com/docs/analytics/limits-and-pricing)
