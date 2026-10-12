# Legal and privacy launch record

Prepared 11 October 2026. Source drafts only; not legal approval, Stripe approval,
provider configuration, a deployed retention job or an authorization to launch.

## Reviewable deliverables

- `website/privacy.html`: website delivery, optional analytics, Tally single opt-in,
  beta invitations, contact handling, rights and unresolved facts.
- `website/account-privacy.html` and `account-web/app/privacy/page.tsx`: actual
  owner-only Auth0/session and sandbox billing processing; separate Hosted limits.
- `website/terms.html`: proposed Hosted subscription terms, acceptance/confirmation,
  renewal/cancellation, consumer protections and licence boundaries.
- `website/refunds.html`: proposed full 14-day withdrawal refund, model statement,
  ordinary renewal cancellation and statutory service-problem remedies.
- `website/contact.html`: approved controller identity and honest contact status.
- `docs/DATA_RETENTION.md`: proposed schedule and deletion/hold/backup procedure.

The static bundle includes these pages and links them from every footer. The
account footer links its local privacy page and the product legal pages. Those
external pages become available only when this website revision is deployed.
Neither repository publication nor deployment is part of this source change.

## Owner confirmations and evidence required

Record decisions in private operations where appropriate. Public policy text may
contain public business facts only; never commit forwarding destinations, API keys,
provider exports, live user data or deployment environment values here.

| ID | Confirmation needed | Evidence before activation |
| --- | --- | --- |
| L1 | Confirm the trader remains Alexander Belik, operating as Abelik1, Ireland; business registration/tax/VAT presentation and countries served | Approved public identity and checkout/invoice presentation; identity was previously approved in website/LAUNCH.md |
| L2 | Supply public geographical trader address, email and telephone contact; decide support/billing/privacy handling | Verified incoming message from a separate address and named request owner; approved address/phone; no proposed mailbox is presented as live |
| L3 | Confirm website, analytics, Auth0, Neon, Stripe and mail provider settings, recipients, regions, logs, subprocessors, contracts and transfer safeguards | Provider settings plus actual DPAs/transfer assessment; keep account and Hosted hosting scopes distinct |
| L4 | Approve purposes/bases, legitimate-interests assessments and any ePrivacy consent requirements | Documented assessment for delivery/security/analytics; marketing remains separately consented; no cookie-free exemption is assumed |
| L5 | Approve each retention period and accounting trigger; name cleanup/rights-request owner | Adopted schedule in DATA_RETENTION.md, provider windows and tested deletion/export runbook; immutable billing identity trigger currently blocks ordinary customer deletion |
| L6 | Confirm Tally form controls/integrations, sender, unsubscribe, suppression, tracking and actual deletion/export steps | Existing website/LAUNCH.md checklist, delivered synthetic update and verified unsubscribe/deletion; signup remains disabled |
| L7 | Approve Hosted features, limits, compatibility, support, availability, export/deletion grace and recovery claims | Product acceptance/security review and accurate final service description; login/payment is separate from device approval |
| L8 | Approve price, currency/taxes, period, renewal notice and the proposed full first-14-day withdrawal refund with no usage deduction | Consistent order page, Stripe product/portal settings, terms and durable confirmation; no production price is inferred from the EUR 1 sandbox |
| L9 | Confirm Irish implementation and relevant cross-border rules for the online withdrawal function introduced by Directive (EU) 2023/2673, applicable from 19 June 2026 | Accessible withdrawal flow, explicit confirmation, durable receipt and timely refund tested before consumer sales; ordinary Stripe end-of-period cancellation is a different operation |
| L10 | Review terms, privacy, refund and contact text as one release; obtain appropriate legal review for the final offer | Dated approval tied to revision and actual operations; draft removal is not automatic |
| L11 | Configure Stripe public business details, terms/privacy/refund URLs, customer support contacts and Checkout agreement | Verify anonymously accessible HTTPS policy pages, actual Checkout display/acceptance and cancellation/refund workflow; no promise of Stripe approval |
| L12 | Approve and verify publication/activation separately | Deployment receipt, live policy/contact links, contact delivery, provider flow evidence and rollback record; repository source alone is not a launch |

Keep `privacy.status=draft`, `privacy.contactEmail` empty and `waitlistUrl` empty
until the existing website gates pass. `subscribeUrl` and `hostedPrice` stay empty;
the builder continues to reject paid settings. Public account onboarding remains
closed and Deployment Protection stays enabled. Optional analytics stays off until
its own privacy/provider review and dashboard work are complete.

## Withdrawal and cancellation acceptance

Before paid use, test withdrawal during the applicable period without requiring a
reason, first-payment refund, stopping subsequent renewal, duplicate submissions,
provider failure and a timestamped durable acknowledgement. The online function
must be easy to find throughout the withdrawal period, allow contract/customer
identification and a clear confirmation, and issue a durable receipt. Confirm the
exact national rules and wording with legal review; do not substitute a dead link,
mailto-only page, or a Stripe cancellation toggle. Do not collect live consumer
payments to test. No online withdrawal endpoint is implemented by this draft.

Normal end-of-term cancellation needs its own confirmation of the effective date,
continued access until that date and no subsequent charge. Test service faults and
trader-initiated closure refunds separately. Never label all subscriptions
non-refundable or require surrender of mandatory consumer rights.

## Sources checked on 11 October 2026

These are authoritative preparation sources, not a compliance certification.

- [DPC privacy-policy guidance](https://www.dataprotection.ie/en/faqs/responsibilities-data-controllers/how-do-i-make-privacy-policy),
  [transparency](https://dataprotection.ie/en/organisations/know-your-obligations/transparency)
  and [rights-response timing](https://www.dataprotection.ie/en/individuals/exercising-your-rights/how-long-will-it-take).
- [CCPC online purchases](https://www.ccpc.ie/consumer-advice/consumer-rights/buying-goods/buying-online/)
  and [digital-service trader obligations](https://www.ccpc.ie/information-for-businesses/selling-goods-and-services/selling-digital-content-or-services/).
- [Directive (EU) 2023/2673](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32023L2673),
  which inserts Article 11a into the Consumer Rights Directive; national implementation still needs confirmation.
- [Irish Revenue business records](https://www.revenue.ie/en/starting-a-business/starting-a-business/keeping-records.aspx).
- [Auth0 data processing](https://auth0.com/docs/secure/data-privacy-and-compliance/data-processing)
  and [Stripe privacy](https://stripe.com/privacy).
- [Stripe website checklist](https://docs.stripe.com/get-started/checklist/website)
  and [Checkout policies/contact display](https://docs.stripe.com/payments/checkout/custom-components?platform=web&payment-ui=embedded-page).
  Official Stripe documentation connector was used because the Stripe CLI is absent.
- [Vercel analytics privacy](https://vercel.com/docs/analytics/privacy-policy).

Actual Saiph facts were checked against website/LAUNCH.md, account-web/README.md,
account-web/lib/auth.ts, account-web/lib/billing/service.ts,
account-web/migrations/0001_billing.sql and docs/SECURITY_MODEL.md. Provider regions,
backup windows and contact delivery are deliberately not inferred from source.
