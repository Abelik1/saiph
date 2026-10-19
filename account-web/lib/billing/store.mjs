import { transaction } from "./transaction.mjs";
import { disputeBlocks } from "./grant.mjs";
import { extendableDays, extendedTrialEnd, validEmailKey } from "./trial.mjs";

const EVENT_TYPES = new Set([
  "checkout.session.completed", "checkout.session.async_payment_succeeded",
  "checkout.session.async_payment_failed", "customer.subscription.created",
  "customer.subscription.updated", "customer.subscription.deleted",
  "invoice.paid", "invoice.payment_failed",
]);
const DISPUTE_EVENT_TYPES = new Set(["charge.dispute.created", "charge.dispute.updated", "charge.dispute.closed"]);
const STATUSES = new Set([
  "incomplete", "incomplete_expired", "trialing", "active",
  "past_due", "canceled", "unpaid", "paused",
]);
const TERMINAL = new Set(["canceled", "incomplete_expired"]);
const DISPUTE_ID = /^(dp|du)_[A-Za-z0-9]{1,250}$/;
// Trial row columns; with migration 0005 the end includes an owner extension.
const TRIAL_COLUMNS = "auth_subject, trial_ref, started_at, ends_at, dirty, pushed_until";
const TRIAL_COLUMNS_EXTENDED = "auth_subject, trial_ref, started_at, COALESCE(extended_until, ends_at) AS ends_at, dirty, pushed_until";
const FUNNEL_STEPS = new Set(["signin_view", "signin_done", "checkout_started", "purchase", "trial_started"]);

