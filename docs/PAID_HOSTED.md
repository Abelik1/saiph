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
grant or end paid access for any account, for at most 45 days per push.** It
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

Hosted service (`/etc/saiph-beta/shared.env`): `ORION_BILLING_GRANTS=sandbox`
(or `live`) and `ORION_BILLING_GRANT_KEYS=<id>:<public key>` printed by the key
generator; several comma-separated keys allow rotation. Without both, the push
endpoint does not exist. The deployment bundle's module allowlist in operations
must include `hosted_billing`. Webhook endpoint events: the eight subscription
events plus the three `charge.dispute.*` events. Database: migration 0003.

## Remaining

- Real Stripe sandbox run on the development deployment (checkout, renewal,
  failed payment, cancellation with test clocks, a dispute), recorded in
  operations. Test clocks move Stripe's period dates but not this service's
  clock, so the 3-day grace and the 35-day window are measured in real time.
- Owner-only live activation steps and service readiness for paying customers
  are listed in operations, separately.
- Independent security review of the push endpoint and key handling.
