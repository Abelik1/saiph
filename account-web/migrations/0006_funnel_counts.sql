-- Aggregate sign-in and checkout funnel counts (docs/LANDING_CONVERSION.md).
-- Daily totals by step, plan and price-test variant only: no person, session,
-- customer, Stripe or analytics identifier. Additive; until it is applied the
-- account site simply skips counting.
CREATE TABLE saiph_billing.funnel_daily (
    stripe_account_id text NOT NULL CHECK (stripe_account_id ~ '^acct_[A-Za-z0-9]+$'),
    day date NOT NULL,
    step text NOT NULL CHECK (step IN ('signin_view', 'signin_done', 'checkout_started', 'purchase', 'trial_started')),
    -- "trial" is the free-trial path from Start your free trial.
    plan text NOT NULL CHECK (plan IN ('monthly', 'yearly', 'trial')),
    price_test text NOT NULL CHECK (price_test ~ '^([a-z0-9][a-z0-9-]{0,39})?$'),
    variant text NOT NULL CHECK (variant ~ '^[a-d]$'),
    count integer NOT NULL CHECK (count > 0),
    PRIMARY KEY (stripe_account_id, day, step, plan, price_test, variant)
);
