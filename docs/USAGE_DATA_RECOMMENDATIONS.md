# Usage data and search: recommendations (2026-10-19)

A review of what Saiph can learn about its website, desktop app and Android app
without weakening end-to-end encryption or the published privacy promises. It
builds on what already exists: `website/ANALYTICS.md` (website pageviews) and
`docs/USAGE_ANALYTICS.md` (opt-in anonymous app counts).

## Status (19 October 2026)

Everything below except the owner steps is implemented on branch
`claude/usage-data-seo`. Nothing is deployed.

| Item | Where | State |
| --- | --- | --- |
| robots.txt, sitemap.xml, canonical, Open Graph/Twitter tags, share image, JSON-LD, unique descriptions | `website/`, `tests/test_website_seo.py` | Done; live after the next landing deploy |
| Allow-listed campaign tags and four button counts | `website/assets/analytics.js`, `website/ANALYTICS.md`, privacy page | Done; live after the next landing deploy |
| Usage schema 2: `active_days`, `os`, `enabled`, `failures`, `crashes` | desktop `usage.py`, Android `UsageAnalytics.kt`, `hosted_usage.py`, `docs/USAGE_ANALYTICS.md` | Done; apps fall back to schema 1 if the service is older |
| Failure counts (Cloud send/receive, file send/receive, Hub connection) | desktop `hosted_transport.py`, `link_client.py`; Android `HostedHttpTransport.kt`, `OrionLink.kt` | Done |
| Crash counts by thread kind | desktop `install_crash_counter`, Android `installCrashCounter` | Done; counts only, no "Send report" flow yet |
| Delivery health, blob sizes, daily active accounts/devices, download tickets | `hosted.py`, `hosted_blobs.py`, `hosted_service.py`, `hosted_usage.py` | Done; in-memory IDs, daily totals only |
| Small-cell suppression | `usage-report --min-cell`, `funnel-report`, `billing:report` | Done; default hides groups under 5 |
| Registry funnel report | `python -m orion_hub.hosted_service_admin funnel-report` | Done |
| Billing funnel report | `npm run billing:report` in `account-web` | Done |
| In-app feedback (rating + text) | — | Not started; needs a design decision on where feedback goes |
| Google Search Console + Bing | Owner | **Owner step** (DNS TXT record) |
| Google Analytics 4 with consent banner, Buy now funnel, server-side checkout/purchase events, price test (off) | `website/assets/consent.js`, `account-web/lib/ga.mjs`, `website/ANALYTICS.md`, `docs/LANDING_CONVERSION.md` | Done in source on `claude/quirky-mirzakhani-7a7546`; off until the owner sets the GA4 measurement ID |

Deploy order: the Hosted service first (so it accepts schema 2), then the
landing site, then desktop and Android releases. Older apps keep working
because the service still accepts schema 1, and new apps resend as schema 1 to
an older service.

## Where things stand

| Source | What exists | State |
| --- | --- | --- |
| Website | Vercel Web Analytics, pageviews only. `assets/analytics.js` strips queries, fragments and UTM tags, drops custom events and honours GPC/DNT. | Live and ingesting. 12–19 Oct: 19 visitors, 43 pageviews (40 on `/`). Every referrer is empty. |
| Website search | Nothing. No `robots.txt`, no `sitemap.xml`, no canonical, Open Graph or structured data tags. Search Console not set up. | Gap. |
| Desktop and Android | Opt-in daily batch (`schema 1`): app, platform, version, mode, install-age range, setup stage, feature-use ranges. No identifier. Folded into daily totals by `hub/orion_hub/hosted_usage.py`. | Built and tested. Self-hosted builds never send. |
| Hosted service | Daily request totals by fixed route name and status class (`service_daily`). | Built. |
| Account and billing | Auth0 sign-ins, Stripe customers and subscriptions in `saiph_billing`. | Data exists. No report built on it. |
| Crashes and errors | Nothing. | Gap. |
| Android SDKs | Firebase Messaging and App Distribution only. No Firebase Analytics or Crashlytics. | Keep it that way. |

## 1. Google Analytics and Vercel

Vercel Web Analytics is Vercel's own product. It does not set up Google
Analytics, send anything to Google, or show which searches brought people to the
site. Pro adds custom events and longer reporting. The site's loader drops custom
events and UTM tags on purpose, so Pro's extras are unused today.

