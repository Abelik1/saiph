# Paid Hosted access

Status, 14 October 2026: **design agreed by the owner and implemented in source
on `feat/paid-hosted`, with synthetic tests only.** Nothing is deployed. No real
Stripe sandbox checkout has reached the Hosted service yet, and sandbox results
will not establish live readiness. Live payments stay off.

## Problem

The account website stores Stripe subscription observations from the signed
webhook (`account-web/lib/billing/*`) and derives a billing standing. The Hosted
service admits accounts only through durable grants in `accounts.sqlite3`
(`access_grants`: `admin` and `beta`). Before this change nothing connected the
two, so a paying customer got no Hosted access.

## Design

1. The account website stays the only party that talks to Stripe. After it
   applies a **signed, verified Stripe webhook** to its database, it pushes the
   resulting paid grant to the Hosted service.
2. The push is a small JSON command signed with an **Ed25519 billing key**. The
   website holds the private key (server-only Vercel environment). The Hosted
   service holds only public keys and verifies every push
   (`hub/orion_hub/hosted_billing.py`).
3. The Hosted service stores the grant in the existing `access_grants` table as
   `kind='paid'`, `reference='stripe:<subscription id>'`, with an expiry. The
   existing check (any unrevoked, unexpired grant) then admits bearer and
   signed-device requests exactly as it does for beta codes.
4. Beta codes, admin grants and account suspension are unchanged and work
   alongside paid grants. A push can only change its own `paid` row.

Prices (owner decision, 16 October 2026): **€9.99 per month or €89.99 per year**, one
Stripe product with two recurring EUR prices. The code refuses a configured
price whose amount or interval differs. Before releasing this change, operations
must create the €9.99/month and €89.99/year recurring prices and update the protected
price IDs and billing portal configuration. Existing subscriptions are not
migrated by this source change; refunds continue to use actual paid charges.

## Trust boundary

| Party | Trusted for | Not trusted for |
| --- | --- | --- |
| Stripe | Subscription and dispute status, fetched by the website with its restricted key after a signed event | Identity |
| Account website server (Vercel) | Mapping a verified login (issuer/subject) to a Stripe customer; deciding the paid grant expiry from stored webhook observations | Approving devices, reading content, touching beta/admin grants |
| Browser | Nothing about payment. Checkout return URLs and query strings only choose a notice | |
| Hosted service | Final admission decision; device approval stays with the user's root device | |

What the Hosted service must trust: **whoever holds the billing private key can
grant or end paid access for any account, for at most 45 days per push** (31 days
for a free trial, and one trial per account). It
cannot approve devices, decrypt anything (content is end-to-end encrypted), extend
beta/admin grants, reactivate a suspended account, or move a subscription to a
different account. If the key leaks: remove its public key from the service
environment (pushes then fail closed while existing paid grants run out), create
a new key, and run `npm run billing:resync`.

Rejected alternatives:

- *Auth0 client-credentials token for the website.* The operations docs forbid
  enabling client credentials; it would also widen the Auth0 surface.
- *Shared HMAC secret.* Works, but puts a forging secret on the droplet as well.
  Ed25519 leaves only a public key there.
- *Hosted service calls Stripe itself.* Adds a Stripe client, a second
  customer/subject mapping and memory on a 1 GB host that already peaks near its
  limit. The website already holds the Stripe write key, so the trust gain is
  small.

Identity: the website's customer row binds `auth_subject` (from the verified web
session) to one Stripe customer, immutably. The push carries the website's Auth0
issuer (`https://<AUTH0_DOMAIN>/`) and that subject; the service refuses any
other issuer and finds or creates the account by issuer/subject, as beta
redemption does. The first account a subscription names keeps it (a push naming
another account gets 409). Web tokens and native tokens remain separate; the
push uses neither. The website reads access through `GET /v1/billing/access`
(web token only), which adds which grant kinds apply, and falls back to the
existing `/v1/beta/access` against an older service release.

## Grant lifecycle

The website computes the grant from its stored subscription row and dispute
records (never from an event payload or a redirect), in
`account-web/lib/billing/grant.mjs`:

| Stripe state | Paid grant expiry pushed |
| --- | --- |
| `active`/`trialing`, renewing | `current_period_end` + 72 h (covers late renewal webhooks) |
| `active`, cancellation scheduled | the scheduled end, no grace |
| `past_due` (payment failed) | first observed failure + 3 days while Stripe retries (owner decision) |
| `unpaid`, `paused`, `incomplete`, `canceled`, `incomplete_expired` | 0 (access ends) |
| Open or lost dispute on the customer | 0 until the dispute is won (owner decision) |
| Free trial (`trial:<ref>`, no Stripe) | the trial end (at most 30 days after it starts), never extended |

