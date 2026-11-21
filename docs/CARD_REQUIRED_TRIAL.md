# Card-required 14-day trial — 27 October 2026

Owner decision: new visitors provide a card for a 14-day free trial, then pay
€9.99/month automatically unless they cancel. Keep the compact landing and its
one primary trial action below the demonstration, with “14 days free, then
€9.99/month.” as its support line. Explain the card requirement and cancellation
condition on `/trial` before sign-in and again at Stripe Checkout. Direct monthly/yearly
purchases remain separate, explicit purchase paths.

## Implementation

- `/trial` explains the offer, then Google sign-in returns to the same fixed path.
  The signed-in page posts `trial=start` to the same-origin trial action, which
  reserves eligibility and redirects to Stripe. No card details enter Saiph.
- Checkout requires a payment method, uses the standard monthly price, sets
  `trial_period_days=14` and cancels if the payment method is missing at the end.
  Neither entering the page, reserving an offer nor returning from Checkout
  grants access. Existing verified subscription webhooks grant/revoke access.
- Migration **0007_card_trial_claims.sql** stores a permanent account/keyed-email
  reservation with a random reference. It grants no access. The reservation is
  committed before Stripe requests, so ambiguous provider success can be retried
  safely. Customer locks serialize Checkout reuse. An abandoned session can be
  resumed by the same account; switching between Buy and Trial expires the other
  open session, even if its price matches.
- Legacy no-card claims, previous subscriptions and mailbox aliases block a new
  trial. Provider subscription history also blocks repeats while a webhook is
  delayed. The optional cap counts legacy trials plus reserved card-trial offers;
  abandoned reservations retain a place, but the same account can resume its
  place when the cap is full. The cap is off by default.
- New card trials always use 14 days even if an older environment still says 30.
  `SAIPH_TRIAL_DAYS=0` still disables new offers. Legacy trials retain their
  original/extended end dates, no-charge terms and signed grant delivery.
- A verified completed card-trial Checkout counts `trial_started` once, not a
  paid purchase. Opening Checkout counts only `checkout_started`. Paid conversion
  and revenue must be read from actual paid billing observations/Stripe reports;
  the existing Checkout purchase counter is not a count of later trial renewals.

## Activation prerequisites

This source change does not deploy services, migrate production or change
existing subscriptions. Keep actual provider/environment values and receipts in
private operations. Release marketing and account behavior together.

1. Apply the reviewed migration through the existing account database procedure.
   No migration runs on startup or during a web request. Check the full migration
   history/checksums, including 0007; preserve existing trial rows.
2. In Stripe **Settings → Billing → Subscriptions and emails**, enable trial-end
   reminder emails. Use the Stripe-hosted management link, set the cancellation
   URL to the account's Manage billing entry, and verify the displayed subsequent
   price, first-charge date and cancellation instructions. Stripe documents a
   reminder seven days before the trial ends. Verify successful-payment receipts
   and trial information as appropriate. This is transactional billing mail, not
   marketing mail or a request to email current customers manually.
3. Verify the configured portal permits payment-method updates and cancellation
   at the end of the trial/period, without immediately billing a cancelled trial.
   The live default portal inspected on 27 October already had both enabled, with
   cancellation at period end. Confirm the deployed portal configuration is that
   intended configuration; do not infer live acceptance from a synthetic test.
4. Verify a provider test trial: card required, 14 days, correct price/date, a
   signed webhook delivering access, and cancellation before trial end producing
   no first charge. Stripe says sandbox trial reminder emails are not sent, so
   test clocks alone cannot prove delivery. Record the live messaging settings
   and appropriate delivery evidence separately.
5. Only after those checks, enable `SAIPH_CARD_TRIAL_READY=true` in the private
   live account deployment. Without it, new live card trials fail closed. Keep
   the trial secret stable to preserve mailbox deduplication. This flag does not
   configure Stripe or certify legal compliance; it records completed operational
   checks. The original standalone no-card start route is no longer offered.

Stripe references: [Checkout trials](https://docs.stripe.com/payments/checkout/free-trials)
and [trial communications and cancellation](https://docs.stripe.com/billing/subscriptions/trials/manage-trial-compliance).
These implementation checks support the requested flow; they are not an
independent legal review.

## Verification and current limits

The local release-status entry records exact checks. Real Chrome control failed
to initialize because the desktop computer-use helper could not launch
(`The system cannot find the file specified`, OS error 2), including recovery.
The Stripe connector exposes the portal configuration but no automatic-email
settings endpoint. Therefore no reminder setting was changed or verified by this
run, no readiness flag was enabled, and no live subscriptions were created or
modified. No conversion improvement is inferred from passing tests.

Local verification passed: 121 account unit tests, 51 isolated PostgreSQL tests,
233 website tests, 17 frontend tests, TypeScript and the actual trial routes in a
development HTTP server. Production compilation/typechecking completed but final
prerender/build acceptance remains pending after filesystem EPERM and an elevated
retry blocked by the automatic approval review quota. The existing Next.js
16.4.0 security advisory remains unresolved. See `docs/RELEASE_STATUS.md` for the
failed attempts and precise limits; do not equate the development HTTP result
with a passed production build or real provider acceptance.
