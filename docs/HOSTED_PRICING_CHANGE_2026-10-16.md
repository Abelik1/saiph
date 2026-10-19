# Prepared Hosted pricing change

Owner-approved prices: €9.99/month or €89.99/year (about 25% less than monthly).
This branch aligns the landing/Hosted/terms pages, README and plan artwork,
account plan labels, and server-side exact Stripe-price validation. Amounts
are 999 and 8999 euro cents. Withdrawal fixtures retain earlier paid charge
amounts: refunds must use actual payments, not the new catalog price.

This change is committed for review, not activated. The website publication
continues to use €3.99/month and €36/year until the account and Stripe settings
can change together. Operations must create matching recurring EUR prices,
update protected monthly/yearly price IDs and portal configuration, verify
checkout/webhook/entitlement behavior, and coordinate the landing and account
deployments. Existing subscriptions are not migrated automatically.

The five changed account files exactly match the isolated copy previously
validated in this chat: 79 unit tests, 41 disposable-PostgreSQL tests, typecheck,
production build and 30 synthetic production HTTP cases passed. No real Stripe
payment or provider acceptance is established by those checks. Account checks
were not repeated for byte-identical files. Website checks and SVG parsing were
run again in this isolated pricing branch. Billing source belongs in the product
repository; provider IDs, credentials and activation belong in private operations.