Every pushed expiry is also capped at **now + 35 days**. The service rejects
anything beyond now + 45 days. A yearly subscription is therefore granted 35
days at a time: a daily Vercel Cron (`/api/billing/refresh`, `CRON_SECRET`)
re-pushes any grant with fewer than 25 days left. If the website, the cron or
the key stops working, paid access runs out by itself within 35 days, never
later. Monthly grants (one period plus 72 h) normally fit inside the cap.

Ending access never deletes the account, its workspace or devices. A later push
(renewal, resubscription, dispute won) raises the expiry again. A new
subscription after cancellation is a new `stripe:<id>` grant.

## Idempotency and ordering

- **Stripe → website:** unchanged. `processed_events` is the append-only receipt
  ledger (now also for dispute events); duplicates are no-ops; the current
  subscription or dispute is re-fetched from Stripe under a per-customer lock;
  terminal states cannot be undone by older events.
- **Website → service:** applying an event marks the affected grants as needing
  delivery (`grant_state.dirty`) in the same transaction. Delivery then runs in
  its own transaction under the same customer row lock: it reads the current
  row, takes a new number from the Postgres sequence `grant_sequence`, pushes,
  and records the delivered expiry. A webhook for the same customer waits for
  that lock, so a later decision always carries a higher number. The service
  stores the last applied number per grant and ignores any push at or below it:
  repeats are harmless and an older push arriving late cannot overwrite a newer
  one.
- **Delivery failures:** if the service is unreachable or refuses the push, the
  webhook answers 503, so Stripe retries the event (for up to three days). The
  retry is a duplicate for the ledger but finds the grant still marked and pushes
  again. The daily refresh also retries anything still marked. After restoring
  the service from a backup or rotating keys, `npm run billing:resync` re-pushes
  every current grant.

Signed push format: `POST /v1/billing/grant`, body exactly
`{"issuer","subject","grant","until","sequence","livemode"}` in that order,
header `Saiph-Billing-Signature: t=<unix>,k=<key id>,v1=<base64url Ed25519 over
"saiph-billing-grant-v1." + t + "." + body>`. The service rejects timestamps more
than 5 minutes off, unknown keys, extra or duplicate fields, cookies, origins,
bearer tokens, query strings and bodies over 2 KB. A shared synthetic vector in
both test suites checks that the two implementations agree.

## Sandbox and live separation

- Each push states `livemode`. The service accepts pushes only for the mode it is
  configured for (`ORION_BILLING_GRANTS=sandbox|live`), and test and live use
  different signing keys. A test-mode subscription cannot grant access on a
  live-configured service.
- `SAIPH_BILLING_MODE=owner-sandbox` requires `rk_test_` keys and lets only the
  owner's subject check out (owner decision). The grant sync also pushes 0 for
  any other subject in sandbox mode. Otherwise anyone who signs in could get real
  Hosted access on the development service with Stripe's 4242 test card.
- `SAIPH_BILLING_MODE=live` requires `rk_live_` keys, lets any signed-in user
  subscribe (still subject to `SAIPH_REQUIRE_MFA`), and requires the customer to
  accept the terms of service in Checkout. `SAIPH_BILLING_AUTOMATIC_TAX=true`
  turns on Stripe Tax once the owner has set it up.
- One billing database serves one mode: the store records the mode on first use
  (`saiph_billing.settings`) and refuses the other afterwards. Live needs its own
  database.

## Refunds and disputes

- **Refund** alone does not change access (a partial goodwill refund is common).
  To refund and end service, the owner cancels the subscription immediately with
  a refund in the Stripe dashboard; `customer.subscription.deleted` ends the grant.
- **Dispute (chargeback):** the webhook accepts `charge.dispute.created`,
  `.updated` and `.closed`, fetches the current dispute and its charge's customer
  from Stripe, and stores the status. `needs_response`, `under_review`, `lost`
  and any status Stripe adds later end paid access at once; inquiries
  (`warning_*`), `won` and `prevented` do not. Disputes never affect beta or
  admin grants.

## Account page

One page for beta and paid users (`app/account`): current Hosted access from the
service and whether it comes from a subscription or a beta invitation; the
subscription state and renewal or end date from stored webhook observations;
**€9.99 / month** and **€89.99 / year** buttons when there is no current
subscription; **Manage billing** (Stripe customer portal) once a customer exists;
and the beta code form. After returning from checkout the page says Stripe is
confirming the payment; it never treats the return as payment.

## Free trial on sign-up

Owner request, 19 October 2026: "a free trial on sign up so that we can get more
active users". Implemented in source on `claude/cloud-free-trial-0f6417`, with
synthetic tests only. Nothing is deployed; the steps below are owner-run.

