import { transaction } from "./transaction.mjs";

const EVENT_TYPES = new Set([
  "checkout.session.completed", "checkout.session.async_payment_succeeded",
  "checkout.session.async_payment_failed", "customer.subscription.created",
  "customer.subscription.updated", "customer.subscription.deleted",
  "invoice.paid", "invoice.payment_failed",
]);
const STATUSES = new Set([
  "incomplete", "incomplete_expired", "trialing", "active",
  "past_due", "canceled", "unpaid", "paused",
]);
const TERMINAL = new Set(["canceled", "incomplete_expired"]);

/** @typedef {{subject: string, customerId: string}} CustomerMapping */
/** @typedef {{eventId: string, type: string, created: number, customerId: string, livemode: false}} BillingEvent */
/** @typedef {{subscriptionId: string, customerId: string, priceId: string, status: string, currentPeriodEnd: number | null, cancelAtPeriodEnd: boolean, cancelAt?: number | null, canceledAt: number | null, endedAt: number | null, livemode: false}} SubscriptionSnapshot */

/** Deliberately generic: never put provider payloads, identifiers or database details into errors. */
export class BillingStoreError extends Error {
  /** @param {string} code */
  constructor(code) {
    super("Billing storage operation rejected");
    this.name = "BillingStoreError";
    this.code = code;
  }
}

/** @param {unknown} value @param {string} prefix */
function identifier(value, prefix) {
  if (typeof value !== "string" || value.length > 255 ||
      !new RegExp("^" + prefix + "_[A-Za-z0-9]+$").test(value)) {
    throw new BillingStoreError("INVALID_IDENTIFIER");
  }
  return value;
}
/** @param {unknown} subject */
function subjectValue(subject) {
  if (typeof subject !== "string" || subject.length < 1 || subject.length > 255 ||
      /[\u0000-\u001f\u007f]/u.test(subject)) {
    throw new BillingStoreError("INVALID_SUBJECT");
  }
  return subject;
}
/** @param {unknown} value @param {boolean} [nullable] */
function timestamp(value, nullable = false) {
  if (nullable && value === null) return;
  if (!Number.isSafeInteger(value) || Number(value) < 0) {
    throw new BillingStoreError("INVALID_TIMESTAMP");
  }
}
/** @param {SubscriptionSnapshot} snapshot @param {string} customerId */
function validateSnapshot(snapshot, customerId) {
  if (!snapshot || snapshot.livemode !== false || snapshot.customerId !== customerId) {
    throw new BillingStoreError("SNAPSHOT_SCOPE_MISMATCH");
  }
  identifier(snapshot.subscriptionId, "sub");
  identifier(snapshot.priceId, "price");
  if (!STATUSES.has(snapshot.status) || typeof snapshot.cancelAtPeriodEnd !== "boolean") {
    throw new BillingStoreError("INVALID_SNAPSHOT");
  }
  timestamp(snapshot.currentPeriodEnd, true);
  timestamp(snapshot.cancelAt ?? null, true);
  timestamp(snapshot.canceledAt, true);
  timestamp(snapshot.endedAt, true);
}

/**
 * Server-side billing observations. The caller must verify the webhook signature
 * and Stripe account before calling applyEvent. No method grants Hosted access.
 * @param {import("./transaction.mjs").SqlPool} pool
 * @param {{stripeAccountId: string}} options
 */