**Update, 19 October 2026: the owner asked for Google Analytics 4, and it is
now built, reversing the recommendation below.** It follows the conditions this
section set: GA loads only after an explicit Accept on a banner where Decline is
equally easy, Consent Mode v2 defaults every signal to denied (basic mode, so
nothing reaches Google before Accept), the site's CSP is opened only to Google's
analytics hosts, and Vercel Web Analytics stays as the cookie-free baseline for
everyone. It measures the Buy now funnel end to end, including server-side
Checkout and purchase events from the account site, with no personal data sent.
Search terms still come from Search Console. Details, the GA4 funnel recipe and
the owner steps: `website/ANALYTICS.md`; research: `docs/LANDING_CONVERSION.md`.
The original reasoning is kept below for the record.

**Original recommendation (superseded): don't add Google Analytics 4.**

- GA4 sets `_ga` cookies and sends a client ID to Google. In Ireland that needs
  a consent banner and opt-in before loading (ePrivacy/Irish DPC guidance).
  It also needs the site's `script-src 'self'` / `connect-src 'self'` policy
  opened to Google's domains.
- It contradicts the product's message on the page that sells encryption.
- It does not show search queries either. That comes from Search Console.

If GA4 is ever required (for Google Ads conversion tracking, say), load it only
after an explicit "Accept" with Consent Mode defaulting to denied. Keep Vercel
as the baseline count.

## 2. Search (SEO)

**Owner step: set up Google Search Console and Bing Webmaster Tools.** They're
free and add no script or cookie to the site, so the privacy page stays the same.
They show the search terms people used, impressions, clicks, average position
and indexing errors. Verify `usesaiph.com` as a *Domain property* with a DNS TXT
record, then submit the sitemap. Bing can import from Search Console, and Bing
data also feeds DuckDuckGo and ChatGPT search.

Site fixes, all source changes in `website/` and the builder:

1. **Add `robots.txt` and `sitemap.xml`.** Both return 404 today. List the
   public pages. Leave out `contact.html` (already `noindex`) and
   `android/oauth2redirect`.
2. **Add canonical links** on every page (`https://usesaiph.com/<page>`). Then
   `www`, `.html` and query variants don't compete with each other.
3. **Add Open Graph and Twitter card tags** plus a 1200×630 share image. Links
   shared on Reddit, X, Discord and WhatsApp show a blank card today, which
   matters for the ad campaign. The campaign stills in
   `docs/marketing/2026-10-campaign` can provide the image.
4. **Add structured data:** a `SoftwareApplication` JSON-LD block on `index.html`
   (name, OS, category, offers €0 self-host / €9.99 Cloud). JSON-LD isn't
   executed, so the current CSP allows it as-is.