**What a person gets.** Every new Saiph account can start **one free trial of 14
days** (configurable) from the account page with one press of **Start free
trial**. No card, no Stripe customer, no checkout. The trial is a Hosted grant
like a paid one, so it admits the account's bearer and device requests exactly as
a subscription does. An optional cap ("the first 100 people") is off by default.

**How it is granted.** The account website decides and the Hosted service
enforces, through the same signed push as paid grants:

1. `POST /api/billing/trial` (exactly `trial=start`, same-origin form, signed-in
   session; in `owner-sandbox` mode only the owner) calls `store.startTrial`.
2. Under one global Postgres advisory lock the store checks the rules and inserts
   a row in `saiph_billing.trials` (migration 0004): subject, keyed email hash,
   random 32-hex reference, start, end. The lock makes the cap and the
   one-per-email rule hold when sign-ups race.
3. The grant `trial:<reference>` with `until` = trial end is pushed at once
   (Ed25519, next number from `grant_sequence`). If the push fails the page says
   to press again; pressing again re-delivers the same trial and never starts a
   second one or adds days. The daily refresh and `npm run billing:resync` also
   deliver trials.
4. The Hosted service stores it as `access_grants.kind='trial'`. It accepts only
   `trial:[a-f0-9]{32}`, at most 31 days ahead, binds the reference to the first
   account that names it, and refuses (409) a second trial reference for an
   account that already had one, whatever the website sends.

**One trial per person.** Enforced three ways: one row per sign-in subject; one
row per normalised verified email (lower case, no `+tag`, Gmail without dots and
`googlemail.com` folded into `gmail.com`), stored only as
HMAC-SHA256(`SAIPH_TRIAL_SECRET`, address), never the address; and one trial
reference per Hosted account. Rows cannot be updated or deleted (trigger), so a
trial cannot be reset by accident. An account that already has a subscription
(any status except an abandoned `incomplete`/`incomplete_expired` checkout) gets
no trial. The email hash is computed at sign-in from Google's verified `email`
claim and kept in the encrypted session cookie (`trialKey`); sessions created
before this release lack it, and the page asks the person to sign in again.
Limits: a person with two different Google accounts can still get two trials.
That is accepted for now; card fingerprinting would need a card up front.

**When the trial ends.** Nothing is pushed: the grant simply expires at its end
and the Hosted service refuses the account (403) like any expired grant. This is
non-destructive. The account, workspace database, approved devices, device
bindings and keys are kept, exactly as when a subscription lapses. The account
page shows **Your free trial has ended** with the subscribe buttons; the desktop
shows "Paused: no Cloud access" with the trial-ended message and **Subscribe**;
the Android app shows the same card with **Subscribe**. Subscribing pushes a paid
grant and the same devices reconnect on their next pass, with no new setup.

**Subscribing during the trial.** Checkout passes
`subscription_data.trial_end` = the free trial's end when at least 48 hours (plus
10 minutes) remain, so the remaining free days are kept and Stripe takes the
first payment when the trial ends (Stripe status `trialing`, already granted
until `current_period_end` + 72 h). With less than 48 hours left (Stripe's
minimum) the first payment is taken at once. The 14-day withdrawal period then
runs from the first paid day (`trial_end`), which is the more generous reading;
the withdraw page and terms say so.

**Apps.** The Hosted service has a new `GET /v1/access` for native (app) tokens:
the same answer as `/v1/billing/access` (`entitled`, `until`, `kinds`, plus
`trial_until` for accounts that ever had a trial). It works without a grant and
never creates an account. The desktop (`src/orion_mini/hosted_access.py`) and
Android (`HostedTrial.kt`) read it at most every 6 hours while connected and at
once after a refusal, and show days left or the trial-ended notice with a
**Subscribe** button that opens `https://usesaiph.com/hosted.html`. Wording only:
the service alone decides access. A service without `/v1/access` (older release)
leaves the notice off. `/v1/billing/access` keeps its original three fields for
accounts without a trial, so an older account website keeps working.

### Owner steps to turn trials on (owner-run, in this order)

Nothing in Stripe has to change for the no-card trial itself.

1. **Database:** apply migration 0004. In Neon, open the account database for
   the mode (the development database first) and run the whole regenerated
   `account-web/migrations/reviewed-migration.sql`; the receipt must show
   versions 1 to 4 (see `account-web/migrations/README.md`). Do this before
   deploying the website; without it the trial simply stays off (subscribing and
   the rest of the account page are unaffected).
2. **Hosted service:** deploy the Hub release containing this change (it accepts
   `trial:` grants and serves `GET /v1/access`). No new environment variable.
   An older service refuses trial pushes (400), so a trial start would answer
   "press again" until it is updated.
