-- Reservations prevent multiple card trials across accounts/mailbox aliases.
-- They never grant access; verified Stripe subscription events do that.
CREATE TABLE saiph_billing.card_trial_claims (
    stripe_account_id text NOT NULL CHECK (stripe_account_id ~ '^acct_[A-Za-z0-9]+$'),
    auth_subject text NOT NULL CHECK (length(auth_subject) BETWEEN 1 AND 255),
    email_key text NOT NULL CHECK (email_key ~ '^[a-f0-9]{64}$'),
    trial_ref text NOT NULL CHECK (trial_ref ~ '^[a-f0-9]{32}$'),
    reserved_at bigint NOT NULL CHECK (reserved_at > 0),
    PRIMARY KEY (stripe_account_id, auth_subject),
    UNIQUE (stripe_account_id, email_key),
    UNIQUE (trial_ref)
);

CREATE FUNCTION saiph_billing.protect_card_trial_claim() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Card trial claims are permanent' USING ERRCODE = '23514';
END;
$$;
CREATE TRIGGER protect_card_trial_claim
BEFORE UPDATE OR DELETE ON saiph_billing.card_trial_claims
FOR EACH ROW EXECUTE FUNCTION saiph_billing.protect_card_trial_claim();
