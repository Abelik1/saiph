-- Free trial of Saiph Cloud on sign-up (docs/PAID_HOSTED.md). Additive: code
-- from 0003 keeps working against it.

-- One row per person who started a trial. The row is the abuse guard, so it is
-- never deleted: one trial per sign-in subject and per normalised verified email
-- (stored only as a keyed hash). Delivery columns mirror grant_state.
CREATE TABLE saiph_billing.trials (
    stripe_account_id text NOT NULL CHECK (stripe_account_id ~ '^acct_[A-Za-z0-9]+$'),
    auth_subject text NOT NULL CHECK (length(auth_subject) BETWEEN 1 AND 255),
    email_key text NOT NULL CHECK (email_key ~ '^[a-f0-9]{64}$'),
    trial_ref text NOT NULL CHECK (trial_ref ~ '^[a-f0-9]{32}$'),
    started_at bigint NOT NULL CHECK (started_at >= 0),
    ends_at bigint NOT NULL CHECK (ends_at > started_at),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    dirty boolean NOT NULL DEFAULT true,
    pushed_sequence bigint CHECK (pushed_sequence > 0),
    pushed_until bigint CHECK (pushed_until >= 0),
    pushed_at timestamptz,
    PRIMARY KEY (stripe_account_id, auth_subject),
    UNIQUE (stripe_account_id, email_key),
    UNIQUE (trial_ref)
);

CREATE FUNCTION saiph_billing.protect_trial_claim() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Trial claims are permanent' USING ERRCODE = '23514';
    END IF;
    IF ROW(NEW.stripe_account_id, NEW.auth_subject, NEW.email_key, NEW.trial_ref, NEW.started_at, NEW.ends_at)
       IS DISTINCT FROM ROW(OLD.stripe_account_id, OLD.auth_subject, OLD.email_key, OLD.trial_ref, OLD.started_at, OLD.ends_at) THEN
        RAISE EXCEPTION 'Trial claims are permanent' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER protect_trial_claim
BEFORE UPDATE OR DELETE ON saiph_billing.trials
FOR EACH ROW EXECUTE FUNCTION saiph_billing.protect_trial_claim();
