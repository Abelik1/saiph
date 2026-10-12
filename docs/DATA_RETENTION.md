# Proposed data retention and deletion rules

2026-10-12 implementation update: hosted source now schedules bounded expiry
cleanup for active, idle and suspended workspaces. See the
[worker schedule and limits](SECURITY_FIXES_2026-10-12.md#primary-storage-expiry).
This changes primary-storage cleanup behavior after deployment; it does not
approve the production schedule below or establish secure erasure or backup purge.

Prepared 11 October 2026. The controller must approve these targets, assign a
responsible person, confirm provider capabilities and test deletion before public
collection or account onboarding. No new cleanup job or deployed guarantee is
created by this document. Public notices must describe the adopted, working rules.

## Schedule for approval

| Record | Purpose and proposed basis | Proposed retention/trigger | Action and current limit |
| --- | --- | --- | --- |
| Website hosting/security request metadata | Delivery and abuse prevention; assessed legitimate interests | 30 days from collection, except a documented incident hold | Confirm actual Vercel plan/platform logs, caches, exports and provider windows; do not promise this before verification |
| Optional website pageview analytics | Improve public website; assessed legitimate interests plus any required consent | Select the shortest useful supported report period before enabling | Provider report retention is unconfirmed; a visitor hash expiring is not deletion of reports; dashboard and contract review required |
| Launch-list email, consent version/time and status | Consented launch updates; limited consent evidence | Active-list deletion at the earlier of 90 days after public launch or 12 months without an update; withdrawal stops sending immediately | Owner must approve clock/cleanup; remove Tally, campaign and exported copies; the list is currently disabled |
| Minimum unsubscribe suppression record | Prevent unwanted recontact; assessed legitimate interests | While launch marketing continues, review annually and delete 90 days after it ends unless a documented need remains | Keep only address or keyed match value and withdrawal date/version; still personal data; never reimport withdrawn addresses |
| Auth0 profile/subject and account administration | Requested account/service and security; contract/assessed legitimate interests | Account lifetime plus up to 30 days after closure for completion of deletion | Delete via Auth0 and local service procedure; actual tenant logs/backups and tokens must be checked; no self-service deletion exists |
| Portal session and transaction cookies | Essential authentication | Current portal session: transient, non-rolling, at most one hour; transaction cookies temporary | Verify actual SDK/browser behavior and Auth0's separate session; local logout is not provider erasure |
| Billing account/customer mappings and subscription snapshots | Contract administration and reconciliation | While needed for billing, then remove/minimize within 30 days after closure unless a specific legal record is needed | Current schema prevents customer deletion and links event/subscription records; a reviewed maintenance path is a launch blocker, never disable integrity triggers ad hoc |
| Minimal webhook replay receipts/creation intents | Avoid duplicate charges/state loss; assessed legitimate interests | Keep through active reconciliation; set bounded archive/purge period after cancellation based on verified replay/duplicate risks | No automatic purge exists; do not drop replay protection or unresolved creation intents without reconciling Stripe and defining safe archival |
| Required invoices/tax/accounting evidence | Statutory accounting duty | Generally six years under Irish Revenue guidance; accountant must confirm exact records, start point and any longer legal obligation | Keep only required financial facts under restricted access, not whole profiles or message content; Stripe may have separate controller duties |
| Routine support/contact messages | Respond to requests and resolve problems; requested steps/assessed legitimate interests | 12 months after resolution, with earlier removal of unnecessary attachments | Confirm all mail providers, sent/deleted folders, exports and forwarding; no working public contact is yet confirmed |
| Rights-request record | Demonstrate handling; legal obligation/assessed legitimate interests | Proposed 3 years after completion, subject to documented necessity review | Keep dates, decision and minimum evidence; remove identity-document copies once verified unless justified; respond within statutory timing |
| Android beta tester invitation/address | Administer requested beta and invitations | Remove within 30 days after beta exit/end | Verify Firebase access-removal and deletion behavior; distribution and any independent Google retention differ |
| Hosted sealed events/blobs, device roster and routing metadata | Deliver approved-device service; contract and security | Final production limits not yet approved; select explicit event/blob TTLs, metadata lifetime and backup purge windows before launch | Prototype expiry is not evidence that every replica/log/backup is deleted; no production retention promise is made |

Exceptions require a documented legal obligation or narrowly scoped hold. A hold
records the reason, covered records, start/review date and decision owner. Review
at least quarterly; delete when the obligation or dispute ends. Do not extend all
account data merely because an invoice or one event is required.

## Operating procedure to approve and verify

1. Log the request and date; verify identity using the least intrusive sufficient
   information. Find records by the user's account/customer reference without
   copying secrets or full payloads into tickets. Separate cancellation, refund,
   withdrawal, marketing suppression and erasure; action each requested operation.
2. Stop optional processing promptly (for example launch updates), disable future
   renewal where requested and preserve evidence of the effective date. Explain
   what account access or delivery data must remain until the service ends.
3. Inventory Auth0, Neon/account tables, Stripe, Hosted storage, Vercel logs,
   Firebase, Tally, campaign sender, contact-mail providers and local exports.
   Export accessible data through a secure channel when requested. Do not send
   plaintext keys, unrelated users' data, or full card details.
4. Reconcile billing and any unresolved creation intents before minimization.
   Implement a reviewed, auditable maintenance path compatible with immutable
   mappings and foreign keys; do not improvise SQL that bypasses integrity or
   retention protections. Stripe/regulated records may have lawful exceptions;
   tell the requester precisely which facts and reasons apply.
5. Delete live copies and redundant exports; request provider deletion where
   supported. Record backup purge deadlines and prevent a restored backup from
   silently reactivating deleted users or marketing consent. A backup window is
   not permission to retain active data indefinitely. Tally's documented backup
   deletion window is up to 90 days; confirm each other provider separately.
6. Confirm completion/remaining lawful exceptions, expected backup purge dates
   and complaint rights. Answer without undue delay and normally within one
   month; explain any legally justified extension within the first month.
7. Keep minimal completion evidence, schedule remaining purge work and verify it.
   Before activation, run the procedure on synthetic records across all actual
   providers, including backup restoration behavior, and record real outcomes.

The controller owns the schedule and rights handling. Operations executes cleanup,
access controls and provider deletion; an accountant confirms statutory financial
retention. Those roles must be assigned to named people before launch. Review the
schedule every year and whenever providers, features or purposes change.

Sources and owner decisions: [LEGAL_PRIVACY.md](LEGAL_PRIVACY.md) and
[website launch gates](../website/LAUNCH.md). No provider backup/region facts beyond
the cited, reviewed information are assumed.