/** @typedef {{subject: string, customerId: string}} CustomerMapping */
/** @typedef {{eventId: string, type: string, created: number, customerId: string, livemode: boolean}} BillingEvent */
/** @typedef {{subscriptionId: string, customerId: string, priceId: string, status: string, currentPeriodEnd: number | null, cancelAtPeriodEnd: boolean, cancelAt?: number | null, canceledAt: number | null, endedAt: number | null, livemode: boolean}} SubscriptionSnapshot */
/** @typedef {{disputeId: string, customerId: string, status: string, livemode: boolean}} DisputeSnapshot */
/** @typedef {{subscriptionId: string, customerId: string, subject: string, status: string, currentPeriodEnd: number | null,
 *   cancelAtPeriodEnd: boolean, cancelAt: number | null, canceledAt: number | null, endedAt: number | null,
 *   paymentFailedAt: number | null, disputed: boolean, dirty: boolean, pushedUntil: number | null}} GrantRow */

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
/** @param {SubscriptionSnapshot} snapshot @param {string} customerId @param {boolean} livemode */
function validateSnapshot(snapshot, customerId, livemode) {
  if (!snapshot || snapshot.livemode !== livemode || snapshot.customerId !== customerId) {
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
/** @param {BillingEvent} event @param {Set<string>} types @param {boolean} livemode */
function validateEvent(event, types, livemode) {
  if (!event || event.livemode !== livemode || !types.has(event.type)) {
    throw new BillingStoreError("INVALID_EVENT");
  }
  identifier(event.eventId, "evt");
  identifier(event.customerId, "cus");
  timestamp(event.created);
}
/** @param {Record<string, any>} row @returns {GrantRow} */
function grantRow(row) {
  const number = (/** @type {unknown} */ value) => value === null ? null : Number(value);
  return {
    subscriptionId: String(row.stripe_subscription_id), customerId: String(row.stripe_customer_id),
    subject: String(row.auth_subject), status: String(row.status),
    currentPeriodEnd: number(row.current_period_end), cancelAtPeriodEnd: Boolean(row.cancel_at_period_end),
    cancelAt: number(row.cancel_at), canceledAt: number(row.canceled_at), endedAt: number(row.ended_at),
    paymentFailedAt: number(row.payment_failed_at),
    disputed: (row.dispute_statuses ?? []).some((/** @type {string} */ status) => disputeBlocks(status)),
    dirty: Boolean(row.dirty), pushedUntil: number(row.pushed_until),
  };
}
const GRANT_SELECT = `
  SELECT s.stripe_subscription_id, s.stripe_customer_id, c.auth_subject, s.status, s.current_period_end,
         s.cancel_at_period_end, s.cancel_at, s.canceled_at, s.ended_at, s.payment_failed_at,
         g.dirty, g.pushed_until,
         ARRAY(SELECT d.status FROM saiph_billing.disputes d
               WHERE d.stripe_account_id=s.stripe_account_id AND d.stripe_customer_id=s.stripe_customer_id) AS dispute_statuses
  FROM saiph_billing.subscriptions s
  JOIN saiph_billing.customers c USING (stripe_account_id, stripe_customer_id)
  JOIN saiph_billing.grant_state g USING (stripe_account_id, stripe_subscription_id)`;

/**
 * Server-side billing observations. The caller must verify the webhook signature
 * and Stripe account before calling applyEvent. Hosted access follows these rows
 * only through withGrant(), which serializes the signed push per customer.
 * @param {import("./transaction.mjs").SqlPool} pool
 * @param {{stripeAccountId: string, livemode?: boolean}} options
 */
export function createBillingStore(pool, { stripeAccountId, livemode = false }) {
  identifier(stripeAccountId, "acct");
  if (typeof livemode !== "boolean") throw new BillingStoreError("INVALID_MODE");

  /** Every transaction first checks this database serves the configured Stripe mode.
   * @template T @param {(client: import("./transaction.mjs").SqlClient) => Promise<T>} callback */
  function tx(callback) {
    return transaction(pool, async (client) => {
      await client.query("INSERT INTO saiph_billing.settings (id, livemode) VALUES (1, $1) ON CONFLICT (id) DO NOTHING", [livemode]);
      const { rows } = await client.query("SELECT livemode FROM saiph_billing.settings WHERE id=1");
      if (rows[0]?.livemode !== livemode) throw new BillingStoreError("MODE_MISMATCH");
      return callback(client);
    });
  }

  /** Whether migration 0005 (owner trial extensions) is applied; checked once per store.
   * Until it is, trials read and behave exactly as before. */
  let extensionColumn = false;
  /** @param {import("./transaction.mjs").SqlClient} client */
  async function trialColumns(client) {
    if (!extensionColumn) {
      const { rows } = await client.query(
        `SELECT 1 FROM information_schema.columns
         WHERE table_schema='saiph_billing' AND table_name='trials' AND column_name='extended_until'`);
      extensionColumn = rows.length > 0;
    }
    return extensionColumn ? TRIAL_COLUMNS_EXTENDED : TRIAL_COLUMNS;
  }

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

  /** Lock the customer row by Stripe customer ID (webhook paths).
   * @param {import("./transaction.mjs").SqlClient} client @param {string} customerId */
  async function lockCustomer(client, customerId) {
    const { rows } = await client.query(
      "SELECT auth_subject, stripe_customer_id FROM saiph_billing.customers WHERE stripe_account_id=$1 AND stripe_customer_id=$2 FOR UPDATE",
      [stripeAccountId, customerId],
    );
    if (!rows[0]) throw new BillingStoreError("UNKNOWN_CUSTOMER");
    return { subject: String(rows[0].auth_subject), customerId };
  }

  /** @param {import("./transaction.mjs").SqlClient} client @param {BillingEvent} event @param {string} target */
  async function priorReceipt(client, event, target) {
    const processed = await client.query(
      "SELECT stripe_customer_id, coalesce(stripe_subscription_id, stripe_dispute_id) AS target, event_type, event_created FROM saiph_billing.processed_events WHERE stripe_account_id=$1 AND stripe_event_id=$2",
      [stripeAccountId, event.eventId],
    );
    const prior = processed.rows[0];
    if (!prior) return null;
    if (prior.stripe_customer_id !== event.customerId || prior.event_type !== event.type ||
        Number(prior.event_created) !== event.created || (target && prior.target !== target)) {
      throw new BillingStoreError("EVENT_ID_COLLISION");
    }
    return String(prior.target);
  }

  /** @param {string} subject @param {() => Promise<string>} createCustomer */
  async function getOrCreateCustomer(subject, createCustomer) {
    subjectValue(subject);
    // Commit the intent BEFORE calling Stripe. It survives an ambiguous remote
    // success + database rollback, so a retry outside Stripe's retention window
    // cannot silently create a second customer.
    const bound = await tx(async (client) => {
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
    return tx(async (client) => {
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
      return tx(async (client) => {
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
      return tx((client) => selectCustomer(client, subject));
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
      return tx(async (client) => {
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
      validateEvent(event, EVENT_TYPES, livemode);
      return tx(async (client) => {
        const mapping = await lockCustomer(client, event.customerId);
        const duplicate = await priorReceipt(client, event, "");
        if (duplicate !== null) return { outcome: "duplicate", subscriptionId: duplicate };

        const snapshot = await loadSnapshot(mapping);
        validateSnapshot(snapshot, event.customerId, livemode);
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
          // payment_failed_at keeps the FIRST observed failure while past_due.
          await client.query(
            `INSERT INTO saiph_billing.subscriptions
              (stripe_account_id,stripe_subscription_id,stripe_customer_id,stripe_price_id,
               status,current_period_end,cancel_at_period_end,canceled_at,ended_at,
               last_event_created,last_event_id,cancel_at,payment_failed_at)
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
             ON CONFLICT (stripe_account_id,stripe_subscription_id) DO UPDATE SET
               stripe_price_id=EXCLUDED.stripe_price_id,status=EXCLUDED.status,
               current_period_end=EXCLUDED.current_period_end,
               cancel_at_period_end=EXCLUDED.cancel_at_period_end,
               cancel_at=EXCLUDED.cancel_at,canceled_at=EXCLUDED.canceled_at,ended_at=EXCLUDED.ended_at,
               last_event_created=GREATEST(saiph_billing.subscriptions.last_event_created,EXCLUDED.last_event_created),
               last_event_id=EXCLUDED.last_event_id,observed_at=clock_timestamp(),
               payment_failed_at=CASE WHEN EXCLUDED.status='past_due'
                 THEN coalesce(saiph_billing.subscriptions.payment_failed_at,EXCLUDED.payment_failed_at) END`,
            [stripeAccountId, snapshot.subscriptionId, event.customerId, snapshot.priceId,
              snapshot.status, snapshot.currentPeriodEnd, snapshot.cancelAtPeriodEnd,
              snapshot.canceledAt, snapshot.endedAt, event.created, event.eventId,
              snapshot.cancelAt ?? null, snapshot.status === "past_due" ? event.created : null],
          );
        }
        // Any observation may change the grant; the push happens after commit.
        await client.query(
          `INSERT INTO saiph_billing.grant_state (stripe_account_id,stripe_subscription_id) VALUES ($1,$2)
           ON CONFLICT (stripe_account_id,stripe_subscription_id) DO UPDATE SET dirty=true`,
          [stripeAccountId, snapshot.subscriptionId],
        );
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

    /**
     * Record a chargeback's CURRENT status (fetched in loadDispute under the
     * customer lock) and mark every subscription of that customer for a push.
     * @param {BillingEvent} event
     * @param {(mapping: CustomerMapping) => Promise<DisputeSnapshot>} loadDispute
     */
    async applyDisputeEvent(event, loadDispute) {
      validateEvent(event, DISPUTE_EVENT_TYPES, livemode);
      return tx(async (client) => {
        const mapping = await lockCustomer(client, event.customerId);
        const duplicate = await priorReceipt(client, event, "");
        if (duplicate !== null) return { outcome: "duplicate", disputeId: duplicate };
        const dispute = await loadDispute(mapping);
        if (!dispute || dispute.livemode !== livemode || dispute.customerId !== event.customerId ||
            typeof dispute.disputeId !== "string" || !DISPUTE_ID.test(dispute.disputeId) ||
            typeof dispute.status !== "string" || !/^[a-z_]{1,40}$/.test(dispute.status)) {
          throw new BillingStoreError("INVALID_DISPUTE");
        }
        const current = await client.query(
          "SELECT stripe_customer_id, last_event_created FROM saiph_billing.disputes WHERE stripe_account_id=$1 AND stripe_dispute_id=$2",
          [stripeAccountId, dispute.disputeId],
        );
        const prior = current.rows[0];
        if (prior && prior.stripe_customer_id !== event.customerId) throw new BillingStoreError("DISPUTE_ALREADY_BOUND");
        const outcome = prior && event.created < Number(prior.last_event_created) ? "stale" : "applied";
        if (outcome === "applied") {
          await client.query(
            `INSERT INTO saiph_billing.disputes (stripe_account_id,stripe_dispute_id,stripe_customer_id,status,last_event_created)
             VALUES ($1,$2,$3,$4,$5)
             ON CONFLICT (stripe_account_id,stripe_dispute_id) DO UPDATE SET status=EXCLUDED.status,
               last_event_created=GREATEST(saiph_billing.disputes.last_event_created,EXCLUDED.last_event_created),
               observed_at=clock_timestamp()`,
            [stripeAccountId, dispute.disputeId, event.customerId, dispute.status, event.created],
          );
          await client.query(
            `UPDATE saiph_billing.grant_state g SET dirty=true FROM saiph_billing.subscriptions s
             WHERE s.stripe_account_id=$1 AND s.stripe_customer_id=$2
               AND g.stripe_account_id=s.stripe_account_id AND g.stripe_subscription_id=s.stripe_subscription_id`,
            [stripeAccountId, event.customerId],
          );
        }
        await client.query(
          `INSERT INTO saiph_billing.processed_events
             (stripe_account_id,stripe_event_id,stripe_customer_id,stripe_dispute_id,event_type,event_created,outcome)
           VALUES ($1,$2,$3,$4,$5,$6,$7)`,
          [stripeAccountId, event.eventId, event.customerId, dispute.disputeId, event.type, event.created, outcome],
        );
        return { outcome, disputeId: dispute.disputeId };
      });
    },

    /** Billing display observations; deliberately no entitlement Boolean.
     * @param {string} subject
     */
    async listSubscriptions(subject) {
      subjectValue(subject);
      return tx(async (client) => {
        const { rows } = await client.query(
          `SELECT s.stripe_subscription_id AS "subscriptionId", s.stripe_price_id AS "priceId",
                  s.status, s.current_period_end AS "currentPeriodEnd",
                  s.cancel_at_period_end AS "cancelAtPeriodEnd", s.cancel_at AS "cancelAt",
                  s.canceled_at AS "canceledAt",
                  s.ended_at AS "endedAt", s.payment_failed_at AS "paymentFailedAt"
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
          paymentFailedAt: row.paymentFailedAt === null ? null : Number(row.paymentFailedAt),
        }));
      });
    },

    /** Whether an open or lost chargeback currently blocks paid access.
     * @param {string} subject */
    async hasBlockingDispute(subject) {
      subjectValue(subject);
      return tx(async (client) => {
        const { rows } = await client.query(
          `SELECT d.status FROM saiph_billing.disputes d
           JOIN saiph_billing.customers c USING (stripe_account_id,stripe_customer_id)
           WHERE c.stripe_account_id=$1 AND c.auth_subject=$2`,
          [stripeAccountId, subject],
        );
        return rows.some((row) => disputeBlocks(String(row.status)));
      });
    },

    /** Subscriptions whose grant may need a push: undelivered, nonterminal, or
     * still running at the service. Optionally limited to one customer.
     * @param {{customerId?: string}} [filter] @returns {Promise<GrantRow[]>} */
    async grantCandidates({ customerId } = {}) {
      if (customerId !== undefined) identifier(customerId, "cus");
      return tx(async (client) => {
        const { rows } = await client.query(
          GRANT_SELECT + `
           WHERE s.stripe_account_id=$1 AND ($2::text IS NULL OR s.stripe_customer_id=$2)
             AND (g.dirty OR g.pushed_until IS NULL OR s.status NOT IN ('canceled','incomplete_expired')
                  OR g.pushed_until > extract(epoch FROM clock_timestamp()))
           ORDER BY s.stripe_customer_id, s.stripe_subscription_id`,
          [stripeAccountId, customerId ?? null],
        );
        return rows.map(grantRow);
      });
    },

    /**
     * Push one subscription's grant under its customer row lock, so a webhook
     * cannot change it between computing and recording. The callback receives a
     * fresh row and a new sequence number and must resolve with the expiry it
     * delivered; a throw leaves the grant marked for another attempt.
     * @param {string} subscriptionId
     * @param {(row: GrantRow, sequence: number) => Promise<number>} push
     */
    async withGrant(subscriptionId, push) {
      identifier(subscriptionId, "sub");
      return tx(async (client) => {
        const owner = await client.query(
          `SELECT c.stripe_customer_id FROM saiph_billing.customers c
           JOIN saiph_billing.subscriptions s USING (stripe_account_id,stripe_customer_id)
           WHERE s.stripe_account_id=$1 AND s.stripe_subscription_id=$2 FOR UPDATE OF c`,
          [stripeAccountId, subscriptionId],
        );
        if (!owner.rows[0]) throw new BillingStoreError("UNKNOWN_SUBSCRIPTION");
        const { rows } = await client.query(GRANT_SELECT + " WHERE s.stripe_account_id=$1 AND s.stripe_subscription_id=$2",
          [stripeAccountId, subscriptionId]);
        const sequence = Number((await client.query("SELECT nextval('saiph_billing.grant_sequence') AS value")).rows[0].value);
        const until = await push(grantRow(rows[0]), sequence);
        timestamp(until);
        await client.query(
          `UPDATE saiph_billing.grant_state SET dirty=false, pushed_sequence=$3, pushed_until=$4, pushed_at=clock_timestamp()
           WHERE stripe_account_id=$1 AND stripe_subscription_id=$2`,
          [stripeAccountId, subscriptionId, sequence, until],
        );
        return { sequence, until };
      });
    },

    /**
     * Add one to today's aggregate funnel count (migration 0006). Only the step,
     * plan and price-test variant are stored, never who. Rejects without
     * migration 0006; callers treat counting as optional.
     * "trial" is the free-trial path (sign-in page, sign-in done, trial started).
     * @param {{step: "signin_view"|"signin_done"|"checkout_started"|"purchase"|"trial_started", plan: "monthly"|"yearly"|"trial", test?: string | null, variant?: string}} count
     */
    async countFunnel({ step, plan, test = null, variant = "a" }) {
      if (!FUNNEL_STEPS.has(step) || (plan !== "monthly" && plan !== "yearly" && plan !== "trial")
          || (test !== null && !/^[a-z0-9][a-z0-9-]{0,39}$/.test(test)) || !/^[a-d]$/.test(variant)) {
        throw new BillingStoreError("INVALID_FUNNEL_COUNT");
      }
      await tx((client) => client.query(
        `INSERT INTO saiph_billing.funnel_daily (stripe_account_id,day,step,plan,price_test,variant,count)
         VALUES ($1,(now() AT TIME ZONE 'UTC')::date,$2,$3,$4,$5,1)
         ON CONFLICT (stripe_account_id,day,step,plan,price_test,variant) DO UPDATE SET count=saiph_billing.funnel_daily.count+1`,
        [stripeAccountId, step, plan, test ?? "", test ? variant : "a"],
      ));
    },

    /** This subject's trial and what the trial decision needs (lib/billing/trial.mjs).
     * @param {string} subject @param {string | null} emailKey */
    async trialFacts(subject, emailKey) {
      subjectValue(subject);
      return tx((client) => trialFacts(client, subject, emailKey));
    },

    /**
     * Start this subject's free trial if the rules allow it. One global lock
     * serializes trial starts, so the optional cap and the one-per-email rule
     * hold under concurrent sign-ups. Starting again returns the existing trial.
     * @param {{subject: string, emailKey: string, now: number, days: number, cap: number | null, ref: string}} request
     * @returns {Promise<{outcome: "started"|"exists"|"subscribed"|"used"|"full", trial: TrialRow | null}>}
     */
    async startTrial({ subject, emailKey, now, days, cap, ref }) {
      subjectValue(subject);
      if (!/^[a-f0-9]{64}$/.test(emailKey) || !/^[a-f0-9]{32}$/.test(ref)) throw new BillingStoreError("INVALID_TRIAL");
      timestamp(now);
      if (!Number.isSafeInteger(days) || days < 1 || days > 30 || cap !== null && (!Number.isSafeInteger(cap) || cap < 0)) {
        throw new BillingStoreError("INVALID_TRIAL");
      }
      return tx(async (client) => {
        await client.query("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
          [JSON.stringify(["saiph-billing-trial", stripeAccountId])]);
        const facts = await trialFacts(client, subject, emailKey);
        if (facts.stored) return { outcome: "exists", trial: facts.stored };
        if (facts.subscribed) return { outcome: "subscribed", trial: null };
        if (facts.emailUsed) return { outcome: "used", trial: null };
        if (cap !== null && facts.started >= cap) return { outcome: "full", trial: null };
        const endsAt = now + days * 86400;
        await client.query(
          `INSERT INTO saiph_billing.trials (stripe_account_id,auth_subject,email_key,trial_ref,started_at,ends_at)
           VALUES ($1,$2,$3,$4,$5,$6)`,
          [stripeAccountId, subject, emailKey, ref, now, endsAt],
        );
        return { outcome: "started", trial: { subject, ref, startedAt: now, endsAt, dirty: true, pushedUntil: null } };
      });
    },

    /** The trial started with this keyed email address (owner admin page), or null.
     * @param {string} emailKey @returns {Promise<TrialRow | null>} */
    async trialByEmail(emailKey) {
      if (!validEmailKey(emailKey)) throw new BillingStoreError("INVALID_TRIAL");
      return tx(async (client) => {
        const { rows } = await client.query(
          `SELECT ${await trialColumns(client)} FROM saiph_billing.trials WHERE stripe_account_id=$1 AND email_key=$2`,
          [stripeAccountId, emailKey],
        );
        return rows[0] ? trialRow(rows[0]) : null;
      });
    },

    /**
     * Owner extension: add `days` to the trial started with this keyed email, from
     * its current end (or from now if it has ended), at most 30 days ahead. Only the
     * extension column changes; the trigger refuses shortening it. Marks the grant
     * for delivery; the caller pushes it.
     * @param {{emailKey: string, days: number, now: number}} request
     * @returns {Promise<{outcome: "extended", trial: TrialRow, previousEnd: number}
     *   | {outcome: "not_found", trial: null} | {outcome: "too_long", trial: TrialRow, extendable: number}>}
     */
    async extendTrial({ emailKey, days, now }) {
      if (!validEmailKey(emailKey) || !Number.isSafeInteger(days) || days < 1 || days > 30) throw new BillingStoreError("INVALID_TRIAL");
      timestamp(now);
      return tx(async (client) => {
        if (await trialColumns(client) !== TRIAL_COLUMNS_EXTENDED) throw new BillingStoreError("MIGRATION_PENDING");
        const { rows } = await client.query(
          `SELECT ${TRIAL_COLUMNS_EXTENDED} FROM saiph_billing.trials WHERE stripe_account_id=$1 AND email_key=$2 FOR UPDATE`,
          [stripeAccountId, emailKey],
        );
        if (!rows[0]) return { outcome: "not_found", trial: null };
        const trial = trialRow(rows[0]);
        const end = extendedTrialEnd(trial.endsAt, days, now);
        if (end === null) return { outcome: "too_long", trial, extendable: extendableDays(trial.endsAt, now) };
        await client.query(
          "UPDATE saiph_billing.trials SET extended_until=$3, dirty=true WHERE stripe_account_id=$1 AND auth_subject=$2",
          [stripeAccountId, trial.subject, end],
        );
        return { outcome: "extended", trial: { ...trial, endsAt: end, dirty: true }, previousEnd: trial.endsAt };
      });
    },

    /** Trials whose grant may need a push: undelivered or still running at the service.
     * @param {{subject?: string}} [filter] @returns {Promise<TrialRow[]>} */
    async trialGrantCandidates({ subject } = {}) {
      if (subject !== undefined) subjectValue(subject);
      return tx(async (client) => {
        const { rows } = await client.query(
          `SELECT ${await trialColumns(client)} FROM saiph_billing.trials
           WHERE stripe_account_id=$1 AND ($2::text IS NULL OR auth_subject=$2)
             AND (dirty OR pushed_until IS NULL OR pushed_until > extract(epoch FROM clock_timestamp()))
           ORDER BY auth_subject`,
          [stripeAccountId, subject ?? null],
        );
        return rows.map(trialRow);
      });
    },

    /** Push one trial grant under its row lock; same contract as withGrant.
     * @param {string} subject
     * @param {(row: TrialRow, sequence: number) => Promise<number>} push */
    async withTrialGrant(subject, push) {
      subjectValue(subject);
      return tx(async (client) => {
        const { rows } = await client.query(
          `SELECT ${await trialColumns(client)} FROM saiph_billing.trials
           WHERE stripe_account_id=$1 AND auth_subject=$2 FOR UPDATE`,
          [stripeAccountId, subject],
        );
        if (!rows[0]) throw new BillingStoreError("UNKNOWN_TRIAL");
        const sequence = Number((await client.query("SELECT nextval('saiph_billing.grant_sequence') AS value")).rows[0].value);
        const until = await push(trialRow(rows[0]), sequence);
        timestamp(until);
        await client.query(
          `UPDATE saiph_billing.trials SET dirty=false, pushed_sequence=$3, pushed_until=$4, pushed_at=clock_timestamp()
           WHERE stripe_account_id=$1 AND auth_subject=$2`,
          [stripeAccountId, subject, sequence, until],
        );
        return { sequence, until };
      });
    },
  };

  /** @param {import("./transaction.mjs").SqlClient} client @param {string} subject @param {string | null} emailKey */
  async function trialFacts(client, subject, emailKey) {
    const own = await client.query(
      `SELECT ${await trialColumns(client)} FROM saiph_billing.trials
       WHERE stripe_account_id=$1 AND auth_subject=$2`,
      [stripeAccountId, subject],
    );
    const email = typeof emailKey === "string" && /^[a-f0-9]{64}$/.test(emailKey)
      ? await client.query("SELECT 1 FROM saiph_billing.trials WHERE stripe_account_id=$1 AND email_key=$2 AND auth_subject<>$3",
        [stripeAccountId, emailKey, subject])
      : { rows: [] };
    const subscribed = await client.query(
      `SELECT 1 FROM saiph_billing.subscriptions s JOIN saiph_billing.customers c USING (stripe_account_id,stripe_customer_id)
       WHERE c.stripe_account_id=$1 AND c.auth_subject=$2 AND s.status NOT IN ('incomplete','incomplete_expired') LIMIT 1`,
      [stripeAccountId, subject],
    );
    const count = await client.query("SELECT count(*) AS started FROM saiph_billing.trials WHERE stripe_account_id=$1", [stripeAccountId]);
    return { stored: own.rows[0] ? trialRow(own.rows[0]) : null, emailUsed: email.rows.length > 0,
      subscribed: subscribed.rows.length > 0, started: Number(count.rows[0].started) };
  }
}

/** @typedef {{subject: string, ref: string, startedAt: number, endsAt: number, dirty: boolean, pushedUntil: number | null}} TrialRow */
/** @param {Record<string, any>} row @returns {TrialRow} */
function trialRow(row) {
  return { subject: String(row.auth_subject), ref: String(row.trial_ref), startedAt: Number(row.started_at),
    endsAt: Number(row.ends_at), dirty: Boolean(row.dirty), pushedUntil: row.pushed_until === null ? null : Number(row.pushed_until) };
}
