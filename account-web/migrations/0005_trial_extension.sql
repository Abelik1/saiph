-- Owner extensions of a free trial (docs/PAID_HOSTED.md, "Extending a trial").
-- Additive: code from 0004 keeps working against it, and newer code reads the
-- trial end as before until this is applied.

-- The extended end, when the owner has added days. The trial's own dates stay
-- permanent; this can only move later and never be cleared.
ALTER TABLE saiph_billing.trials
    ADD COLUMN extended_until bigint CHECK (extended_until IS NULL OR extended_until > ends_at);

CREATE OR REPLACE FUNCTION saiph_billing.protect_trial_claim() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Trial claims are permanent' USING ERRCODE = '23514';
    END IF;
    IF ROW(NEW.stripe_account_id, NEW.auth_subject, NEW.email_key, NEW.trial_ref, NEW.started_at, NEW.ends_at)
       IS DISTINCT FROM ROW(OLD.stripe_account_id, OLD.auth_subject, OLD.email_key, OLD.trial_ref, OLD.started_at, OLD.ends_at) THEN
        RAISE EXCEPTION 'Trial claims are permanent' USING ERRCODE = '23514';
    END IF;
    IF OLD.extended_until IS NOT NULL AND (NEW.extended_until IS NULL OR NEW.extended_until < OLD.extended_until) THEN
        RAISE EXCEPTION 'A trial extension cannot be shortened' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