export function createBillingStore(pool, { stripeAccountId }) {
  identifier(stripeAccountId, "acct");

  /** @param {import("./transaction.mjs").SqlClient} client @param {string} subject */
  async function lockSubject(client, subject) {
    await client.query(
      "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
      [JSON.stringify(["saiph-billing-customer", stripeAccountId, subject])],
    );
  }

  /** @param {import("./transaction.mjs").SqlClient} client @param {string} subject */
  async function selectCustomer(client, subject) {
    const { rows } = await client.query(
      "SELECT auth_subject, stripe_customer_id FROM saiph_billing.customers WHERE stripe_account_id=$1 AND auth_subject=$2 FOR UPDATE",
      [stripeAccountId, subject],
    );
    return rows[0] ? { subject: String(rows[0].auth_subject), customerId: String(rows[0].stripe_customer_id) } : null;
  }

  /** @param {string} subject @param {() => Promise<string>} createCustomer */
  async function getOrCreateCustomer(subject, createCustomer) {
    subjectValue(subject);
    // Commit the intent BEFORE calling Stripe. It survives an ambiguous remote
    // success + database rollback, so a retry outside Stripe's retention window
    // cannot silently create a second customer.
    const bound = await transaction(pool, async (client) => {
      await lockSubject(client, subject);
      const existing = await selectCustomer(client, subject);
      if (existing) return existing;
      await client.query(
        'INSERT INTO saiph_billing.customer_creation_intents (stripe_account_id,auth_subject) VALUES ($1,$2) ON CONFLICT DO NOTHING',
        [stripeAccountId, subject],
      );
      return null;
    });
    if (bound) return bound;
    return transaction(pool, async (client) => {
      await lockSubject(client, subject);
      const existing = await selectCustomer(client, subject);
      if (existing) return existing;
      const { rows } = await client.query(
        "SELECT created_at > clock_timestamp() - interval '23 hours' AS retry_safe FROM saiph_billing.customer_creation_intents WHERE stripe_account_id=$1 AND auth_subject=$2",
        [stripeAccountId, subject],
      );
      if (!rows[0]?.retry_safe) throw new BillingStoreError('CUSTOMER_RECONCILIATION_REQUIRED');
      // The adapter MUST use the same deterministic Stripe idempotency key on
      // every retry for this account/subject. The provider cannot roll back.
      const customerId = identifier(await createCustomer(), 'cus');
      await client.query(
        'INSERT INTO saiph_billing.customers (stripe_account_id,auth_subject,stripe_customer_id) VALUES ($1,$2,$3)',
        [stripeAccountId, subject, customerId],
      );
      return { subject, customerId };
    });
  }
  return {
    getOrCreateCustomer,

    /** Explicit reconciliation of an already verified provider customer.
     * @param {{subject: string, customerId: string}} mapping
     */
    async bindCustomer({ subject, customerId }) {
      subjectValue(subject);
      identifier(customerId, 'cus');
      return transaction(pool, async (client) => {
        await lockSubject(client, subject);
        const mapped = await selectCustomer(client, subject);
        if (mapped) {
          if (mapped.customerId !== customerId) throw new BillingStoreError('CUSTOMER_ALREADY_BOUND');
          return mapped;
        }
        await client.query(
          'INSERT INTO saiph_billing.customers (stripe_account_id,auth_subject,stripe_customer_id) VALUES ($1,$2,$3)',
          [stripeAccountId, subject, customerId],
        );
        return { subject, customerId };
      });
    },
    /** @param {string} subject @returns {Promise<CustomerMapping | null>} */
    async findCustomer(subject) {
      subjectValue(subject);
      return transaction(pool, (client) => selectCustomer(client, subject));
    },

    /**
     * Serialize checkout/portal provider calls with webhook processing.
     * Do not call another store method from the callback (nested locks).
     * @template T
     * @param {string} subject
     * @param {(mapping: CustomerMapping) => Promise<T>} callback
     * @returns {Promise<T>}
     */
    async withCustomer(subject, callback) {
      subjectValue(subject);
      return transaction(pool, async (client) => {
        await lockSubject(client, subject);
        const mapping = await selectCustomer(client, subject);
        if (!mapping) throw new BillingStoreError("UNKNOWN_CUSTOMER");
        return callback(mapping);
      });
    },

    /**
     * Fetch a CURRENT Stripe snapshot in loadSnapshot, never copy an old event's
     * embedded subscription. The callback runs after the customer row lock.
     * @param {BillingEvent} event
     * @param {(mapping: CustomerMapping) => Promise<SubscriptionSnapshot>} loadSnapshot
     */
    async applyEvent(event, loadSnapshot) {
      if (!event || event.livemode !== false || !EVENT_TYPES.has(event.type)) {
        throw new BillingStoreError("INVALID_EVENT");
      }
      identifier(event.eventId, "evt");
      identifier(event.customerId, "cus");
      timestamp(event.created);
      return transaction(pool, async (client) => {
        const customer = await client.query(
          "SELECT auth_subject, stripe_customer_id FROM saiph_billing.customers WHERE stripe_account_id=$1 AND stripe_customer_id=$2 FOR UPDATE",
          [stripeAccountId, event.customerId],
        );
        if (!customer.rows[0]) throw new BillingStoreError("UNKNOWN_CUSTOMER");
        const processed = await client.query(
          "SELECT stripe_customer_id, stripe_subscription_id, event_type, event_created FROM saiph_billing.processed_events WHERE stripe_account_id=$1 AND stripe_event_id=$2",
          [stripeAccountId, event.eventId],
        );
        if (processed.rows[0]) {
          const prior = processed.rows[0];
          if (prior.stripe_customer_id !== event.customerId || prior.event_type !== event.type ||
              Number(prior.event_created) !== event.created) {
            throw new BillingStoreError("EVENT_ID_COLLISION");
          }
          return { outcome: "duplicate", subscriptionId: String(prior.stripe_subscription_id) };
        }

        const snapshot = await loadSnapshot({ subject: String(customer.rows[0].auth_subject), customerId: event.customerId });
        validateSnapshot(snapshot, event.customerId);
        const current = await client.query(
          "SELECT stripe_customer_id, status, last_event_created FROM saiph_billing.subscriptions WHERE stripe_account_id=$1 AND stripe_subscription_id=$2",
          [stripeAccountId, snapshot.subscriptionId],
        );
        const prior = current.rows[0];
        if (prior && prior.stripe_customer_id !== event.customerId) {
          throw new BillingStoreError("SUBSCRIPTION_ALREADY_BOUND");
        }
        let outcome = "applied";
        if (prior && TERMINAL.has(prior.status) && snapshot.status !== prior.status) {
          outcome = "terminal_ignored";
        } else if (prior && event.created < Number(prior.last_event_created) &&
                   !TERMINAL.has(snapshot.status)) {
          outcome = "stale";
        } else {
          // Terminal observations are accepted even for a delayed event. An old
          // renewal cannot undo them; a new purchase needs a new subscription ID.
          await client.query(
            `INSERT INTO saiph_billing.subscriptions
              (stripe_account_id,stripe_subscription_id,stripe_customer_id,stripe_price_id,
               status,current_period_end,cancel_at_period_end,canceled_at,ended_at,
               last_event_created,last_event_id,cancel_at)
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
             ON CONFLICT (stripe_account_id,stripe_subscription_id) DO UPDATE SET
               stripe_price_id=EXCLUDED.stripe_price_id,status=EXCLUDED.status,
               current_period_end=EXCLUDED.current_period_end,
               cancel_at_period_end=EXCLUDED.cancel_at_period_end,
               cancel_at=EXCLUDED.cancel_at,canceled_at=EXCLUDED.canceled_at,ended_at=EXCLUDED.ended_at,
               last_event_created=GREATEST(saiph_billing.subscriptions.last_event_created,EXCLUDED.last_event_created),
               last_event_id=EXCLUDED.last_event_id,observed_at=clock_timestamp()`,
            [stripeAccountId, snapshot.subscriptionId, event.customerId, snapshot.priceId,
              snapshot.status, snapshot.currentPeriodEnd, snapshot.cancelAtPeriodEnd,
              snapshot.canceledAt, snapshot.endedAt, event.created, event.eventId,
              snapshot.cancelAt ?? null],
          );
        }
        await client.query(
          `INSERT INTO saiph_billing.processed_events
             (stripe_account_id,stripe_event_id,stripe_customer_id,stripe_subscription_id,event_type,event_created,outcome)
           VALUES ($1,$2,$3,$4,$5,$6,$7)`,
          [stripeAccountId, event.eventId, event.customerId, snapshot.subscriptionId,
            event.type, event.created, outcome],
        );
        return { outcome, subscriptionId: snapshot.subscriptionId };
      });
    },

    /** Billing display observations; deliberately no entitlement boolean.
     * @param {string} subject
     */
    async listSubscriptions(subject) {
      subjectValue(subject);
      return transaction(pool, async (client) => {
        const { rows } = await client.query(
          `SELECT s.stripe_subscription_id AS "subscriptionId", s.stripe_price_id AS "priceId",
                  s.status, s.current_period_end AS "currentPeriodEnd",
                  s.cancel_at_period_end AS "cancelAtPeriodEnd", s.cancel_at AS "cancelAt",
                  s.canceled_at AS "canceledAt",
                  s.ended_at AS "endedAt"
           FROM saiph_billing.subscriptions s
           JOIN saiph_billing.customers c USING (stripe_account_id,stripe_customer_id)
           WHERE c.stripe_account_id=$1 AND c.auth_subject=$2
           ORDER BY s.observed_at DESC, s.stripe_subscription_id`,
          [stripeAccountId, subject],
        );
        return rows.map((row) => ({
          subscriptionId: String(row.subscriptionId), priceId: String(row.priceId),
          status: String(row.status), cancelAtPeriodEnd: Boolean(row.cancelAtPeriodEnd),
          currentPeriodEnd: row.currentPeriodEnd === null ? null : Number(row.currentPeriodEnd),
          cancelAt: row.cancelAt === null ? null : Number(row.cancelAt),
          canceledAt: row.canceledAt === null ? null : Number(row.canceledAt),
          endedAt: row.endedAt === null ? null : Number(row.endedAt),
        }));
      });
    },
  };
}
