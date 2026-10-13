# Saiph account website

Owner-only development application. Product code belongs here; private environment values, Vercel/DNS identifiers and deployment receipts belong in saiph-cloud or protected storage.

An explicitly enabled friends-beta mode adds code-based Hosted access to the same
account application. Keep the existing Auth0 settings; add server-only
`SAIPH_ACCOUNT_MODE=friends-beta`, `SAIPH_HOSTED_API_URL` (canonical HTTPS origin)
and `SAIPH_HOSTED_API_AUDIENCE`. Keep `SAIPH_BILLING_MODE=disabled` for this beta.
Missing beta configuration fails closed. Non-owner sessions can reach code entry;
only the backend's durable entitlement grants Hosted access. Verify the web
client's API audience/token permission separately in Auth0. Keep that client out
of the native device-client allowlist. Default owner-only behavior remains when
friends-beta mode is absent.

`npm run test:beta-integration` exercises actual production HTTP and official
SDK-encrypted synthetic sessions with a test-only backend transport. Run it after
the production build alongside default owner checks. It does not establish real
Auth0 login, live redemption or device acceptance. See
[the hosted friends guide](../docs/HOSTED_FRIENDS_BETA.md) and private operations
for deployment protection and existing-address cutover.

Node 24: `npm ci`, `npm test`, `npm run build`, `npm run test:integration`, `npm start`. Auth0 SDK 4 mounts the login/logout/callback routes through Next 16 `proxy.ts`. Missing configuration fails closed with HTTP 503 on account/auth routes; the home page explains setup is pending. No browser token/profile endpoint, refresh scope, API audience, native-client reuse or public registration is enabled. Callback redirects are fixed and non-owner callback session cookies are expired, including chunks. The account page also checks the session subject independently.

