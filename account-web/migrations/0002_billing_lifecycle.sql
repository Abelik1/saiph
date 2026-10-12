-- Scheduled cancellation may be expressed as cancel_at as well as cancel_at_period_end.
ALTER TABLE saiph_billing.subscriptions
    ADD COLUMN cancel_at bigint CHECK (cancel_at >= 0);

-- Lookups by customer (account page, entitlement derivation) and per-subscription
-- ledger audit. The processed_events index also covers its subscription foreign key.
CREATE INDEX subscriptions_customer ON saiph_billing.subscriptions
    (stripe_account_id, stripe_customer_id);
CREATE INDEX processed_events_subscription ON saiph_billing.processed_events
    (stripe_account_id, stripe_subscription_id, event_created);

-- The receipt ledger is append-only: deleting or rewriting a receipt would let a
-- replayed delivery be processed again. Retention must be a reviewed migration.
CREATE FUNCTION saiph_billing.protect_processed_events() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Processed billing events are append-only' USING ERRCODE = '23514';
END;
$$;
CREATE TRIGGER protect_processed_events
BEFORE UPDATE OR DELETE ON saiph_billing.processed_events
FOR EACH ROW EXECUTE FUNCTION saiph_billing.protect_processed_events();