5. **Fix the generic descriptions.** `downloads.html`, `privacy.html` and
   `waitlist.html` all say "Current release and launch preparation status."
   Give each its own description and a title with search terms ("Download Saiph
   for Windows, Linux and Android").
6. **Target the searches people already make.** Comparison and intent pages are
   where a new product can rank: "Phone Link alternative for Linux", "KDE
   Connect alternative", "share clipboard between Android and Windows", "send
   SMS from PC Linux". `docs/POSITIONING.md` and the comparison table already
   have the material. The `competitor-alternatives` and `seo-audit` skills can
   draft them.
7. Optional: enable `cleanUrls` in `vercel.json` (`/hosted` instead of
   `/hosted.html`) with redirects. If you do, update the page allow-list in
   `analytics.js`.

## 3. Website analytics within the current boundary

- **Allow-listed campaign tags.** The loader removes every query parameter, so
  the October campaign can't be attributed. Keep `utm_source`, `utm_medium` and
  `utm_campaign` only when the value is on a fixed list in `analytics.js`
  (for example `reddit` / `paid_social` / `2026-10-launch`), and drop the
  rest. Implemented; see `website/ANALYTICS.md`.
- **A few custom events (Pro).** Track intent, not people: `download_click`
  with `platform`, `cloud_click`, `account_click` and `github_click`
  (implemented), plus `buy_click` with `plan` for the Buy now funnel. The
  Self-host link is an ordinary page view of `self-host.html`, so it needs no
  event. No email or account events; Checkout and purchase steps are counted on
  the account site (`billing:report`) and, after Accept, in GA4.
- **Why referrers are empty.** The site's own `no-referrer` policy hides
  internal navigation, and so far traffic has been direct. Search Console
  (section 2) fills this gap for search traffic.

## 4. Business funnel from data we already hold

Account and billing data is not end-to-end encrypted, and Saiph needs it to run
the service anyway. A read-only aggregate report needs no new collection. Add it
as a `usage-report`-style admin command or a dashboard query, run by the owner:

- sign-ups per week (Auth0), trials started, trial → paid conversion, monthly vs
  yearly mix, cancellations and `cancel_at_period_end`, involuntary churn
  (`past_due`)
- devices per account as a distribution (1, 2, 3, 4+), from the Hosted
  registry's `devices` table
- downloads per platform and update checks per version, from `service_daily`
  (`download.file`, `desktop.release`). This is the denominator for the opt-in
  app counts.

Report totals only, and hide any cell under 5 (see section 6).

## 5. App usage: gaps and recommended additions

The current design is sound: opt-in, no identifier, coarse ranges, a published
list enforced by three matching code lists and tests. The additions below keep
those rules. Each one means a `schema: 2` batch with docs, desktop, Android and
service updated together.

| Addition | Why | How it stays private |
| --- | --- | --- |
| `active_days_7`: `1`, `2-3`, `4-6`, `7` | Engagement and stickiness. `install_age` alone can't tell a daily user from a weekly one. | Worked out on the device from local counts. A range, no identifier. |
| `failures`: `connect_failed`, `pairing_failed`, `hosted_send_failed`, `hosted_receive_failed`, `phone_offline` in ranges | Reliability. Today a silent failure looks the same as non-use. | Counts by fixed reason code only. No error text, addresses or device names. |
| `os_family`: `windows_10`, `windows_11`, `linux_x11`, `linux_wayland`; Android `api_29-31`, `api_32-34`, `api_35+` | Which platforms to test and support. | Coarse buckets, no build numbers or device models. |
| `enabled`: feature switches as true/false (notifications mirror, clipboard auto-send, SMS, camera) | What people keep on, not only what they touch. | Booleans from settings, no content. |
| Opt-in crash summary | No crash visibility at all today. | Local crash record shown in **See what Saiph sends**. Sends only app version, component and exception type, without message text, paths or stack frames. A full report goes only by an explicit "Send report" per crash, with its contents shown first. |
| In-app feedback (1–5 rating + optional text) | The "why" behind the numbers. | Voluntary, separate from the batch, text typed by the user for that purpose. |

Two more go on the server and need no app change:

- **Delivery health of sealed events:** daily delivery lag (publish → ack)
  p50/p95, the expired-undelivered share, and blob sizes in ranges. The service
  already sees this metadata. Store daily totals only, never per account. Mention
  it on the privacy page.
- **Daily active Hosted accounts:** a single number per day from accounts that
  polled. Count them in memory and keep only the total.

Don't send any "declined" signal from people who said no; the downloads
denominator in section 4 covers the opt-in rate.

## 6. Small-numbers protection

With a beta this size, one combination of version + platform + mode + age +
stage can be one person. Before anything leaves the admin command or appears in
a shared dashboard:

- hide or merge any cell under 5 installs or accounts
- report `version` grouped to minor version when a patch has under 5 installs
- don't join app totals with account or billing data

## 7. Lines not to cross

These would weaken end-to-end encryption or break the published promise in
`docs/USAGE_ANALYTICS.md`:

- any message, notification, clipboard, file or call content, or anything
  derived from it (word counts, languages, sentiment)
- **notification app names or package names**, even aggregated. They reveal
  which apps (banks, dating, health) a person uses.
- contact names, numbers, file names, exact file sizes, exact counts or times
- install, device, advertising or account IDs in the usage batch; linking
  batches across days
- storing IP addresses or IP-derived location with usage data
- Firebase Analytics, Crashlytics, GA4 or any third-party SDK in the apps or the
  desktop web view (GA4 on the public website and the account site's buy pages,
  after Accept, is the one exception, at the owner's request)
- server-side decryption, or keys held by Saiph, "for diagnostics"
- telemetry from self-hosted Hubs unless the operator opts in separately

## Original suggested order

1. Owner: Search Console + Bing Webmaster Tools via DNS TXT (about 15 minutes).
2. Website SEO pass: robots, sitemap, canonical, Open Graph image, JSON-LD and
   descriptions. Low risk, one PR.
3. Allow-listed UTM tags and the four website custom events, before ad spend
   ramps up.
4. Aggregate funnel report from billing, the registry and `service_daily`, with
   small-cell suppression.
5. Usage `schema: 2` (active days, failures, OS family, enabled switches).
6. Opt-in crash summaries.