Server-only environment: `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, `AUTH0_SECRET` (32 random bytes in hex), `APP_BASE_URL` (canonical HTTPS origin with no trailing slash), `SAIPH_OWNER_SUBJECT`. Optional `SAIPH_REQUIRE_MFA=true` refuses any sign-in whose verified ID token `amr` claim lacks `mfa`, including the owner's; turn it on only after the tenant requires a second factor on every login for this client (see [account security](../docs/ACCOUNT_SECURITY.md)), otherwise nobody can sign in. Enter values through protected deployment settings. Never use NEXT_PUBLIC for these values. The SDK session is secure, host-only, HTTP-only, SameSite Lax, non-rolling, transient and limited to an hour. Logout clears the local session and invokes the provider logout flow; real browser verification remains required.

Stripe sandbox handlers are implemented but disabled by default. The test-provider resources and dedicated database were provisioned before this code. This revision has not migrated the remote database, registered a webhook, changed Deployment Protection, or been deployed. No real sandbox acceptance is implied by synthetic tests.

Enable only for reviewed owner testing with server-only `SAIPH_BILLING_MODE=owner-sandbox`, `STRIPE_EXPECTED_ACCOUNT_ID`, `STRIPE_PRODUCT_ID`, `STRIPE_PRICE_ID`, `STRIPE_PORTAL_CONFIGURATION_ID`, restricted `STRIPE_SECRET_KEY` (`rk_test_` only), `STRIPE_WEBHOOK_SECRET`, and `DATABASE_URL`, in addition to all Auth0 settings. Keep actual values in private operations/protected settings. Missing configuration, unmigrated storage, provider errors and binding mismatches fail closed. Never enable live keys. The configured price must be active, test mode, EUR 1/month with one unit of the configured test product.

`POST /api/billing/checkout` and `POST /api/billing/portal` independently require the verified exact owner session and canonical Origin. Requests accept no query/body billing identifiers. Customer creation and checkout inspection run under database locks; provider requests use deterministic idempotency. A durable creation intent survives rollback; an unresolved intent older than 23 hours refuses automatic recreation and requires verified reconciliation, before Stripe can evict its 24-hour idempotency record. Open checkout is reused and an existing nonterminal subscription prevents another purchase. Portal uses only the persisted customer and fixed configuration/return URL. Provider redirects are limited to exact HTTPS Checkout/Portal Stripe hosts. Returning from Checkout does not update billing state.

Only exact `/api/stripe/webhook` bypasses Auth0 middleware. Vercel Deployment Protection is a separate gate and remains unchanged; do not register delivery until a narrowly scoped, reviewed external delivery path exists. Use **snapshot** events at API version `2026-09-30.endive` (Stripe SDK 23). The receiver reads at most 256 KiB of raw bytes and verifies the official SDK signature with a five-minute timestamp window, including rejection of future timestamps. It rejects live/wrong-account/incompatible-version events. Own-account events may omit `account`; fixed test resource IDs and customer/subscription metadata still bind the configured account and hashed owner reference. Relevant events reconcile current Stripe state under the locked customer row, then atomically save subscription and event receipt. The durable event ledger handles duplicate replay and stale ordering; terminal subscriptions cannot reactivate from old events. Only billing status is stored: no Hosted entitlement, device approval, content key or app-traffic encryption is produced.

Billing standing is derived only from those webhook-persisted subscription rows by the pure `lib/billing/entitlement.mjs` (`deriveEntitlement(store.listSubscriptions(subject), now)`); the account page displays it independently of checkout-return feedback. The return query changes only the explanatory banner; it never enters billing derivation. `active`/`trialing` are entitled until the observed period end (with a 72-hour renewal grace, after which an unrenewed row is `renewal_unconfirmed`); scheduled cancellation (`cancel_at_period_end` or `cancel_at`) stays entitled only until the earliest scheduled end, even if the deletion webhook is late; `past_due`/`unpaid` (failed renewal) are suspended; `incomplete`, `paused`, `canceled`, `incomplete_expired` and unknown statuses are not entitled. This is sandbox billing standing only: it does not approve devices, unlock content or enable Hosted service. Treating `past_due` as suspended rather than a dunning grace period is an owner decision that can be revisited.

Supported events: `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed`. Events without a subscription (for example an unsuccessful uncompleted Checkout) are acknowledged without changing billing state. Unbound customers/provider failures return a sanitized retryable error rather than acknowledging lost state. A signing secret alone does not prove event delivery.

Run `npm test` and the isolated Postgres integration tests documented alongside the migration before activation. `npm run test:billing-db` also runs `tests/billing-lifecycle.test.mjs`: the real checkout/portal/webhook HTTP handlers against real migrated PostgreSQL with a stateful synthetic Stripe fixture (signature failures, duplicate/concurrent delivery, out-of-order events, payment failure, cancellation, portal customer binding, checkout redirect granting nothing). Synthetic handler tests use the official Stripe signature verifier and in-memory provider fixtures, not real sandbox credentials. Real Auth0 + restricted-key checkout/portal permissions, webhook delivery/replay, failure/cancellation and durable state after restart still require actual owner acceptance.

References: [Stripe webhooks](https://docs.stripe.com/webhooks), [Checkout Session creation](https://docs.stripe.com/api/checkout/sessions/create), [idempotent requests](https://docs.stripe.com/api/idempotent_requests), [official stripe-node signing](https://github.com/stripe/stripe-node#webhook-signing).

Keep Vercel Deployment Protection enabled for all deployments. Test owner login, non-owner denial, logout, callback/state tampering, unavailable-provider handling and cookie security using real Auth0 before calling login complete. Public onboarding requires an approved privacy policy and the separate production gates. This application is not a paid Hosted launch.

Verification: synthetic HTTP integration tests exercise the actual production server with SDK-encrypted owner, other-owner (including chunked), expired, tampered and absent sessions; query override and callback-state rejection. They use no real provider credentials and do not prove real browser login. Denied-callback cleanup tests use cookie chunks emitted by the installed Auth0 SDK.

## Legal/privacy preparation bundle

Draft website/account privacy, Hosted terms, refund/withdrawal and contact pages
are prepared. Read [the legal review record](../docs/LEGAL_PRIVACY.md) and the proposed
retention schedule before approving any public collection or paid service. The
public contact and provider/retention facts remain unconfirmed. The draft pages
and passing source checks do not establish legal or Stripe approval.


## Account preview interface

The responsive home, account overview and privacy pages share navigation and keyboard skip access. The account page shows only fixed test-subscription labels and validated period dates from stored billing observations. It reads storage only after owner verification and displays a pending state when billing/storage is unavailable. Subscription management appears only after a stored customer exists. Checkout return queries display feedback; they never set subscription state or Hosted access. Loading and error states keep account/provider details private.

Run `npm test`, `npm run build`, `npm run typecheck` and `npm run test:integration` after interface or dependency changes. The HTTP checks use synthetic encrypted Auth0 sessions and include checkout return/cancellation feedback with unavailable billing. Real provider sign-in and sandbox delivery still need separate acceptance.