3. **Account website (Vercel, server-only environment), then redeploy:**

   | Variable | Value |
   | --- | --- |
   | `SAIPH_TRIAL_SECRET` | **Required to turn trials on.** 32+ random URL-safe characters, e.g. `node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))"`. Separate values for development and production. Never change it once trials are live: a new secret lets everyone who had a trial start another with a new account. |
   | `SAIPH_TRIAL_DAYS` | Optional. Default `14`; `1`–`30`; `0` turns new trials off (running trials continue). |
   | `SAIPH_TRIAL_CAP` | Optional. Unset or empty: no cap. A whole number: at most that many trials ever in this database, e.g. `100` for the first 100 people. Raising or clearing it reopens trials; lowering it never ends a running trial. |

   An invalid value turns trials off (never billing) and logs the setting's name.
4. **Stripe (recommended, live mode):** in Billing → Subscriptions and emails,
   turn on the reminder email before a trial ends. It applies only to people who
   subscribed during their free trial (Stripe `trialing`, card on file), and
   card network rules expect a reminder before a trial converts to paid.
5. **Website:** in the same release, set `"hostedTrial": "Free for 14 days, no
   card needed"` in `website/landing-settings.json` (match `SAIPH_TRIAL_DAYS`);
   it shows the trial line on the Cloud page and turns the main button into
   **Start your free trial**. The terms (`terms.html#trial`), refunds page and
   account privacy notice already describe the trial.
6. **Apps:** the days-left and trial-ended notices need the desktop and Android
   builds from this branch; older apps show their existing messages.
7. **Sandbox check (owner-sandbox, development):** sign in as the owner, press
   **Start free trial**, confirm Cloud works on a test computer and phone and the
   apps show the days left; check `/v1/billing/access` shows `kinds: ["trial"]`.
   To see expiry without waiting, an operator can set that test account's trial
   grant `expires_at` in the development service's `accounts.sqlite3` to the past
   (`UPDATE access_grants SET expires_at=strftime('%s','now')-60 WHERE kind='trial' AND account=?`),
   then subscribe with the 4242 card and confirm the same devices reconnect.

To stop offering trials: set `SAIPH_TRIAL_DAYS=0` (or a cap at the current
count) and remove `hostedTrial` from the website settings. Trial rows are kept
while trials are offered; deleting them later needs a reviewed migration that
drops the `protect_trial_claim` trigger (the privacy notice promises deletion
within 12 months after trials stop).

## Configuration

Account website (server-only Vercel environment), in addition to the existing
Auth0 and `DATABASE_URL` values:

| Variable | Value |
| --- | --- |
| `SAIPH_BILLING_MODE` | `owner-sandbox` (dev) or `live` |
| `STRIPE_SECRET_KEY` | restricted key, `rk_test_…` or `rk_live_…` to match the mode |
| `STRIPE_WEBHOOK_SECRET` | the endpoint's `whsec_…` |
| `STRIPE_EXPECTED_ACCOUNT_ID`, `STRIPE_PRODUCT_ID`, `STRIPE_PORTAL_CONFIGURATION_ID` | as before |
| `STRIPE_PRICE_ID` / `STRIPE_YEARLY_PRICE_ID` | the €9.99 monthly and €89.99 yearly prices |
| `SAIPH_HOSTED_API_URL` | Hosted service origin (already set for beta access) |
| `SAIPH_BILLING_GRANT_KEY` / `SAIPH_BILLING_GRANT_KEY_ID` | from `npm run billing:keygen <id> <new file>` |
| `CRON_SECRET` | 32+ random URL-safe characters for the daily refresh |
| `SAIPH_TRIAL_SECRET`, `SAIPH_TRIAL_DAYS`, `SAIPH_TRIAL_CAP` | free trial (see "Free trial on sign-up"); trials are off without the secret |

Hosted service (`/etc/saiph-beta/shared.env`): `ORION_BILLING_GRANTS=sandbox`
(or `live`) and `ORION_BILLING_GRANT_KEYS=<id>:<public key>` printed by the key
generator; several comma-separated keys allow rotation. Without both, the push
endpoint does not exist. The deployment bundle's module allowlist in operations
must include `hosted_billing`. Webhook endpoint events: the eight subscription
events plus the three `charge.dispute.*` events. Database: migrations 0003 and
0004 (free trial).

## Remaining

- Real Stripe sandbox run on the development deployment (checkout, renewal,
  failed payment, cancellation with test clocks, a dispute), recorded in
  operations. Test clocks move Stripe's period dates but not this service's
  clock, so the 3-day grace and the 35-day window are measured in real time.
- Owner-only live activation steps and service readiness for paying customers
  are listed in operations, separately.
- Independent security review of the push endpoint and key handling.
