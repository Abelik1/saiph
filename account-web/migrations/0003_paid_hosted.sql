-- Paid Hosted grants (docs/PAID_HOSTED.md). Additive: code from 0002 keeps working.

-- One database serves one Stripe mode. The store records it on first use and
-- refuses to mix test and live observations afterwards.
CREATE TABLE saiph_billing.settings (
    id integer PRIMARY KEY CHECK (id = 1),
    livemode boolean NOT NULL
);

-- First observed failed renewal, for the payment grace window. Cleared once the
-- subscription is observed in any other status.
ALTER TABLE saiph_billing.subscriptions
    ADD COLUMN payment_failed_at bigint CHECK (payment_failed_at >= 0);

-- Chargebacks. Only the current status is kept; it ends paid access while open or lost.
CREATE TABLE saiph_billing.disputes (
    stripe_account_id text NOT NULL,
    stripe_dispute_id text NOT NULL CHECK (stripe_dispute_id ~ '^(dp|du)_[A-Za-z0-9]+$'),
    stripe_customer_id text NOT NULL,
    status text NOT NULL CHECK (status ~ '^[a-z_]{1,40}$'),
    last_event_created bigint NOT NULL CHECK (last_event_created >= 0),
    observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (stripe_account_id, stripe_dispute_id),
    FOREIGN KEY (stripe_account_id, stripe_customer_id)
        REFERENCES saiph_billing.customers (stripe_account_id, stripe_customer_id)
);
CREATE INDEX disputes_customer ON saiph_billing.disputes (stripe_account_id, stripe_customer_id);

-- Receipts now also cover dispute events, which target a dispute instead of a subscription.
ALTER TABLE saiph_billing.processed_events
    ALTER COLUMN stripe_subscription_id DROP NOT NULL;
ALTER TABLE saiph_billing.processed_events
    ADD COLUMN stripe_dispute_id text CHECK (stripe_dispute_id ~ '^(dp|du)_[A-Za-z0-9]+$');
ALTER TABLE saiph_billing.processed_events
    ADD CONSTRAINT processed_events_one_target
    CHECK ((stripe_subscription_id IS NULL) <> (stripe_dispute_id IS NULL));
ALTER TABLE saiph_billing.processed_events
    DROP CONSTRAINT processed_events_event_type_check;
ALTER TABLE saiph_billing.processed_events
    ADD CONSTRAINT processed_events_event_type_check CHECK (event_type IN (
      'checkout.session.completed','checkout.session.async_payment_succeeded',
      'checkout.session.async_payment_failed','customer.subscription.created',
      'customer.subscription.updated','customer.subscription.deleted',
      'invoice.paid','invoice.payment_failed',
      'charge.dispute.created','charge.dispute.updated','charge.dispute.closed'));

-- Delivery state of each subscription's grant to the Hosted service. Sequence
-- numbers come from one Postgres sequence, allocated under the customer row lock,
-- so a later decision always carries a higher number.
CREATE SEQUENCE saiph_billing.grant_sequence AS bigint MINVALUE 1;
CREATE TABLE saiph_billing.grant_state (
    stripe_account_id text NOT NULL,
    stripe_subscription_id text NOT NULL,
    dirty boolean NOT NULL DEFAULT true,
    pushed_sequence bigint CHECK (pushed_sequence > 0),
    pushed_until bigint CHECK (pushed_until >= 0),
    pushed_at timestamptz,
    PRIMARY KEY (stripe_account_id, stripe_subscription_id),
    FOREIGN KEY (stripe_account_id, stripe_subscription_id)
        REFERENCES saiph_billing.subscriptions (stripe_account_id, stripe_subscription_id)
);
INSERT INTO saiph_billing.grant_state (stripe_account_id, stripe_subscription_id)
    SELECT stripe_account_id, stripe_subscription_id FROM saiph_billing.subscriptions;
