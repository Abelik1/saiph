-- Durable remote-creation intent; an old ambiguous attempt requires reconciliation.
CREATE TABLE saiph_billing.customer_creation_intents (
    stripe_account_id text NOT NULL CHECK (stripe_account_id ~ '^acct_[A-Za-z0-9]+$'),
    auth_subject text NOT NULL CHECK (length(auth_subject) BETWEEN 1 AND 255),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (stripe_account_id, auth_subject)
);
-- Billing observations only. This schema cannot approve devices or grant Hosted access.
CREATE TABLE saiph_billing.customers (
    stripe_account_id text NOT NULL CHECK (stripe_account_id ~ '^acct_[A-Za-z0-9]+$'),
    auth_subject text NOT NULL CHECK (length(auth_subject) BETWEEN 1 AND 255),
    stripe_customer_id text NOT NULL CHECK (stripe_customer_id ~ '^cus_[A-Za-z0-9]+$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (stripe_account_id, auth_subject),
    UNIQUE (stripe_account_id, stripe_customer_id)
);

CREATE FUNCTION saiph_billing.protect_customer_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Billing customer identity is immutable' USING ERRCODE = '23514';
    END IF;
    IF ROW(NEW.stripe_account_id, NEW.auth_subject, NEW.stripe_customer_id)
       IS DISTINCT FROM ROW(OLD.stripe_account_id, OLD.auth_subject, OLD.stripe_customer_id) THEN
        RAISE EXCEPTION 'Billing customer identity is immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER protect_customer_identity
BEFORE UPDATE OR DELETE ON saiph_billing.customers
FOR EACH ROW EXECUTE FUNCTION saiph_billing.protect_customer_identity();

CREATE TABLE saiph_billing.subscriptions (
    stripe_account_id text NOT NULL,
    stripe_subscription_id text NOT NULL CHECK (stripe_subscription_id ~ '^sub_[A-Za-z0-9]+$'),
    stripe_customer_id text NOT NULL,
    stripe_price_id text NOT NULL CHECK (stripe_price_id ~ '^price_[A-Za-z0-9]+$'),
    status text NOT NULL CHECK (status IN
      ('incomplete','incomplete_expired','trialing','active','past_due','canceled','unpaid','paused')),
    current_period_end bigint CHECK (current_period_end >= 0),
    cancel_at_period_end boolean NOT NULL,
    canceled_at bigint CHECK (canceled_at >= 0),
    ended_at bigint CHECK (ended_at >= 0),
    last_event_created bigint NOT NULL CHECK (last_event_created >= 0),
    last_event_id text NOT NULL CHECK (last_event_id ~ '^evt_[A-Za-z0-9]+$'),
    observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (stripe_account_id, stripe_subscription_id),
    FOREIGN KEY (stripe_account_id, stripe_customer_id)
        REFERENCES saiph_billing.customers (stripe_account_id, stripe_customer_id)
);

CREATE FUNCTION saiph_billing.protect_subscription_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.stripe_account_id, NEW.stripe_subscription_id, NEW.stripe_customer_id)
       IS DISTINCT FROM ROW(OLD.stripe_account_id, OLD.stripe_subscription_id, OLD.stripe_customer_id) THEN
        RAISE EXCEPTION 'Billing subscription identity is immutable' USING ERRCODE = '23514';
    END IF;
    IF OLD.status IN ('canceled','incomplete_expired') AND NEW.status <> OLD.status THEN
        RAISE EXCEPTION 'Terminal subscription cannot be reinstated' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER protect_subscription_identity
BEFORE UPDATE ON saiph_billing.subscriptions
FOR EACH ROW EXECUTE FUNCTION saiph_billing.protect_subscription_identity();

CREATE TABLE saiph_billing.processed_events (
    stripe_account_id text NOT NULL,
    stripe_event_id text NOT NULL CHECK (stripe_event_id ~ '^evt_[A-Za-z0-9]+$'),
    stripe_customer_id text NOT NULL,
    stripe_subscription_id text NOT NULL,
    event_type text NOT NULL CHECK (event_type IN (
      'checkout.session.completed','checkout.session.async_payment_succeeded',
      'checkout.session.async_payment_failed','customer.subscription.created',
      'customer.subscription.updated','customer.subscription.deleted',
      'invoice.paid','invoice.payment_failed')),
    event_created bigint NOT NULL CHECK (event_created >= 0),
    outcome text NOT NULL CHECK (outcome IN ('applied','stale','terminal_ignored')),
    processed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (stripe_account_id, stripe_event_id),
    FOREIGN KEY (stripe_account_id, stripe_customer_id)
        REFERENCES saiph_billing.customers (stripe_account_id, stripe_customer_id),
    FOREIGN KEY (stripe_account_id, stripe_subscription_id)
        REFERENCES saiph_billing.subscriptions (stripe_account_id, stripe_subscription_id)
);
CREATE INDEX processed_events_customer ON saiph_billing.processed_events
    (stripe_account_id, stripe_customer_id, processed_at);
